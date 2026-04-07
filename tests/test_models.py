import pytest
from src.models import Product, Category, CrawlState, CrawlStatus, PageType, QualityReport


class TestProduct:
    def test_create_minimal(self):
        p = Product(name="Test", url="https://test.com")
        assert p.name == "Test"
        assert p.brand is None
        assert p.sku is None
        assert p.image_urls == []

    def test_create_full(self, sample_product):
        assert sample_product.name == "Test Dental Gloves"
        assert sample_product.brand == "TestBrand"
        assert sample_product.sku == "SKU-001"
        assert len(sample_product.category_hierarchy) == 2
        assert sample_product.price == "$9.99"

    def test_serialization(self, sample_product):
        data = sample_product.model_dump()
        assert isinstance(data, dict)
        assert data["name"] == "Test Dental Gloves"
        restored = Product(**data)
        assert restored.name == sample_product.name

    def test_optional_fields_default(self):
        p = Product(name="Min", url="https://test.com")
        assert p.specifications == {}
        assert p.alternative_products == []
        assert p.category_hierarchy == []


class TestCategory:
    def test_create_simple(self):
        c = Category(name="Gloves", url="https://test.com/catalog/gloves")
        assert c.name == "Gloves"
        assert c.parent is None
        assert c.subcategories == []

    def test_with_subcategories(self):
        sub = Category(name="Nitrile", url="https://test.com/catalog/gloves/nitrile")
        parent = Category(name="Gloves", url="https://test.com/catalog/gloves", subcategories=[sub])
        assert len(parent.subcategories) == 1
        assert parent.subcategories[0].name == "Nitrile"


class TestCrawlState:
    def test_default_status(self):
        cs = CrawlState(url="https://test.com")
        assert cs.status == CrawlStatus.PENDING
        assert cs.error is None

    def test_failed_state(self):
        cs = CrawlState(url="https://test.com", status=CrawlStatus.FAILED, error="404 Not Found")
        assert cs.status == CrawlStatus.FAILED
        assert cs.error == "404 Not Found"
