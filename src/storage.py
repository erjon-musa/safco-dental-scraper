import csv
import json
import os
from datetime import datetime

import aiosqlite

from src.models import Product


class CheckpointDB:
    def __init__(self, db_path: str = "output/checkpoint.db"):
        self.db_path = db_path

    async def init(self):
        """Create tables if they don't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_state (
                    url TEXT PRIMARY KEY,
                    status TEXT,
                    page_type TEXT,
                    timestamp TEXT,
                    error TEXT
                )
                """
            )
            await db.commit()

    async def upsert(
        self,
        url: str,
        status: str,
        page_type: str | None = None,
        error: str | None = None,
    ):
        """Insert or update a crawl state record."""
        timestamp = datetime.now().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO crawl_state (url, status, page_type, timestamp, error)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    status = excluded.status,
                    page_type = excluded.page_type,
                    timestamp = excluded.timestamp,
                    error = excluded.error
                """,
                (url, status, page_type, timestamp, error),
            )
            await db.commit()

    async def get_pending_urls(self) -> list[str]:
        """Return all URLs with pending status."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT url FROM crawl_state WHERE status = 'pending'"
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_by_status(self, status: str) -> list[dict]:
        """Return all records matching the given status."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT url, status, page_type, timestamp, error FROM crawl_state WHERE status = ?",
                (status,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_completed_count(self) -> int:
        """Return the count of completed URLs."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM crawl_state WHERE status = 'completed'"
            )
            row = await cursor.fetchone()
            return row[0]


def save_json(products: list[Product], path: str):
    """Save products as pretty-printed JSON."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    data = [p.model_dump() for p in products]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def save_csv(products: list[Product], path: str):
    """Save products as CSV with flattened fields."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    if not products:
        return

    fieldnames = [
        "name",
        "brand",
        "sku",
        "category_hierarchy",
        "url",
        "price",
        "unit_pack_size",
        "availability",
        "description",
        "specifications",
        "image_urls",
        "alternative_products",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for product in products:
            row = product.model_dump()
            # Flatten list/dict fields
            row["image_urls"] = ";".join(row.get("image_urls", []))
            row["alternative_products"] = ";".join(row.get("alternative_products", []))
            row["category_hierarchy"] = " > ".join(row.get("category_hierarchy", []))
            row["specifications"] = json.dumps(row.get("specifications", {}))
            writer.writerow(row)
