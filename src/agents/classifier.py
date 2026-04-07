import logging
import re
from urllib.parse import urlparse

from src.models import ClassificationResult, PageType

logger = logging.getLogger(__name__)


class ClassifierAgent:
    """Classifies web pages by type using URL patterns and optional LLM fallback."""

    def __init__(self, config: dict, llm_client=None):
        self.config = config
        self.llm_client = llm_client  # anthropic.AsyncAnthropic client, optional

    def classify(self, url: str, html: str = "") -> ClassificationResult:
        """Classify a page by its type.

        Primary: URL pattern matching
        Fallback: LLM classification for ambiguous pages
        """
        path = urlparse(url).path.rstrip("/")

        # Pattern 1: Product detail page /product/slug
        if re.match(r"^/product/[\w-]+$", path):
            logger.debug(f"Classified as product_detail (URL pattern): {url}")
            return ClassificationResult(
                page_type=PageType.PRODUCT_DETAIL,
                confidence=0.95,
                method="url_pattern",
            )

        # Pattern 2: Top-level category /catalog/slug
        if re.match(r"^/catalog/[\w-]+$", path):
            logger.debug(f"Classified as category_listing (URL pattern): {url}")
            return ClassificationResult(
                page_type=PageType.CATEGORY_LISTING,
                confidence=0.9,
                method="url_pattern",
            )

        # Pattern 3: Subcategory /catalog/parent/child
        if re.match(r"^/catalog/[\w-]+/[\w-]+$", path):
            logger.debug(f"Classified as subcategory_listing (URL pattern): {url}")
            return ClassificationResult(
                page_type=PageType.SUBCATEGORY_LISTING,
                confidence=0.9,
                method="url_pattern",
            )

        # Fallback: LLM classification if HTML provided and client available
        if html and self.llm_client:
            return self._classify_with_llm(url, html)

        logger.warning(f"Could not classify: {url}")
        return ClassificationResult(
            page_type=PageType.UNKNOWN,
            confidence=0.0,
            method="none",
        )

    async def classify_async(self, url: str, html: str = "") -> ClassificationResult:
        """Async version of classify with LLM fallback."""
        # Try URL pattern first (synchronous)
        result = self.classify(url)
        if result.page_type != PageType.UNKNOWN:
            return result

        # LLM fallback
        if html and self.llm_client:
            return await self._classify_with_llm_async(url, html)

        return result

    def _classify_with_llm(self, url: str, html: str) -> ClassificationResult:
        """Synchronous LLM classification fallback (for non-async contexts)."""
        logger.info(f"Using LLM fallback for classification: {url}")
        # In sync context, return unknown -- caller should use async version
        return ClassificationResult(
            page_type=PageType.UNKNOWN,
            confidence=0.0,
            method="llm_unavailable_sync",
        )

    async def _classify_with_llm_async(self, url: str, html: str) -> ClassificationResult:
        """Use Claude API to classify ambiguous pages."""
        logger.info(f"Using LLM fallback for classification: {url}")
        try:
            truncated_html = html[:2000]
            response = await self.llm_client.messages.create(
                model=self.config.get("llm", {}).get("model", "claude-sonnet-4-20250514"),
                max_tokens=100,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Classify this web page. URL: {url}\n\n"
                            f"HTML (truncated):\n{truncated_html}\n\n"
                            "Respond with ONLY one of: "
                            "category_listing, product_detail, subcategory_listing, unknown"
                        ),
                    }
                ],
            )
            page_type_str = response.content[0].text.strip().lower()

            type_map = {
                "category_listing": PageType.CATEGORY_LISTING,
                "product_detail": PageType.PRODUCT_DETAIL,
                "subcategory_listing": PageType.SUBCATEGORY_LISTING,
            }

            page_type = type_map.get(page_type_str, PageType.UNKNOWN)
            logger.info(f"LLM classified {url} as {page_type.value}")

            return ClassificationResult(
                page_type=page_type,
                confidence=0.7,
                method="llm",
            )
        except Exception as e:
            logger.error(f"LLM classification failed for {url}: {e}")
            return ClassificationResult(
                page_type=PageType.UNKNOWN,
                confidence=0.0,
                method="llm_error",
            )
