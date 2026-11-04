"""Web pipeline: incremental sync of public pages.

The source's type_data keeps a manifest {url: {etag, last_modified, content_hash, title}}. A run fetches
the seeds and the pages they link to; a page is embedded only when it is new or its body hash changed.
The points of changed and vanished pages are deleted before the new ones are stored (stale_point_filters),
so a run over unchanged pages embeds nothing. A page that cannot be read keeps its manifest entry: a
network error never deletes knowledge.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections.abc import Callable
from typing import Any

from core.data_sources.classification import chunk_classification, classification_changed
from core.data_sources.service import DataSourceService
from core.pipeline.domain.port import PipelineContext, SourcePipelinePort
from core.vector.domain.embedder import EmbeddingGenerator
from core.vector.domain.model import VectorChunk
from infrastructure.sources.confluence.html_text import html_to_text
from infrastructure.sources.web.connector import WebConnector, WebPage

from core.data_sources.deletion_guard import SyncDegraded, refuse_vanished_chunks, refuse_vanished_pages

logger = logging.getLogger("rag_pipeline")

POINT_NAMESPACE = uuid.UUID("6d0c5b1e-8a47-4f0e-b3c9-2e7f1a9d4c85")
_TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>|<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


def page_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def page_title(html: str, url: str) -> str:
    match = _TITLE.search(html)
    title = _TAGS.sub("", match.group(1) or match.group(2) or "") if match else ""
    return " ".join(title.split()) or url


class WebCrawlDegraded(SyncDegraded):
    """The crawl found far fewer pages than the source holds: failing keeps the index as it is."""


_CAUSE = "the site probably blocked or throttled the crawl"


class WebPipelineHandler(SourcePipelinePort):

    def __init__(self, connector_factory: Callable[[], WebConnector], chunker: Any,
                 embedder: EmbeddingGenerator, data_source_service: DataSourceService,
                 min_chunk_chars: int = 200, index_version: int = 1, max_deleted_ratio: float = 0.5) -> None:
        self._connector_factory = connector_factory
        # A source synced at an older index version re-embeds every page (sparse encoder migration).
        self._index_version = index_version
        # Chunks with less real text than this (navigation fragments, a lone heading) are not embedded: they would
        # take search slots with nothing to say. 0 keeps every chunk.
        self._min_chunk_chars = max(0, min_chunk_chars)
        self._max_deleted_ratio = max(0.0, max_deleted_ratio)
        self._chunker = chunker
        self._embedder = embedder
        self._sources = data_source_service
        self._manifest: dict[str, dict[str, Any]] = {}
        self._changed: list[str] = []
        self._deleted: list[str] = []
        self._unchanged = 0
        self._classification = ""

    @property
    def source_type(self) -> str:
        return "WEB"

    def _settings(self, context: PipelineContext) -> dict[str, Any]:
        source = self._sources.get_by_id(context.source_id)
        if source is None:
            raise ValueError(f"Web source {context.source_id} is not registered")
        return source.type_data or {}

    def collect(self, context: PipelineContext) -> list[WebPage]:
        settings = self._settings(context)
        previous: dict[str, dict[str, Any]] = dict(settings.get("pages") or {})
        self._classification = str(settings.get("classification") or "")
        reingest = int(settings.get("index_version") or 1) < self._index_version or classification_changed(settings)
        if reingest:
            logger.info(f"Web source {context.source_name}: re-ingesting every page (index version {self._index_version}, "
                        f"classification {settings.get('classification') or 'none'})")
        connector = self._connector_factory()
        manifest: dict[str, dict[str, Any]] = {}
        changed: list[WebPage] = []
        # Without the previous manifest the connector fetches every page unconditionally.
        for url, page in connector.iter_pages(settings["urls"], {} if reingest else previous, settings.get("include", []),
                                              settings.get("exclude", []), settings.get("crawl", "redhat-docs"),
                                              int(settings.get("max_pages", 50))):
            old = previous.get(url)
            if page is None:  # not modified, or unreadable: keep what is indexed
                if old is not None:
                    manifest[url] = old
                continue
            entry = {"etag": page.etag, "last_modified": page.last_modified, "content_hash": page.content_hash,
                     "title": (old or {}).get("title") if old and old.get("content_hash") == page.content_hash
                     else page_title(page.html, url)}
            manifest[url] = entry
            if reingest or old is None or old.get("content_hash") != page.content_hash:
                changed.append(page)
        self._manifest = manifest
        self._changed = [p.url for p in changed]
        deleted = sorted(set(previous) - set(manifest))
        try:
            refuse_vanished_pages(f"web source {context.source_name}", len(previous), len(manifest), len(deleted),
                                  self._max_deleted_ratio, _CAUSE)
        except SyncDegraded as e:
            raise WebCrawlDegraded(str(e)) from e
        self._deleted = deleted
        self._unchanged = len(manifest) - len(changed)
        logger.info(f"Web source {context.source_name}: {len(manifest)} pages, {len(changed)} new or changed, "
                    f"{len(self._deleted)} deleted, {self._unchanged} unchanged")
        return changed

    def process(self, context: PipelineContext, raw_data: list[WebPage]) -> list[dict[str, Any]]:
        settings = self._settings(context)
        extra = {**dict(settings.get("metadata") or {}), **chunk_classification(settings)}
        docs = []
        for page in raw_data:
            text = html_to_text(page.html)
            if not text:
                continue
            title = self._manifest[page.url]["title"]
            docs.append({
                "content": f"# {title}\n\n{text}",
                "filename": title,
                "metadata": {**extra, "page_id": page_id(page.url), "title": title, "url": page.url,
                             "last_modified": page.last_modified},
            })
        return docs

    def chunk_and_embed(self, context: PipelineContext, processed: list[dict[str, Any]]) -> list[VectorChunk]:
        chunk_dicts: list[dict[str, Any]] = []
        skipped = 0
        for doc in processed:
            pieces = self._chunker.chunk_content([{"content": doc["content"], "filename": doc["filename"]}])
            for i, piece in enumerate(pieces):
                text = piece.get("text") or piece.get("content", "")
                if len(" ".join(text.split())) < self._min_chunk_chars:
                    skipped += 1
                    continue  # the index is kept, so the ids of the other chunks of the page do not move
                chunk_dicts.append({
                    "text": text,
                    "id": str(uuid.uuid5(POINT_NAMESPACE, f"{context.source_id}:{doc['metadata']['page_id']}:{i}")),
                    "metadata": {**doc["metadata"], "chunk_index": i, "source_id": context.source_id,
                                 "source_type": self.source_type, "owner_id": context.owner_id},
                })
        if skipped:
            logger.info("Web source %s: %d chunks under %d characters skipped", context.source_id, skipped,
                        self._min_chunk_chars)
        if not chunk_dicts:
            return []
        embedded = self._embedder.generate_embeddings(chunk_dicts)
        return [VectorChunk(text=d["text"], id=d["id"], metadata=d["metadata"],
                            embedding=d["embedding"].tolist() if hasattr(d["embedding"], "tolist") else d["embedding"])
                for d in embedded]

    def guard_stale(self, context: PipelineContext, vector_repo: Any) -> None:
        """Refuse a sync whose vanished pages hold most of the source's chunks in the vector store.

        The manifest guard in collect() trusts the manifest; a source whose manifest was cut down by an earlier
        degraded sync lists few pages for many chunks and would pass it. The store is the truth.
        """
        try:
            refuse_vanished_chunks(f"web source {context.source_name}", context.source_id,
                                   [page_id(u) for u in self._deleted], vector_repo, self._max_deleted_ratio, _CAUSE)
        except SyncDegraded as e:
            raise WebCrawlDegraded(str(e)) from e

    def stale_point_filters(self, context: PipelineContext) -> list[dict[str, Any]]:
        """Points to delete before storing: every chunk of a changed or vanished page."""
        stale = [page_id(u) for u in self._changed + self._deleted]
        if not stale:
            return []
        return [{"metadata.source_id": context.source_id, "metadata.page_id": stale}]

    def get_summary(self, context: PipelineContext, collected: Any) -> dict[str, Any]:
        return {"pages": self._manifest, "page_count": len(self._manifest), "pages_changed": len(self._changed),
                "pages_deleted": len(self._deleted), "pages_unchanged": self._unchanged,
                "index_version": self._index_version,
                "ingested_classification": self._classification}

    def cleanup(self, context: PipelineContext) -> bool:
        return True
