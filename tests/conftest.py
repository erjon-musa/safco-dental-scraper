import pytest
from src.models import Product


@pytest.fixture
def sample_product():
    return Product(
        name="Test Dental Gloves",
        brand="TestBrand",
        sku="SKU-001",
        category_hierarchy=["Gloves", "Nitrile Gloves"],
        url="https://www.safcodental.com/product/test-gloves",
        price="$9.99",
        unit_pack_size="Box of 100",
        availability="In Stock",
        description="High quality nitrile dental exam gloves",
        specifications={"Material": "Nitrile", "Size": "Medium"},
        image_urls=["https://www.safcodental.com/img/test.jpg"],
        alternative_products=["https://www.safcodental.com/product/alt-gloves"],
    )


@pytest.fixture
def sample_products():
    return [
        Product(name="Product A", url="https://test.com/p1", sku="SKU-A", price="$10.00", brand="BrandA"),
        Product(name="Product B", url="https://test.com/p2", sku="SKU-B", price="$20.00", brand="BrandB"),
        Product(name="Product A", url="https://test.com/p1", sku="SKU-A", price="$10.00", brand="BrandA"),  # duplicate
    ]


@pytest.fixture
def sample_json_ld_product_html():
    return '''<html><head>
    <script type="application/ld+json">
    {
        "@type": "Product",
        "name": "Alasta Pro Nitrile Gloves",
        "sku": "ALG-100",
        "url": "https://www.safcodental.com/product/alasta-pro",
        "brand": {"name": "Alasta"},
        "description": "Premium nitrile exam gloves",
        "image": "https://www.safcodental.com/img/alasta.jpg",
        "offers": {
            "price": "12.99",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
        },
        "additionalProperty": [
            {"name": "Material", "value": "Nitrile"},
            {"name": "Size", "value": "Large"}
        ]
    }
    </script></head><body></body></html>'''


@pytest.fixture
def sample_json_ld_listing_html():
    return '''<html><head>
    <script type="application/ld+json">
    {
        "@type": "ItemList",
        "itemListElement": [
            {
                "name": "Product 1",
                "url": "https://www.safcodental.com/product/prod-1",
                "sku": "P1",
                "image": "https://test.com/img1.jpg",
                "offers": {"price": "5.99", "priceCurrency": "USD"}
            },
            {
                "name": "Product 2",
                "url": "https://www.safcodental.com/product/prod-2",
                "sku": "P2",
                "image": "https://test.com/img2.jpg"
            }
        ]
    }
    </script></head><body></body></html>'''
