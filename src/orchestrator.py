import asyncio
import logging
import os
import time
from typing import Optional

import httpx

from src.agents.classifier import ClassifierAgent
from src.agents.extractor import ExtractorAgent
from src.agents.navigator import NavigatorAgent
from src.agents.validator import ValidatorAgent
from src.models import CrawlStatus, PageType, Product
from src.rate_limiter import RateLimiter
from src.storage import CheckpointDB, save_csv, save_json
from src.utils import load_config, setup_logging

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates all agents to crawl, extract, validate, and store product data."""

    def __init__(self, config: dict):
        self.config = config
        self.rate_limiter = RateLimiter(
            delay_seconds=config.get("rate_limiting", {}).get("delay_seconds", 2.0),
            max_concurrent=config.get("rate_limiting", {}).get("max_concurrent", 3),
        )
        self.checkpoint_db = CheckpointDB(
            os.path.join(config.get("output", {}).get("directory", "output"), "checkpoint.db")
        )
        self.classifier = ClassifierAgent(config)
        self.extractor = ExtractorAgent(config)
        self.data_validator = ValidatorAgent(config)
        self.all_products: list[Product] = []
        self.stats = {
            "urls_crawled": 0,
            "urls_failed": 0,
            "products_extracted": 0,
            "start_time": 0.0,
        }

    async def run(self, category_urls: Optional[list[str]] = None) -> list[Product]:
        """Run the full scraping pipeline."""
        self.stats["start_time"] = time.time()

        # Initialize checkpoint DB
        await self.checkpoint_db.init()

        # Use provided URLs or config defaults
        urls = category_urls or self.config.get("targets", {}).get("categories", [])
        if not urls:
            logger.error("No target URLs provided")
            return []

        logger.info(f"Starting pipeline with {len(urls)} seed categories")

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "SafcoDentalScraper/1.0 (POC; educational use)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
        ) as client:
            navigator = NavigatorAgent(self.config, self.rate_limiter, client)

            # Phase 1: Discover categories and product URLs
            logger.info("=== Phase 1: Category Discovery ===")
            categories, product_urls = await navigator.build_url_queue(urls)
            logger.info(f"Discovered {len(categories)} categories, {len(product_urls)} product URLs")

            # Phase 2: Extract products from category listing pages
            logger.info("=== Phase 2: Category Listing Extraction ===")
            for url in urls:
                await self._process_listing(client, url)

            # Also process subcategory pages that were discovered
            for cat in categories:
                for sub in cat.subcategories:
                    await self._process_listing(client, sub.url)

            # Build product-to-category mapping from navigator
            self._product_category_map = navigator.product_to_category

            # Phase 3: Extract products from product detail pages
            logger.info("=== Phase 3: Product Detail Extraction ===")
            for url in product_urls:
                await self._process_detail(client, url)

        # Phase 4: Validate and deduplicate
        logger.info("=== Phase 4: Validation & Deduplication ===")
        original_count = len(self.all_products)
        self.all_products = self.data_validator.deduplicate(self.all_products)
        duplicates_removed = original_count - len(self.all_products)

        # Generate quality report
        report = self.data_validator.quality_report(self.all_products)
        report.duplicates_removed = duplicates_removed

        # Phase 5: Save output
        logger.info("=== Phase 5: Saving Output ===")
        output_dir = self.config.get("output", {}).get("directory", "output")
        os.makedirs(output_dir, exist_ok=True)

        save_json(self.all_products, os.path.join(output_dir, "products.json"))
        save_csv(self.all_products, os.path.join(output_dir, "products.csv"))

        # Save per-category output
        self._save_per_category(output_dir)

        # Print summary
        elapsed = time.time() - self.stats["start_time"]
        logger.info(
            f"\n{'='*50}\n"
            f"Pipeline Complete!\n"
            f"  Time: {elapsed:.1f}s\n"
            f"  URLs crawled: {self.stats['urls_crawled']}\n"
            f"  URLs failed: {self.stats['urls_failed']}\n"
            f"  Products extracted: {len(self.all_products)}\n"
            f"  Duplicates removed: {duplicates_removed}\n"
            f"  Valid products: {report.valid_products}/{report.total_products}\n"
            f"  Field completeness: {report.field_completeness}\n"
            f"{'='*50}"
        )

        return self.all_products

    async def resume(self) -> list[Product]:
        """Resume a previously interrupted crawl."""
        await self.checkpoint_db.init()
        pending_urls = await self.checkpoint_db.get_pending_urls()
        completed = await self.checkpoint_db.get_completed_count()

        logger.info(f"Resuming: {completed} completed, {len(pending_urls)} pending")

        if not pending_urls:
            logger.info("Nothing to resume -- all URLs completed")
            return []

        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "SafcoDentalScraper/1.0 (POC; educational use)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
        ) as client:
            for url in pending_urls:
                classification = self.classifier.classify(url)
                if classification.page_type == PageType.PRODUCT_DETAIL:
                    await self._process_detail(client, url)
                else:
                    await self._process_listing(client, url)

        # Validate and save
        self.all_products = self.data_validator.deduplicate(self.all_products)
        output_dir = self.config.get("output", {}).get("directory", "output")
        os.makedirs(output_dir, exist_ok=True)
        save_json(self.all_products, os.path.join(output_dir, "products.json"))
        save_csv(self.all_products, os.path.join(output_dir, "products.csv"))

        return self.all_products

    async def _process_listing(self, client: httpx.AsyncClient, url: str):
        """Process a category/listing page."""
        try:
            await self.checkpoint_db.upsert(url, CrawlStatus.IN_PROGRESS.value)

            async with self.rate_limiter:
                response = await client.get(url)
                response.raise_for_status()

            result = self.extractor.extract_from_listing(response.text, url)
            self.all_products.extend(result.products)
            self.stats["urls_crawled"] += 1
            self.stats["products_extracted"] += len(result.products)

            await self.checkpoint_db.upsert(url, CrawlStatus.COMPLETED.value, page_type="listing")
            logger.info(f"Listing OK: {url} ({len(result.products)} products)")

        except Exception as e:
            self.stats["urls_failed"] += 1
            await self.checkpoint_db.upsert(url, CrawlStatus.FAILED.value, error=str(e))
            logger.error(f"Failed to process listing {url}: {e}")

    async def _process_detail(self, client: httpx.AsyncClient, url: str):
        """Process a product detail page."""
        try:
            await self.checkpoint_db.upsert(url, CrawlStatus.IN_PROGRESS.value)

            async with self.rate_limiter:
                response = await client.get(url)
                response.raise_for_status()

            result = self.extractor.extract_from_detail(response.text, url)
            # Assign category hierarchy from navigator's mapping if not already set
            cat_map = getattr(self, "_product_category_map", {})
            for product in result.products:
                if not product.category_hierarchy and url in cat_map:
                    product.category_hierarchy = cat_map[url]
            self.all_products.extend(result.products)
            self.stats["urls_crawled"] += 1
            self.stats["products_extracted"] += len(result.products)

            await self.checkpoint_db.upsert(url, CrawlStatus.COMPLETED.value, page_type="detail")
            logger.debug(f"Detail OK: {url}")

        except Exception as e:
            self.stats["urls_failed"] += 1
            await self.checkpoint_db.upsert(url, CrawlStatus.FAILED.value, error=str(e))
            logger.error(f"Failed to process detail {url}: {e}")

    def _save_per_category(self, output_dir: str):
        """Save products grouped by top-level category."""
        category_products: dict[str, list[Product]] = {}

        for product in self.all_products:
            if product.category_hierarchy:
                cat = product.category_hierarchy[0]
            else:
                # Infer from URL
                cat = "uncategorized"
                if "suture" in product.url.lower() or "surgical" in product.url.lower():
                    cat = "sutures-surgical-products"
                elif "glove" in product.url.lower():
                    cat = "gloves"

            if cat not in category_products:
                category_products[cat] = []
            category_products[cat].append(product)

        for cat_name, products in category_products.items():
            safe_name = cat_name.lower().replace(" ", "-").replace("/", "-")
            save_json(products, os.path.join(output_dir, f"{safe_name}.json"))
            logger.info(f"Saved {len(products)} products for category '{cat_name}'")
