import asyncio
import csv
import json
import os
import tempfile

import pytest

from src.models import Product
from src.storage import CheckpointDB, save_csv, save_json


class TestSaveJson:
    def test_save_and_load(self, sample_product):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            save_json([sample_product], path)
            with open(path) as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]["name"] == "Test Dental Gloves"
        finally:
            os.unlink(path)

    def test_save_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            save_json([], path)
            with open(path) as f:
                data = json.load(f)
            assert data == []
        finally:
            os.unlink(path)


class TestSaveCsv:
    def test_save_and_load(self, sample_product):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            save_csv([sample_product], path)
            with open(path) as f:
                rows = list(csv.DictReader(f))
            assert len(rows) == 1
            assert rows[0]["name"] == "Test Dental Gloves"
        finally:
            os.unlink(path)


class TestCheckpointDB:
    @pytest.fixture
    def db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        yield path
        if os.path.exists(path):
            os.unlink(path)

    def test_upsert_and_query(self, db_path):
        async def _test():
            db = CheckpointDB(db_path)
            await db.init()
            await db.upsert("https://test.com/p1", "completed")
            await db.upsert("https://test.com/p2", "pending")

            pending = await db.get_pending_urls()
            assert len(pending) == 1
            assert pending[0] == "https://test.com/p2"

            count = await db.get_completed_count()
            assert count == 1

        asyncio.run(_test())

    def test_upsert_update(self, db_path):
        async def _test():
            db = CheckpointDB(db_path)
            await db.init()
            await db.upsert("https://test.com/p1", "pending")
            await db.upsert("https://test.com/p1", "completed")

            pending = await db.get_pending_urls()
            assert len(pending) == 0

            count = await db.get_completed_count()
            assert count == 1

        asyncio.run(_test())
