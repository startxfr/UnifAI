"""Public web pages: conditional fetching and one-level link discovery.

A source is a list of seed URLs. Each seed is fetched on every run (its links
are needed for discovery); every other page is fetched with If-None-Match /
If-Modified-Since from the manifest of the previous run. A page whose body
hash did not change is reported as unchanged, whatever the server said.
"""
from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import logging
import re
import socket
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

# Deprecated, removed in 0.2: the former default crawl, docs.redhat.com books, kept as a preset of the generic rules.
# The same source is `crawl: site` with these include patterns (the source's own include narrows them further) and
# rewrite.
REDHAT_DOCS_INCLUDE = ("*/html/*", "*/html-single/*")
REDHAT_DOCS_REWRITES = ((r"^(https?://docs\.redhat\.com)/documentation/", r"\1/en/documentation/"),)
USER_AGENT = "unifai-rag-web/1.0"


def user_agent(contact: str = "") -> str:
    """The crawler's honest identity; with a contact (URL or address) a site operator can reach us. Never a browser's."""
    contact = " ".join(contact.split())
    return f"{USER_AGENT} (+{contact})" if contact else USER_AGENT
MAX_RETRIES = 3
MAX_RETRY_WAIT = 30.0


def retry_after(value: str | None, attempt: int) -> float:
    """Seconds to wait before a retry: the server's Retry-After (seconds) when it gives one, else 2, 4, 8 ...; capped."""
    try:
        wait = float(value) if value else 2.0 * (2 ** attempt)
    except ValueError:
        wait = 2.0 * (2 ** attempt)
    return min(max(wait, 0.0), MAX_RETRY_WAIT)


@dataclass(frozen=True)
class WebPage:
    url: str
    html: str
    content_hash: str
    etag: str = ""
    last_modified: str = ""


class WebError(RuntimeError):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class WebCrawlBlocked(WebError):
    """The site refused or throttled several requests in a row: the crawl stops instead of hammering it."""


# Statuses a site answers when it blocks or throttles a crawler.
BLOCK_STATUSES = (403, 429, 503)
MAX_CONSECUTIVE_BLOCKS = 5


MAX_REDIRECTS = 5


def resolve_public(host: str) -> None:
    """Refuse a host that resolves to a non-public address (loopback, private, link-local, cluster, metadata).

    The fetch runs in the RAG pod, which reaches internal services and, on a cloud, the instance
    metadata endpoint: a source URL must never be a way to read them.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebError(f"cannot resolve {host}: {exc}") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%")[0])
        if not addr.is_global or addr.is_multicast:
            raise WebError(f"{host} resolves to a non-public address ({addr})")


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def compile_rewrites(rewrites: Sequence[tuple[str, str]]) -> list[tuple[re.Pattern, str]]:
    """(regex, replacement) pairs; raises re.error on an invalid expression."""
    return [(re.compile(match), replace) for match, replace in rewrites]


def rewrite(url: str, rewrites: Sequence[tuple[re.Pattern, str]]) -> str:
    """The URL after each rewrite in turn (a site that serves a page under two URLs keeps one form)."""
    for pattern, replace in rewrites:
        url = pattern.sub(replace, url, count=1)
    return url


def discover_links(base_url: str, html: str, crawl: str, limit: int, include: Sequence[str] = (),
                   exclude: Sequence[str] = (), rewrites: Sequence[tuple[str, str]] = ()) -> list[str]:
    """In-scope links of a landing page, at most ``limit``. crawl: site | generic | none (CRAWL_MODES).

    Each link is rewritten first (``rewrites``: regex, replacement), then kept when it is on the seed's host, in the
    crawl's scope and matches the include/exclude patterns.
    """
    if crawl == "none":
        return []
    preset: Sequence[str] = ()
    if crawl == "redhat-docs":
        crawl, preset, rewrites = "site", REDHAT_DOCS_INCLUDE, (*REDHAT_DOCS_REWRITES, *rewrites)
    compiled = compile_rewrites(rewrites)
    base = urlparse(base_url)
    prefix = base.path if base.path.endswith("/") else base.path.rsplit("/", 1)[0] + "/"
    parser = _Links()
    parser.feed(html)
    found: list[str] = []
    seen = {base_url}
    for href in parser.hrefs:
        url = rewrite(urljoin(base_url, href).split("#", 1)[0], compiled)
        parsed = urlparse(url)
        if url in seen or parsed.scheme not in ("http", "https") or parsed.netloc != base.netloc:
            continue
        if crawl == "generic" and not parsed.path.startswith(prefix):
            continue
        if preset and not in_scope(url, preset, ()):
            continue
        if not in_scope(url, include, exclude):  # before the cap: the limit counts pages the source wants
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= limit:
            logger.warning("web source: link discovery capped at %d for %s", limit, base_url)
            break
    return found


def in_scope(url: str, include: Sequence[str], exclude: Sequence[str]) -> bool:
    if any(fnmatch.fnmatch(url, p) for p in exclude):
        return False
    return not include or any(fnmatch.fnmatch(url, p) for p in include)


class WebConnector:
    def __init__(self, timeout: float = 60.0, min_interval: float = 0.2, verify_tls: bool = True,
                 allowed_hosts: Sequence[str] = (), session: requests.Session | None = None, sleep=time.sleep,
                 host_check=resolve_public, contact: str = "") -> None:
        self._allowed = tuple(h.lower() for h in allowed_hosts)
        self._host_check = host_check
        self._session = session or requests.Session()
        self._session.verify = verify_tls
        self._session.headers.setdefault("User-Agent", user_agent(contact))
        self._timeout = timeout
        self._interval = min_interval
        self._sleep = sleep
        self._last = 0.0

    def _check(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not host:
            raise WebError(f"not an http(s) URL: {url}")
        if self._allowed and not any(host == a or host.endswith("." + a) for a in self._allowed):
            raise WebError(f"{host} is not in the allowed hosts")
        self._host_check(host)

    def _get(self, url: str, headers: dict):
        """GET with the host check applied to the URL and to every redirect (no automatic redirect)."""
        for _ in range(MAX_REDIRECTS + 1):
            self._check(url)
            resp = self._session.get(url, headers=headers, timeout=self._timeout, allow_redirects=False)
            location = resp.headers.get("Location") if 300 <= resp.status_code < 400 and resp.status_code != 304 else None
            if not location:
                return resp
            url = urljoin(url, location)
        raise WebError(f"too many redirects from {url}")

    def fetch(self, url: str, known: dict | None = None) -> WebPage | None:
        """The page, or None when the server says it did not change (304)."""
        headers = {}
        if known and known.get("etag"):
            headers["If-None-Match"] = known["etag"]
        if known and known.get("last_modified"):
            headers["If-Modified-Since"] = known["last_modified"]
        wait = self._interval - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        resp = self._get(url, headers)
        for attempt in range(MAX_RETRIES):  # a throttled site (429/503) is retried after its Retry-After, not hammered
            if resp.status_code not in (429, 503):
                break
            self._sleep(retry_after(resp.headers.get("Retry-After"), attempt))
            resp = self._get(url, headers)
        self._last = time.monotonic()
        if resp.status_code == 304:
            return None
        if resp.status_code >= 400:
            raise WebError(f"{resp.status_code} on {url}", resp.status_code)
        body = resp.text
        return WebPage(url=url, html=body, content_hash=hashlib.sha256(resp.content).hexdigest(),
                       etag=resp.headers.get("ETag", ""), last_modified=resp.headers.get("Last-Modified", ""))

    @staticmethod
    def _count_blocks(blocked: int, exc: Exception) -> int:
        """The count of consecutive blocked requests after this failure; raises when the site keeps refusing."""
        blocked = blocked + 1 if getattr(exc, "status", 0) in BLOCK_STATUSES else 0
        if blocked >= MAX_CONSECUTIVE_BLOCKS:
            raise WebCrawlBlocked(f"the site refused or throttled {blocked} requests in a row ({exc}): crawl stopped")
        return blocked

    def iter_pages(self, seeds: Sequence[str], previous: dict[str, dict], include: Sequence[str] = (),
                   exclude: Sequence[str] = (), crawl: str = "generic", max_pages: int = 50,
                   rewrites: Sequence[tuple[str, str]] = ()) -> Iterator[tuple[str, WebPage | None]]:
        """(url, page) for every in-scope URL; page is None when the URL is unchanged or could not be read.

        A URL that fails keeps its manifest entry: the caller must not treat it as removed.
        """
        seed_pages: dict[str, WebPage | None] = {}
        discovered: list[str] = []
        blocked = 0  # consecutive requests the site refused or throttled
        for seed in seeds:
            try:
                page = self.fetch(seed)  # unconditional: its links are needed
            except (WebError, requests.RequestException) as exc:
                logger.warning("web source: seed %s unreadable: %s", seed, exc)
                page = None
                blocked = self._count_blocks(blocked, exc)
            else:
                blocked = 0
            seed_pages[seed] = page
            if page is not None:
                discovered += [u for u in discover_links(seed, page.html, crawl, max_pages, include, exclude, rewrites)
                               if u not in seed_pages and u not in discovered]
        yield from seed_pages.items()
        for url in discovered:
            try:
                page = self.fetch(url, previous.get(url))
            except (WebError, requests.RequestException) as exc:
                logger.warning("web source: %s unreadable: %s", url, exc)
                page = None
                blocked = self._count_blocks(blocked, exc)
            else:
                blocked = 0
            yield url, page
