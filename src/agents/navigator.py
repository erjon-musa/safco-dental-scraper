import asyncio
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.models import Category
from src.rate_limiter import RateLimiter
from src.retry import retry_async
from src.utils import normalize_url

logger = logging.getLogger(__name__)


class NavigatorAgent:
    """Discovers product categories, subcategories, and product URLs from the target site."""

    def __init__(self, config: dict, rate_limiter: RateLimiter, client: httpx.AsyncClient):
        self.config = config
        self.base_url = config["targets"]["base_url"]
        self.rate_limiter = rate_limiter
        self.client = client
        self.visited_urls: set[str] = set()
        self.product_urls: list[str] = []
        self.categories: list[Category] = []
        self.product_to_category: dict[str, list[str]] = {}  # product_url -> category hierarchy

    async def fetch_page(self, url: str) -> str:
        """Fetch a page with rate limiting and retry."""
        async with self.rate_limiter:
            response = await self.client.get(url, follow_redirects=True)
            response.raise_for_status()
            logger.info(f"Fetched: {url} ({response.status_code})")
            return response.text

    async def discover_categories(self, url: str) -> Category:
        """Fetch a category page and discover subcategories and product links."""
        if url in self.visited_urls:
            return Category(name="", url=url)
        self.visited_urls.add(url)

        html = await self.fetch_page(url)
        soup = BeautifulSoup(html, "lxml")

        # Extract category name from page title or h1
        name = ""
        h1 = soup.find("h1")
        if h1:
            name = h1.get_text(strip=True)

        category = Category(name=name, url=url)

        # Find subcategory links and product links
        subcategory_links: set[str] = set()
        product_links: set[str] = set()

        for a_tag in soup.find_all("a", href=True):
            href = normalize_url(a_tag["href"], self.base_url)
            if not href.startswith(self.base_url):
                continue

            path = urlparse(href).path

            # Product detail pages: /product/slug
            if re.match(r"^/product/[\w-]+/?$", path):
                product_links.add(href)
            # Subcategory pages: /catalog/parent/sub (deeper than current URL)
            elif path.startswith("/catalog/") and href != url:
                current_depth = urlparse(url).path.rstrip("/").count("/")
                link_depth = path.rstrip("/").count("/")
                if link_depth > current_depth:
                    subcategory_links.add(href)

        # Also try to extract product URLs from JSON-LD
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    # ItemList contains product references
                    if data.get("@type") == "ItemList":
                        for item in data.get("itemListElement", []):
                            item_url = item.get("url", "")
                            if item_url and "/product/" in item_url:
                                product_links.add(normalize_url(item_url, self.base_url))
                    # Check for product URL in Product type
                    if data.get("@type") == "Product":
                        prod_url = data.get("url", "")
                        if prod_url:
                            product_links.add(normalize_url(prod_url, self.base_url))
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "ItemList":
                            for elem in item.get("itemListElement", []):
                                item_url = elem.get("url", "")
                                if item_url and "/product/" in item_url:
                                    product_links.add(normalize_url(item_url, self.base_url))
            except (json.JSONDecodeError, TypeError):
                continue

        # Track category hierarchy for each product URL
        category_path = [name] if name else []
        if category.parent:
            category_path = [category.parent] + category_path
        for prod_url in product_links:
            if prod_url not in self.product_to_category:
                self.product_to_category[prod_url] = category_path

        self.product_urls.extend(product_links - set(self.product_urls))
        logger.info(
            f"Category '{name}': found {len(subcategory_links)} subcategories, "
            f"{len(product_links)} products"
        )

        # Recursively discover subcategories
        for sub_url in sorted(subcategory_links):
            sub_category = await self.discover_categories(sub_url)
            if sub_category.name:
                sub_category.parent = name
                category.subcategories.append(sub_category)

        return category

    async def build_url_queue(self, starting_urls: list[str]) -> tuple[list[Category], list[str]]:
        """Build complete URL queue from starting category URLs."""
        logger.info(f"Starting navigation from {len(starting_urls)} seed URLs")

        for url in starting_urls:
            category = await self.discover_categories(url)
            if category.name:
                self.categories.append(category)

        # Deduplicate product URLs
        unique_products = list(dict.fromkeys(self.product_urls))

        logger.info(
            f"Navigation complete: {len(self.categories)} top categories, "
            f"{len(unique_products)} unique product URLs"
        )
        return self.categories, unique_products
