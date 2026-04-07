import pytest
from src.agents.validator import ValidatorAgent
from src.models import Product


class TestValidation:
    def setup_method(self):
        self.validator = ValidatorAgent(config={})

    def test_valid_product(self, sample_product):
        is_valid, errors = self.validator.validate(sample_product)
        assert is_valid
        assert errors == []

    def test_missing_name(self):
        p = Product(name="", url="https://test.com")
        is_valid, errors = self.validator.validate(p)
        assert not is_valid
        assert "Missing product name" in errors

    def test_invalid_url(self):
        p = Product(name="Test", url="not-a-url")
        is_valid, errors = self.validator.validate(p)
        assert not is_valid

    def test_invalid_price(self):
        p = Product(name="Test", url="https://test.com", price="free")
        is_valid, errors = self.validator.validate(p)
        assert not is_valid
        assert any("price" in e.lower() for e in errors)


class TestDeduplication:
    def setup_method(self):
        self.validator = ValidatorAgent(config={})

    def test_remove_sku_duplicates(self, sample_products):
        result = self.validator.deduplicate(sample_products)
        assert len(result) == 2

    def test_remove_url_duplicates(self):
        products = [
            Product(name="A", url="https://test.com/p1"),
            Product(name="B", url="https://test.com/p1"),
        ]
        result = self.validator.deduplicate(products)
        assert len(result) == 1

    def test_remove_name_brand_duplicates(self):
        products = [
            Product(name="Glove A", url="https://test.com/p1", brand="Brand1"),
            Product(name="Glove A", url="https://test.com/p2", brand="Brand1"),
        ]
        result = self.validator.deduplicate(products)
        assert len(result) == 1

    def test_no_duplicates(self):
        products = [
            Product(name="A", url="https://test.com/p1", sku="S1"),
            Product(name="B", url="https://test.com/p2", sku="S2"),
        ]
        result = self.validator.deduplicate(products)
        assert len(result) == 2


class TestQualityReport:
    def setup_method(self):
        self.validator = ValidatorAgent(config={})

    def test_report_counts(self, sample_products):
        report = self.validator.quality_report(sample_products)
        assert report.total_products == 3
        assert report.valid_products == 3

    def test_field_completeness(self):
        products = [
            Product(name="A", url="https://test.com/p1", price="$10"),
            Product(name="B", url="https://test.com/p2"),
        ]
        report = self.validator.quality_report(products)
        assert report.field_completeness["name"] == 100.0
        assert report.field_completeness["price"] == 50.0
