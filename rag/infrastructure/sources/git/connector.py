"""A public GitHub repository read as an archive (R-530).

No git binary and no credentials: the commit of the ref is looked up through the GitHub API (one cheap request), and
only when it changed the repository archive is streamed from codeload.github.com and filtered on the fly. The files
the source selects become documents; every .adoc/.md file is kept in memory (bounded) so that ``include::`` of the
documents can be resolved from the repository itself.
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import posixpath
import re
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import requests

from infrastructure.sources.git.asciidoc import adoc_to_text, title_of

logger = logging.getLogger(__name__)

USER_AGENT = "unifai-rag-git/1.0"
TEXT_SUFFIXES = (".adoc", ".md", ".txt")
MAX_FILE_BYTES = 1_000_000
MAX_MEMORY_BYTES = 400_000_000
_REPO = re.compile(r"^/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_REF = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitFile:
    path: str
    url: str
    text: str
    content_hash: str
    title: str


def parse_repo(url: str) -> tuple[str, str]:
    """(owner, repo) of an https://github.com/<owner>/<repo> URL; anything else is refused."""
    parsed = urlparse(url)
    m = _REPO.match(parsed.path or "")
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "github.com" or not m or parsed.username:
        raise GitError("a git source is a public https://github.com/<owner>/<repo> repository")
    return m.group(1), m.group(2)


def selected(path: str, paths: Sequence[str], include: Sequence[str], exclude: Sequence[str]) -> bool:
    """A document of the source: under one of *paths* (empty = everywhere), matching *include*, not *exclude*."""
    if not path.lower().endswith(TEXT_SUFFIXES):
        return False
    if paths and not any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in paths):
        return False
    if exclude and any(fnmatch.fnmatch(path, p) for p in exclude):
        return False
    return not include or any(fnmatch.fnmatch(path, p) for p in include)


class GitConnector:
    def __init__(self, session: requests.Session | None = None, timeout: float = 120.0, api_url: str = "https://api.github.com",
                 archive_url: str = "https://codeload.github.com") -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)
        self._timeout = timeout
        self._api = api_url.rstrip("/")
        self._archive = archive_url.rstrip("/")

    def head_commit(self, url: str, ref: str) -> str:
        """The commit sha the ref points at, "" when it cannot be told (rate limit): the caller then fetches."""
        owner, repo = parse_repo(url)
        if not _REF.match(ref):
            raise GitError(f"invalid ref {ref!r}")
        try:
            resp = self._session.get(f"{self._api}/repos/{owner}/{repo}/commits/{quote(ref, safe='/')}", timeout=self._timeout,
                                     headers={"Accept": "application/vnd.github.sha"})
        except requests.RequestException as exc:
            logger.warning("git source %s: cannot look the commit up: %s", url, exc)
            return ""
        if resp.status_code == 404:
            raise GitError(f"{url}: ref {ref!r} not found (private repositories are not supported)")
        if resp.status_code != 200:
            logger.warning("git source %s: commit lookup answered %s", url, resp.status_code)
            return ""
        return resp.text.strip()

    def fetch(self, url: str, ref: str, paths: Sequence[str] = (), include: Sequence[str] = (), exclude: Sequence[str] = (),
              max_files: int = 2000) -> list[GitFile]:
        """The documents of the source at *ref*. The archive is streamed: only text files are read, bounded in size."""
        owner, repo = parse_repo(url)
        resp = self._session.get(f"{self._archive}/{owner}/{repo}/tar.gz/{quote(ref, safe='/')}", timeout=self._timeout, stream=True)
        if resp.status_code == 404:
            raise GitError(f"{url}: ref {ref!r} not found (private repositories are not supported)")
        if resp.status_code != 200:
            raise GitError(f"{url}: the archive answered {resp.status_code}")
        sources: dict[str, str] = {}
        used = 0
        try:
            with tarfile.open(fileobj=resp.raw, mode="r|gz") as tar:
                for member in tar:
                    if not member.isfile() or member.size > MAX_FILE_BYTES:
                        continue
                    path = posixpath.normpath(member.name.split("/", 1)[1]) if "/" in member.name else ""
                    if not path or path.startswith("..") or not path.lower().endswith(TEXT_SUFFIXES):
                        continue
                    data = tar.extractfile(member).read()
                    used += len(data)
                    if used > MAX_MEMORY_BYTES:
                        raise GitError(f"{url}: the text files of the repository exceed {MAX_MEMORY_BYTES // 1_000_000} MB")
                    sources[path] = data.decode("utf-8", errors="replace")
        finally:
            resp.close()
        files: list[GitFile] = []
        for path in sorted(sources):
            if not selected(path, paths, include, exclude):
                continue
            text = adoc_to_text(path, sources) if path.lower().endswith(".adoc") else sources[path].strip()
            if not text:
                continue
            blob = f"https://github.com/{owner}/{repo}/blob/{quote(ref, safe='/')}/{quote(path)}"
            files.append(GitFile(path=path, url=blob, text=text, content_hash=hashlib.sha256(text.encode()).hexdigest(),
                                 title=title_of(text, posixpath.basename(path))))
            if len(files) >= max_files:
                logger.warning("git source %s: capped at %d documents", url, max_files)
                break
        return files
