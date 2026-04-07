import logging
import re
from urllib.parse import urlparse

from src.models import Product, QualityReport

logger = logging.getLogger(__name__)


class ValidatorAgent:
    """Validates and deduplicates extracted product data."""

    def __init__(self, config: dict):
        self.config = config
        self.validation_errors: list[dict] = []

    def validate(self, product: Product) -> tuple[bool, list[str]]:
        """Validate a single product. Returns (is_valid, list_of_errors)."""
        errors = []

        # Required: name must be non-empty
        if not product.name or not product.name.strip():
            errors.append("Missing product name")

        # Required: URL must be valid
        if not product.url:
            errors.append("Missing product URL")
        else:
            parsed = urlparse(product.url)
            if not parsed.scheme or not parsed.netloc:
                errors.append(f"Invalid URL: {product.url}")

        # Price should look numeric if present (e.g., "$9.99", "12.50")
        if product.price:
            cleaned = re.sub(r"[$,\s]", "", product.price)
            try:
                float(cleaned)
            except ValueError:
                errors.append(f"Non-numeric price: {product.price}")

        # SKU format: should be non-empty string if present
        if product.sku is not None and not product.sku.strip():
            errors.append("Empty SKU string")

        # Image URLs should be valid
        for img_url in product.image_urls:
            if img_url and not img_url.startswith(("http://", "https://", "//")):
                errors.append(f"Invalid image URL: {img_url}")

        if errors:
            self.validation_errors.append({
                "product": product.name,
                "url": product.url,
                "errors": errors,
            })
            logger.warning(f"Validation errors for '{product.name}': {errors}")

        return len(errors) == 0, errors

    def deduplicate(self, products: list[Product]) -> list[Product]:
        """Remove duplicate products. Priority: SKU > URL > (name + brand)."""
        seen_skus: set[str] = set()
        seen_urls: set[str] = set()
        seen_name_brand: set[str] = set()
        unique: list[Product] = []
        duplicates_count = 0

        for product in products:
            # Check SKU first
            if product.sku:
                sku_key = product.sku.strip().lower()
                if sku_key in seen_skus:
                    duplicates_count += 1
                    logger.debug(f"Duplicate SKU: {product.sku} - {product.name}")
                    continue
                seen_skus.add(sku_key)

            # Check URL
            url_key = product.url.strip().rstrip("/").lower()
            if url_key in seen_urls:
                duplicates_count += 1
                logger.debug(f"Duplicate URL: {product.url}")
                continue
            seen_urls.add(url_key)

            # Check name + brand combo
            name_brand_key = f"{product.name.strip().lower()}|{(product.brand or '').strip().lower()}"
            if name_brand_key in seen_name_brand:
                duplicates_count += 1
                logger.debug(f"Duplicate name+brand: {product.name}")
                continue
            seen_name_brand.add(name_brand_key)

            unique.append(product)

        logger.info(f"Deduplication: {len(products)} -> {len(unique)} ({duplicates_count} duplicates removed)")
        return unique

    def quality_report(self, products: list[Product]) -> QualityReport:
        """Generate a quality report for a list of products."""
        valid_count = 0
        for p in products:
            is_valid, _ = self.validate(p)
            if is_valid:
                valid_count += 1

        # Calculate field completeness
        fields = {
            "name": 0, "brand": 0, "sku": 0, "price": 0,
            "description": 0, "availability": 0, "image_urls": 0,
            "specifications": 0, "category_hierarchy": 0, "unit_pack_size": 0,
        }

        for p in products:
            if p.name: fields["name"] += 1
            if p.brand: fields["brand"] += 1
            if p.sku: fields["sku"] += 1
            if p.price: fields["price"] += 1
            if p.description: fields["description"] += 1
            if p.availability: fields["availability"] += 1
            if p.image_urls: fields["image_urls"] += 1
            if p.specifications: fields["specifications"] += 1
            if p.category_hierarchy: fields["category_hierarchy"] += 1
            if p.unit_pack_size: fields["unit_pack_size"] += 1

        total = len(products)
        completeness = {
            field: round((count / total * 100), 1) if total > 0 else 0.0
            for field, count in fields.items()
        }

        report = QualityReport(
            total_products=total,
            valid_products=valid_count,
            duplicates_removed=0,  # Set by caller after dedup
            field_completeness=completeness,
        )

        logger.info(
            f"Quality Report: {valid_count}/{total} valid, "
            f"completeness: {completeness}"
        )
        return report
