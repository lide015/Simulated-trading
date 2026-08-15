from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from taiwan_stock_ai.storage.db import get_connection


@pytest.fixture()
def db_conn(tmp_path: Path):
    """每個測試都用全新的暫存 DuckDB 檔案,測試之間不互相汙染。"""
    db_path = tmp_path / "test.duckdb"
    conn = get_connection(str(db_path))
    yield conn
    conn.close()
