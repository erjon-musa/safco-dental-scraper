import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.models import ExtractionResult, Product

logger = logging.getLogger(__name__)


class ExtractorAgent:
    """Extracts product data from web pages using JSON-LD, HTML parsing, and LLM fallback."""

    def __init__(self, config: dict, llm_client=None):
        self.config = config
        self.llm_client = llm_client  # anthropic.AsyncAnthropic, optional

    def _parse_json_ld(self, html: str) -> list[dict]:
        """Find and parse all JSON-LD script tags."""
        soup = BeautifulSoup(html, "lxml")
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
        return results

    def _extract_price(self, offer_data: dict) -> Optional[str]:
        """Extract price from schema.org Offer data."""
        if not offer_data:
            return None
        # Could be a single offer or list
        if isinstance(offer_data, list):
            offer_data = offer_data[0] if offer_data else {}
        price = offer_data.get("price") or offer_data.get("lowPrice")
        currency = offer_data.get("priceCurrency", "USD")
        if price:
            return f"${price}" if currency == "USD" else f"{price} {currency}"
        return None

    def _extract_availability(self, offer_data: dict) -> Optional[str]:
        """Extract availability from schema.org Offer data."""
        if not offer_data:
            return None
        if isinstance(offer_data, list):
            offer_data = offer_data[0] if offer_data else {}
        avail = offer_data.get("availability", "")
        # schema.org uses full URLs like https://schema.org/InStock
        if "InStock" in avail:
            return "In Stock"
        elif "OutOfStock" in avail:
            return "Out of Stock"
        elif "PreOrder" in avail:
            return "Pre-Order"
        elif avail:
            return avail.split("/")[-1]
        return None

    def extract_from_listing(self, html: str, url: str) -> ExtractionResult:
        """Extract basic product info from a category/listing page via JSON-LD ItemList."""
        products = []
        json_ld_data = self._parse_json_ld(html)
        method = "json_ld"

        for data in json_ld_data:
            if data.get("@type") == "ItemList":
                for item in data.get("itemListElement", []):
                    try:
                        # ItemList items may have nested product data or just URL/name
                        product_url = item.get("url", "")
                        name = item.get("name", "")
                        image = item.get("image", "")

                        # Some listings embed offer data
                        offers = item.get("offers", {})
                        sku = item.get("sku") or offers.get("sku", "")

                        if name and product_url:
                            product = Product(
                                name=name,
                                url=product_url,
                                sku=sku or None,
                                price=self._extract_price(offers) if offers else None,
                                availability=self._extract_availability(offers) if offers else None,
                                image_urls=[image] if image else [],
                            )
                            products.append(product)
                    except Exception as e:
                        logger.warning(f"Failed to parse listing item: {e}")
                        continue

        # If no JSON-LD products found, try HTML fallback
        if not products:
            method = "html"
            products = self._extract_listing_with_bs4(html, url)

        completeness = self._calculate_completeness(products)
        logger.info(f"Extracted {len(products)} products from listing {url} via {method}")

        return ExtractionResult(
            products=products,
            method=method,
            field_completeness=completeness,
        )

    def extract_from_detail(self, html: str, url: str) -> ExtractionResult:
        """Extract full product data from a product detail page."""
        products = []
        json_ld_data = self._parse_json_ld(html)
        method = "json_ld"

        for data in json_ld_data:
            if data.get("@type") == "Product":
                try:
                    offers = data.get("offers", {})
                    brand_data = data.get("brand", {})
                    brand = brand_data.get("name") if isinstance(brand_data, dict) else str(brand_data) if brand_data else None

                    # Extract images
                    images = data.get("image", [])
                    if isinstance(images, str):
                        images = [images]
                    elif isinstance(images, dict):
                        images = [images.get("url", "")]

                    # Extract description
                    description = data.get("description", "")

                    # Extract SKU
                    sku = data.get("sku") or data.get("mpn") or data.get("productID")
                    if not sku and isinstance(offers, dict):
                        sku = offers.get("sku")

                    # Extract category from breadcrumb or category field
                    category_hierarchy = []
                    category = data.get("category", "")
                    if category:
                        if isinstance(category, str):
                            category_hierarchy = [c.strip() for c in category.split(">")]
                        elif isinstance(category, list):
                            category_hierarchy = category

                    # Extract specifications from additionalProperty
                    specs = {}
                    for prop in data.get("additionalProperty", []):
                        if isinstance(prop, dict):
                            prop_name = prop.get("name", "")
                            prop_value = prop.get("value", "")
                            if prop_name and prop_value:
                                specs[prop_name] = str(prop_value)

                    product = Product(
                        name=data.get("name", ""),
                        brand=brand,
                        sku=sku or None,
                        category_hierarchy=category_hierarchy,
                        url=data.get("url", url),
                        price=self._extract_price(offers),
                        availability=self._extract_availability(offers),
                        description=description or None,
                        specifications=specs,
                        image_urls=[img for img in images if img],
                        alternative_products=[],
                    )
                    products.append(product)
                except Exception as e:
                    logger.warning(f"Failed to parse product detail JSON-LD: {e}")

        # HTML fallback
        if not products:
            method = "html"
            products = self._extract_detail_with_bs4(html, url)

        completeness = self._calculate_completeness(products)
        logger.info(f"Extracted {len(products)} products from detail {url} via {method}")

        return ExtractionResult(
            products=products,
            method=method,
            field_completeness=completeness,
        )

    def _extract_listing_with_bs4(self, html: str, url: str) -> list[Product]:
        """HTML fallback for listing pages using BeautifulSoup."""
        soup = BeautifulSoup(html, "lxml")
        products = []

        # Look for common product listing patterns
        product_cards = soup.find_all("div", class_=re.compile(r"product|item|card", re.I))
        if not product_cards:
            product_cards = soup.find_all("li", class_=re.compile(r"product|item", re.I))

        for card in product_cards:
            try:
                # Find product link and name
                link = card.find("a", href=re.compile(r"/product/"))
                if not link:
                    continue

                name_elem = card.find(["h2", "h3", "h4", "span"], class_=re.compile(r"name|title", re.I))
                name = name_elem.get_text(strip=True) if name_elem else link.get_text(strip=True)

                if not name:
                    continue

                product_url = link.get("href", "")
                if not product_url.startswith("http"):
                    from src.utils import normalize_url
                    product_url = normalize_url(product_url, self.config["targets"]["base_url"])

                # Find price
                price_elem = card.find(["span", "div"], class_=re.compile(r"price", re.I))
                price = price_elem.get_text(strip=True) if price_elem else None

                # Find image
                img = card.find("img")
                image_urls = [img.get("src", "")] if img and img.get("src") else []

                product = Product(
                    name=name,
                    url=product_url,
                    price=price,
                    image_urls=image_urls,
                )
                products.append(product)
            except Exception as e:
                logger.warning(f"Failed to parse product card: {e}")
                continue

        return products

    def _extract_detail_with_bs4(self, html: str, url: str) -> list[Product]:
        """HTML fallback for product detail pages."""
        soup = BeautifulSoup(html, "lxml")

        try:
            # Product name from h1
            h1 = soup.find("h1")
            name = h1.get_text(strip=True) if h1 else ""
            if not name:
                return []

            # Price
            price_elem = soup.find(["span", "div"], class_=re.compile(r"price", re.I))
            price = price_elem.get_text(strip=True) if price_elem else None

            # SKU
            sku = None
            sku_elem = soup.find(["span", "div"], class_=re.compile(r"sku|product-code|item-number", re.I))
            if sku_elem:
                sku = sku_elem.get_text(strip=True)

            # Description
            desc_elem = soup.find(["div", "p"], class_=re.compile(r"description|product-info", re.I))
            description = desc_elem.get_text(strip=True) if desc_elem else None

            # Images
            image_urls = []
            for img in soup.find_all("img", class_=re.compile(r"product|gallery", re.I)):
                src = img.get("src", "")
                if src and "product" in src.lower():
                    image_urls.append(src)

            # Brand
            brand = None
            brand_elem = soup.find(["span", "div"], class_=re.compile(r"brand|manufacturer", re.I))
            if brand_elem:
                brand = brand_elem.get_text(strip=True)

            product = Product(
                name=name,
                brand=brand,
                sku=sku,
                url=url,
                price=price,
                description=description,
                image_urls=image_urls,
            )
            return [product]
        except Exception as e:
            logger.warning(f"HTML detail extraction failed for {url}: {e}")
            return []

    async def extract_with_llm(self, html: str, url: str) -> ExtractionResult:
        """LLM fallback: use Claude to extract product data from irregular pages."""
        if not self.llm_client:
            logger.warning("LLM client not available for extraction fallback")
            return ExtractionResult(products=[], method="llm_unavailable")

        logger.info(f"Using LLM extraction fallback for: {url}")
        try:
            truncated = html[:4000]
            response = await self.llm_client.messages.create(
                model=self.config.get("llm", {}).get("model", "claude-sonnet-4-20250514"),
                max_tokens=self.config.get("llm", {}).get("max_tokens", 4096),
                messages=[{
                    "role": "user",
                    "content": f"""Extract product information from this web page. Return JSON array of products.

URL: {url}

HTML (truncated):
{truncated}

Return a JSON array where each product has these fields (use null for missing):
- name (string, required)
- brand (string or null)
- sku (string or null)
- price (string or null)
- description (string or null)
- availability (string or null)
- image_urls (array of strings)
- category_hierarchy (array of strings)
- specifications (object with string keys/values)
- unit_pack_size (string or null)
- alternative_products (array of strings)

Return ONLY valid JSON, no markdown or explanation."""
                }]
            )

            result_text = response.content[0].text.strip()
            # Try to extract JSON from the response
            if result_text.startswith("```"):
                result_text = re.sub(r"```(?:json)?\n?", "", result_text).rstrip("`").strip()

            raw_products = json.loads(result_text)
            if not isinstance(raw_products, list):
                raw_products = [raw_products]

            products = []
            for raw in raw_products:
                try:
                    product = Product(
                        name=raw.get("name", ""),
                        brand=raw.get("brand"),
                        sku=raw.get("sku"),
                        category_hierarchy=raw.get("category_hierarchy", []),
                        url=raw.get("url", url),
                        price=raw.get("price"),
                        unit_pack_size=raw.get("unit_pack_size"),
                        availability=raw.get("availability"),
                        description=raw.get("description"),
                        specifications=raw.get("specifications", {}),
                        image_urls=raw.get("image_urls", []),
                        alternative_products=raw.get("alternative_products", []),
                    )
                    if product.name:
                        products.append(product)
                except Exception as e:
                    logger.warning(f"Failed to create Product from LLM output: {e}")

            completeness = self._calculate_completeness(products)
            logger.info(f"LLM extracted {len(products)} products from {url}")

            return ExtractionResult(
                products=products,
                method="llm",
                field_completeness=completeness,
            )
        except Exception as e:
            logger.error(f"LLM extraction failed for {url}: {e}")
            return ExtractionResult(products=[], method="llm_error")

    def _calculate_completeness(self, products: list[Product]) -> dict[str, float]:
        """Calculate field completeness percentages across products."""
        if not products:
            return {}

        fields = ["name", "brand", "sku", "price", "description", "availability", "image_urls", "specifications"]
        completeness = {}

        for field in fields:
            filled = 0
            for p in products:
                value = getattr(p, field, None)
                if value:
                    if isinstance(value, (list, dict)):
                        filled += 1 if len(value) > 0 else 0
                    else:
                        filled += 1
            completeness[field] = round(filled / len(products) * 100, 1)

        return completeness
