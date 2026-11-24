"""Recent page pictures, kept in memory so a page drawn once is not drawn again.

Copied from v1 `tools/page_cache.py` (the LRU and its key) with v1's
single-flight from `notes/agent.py` folded in: several requests for the same
cold page wait for one drawing instead of each drawing it. v1 read its size
from `XBRL_PAGE_CACHE_MAX`; here it is a constant (AGENTS.md: nothing but
secrets in `.env`).

The key is (real path, file change time, page, cap, clip, turn). The change time
means a replaced file is never served from the cache. The real path means a
file reached through a symbolic link shares one entry. A page picture is a
few hundred KB, so 64 entries is a few tens of MB.
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Callable, Optional, Tuple

MAX_ENTRIES = 64

_Clip = Tuple[float, float, float, float]
_Key = Tuple[str, int, int, int, Optional[_Clip], int]


def _mtime_ns(path: str) -> int:
    try:
        return int(os.stat(path).st_mtime_ns)
    except OSError:
        return 0


class PageCache:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._store: "OrderedDict[_Key, bytes]" = OrderedDict()
        self._lock = threading.Lock()
        self._inflight: dict[_Key, threading.Lock] = {}
        self.max_entries = max(1, max_entries)
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(path: str, page: int, cap: int, clip: Optional[_Clip] = None, rotate: int = 0) -> _Key:
        real = os.path.realpath(path)
        # Rounded so float noise from two equal requests cannot split one region.
        norm = None if clip is None else tuple(round(float(v), 6) for v in clip)
        return (real, _mtime_ns(real), page, cap, norm, int(rotate))

    def _put(self, key: _Key, data: bytes) -> None:
        with self._lock:
            self._store[key] = data
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)  # the least recently used

    def get_or_render(self, path: str, page: int, cap: int, clip: Optional[_Clip],
                      render: Callable[[], bytes], rotate: int = 0) -> bytes:
        """The cached picture, or `render()` run once however many requests
        for it arrive together. A failure caches nothing, and a request that
        was waiting for it then draws the page itself."""
        key = self.key(path, page, cap, clip, rotate)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self.hits += 1
                return self._store[key]
            self.misses += 1
            flight = self._inflight.setdefault(key, threading.Lock())
        with flight:
            with self._lock:
                if key in self._store:   # drawn by the request this one waited for
                    return self._store[key]
            try:
                data = render()
                self._put(key, data)
                return data
            finally:
                with self._lock:
                    if self._inflight.get(key) is flight:
                        del self._inflight[key]

    def reset(self) -> None:
        with self._lock:
            self._store.clear()
            self._inflight.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


CACHE = PageCache()
