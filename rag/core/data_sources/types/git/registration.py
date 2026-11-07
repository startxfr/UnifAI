"""Git registration: one source = a public GitHub repository at a ref, narrowed to some paths (R-530)."""
from __future__ import annotations

import hashlib
from functools import cached_property
from typing import Any

from core.data_sources.classification import classification_error, source_classification
from core.data_sources.types.confluence.registration import ConfluenceRegistration
from core.registration.domain.model import BaseSourceData
from infrastructure.sources.git.connector import GitError, parse_repo


class GitRegistration(ConfluenceRegistration):
    """Registers (or re-registers, idempotently) a repository; persistence and ownership are shared with the Confluence
    and web sources, only the identity and the form fields differ."""
    DATA_SOURCE_TYPE = "GIT"

    @cached_property
    def source_data(self) -> BaseSourceData:
        url = (self.instance.get("url") or "").strip()
        ref = (self.instance.get("ref") or "main").strip()
        paths = [p.strip().strip("/") for p in (self.instance.get("paths") or []) if p and p.strip()]
        source_id = hashlib.sha256("|".join([url, ref, *sorted(paths)]).encode()).hexdigest()[:24]
        return BaseSourceData(source_id=source_id, source_name=self.instance.get("name") or url,
                              pipeline_id=f"git_{source_id}",
                              form_data={"url": url, "ref": ref, "paths": paths,
                                         "include": list(self.instance.get("include") or []),
                                         "exclude": list(self.instance.get("exclude") or []),
                                         "max_files": int(self.instance.get("maxFiles") or 2000),
                                         "attributes": dict(self.instance.get("attributes") or {}),
                                         "attribute_files": [f.strip().strip("/") for f in (self.instance.get("attributeFiles") or []) if f and f.strip()],
                                         "metadata": dict(self.instance.get("metadata") or {}),
                                         "classification": source_classification(self.instance)})

    def run_validator(self) -> tuple[bool, dict[str, Any] | None]:
        form = self.source_data.form_data
        name = self.source_data.source_name

        def refuse(issue: str, message: str) -> tuple[bool, dict[str, Any]]:
            return False, {"source_name": name, "issue_type": issue, "message": message, "validator": "GitRegistration"}

        if not form["url"]:
            return refuse("MissingField", "missing url")
        try:
            parse_repo(form["url"])
        except GitError as exc:
            return refuse("InvalidUrl", str(exc))
        if error := classification_error(form["classification"]):
            return refuse("InvalidValue", error)
        return True, None
