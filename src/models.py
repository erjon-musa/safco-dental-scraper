from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from datetime import datetime
from enum import Enum


class CrawlStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class PageType(str, Enum):
    CATEGORY_LISTING = "category_listing"
    PRODUCT_DETAIL = "product_detail"
    SUBCATEGORY_LISTING = "subcategory_listing"
    UNKNOWN = "unknown"


class Product(BaseModel):
    name: str
    brand: Optional[str] = None
    sku: Optional[str] = None
    category_hierarchy: list[str] = Field(default_factory=list)
    url: str
    price: Optional[str] = None
    unit_pack_size: Optional[str] = None
    availability: Optional[str] = None
    description: Optional[str] = None
    specifications: dict[str, str] = Field(default_factory=dict)
    image_urls: list[str] = Field(default_factory=list)
    alternative_products: list[str] = Field(default_factory=list)


class Category(BaseModel):
    name: str
    url: str
    parent: Optional[str] = None
    subcategories: list["Category"] = Field(default_factory=list)


class CrawlState(BaseModel):
    url: str
    status: CrawlStatus = CrawlStatus.PENDING
    page_type: Optional[PageType] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None


class ClassificationResult(BaseModel):
    page_type: PageType
    confidence: float = 1.0
    method: str = "url_pattern"


class ExtractionResult(BaseModel):
    products: list[Product] = Field(default_factory=list)
    method: str = "json_ld"
    field_completeness: dict[str, float] = Field(default_factory=dict)


class QualityReport(BaseModel):
    total_products: int = 0
    valid_products: int = 0
    duplicates_removed: int = 0
    field_completeness: dict[str, float] = Field(default_factory=dict)
