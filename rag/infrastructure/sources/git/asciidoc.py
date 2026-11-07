"""A light AsciiDoc to text conversion for documentation repositories (R-530).

It is not an AsciiDoc renderer: it resolves what a documentation set needs to read as prose (``include::`` of files
of the same repository, ``{attribute}`` substitutions, headings, admonition and block markers) and leaves anything else
as the author wrote it. Markdown and plain text pass through unchanged.
"""
from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping

MAX_INCLUDE_DEPTH = 6
_ATTRIBUTE = re.compile(r"^:([A-Za-z0-9_][A-Za-z0-9_-]*)!?:[ \t]*(.*)$")
_INCLUDE = re.compile(r"^include::([^\[]+)\[(.*)\]\s*$")
_HEADING = re.compile(r"^(=+)\s+(\S.*)$")
_USE = re.compile(r"\{([A-Za-z0-9_][A-Za-z0-9_-]*)\}")
_DIRECTIVE = re.compile(r"^(ifdef|ifndef|ifeval|endif)::.*\[.*\]\s*$")
_COMMENT = re.compile(r"^//(?!/)")
_ANCHOR = re.compile(r"^\[\[[^\]]+\]\]\s*$|^\[#[^\]]+\]\s*$")
_BLOCK_ATTRS = re.compile(r"^\[(source|role|id|options|cols|%|\.|subs|discrete|abstract|quote|verse)[^\]]*\]\s*$", re.IGNORECASE)
_DELIMITER = re.compile(r"^(-{4,}|={4,}|\.{4,}|\*{4,}|_{4,}|\+{4,})\s*$")
_ADMONITION = re.compile(r"^(NOTE|TIP|IMPORTANT|WARNING|CAUTION):\s+")


def _read_attributes(lines: list[str], attrs: dict[str, str]) -> None:
    for line in lines:
        m = _ATTRIBUTE.match(line)
        if m:
            attrs[m.group(1)] = m.group(2).strip()


def _substitute(line: str, attrs: Mapping[str, str]) -> str:
    return _USE.sub(lambda m: attrs.get(m.group(1), m.group(0)), line)


_LEVELOFFSET = re.compile(r"leveloffset=([+-]?\d+)")


def _shift(lines: list[str], offset: int) -> list[str]:
    """Shift the headings of an included file by its ``leveloffset`` (the module under an assembly's section)."""
    if not offset:
        return lines
    out = []
    for line in lines:
        h = _HEADING.match(line)
        out.append("=" * max(1, len(h.group(1)) + offset) + " " + h.group(2) if h else line)
    return out


def _expand(path: str, files: Mapping[str, str], attrs: dict[str, str], depth: int, seen: tuple[str, ...]) -> list[str]:
    text = files.get(path)
    if text is None or depth > MAX_INCLUDE_DEPTH or path in seen:
        return []
    out: list[str] = []
    base = posixpath.dirname(path)
    for raw in text.splitlines():
        line = raw.rstrip()
        m = _INCLUDE.match(line)
        if m:
            target = _substitute(m.group(1).strip(), attrs)
            resolved = posixpath.normpath(posixpath.join(base, target))
            offset = _LEVELOFFSET.search(m.group(2))
            out.extend(_shift(_expand(resolved, files, attrs, depth + 1, seen + (path,)), int(offset.group(1)) if offset else 0))
            continue
        a = _ATTRIBUTE.match(line)
        if a:
            attrs[a.group(1)] = _substitute(a.group(2).strip(), attrs)
            continue
        out.append(line)
    return out


def adoc_to_text(path: str, files: Mapping[str, str]) -> str:
    """The prose of the AsciiDoc file *path*, its includes resolved from *files* (repository path to content)."""
    attrs: dict[str, str] = {}
    result: list[str] = []
    for line in _expand(path, files, attrs, 0, ()):
        if _COMMENT.match(line) or _DIRECTIVE.match(line) or _ANCHOR.match(line) or _BLOCK_ATTRS.match(line):
            continue
        if _DELIMITER.match(line):
            continue
        line = _substitute(line, attrs)
        h = _HEADING.match(line)
        if h:
            line = "#" * min(len(h.group(1)), 6) + " " + h.group(2)
        else:
            line = _ADMONITION.sub(lambda m: m.group(1).capitalize() + ": ", line)
        result.append(line)
    text = "\n".join(result)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        m = _HEADING.match(line) or re.match(r"^(#+)\s+(\S.*)$", line)
        if m:
            return " ".join(m.group(2).split())
    return fallback
