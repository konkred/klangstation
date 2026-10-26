"""Kleiner persistenter Key-Value-Cache (SQLite) fuer Online-Metadaten."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

_MISSING = object()


class Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, expires REAL)")
        self.db.execute("DELETE FROM kv WHERE expires < ?", (time.time(),))
        self.db.commit()

    def get(self, key: str, default: Any = _MISSING) -> Any:
        row = self.db.execute("SELECT v, expires FROM kv WHERE k = ?", (key,)).fetchone()
        if row and row[1] >= time.time():
            return json.loads(row[0])
        return None if default is _MISSING else default

    def has(self, key: str) -> bool:
        row = self.db.execute("SELECT expires FROM kv WHERE k = ?", (key,)).fetchone()
        return bool(row and row[0] >= time.time())

    def set(self, key: str, value: Any, ttl: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?, ?)",
                        (key, json.dumps(value), time.time() + ttl))
        self.db.commit()

    def lookup(self, key: str) -> "tuple[bool, Optional[Any]]":
        """(gefunden, wert) - unterscheidet 'nicht im Cache' von 'gecachtes None'."""
        row = self.db.execute("SELECT v, expires FROM kv WHERE k = ?", (key,)).fetchone()
        if row and row[1] >= time.time():
            return True, json.loads(row[0])
        return False, None
