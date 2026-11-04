"""Guards shared by the incremental sources (web, Confluence): a sync that would delete most of a source fails.

An incremental sync deletes the points of the pages that vanished from the listing. When the listing is wrong
(a blocked or throttled crawl, an unreachable or empty space) every page "vanishes" and the source would be wiped.
Two checks, both refusing before anything is embedded or deleted:
- the manifest: pages found against pages known at the last sync;
- the store: chunks the vanished pages hold against the chunks the source holds in the vector store (the manifest
  of a source cut down by an earlier degraded sync lists few pages for many chunks and would pass the first).
"""

from typing import Any, Sequence

# A source with fewer pages than this may lose any share of them in one sync (a handful of pages is not a crawl).
MIN_PAGES_FOR_DELETION_GUARD = 5
# The store check ignores a source holding fewer chunks than this.
MIN_CHUNKS_FOR_DELETION_GUARD = 25


class SyncDegraded(RuntimeError):
    """The listing found far fewer pages than the source holds: failing keeps the index as it is."""


def refuse_vanished_pages(source_name: str, known: int, found: int, vanished: int, max_ratio: float,
                          cause: str) -> None:
    if max_ratio and known >= MIN_PAGES_FOR_DELETION_GUARD and vanished > max_ratio * known:
        raise SyncDegraded(
            f"{source_name}: the sync found {found} pages where {known} are indexed ({vanished} would be deleted, "
            f"more than {max_ratio:.0%}): {cause}; nothing was changed")


def refuse_vanished_chunks(source_name: str, source_id: str, vanished_page_ids: Sequence[str], vector_repo: Any,
                           max_ratio: float, cause: str) -> None:
    if not max_ratio or not vanished_page_ids:
        return
    source = {"metadata.source_id": source_id}
    total = vector_repo.count(source, exact=True)
    if total < MIN_CHUNKS_FOR_DELETION_GUARD:
        return
    doomed = vector_repo.count({**source, "metadata.page_id": list(vanished_page_ids)}, exact=True)
    if doomed > max_ratio * total:
        raise SyncDegraded(
            f"{source_name}: {len(vanished_page_ids)} vanished pages hold {doomed} of the {total} chunks indexed "
            f"(more than {max_ratio:.0%}): {cause}; nothing was changed")
