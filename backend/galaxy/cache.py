"""Tiny SQLite key-value cache with per-read max age."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DAY = 24 * 3600
# Bump when the shape of anything cached changes; old entries are then simply ignored.
CACHE_VERSION = "v1"


class Cache:
    def __init__(self, path: str | Path = ":memory:", version: str = CACHE_VERSION):
        self.prefix = f"{version}:"
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, ts REAL)"
            )
            self._db.commit()

    def get(self, key: str, max_age: float = DAY) -> Any | None:
        with self._lock:
            row = self._db.execute(
                "SELECT value, ts FROM kv WHERE key = ?", (self.prefix + key,)
            ).fetchone()
        if row is None or time.time() - row[1] > max_age:
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any) -> None:
        text = json.dumps(value, separators=(",", ":"))
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO kv (key, value, ts) VALUES (?, ?, ?)",
                (self.prefix + key, text, time.time()),
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
