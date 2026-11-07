"""R-530: a public GitHub repository as a RAG source."""
import io
import tarfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.data_sources.types.git.pipeline_handler import GitPipelineHandler, GitSyncDegraded
from core.data_sources.types.git.registration import GitRegistration
from core.data_sources.types.web.pipeline_handler import page_id
from core.pipeline.domain.port import PipelineContext
from infrastructure.sources.git.asciidoc import adoc_to_text, title_of
from infrastructure.sources.git.connector import GitConnector, GitError, parse_repo, selected

pytestmark = pytest.mark.unit

ASSEMBLY = """:_mod-docs-content-type: ASSEMBLY
[id="installing-ocp"]
= Installing {product-title}
:product-title: OpenShift Container Platform
:context: installing

// a comment
include::modules/intro.adoc[leveloffset=+1]

== Next steps

NOTE: Read {product-title} release notes.

ifdef::openshift-enterprise[]
Enterprise only.
endif::[]
"""
MODULE = """[id="intro_{context}"]
= Introduction

[source,terminal]
----
$ oc get nodes
----
"""
FILES = {"installing/index.adoc": ASSEMBLY.replace("modules/intro.adoc", "../modules/intro.adoc"),
         "modules/intro.adoc": MODULE, "README.md": "# Repo\n\nHello", "images/a.png": "x"}


def test_asciidoc_includes_attributes_and_headings_become_prose():
    text = adoc_to_text("installing/index.adoc", {k: v for k, v in FILES.items() if k.endswith((".adoc", ".md"))})
    assert text.startswith("# Installing OpenShift Container Platform")
    assert "## Introduction" in text and "$ oc get nodes" in text and "----" not in text
    assert "Note: Read OpenShift Container Platform release notes." in text
    assert "a comment" not in text and "ifdef" not in text and "[id=" not in text
    assert title_of(text, "x") == "Installing OpenShift Container Platform"


def test_a_missing_or_cyclic_include_is_dropped_not_fatal():
    files = {"a.adoc": "= A\ninclude::b.adoc[]\ninclude::missing.adoc[]\ntext", "b.adoc": "include::a.adoc[]\nfrom b"}
    assert adoc_to_text("a.adoc", files) == "# A\nfrom b\ntext"


def test_only_github_https_repositories_are_accepted():
    assert parse_repo("https://github.com/openshift/openshift-docs") == ("openshift", "openshift-docs")
    assert parse_repo("https://github.com/o/r.git/") == ("o", "r")
    for bad in ["http://github.com/o/r", "https://gitlab.com/o/r", "https://user@github.com/o/r", "https://github.com/o", "ssh://github.com/o/r"]:
        with pytest.raises(GitError):
            parse_repo(bad)


def test_document_selection_by_path_prefix_and_globs():
    assert selected("installing/a.adoc", ["installing"], [], [])
    assert not selected("installing-x/a.adoc", ["installing"], [], [])
    assert not selected("installing/a.png", [], [], [])
    assert selected("a/b.md", [], ["*.md"], [])
    assert not selected("a/b.md", [], [], ["a/*"])


def _archive(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(f"repo-main/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class _Resp:
    def __init__(self, status=200, body=b"", text=""):
        self.status_code, self.raw, self.text = status, io.BytesIO(body), text

    def close(self):
        pass


def _session(files, sha="a" * 40, status=200):
    session = MagicMock()
    session.headers = {}
    calls = []

    def get(url, **kw):
        calls.append(url)
        if "api.github.com" in url:
            return _Resp(status, text=sha)
        return _Resp(200, _archive(files))
    session.get.side_effect = get
    return session, calls


def test_the_connector_reads_selected_documents_with_includes_and_blob_urls():
    session, calls = _session(FILES)
    connector = GitConnector(session=session)
    assert connector.head_commit("https://github.com/o/r", "main") == "a" * 40
    docs = connector.fetch("https://github.com/o/r", "main", paths=["installing"])
    assert [d.path for d in docs] == ["installing/index.adoc"]
    assert docs[0].url == "https://github.com/o/r/blob/main/installing/index.adoc"
    assert "oc get nodes" in docs[0].text and docs[0].title == "Installing OpenShift Container Platform"
    assert any(c.startswith("https://codeload.github.com/o/r/tar.gz/main") for c in calls)


def test_an_unknown_ref_is_an_error_and_a_rate_limit_only_means_fetch():
    with pytest.raises(GitError):
        GitConnector(session=_session(FILES, status=404)[0]).head_commit("https://github.com/o/r", "nope")
    assert GitConnector(session=_session(FILES, status=403)[0]).head_commit("https://github.com/o/r", "main") == ""
    with pytest.raises(GitError):
        GitConnector(session=_session(FILES)[0]).head_commit("https://github.com/o/r", "bad ref")


def test_registration_identity_and_validation():
    def reg(**inst):
        repo = MagicMock()
        return GitRegistration(data_source_repository=repo, upload_by="admin", instance=inst, skip_validation=True)
    ok = reg(url="https://github.com/o/r", ref="release-4.22", paths=["installing/"], name="ocp-docs")
    assert ok.run_validator() == (True, None)
    data = ok.source_data
    assert data.pipeline_id.startswith("git_") and data.form_data["paths"] == ["installing"] and data.form_data["ref"] == "release-4.22"
    assert reg(url="https://github.com/o/r", ref="a").source_data.source_id != reg(url="https://github.com/o/r", ref="b").source_data.source_id
    assert reg(url="https://gitlab.com/o/r").run_validator()[0] is False
    assert reg().run_validator()[1]["issue_type"] == "MissingField"


class _Chunker:
    def chunk_content(self, docs):
        return [{"text": d["content"]} for d in docs]


class _Embedder:
    def generate_embeddings(self, chunks):
        return [{**c, "embedding": [0.1]} for c in chunks]


CTX = PipelineContext(pipeline_id="p", source_type="GIT", source_id="s1", source_name="ocp", owner_id="admin", metadata={})


def _handler(settings, files, commit="c1", min_chunk_chars=0):
    connector = MagicMock()
    connector.head_commit.return_value = commit
    connector.fetch.return_value = files
    sources = MagicMock()
    sources.get_by_id.return_value = SimpleNamespace(type_data={"url": "https://github.com/o/r", "ref": "main", **settings})
    return GitPipelineHandler(lambda: connector, chunker=_Chunker(), embedder=_Embedder(), data_source_service=sources,
                              min_chunk_chars=min_chunk_chars), connector


def _file(path, text="body", title=None):
    from infrastructure.sources.git.connector import GitFile
    return GitFile(path=path, url=f"https://github.com/o/r/blob/main/{path}", text=text, content_hash=text, title=title or path)


def _run(handler):
    collected = handler.collect(CTX)
    chunks = handler.chunk_and_embed(CTX, handler.process(CTX, collected))
    return chunks, handler.stale_point_filters(CTX), handler.get_summary(CTX, collected)


def test_first_sync_embeds_every_document_and_records_the_commit():
    handler, _ = _handler({"metadata": {"product": "OCP"}}, [_file("a.adoc"), _file("b.adoc")])
    chunks, stale, summary = _run(handler)
    assert {c.metadata["path"] for c in chunks} == {"a.adoc", "b.adoc"}
    assert all(c.metadata["source_type"] == "GIT" and c.metadata["product"] == "OCP" for c in chunks)
    assert summary["commit"] == "c1" and summary["page_count"] == 2


def test_a_ref_that_did_not_move_downloads_nothing():
    first, _ = _handler({}, [_file("a.adoc")])
    _run(first)
    summary = first.get_summary(CTX, None)
    handler, connector = _handler({"pages": summary["pages"], "commit": "c1"}, [_file("a.adoc")])
    chunks, stale, again = _run(handler)
    assert chunks == [] and stale == [] and again["pages_unchanged"] == 1
    connector.fetch.assert_not_called()


def test_a_moved_ref_replaces_only_the_changed_document_and_removes_the_vanished_one():
    first, _ = _handler({}, [_file("a.adoc", "one"), _file("b.adoc", "two"), _file("c.adoc", "three")])
    _run(first)
    pages = first.get_summary(CTX, None)["pages"]
    handler, _ = _handler({"pages": pages, "commit": "c1"}, [_file("a.adoc", "one"), _file("b.adoc", "TWO")], commit="c2")
    chunks, stale, summary = _run(handler)
    assert {c.metadata["path"] for c in chunks} == {"b.adoc"}
    assert set(stale[0]["metadata.page_id"]) == {page_id(_file("b.adoc").url), page_id(_file("c.adoc").url)}
    assert summary["pages_deleted"] == 1 and summary["commit"] == "c2"


def test_a_repository_that_lost_most_documents_fails_instead_of_deleting_them():
    first, _ = _handler({}, [_file(f"{i}.adoc", str(i)) for i in range(10)])
    _run(first)
    pages = first.get_summary(CTX, None)["pages"]
    handler, _ = _handler({"pages": pages, "commit": "c1"}, [_file("0.adoc", "0")], commit="c2")
    with pytest.raises(GitSyncDegraded):
        handler.collect(CTX)
