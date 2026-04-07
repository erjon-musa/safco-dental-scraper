import pytest
from src.agents.extractor import ExtractorAgent


class TestExtractorJsonLd:
    def setup_method(self):
        self.extractor = ExtractorAgent(config={"targets": {"base_url": "https://www.safcodental.com"}, "llm": {}})

    def test_extract_from_detail_json_ld(self, sample_json_ld_product_html):
        result = self.extractor.extract_from_detail(sample_json_ld_product_html, "https://www.safcodental.com/product/alasta-pro")
        assert len(result.products) == 1
        p = result.products[0]
        assert p.name == "Alasta Pro Nitrile Gloves"
        assert p.sku == "ALG-100"
        assert p.brand == "Alasta"
        assert result.method == "json_ld"

    def test_extract_from_listing_json_ld(self, sample_json_ld_listing_html):
        result = self.extractor.extract_from_listing(sample_json_ld_listing_html, "https://www.safcodental.com/catalog/gloves")
        assert len(result.products) == 2
        assert result.products[0].name == "Product 1"
        assert result.method == "json_ld"

    def test_extract_empty_html(self):
        result = self.extractor.extract_from_detail("<html><body></body></html>", "https://test.com/product/x")
        assert len(result.products) == 0

    def test_parse_json_ld_invalid(self):
        html = '<html><head><script type="application/ld+json">invalid json</script></head><body></body></html>'
        data = self.extractor._parse_json_ld(html)
        assert data == []

    def test_field_completeness(self, sample_json_ld_product_html):
        result = self.extractor.extract_from_detail(sample_json_ld_product_html, "https://test.com/p")
        assert "name" in result.field_completeness
        assert result.field_completeness["name"] == 100.0
