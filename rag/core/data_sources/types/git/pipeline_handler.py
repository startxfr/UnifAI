"""Git pipeline: incremental sync of a public repository (R-530).

Same shape as the web pipeline (a manifest {document url: {content_hash, title}} in the source's type_data, only new or
changed documents are embedded, the points of changed and vanished ones are deleted first), with one more shortcut: the
commit of the ref is kept, and a sync whose ref still points at it downloads nothing.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from core.data_sources.classification import chunk_classification, classification_changed
from core.data_sources.deletion_guard import SyncDegraded, refuse_vanished_pages
from core.data_sources.types.web.pipeline_handler import WebPipelineHandler, page_id
from core.pipeline.domain.port import PipelineContext
from infrastructure.sources.git.connector import GitConnector, GitFile

logger = logging.getLogger("rag_pipeline")

_CAUSE = "the repository layout probably changed (a moved path, a wrong ref or a path filter)"


class GitSyncDegraded(SyncDegraded):
    """The repository holds far fewer documents than the source did: failing keeps the index as it is."""


# What selects and renders the documents: a sync at the same commit is only skipped when none of it changed.
_SELECTION = ("url", "ref", "paths", "include", "exclude", "max_files", "attributes", "attribute_files")


def selection_hash(settings: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({k: settings.get(k) for k in _SELECTION}, sort_keys=True, default=str).encode()).hexdigest()[:16]


class GitPipelineHandler(WebPipelineHandler):

    def __init__(self, connector_factory: Callable[[], GitConnector], **kwargs: Any) -> None:
        super().__init__(connector_factory=connector_factory, **kwargs)
        self._commit = ""
        self._selection = ""
        self._files: dict[str, GitFile] = {}

    @property
    def source_type(self) -> str:
        return "GIT"

    def collect(self, context: PipelineContext) -> list[GitFile]:
        settings = self._settings(context)
        previous: dict[str, dict[str, Any]] = dict(settings.get("pages") or {})
        self._classification = str(settings.get("classification") or "")
        reingest = int(settings.get("index_version") or 1) < self._index_version or classification_changed(settings)
        connector = self._connector_factory()
        commit = connector.head_commit(settings["url"], settings.get("ref", "main"))
        self._commit = commit
        self._selection = selection_hash(settings)
        if commit and commit == settings.get("commit") and self._selection == settings.get("settings_hash") and previous and not reingest:
            self._manifest, self._changed, self._deleted, self._unchanged = previous, [], [], len(previous)
            logger.info(f"Git source {context.source_name}: ref still at {commit[:12]}, nothing to do")
            return []
        files = connector.fetch(settings["url"], settings.get("ref", "main"), settings.get("paths", []),
                                settings.get("include", []), settings.get("exclude", []), int(settings.get("max_files", 2000)),
                                dict(settings.get("attributes") or {}), settings.get("attribute_files", []))
        self._files = {f.url: f for f in files}
        manifest = {f.url: {"content_hash": f.content_hash, "title": f.title, "path": f.path} for f in files}
        changed = [f for f in files if reingest or f.url not in previous or previous[f.url].get("content_hash") != f.content_hash]
        deleted = sorted(set(previous) - set(manifest))
        try:
            refuse_vanished_pages(f"git source {context.source_name}", len(previous), len(manifest), len(deleted),
                                  self._max_deleted_ratio, _CAUSE)
        except SyncDegraded as e:
            raise GitSyncDegraded(str(e)) from e
        self._manifest, self._changed, self._deleted = manifest, [f.url for f in changed], deleted
        self._unchanged = len(manifest) - len(changed)
        logger.info(f"Git source {context.source_name}: {len(manifest)} documents, {len(changed)} new or changed, "
                    f"{len(deleted)} deleted at {commit[:12] or 'unknown commit'}")
        return changed

    def process(self, context: PipelineContext, raw_data: list[GitFile]) -> list[dict[str, Any]]:
        settings = self._settings(context)
        extra = {**dict(settings.get("metadata") or {}), **chunk_classification(settings)}
        return [{"content": f"# {f.title}\n\n{f.text}" if not f.text.lstrip().startswith("#") else f.text,
                 "filename": f.title,
                 "metadata": {**extra, "page_id": page_id(f.url), "title": f.title, "url": f.url, "path": f.path}}
                for f in raw_data]

    def get_summary(self, context: PipelineContext, collected: Any) -> dict[str, Any]:
        return {**super().get_summary(context, collected), "commit": self._commit, "settings_hash": self._selection}
