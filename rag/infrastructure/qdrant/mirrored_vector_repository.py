"""Write to several collections, read from one: the index migration of a hybrid collection.

When the sparse encoder changes version, its vectors are not comparable with the old ones, so the new version
lives in its own collection. During the migration every write (store, delete) goes to the old and the new
collections, and searches keep reading the old one; once every source has been re-ingested into the new one,
reads switch to it and the old collection is dropped. Searches never see a half-filled collection.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.vector.domain.repository import VectorRepository


class MirroredVectorRepository(VectorRepository):
    def __init__(self, read: VectorRepository, writes: List[VectorRepository]):
        super().__init__(getattr(read, "collection_name", None) or getattr(read, "_collection_name", ""))
        if read not in writes:
            raise ValueError("the read collection must also be written")
        self._read = read
        self._writes = writes

    def initialize(self) -> None:
        for repo in self._writes:
            repo.initialize()

    def store(self, chunks) -> int:
        stored = 0
        for repo in self._writes:
            n = repo.store(chunks)
            if repo is self._read:
                stored = n
        return stored

    def search(self, *args, **kwargs):
        return self._read.search(*args, **kwargs)

    def count(self, filters: Optional[Dict[str, Any]] = None, exact: bool = False) -> int:
        return self._read.count(filters, exact=exact)

    def delete(self, ids, *args, **kwargs):
        return [repo.delete(ids, *args, **kwargs) for repo in self._writes][self._writes.index(self._read)]

    def delete_by_filter(self, filters, *args, **kwargs):
        return [repo.delete_by_filter(filters, *args, **kwargs) for repo in self._writes][self._writes.index(self._read)]

    def delete_by_source_id(self, source_id, *args, **kwargs):
        return [repo.delete_by_source_id(source_id, *args, **kwargs) for repo in self._writes][self._writes.index(self._read)]
