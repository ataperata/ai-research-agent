"""A tiny JSON cache with expiry. Disk backed when given a directory, in memory otherwise."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class Cache:
    def __init__(
        self,
        directory: str | Path | None = None,
        ttl_seconds: float = 7 * 24 * 3600,
        clock: Callable[[], float] = time.time,
    ):
        self.directory = Path(directory).expanduser() if directory else None
        self.ttl = ttl_seconds
        self.clock = clock
        self._memory: dict[tuple[str, str], tuple[float, Any]] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _digest(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _path(self, namespace: str, key: str) -> Path:
        assert self.directory is not None
        digest = self._digest(key)
        return self.directory / namespace / digest[:2] / f"{digest}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        now = self.clock()
        if self.directory is None:
            entry = self._memory.get((namespace, key))
            if entry and now - entry[0] <= self.ttl:
                self.hits += 1
                return entry[1]
            self.misses += 1
            return None
        path = self._path(namespace, key)
        try:
            payload = json.loads(path.read_text("utf-8"))
            if payload.get("key") == key and now - float(payload["stored_at"]) <= self.ttl:
                self.hits += 1
                return payload["value"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.misses += 1
        return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        now = self.clock()
        if self.directory is None:
            self._memory[(namespace, key)] = (now, value)
            return
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"key": key, "stored_at": now, "value": value}), "utf-8")
        os.replace(tmp, path)
