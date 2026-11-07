"""A light AsciiDoc to text conversion for documentation repositories (R-530).

It is not an AsciiDoc renderer: it resolves what a documentation set needs to read as prose (``include::`` of files
of the same repository, ``{attribute}`` substitutions, headings, admonition and block markers) and leaves anything else
as the author wrote it. Markdown and plain text pass through unchanged.
"""
from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping, Sequence

MAX_INCLUDE_DEPTH = 6
_ATTRIBUTE = re.compile(r"^:!?([A-Za-z0-9_][A-Za-z0-9_-]*)!?:[ \t]*(.*)$")
_INCLUDE = re.compile(r"^include::([^\[]+)\[(.*)\]\s*$")
_HEADING = re.compile(r"^(=+)\s+(\S.*)$")
_USE = re.compile(r"\{([A-Za-z0-9_][A-Za-z0-9_-]*)\}")
_IF = re.compile(r"^(ifdef|ifndef)::([^\[]+)\[(.*)\]\s*$")
_IFEVAL = re.compile(r"^ifeval::\[.*\]\s*$")
_ENDIF = re.compile(r"^endif::[^\[]*\[\]\s*$")
_COMMENT = re.compile(r"^//(?!/)")
_ANCHOR = re.compile(r"^\[\[[^\]]+\]\]\s*$|^\[#[^\]]+\]\s*$")
_BLOCK_ATTRS = re.compile(r"^\[(source|role|id|options|cols|%|\.|subs|discrete|abstract|quote|verse)[^\]]*\]\s*$", re.IGNORECASE)
_DELIMITER = re.compile(r"^(-{4,}|={4,}|\.{4,}|\*{4,}|_{4,}|\+{4,})\s*$")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_TOC = re.compile(r"^toc::\[.*\]\s*$")
_LABEL = re.compile(r"^\[(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$")
_XREF = re.compile(r"xref:[^\[\s]+\[([^\]]*)\]")
_LINK = re.compile(r"(?:link:)?(https?://[^\s\[]+)\[([^\]]*)\]")
_IMAGE = re.compile(r"image::?[^\[\s]+\[[^\]]*\]")
_PASS = re.compile(r"pass:[a-z,]*\[([^\]]*)\]")
_ADMONITION = re.compile(r"^(NOTE|TIP|IMPORTANT|WARNING|CAUTION):\s+")


_BUILTIN = {"nbsp": " ", "empty": "", "sp": " ", "plus": "+", "amp": "&", "lt": "<", "gt": ">"}


def _substitute(line: str, attrs: Mapping[str, str]) -> str:
    """Replace ``{name}``; values may refer to attributes defined later in the file, so they are resolved on use."""
    values = {**_BUILTIN, **attrs}
    for _ in range(6):
        replaced = _USE.sub(lambda m: values.get(m.group(1), m.group(0)), line)
        if replaced == line:
            break
        line = replaced
    return line


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


def resolve_path(path: str, links: Mapping[str, str]) -> str:
    """Follow the repository's symlinks: openshift-docs puts ``modules``, ``snippets`` and ``_attributes`` links in every
    directory, so ``installing/modules/x.adoc`` is ``modules/x.adoc``."""
    for _ in range(5):
        parts = path.split("/")
        for i in range(len(parts), 0, -1):
            prefix = "/".join(parts[:i])
            if prefix in links:
                path = posixpath.normpath(posixpath.join(links[prefix], *parts[i:]))
                break
        else:
            return path
    return path


class _Attributes:
    """Document attributes: the ones given by the source are locked (like attributes passed to Asciidoctor's API), a
    ``name!`` there locks the attribute as unset; the file's own ``:name:`` lines set the others."""

    def __init__(self, given: Mapping[str, str] | None = None) -> None:
        self.values: dict[str, str] = {}
        self.locked: set[str] = set()
        for name, value in (given or {}).items():
            if name.endswith("!"):
                self.locked.add(name[:-1])
            else:
                self.values[name] = value
                self.locked.add(name)

    def set(self, name: str, value: str) -> None:
        if name not in self.locked:
            self.values[name] = value

    def unset(self, name: str) -> None:
        if name not in self.locked:
            self.values.pop(name, None)

    def defined(self, name: str) -> bool:
        return name in self.values


def _holds(kind: str, names: str, attrs: _Attributes) -> bool:
    """ifdef/ifndef: ``a,b`` any of them, ``a+b`` all of them."""
    if "+" in names:
        found = all(attrs.defined(n.strip()) for n in names.split("+"))
    else:
        found = any(attrs.defined(n.strip()) for n in names.split(","))
    return found if kind == "ifdef" else not found


def _expand(path: str, files: Mapping[str, str], attrs: _Attributes, depth: int, seen: tuple[str, ...],
            links: Mapping[str, str] = {}) -> list[str]:  # noqa: B006
    path = resolve_path(path, links)
    text = files.get(path)
    if text is None or depth > MAX_INCLUDE_DEPTH or path in seen:
        return []
    out: list[str] = []
    base = posixpath.dirname(path)
    stack: list[bool] = []  # one entry per open ifdef/ifndef: does its block apply
    for raw in text.splitlines():
        line = raw.rstrip()
        m = _IF.match(line)
        if m:
            holds = _holds(m.group(1), m.group(2), attrs)
            if m.group(3).strip():  # single-line form: ifdef::x[text]
                if all(stack) and holds:
                    out.append(m.group(3))
            else:
                stack.append(holds)
            continue
        if _IFEVAL.match(line):
            stack.append(True)  # an expression is not evaluated: its block is kept
            continue
        if _ENDIF.match(line):
            if stack:
                stack.pop()
            continue
        if not all(stack):
            continue
        m = _INCLUDE.match(line)
        if m:
            target = _substitute(m.group(1).strip(), attrs.values)
            resolved = posixpath.normpath(posixpath.join(base, target))
            offset = _LEVELOFFSET.search(m.group(2))
            out.extend(_shift(_expand(resolved, files, attrs, depth + 1, seen + (path,), links), int(offset.group(1)) if offset else 0))
            continue
        a = _ATTRIBUTE.match(line)
        if a:
            name = a.group(1)
            if line.startswith(":!") or line.endswith("!:") or ":" + name + "!:" in line:
                attrs.unset(name)
            else:
                attrs.set(name, a.group(2).strip())
            continue
        out.append(line)
    return out


def adoc_to_text(path: str, files: Mapping[str, str], attributes: Mapping[str, str] | None = None,
                 attribute_files: Sequence[str] = (), links: Mapping[str, str] | None = None) -> str:
    """The prose of the AsciiDoc file *path*, its includes resolved from *files* (repository path to content).

    *attributes* are given by the source and win over the document's own (``name!`` unsets one); *attribute_files* are
    repository files whose attribute definitions apply to every document before its own lines (the way a documentation
    set pulls in its common attributes). ``ifdef``/``ifndef`` blocks are evaluated against these, so a repository that
    serves several products from one source keeps only the blocks of the chosen one.
    """
    attrs = _Attributes(attributes)
    files = {k: (_FRONT_MATTER.sub("", v, count=1) if k.lower().endswith(".adoc") else v) for k, v in files.items()} \
        if any(v.startswith("---") for v in files.values()) else files
    for seed in attribute_files:
        _expand(seed, files, attrs, 0, (), links or {})
    result: list[str] = []
    for line in _expand(path, files, attrs, 0, (), links or {}):
        if _COMMENT.match(line) or _ANCHOR.match(line) or _BLOCK_ATTRS.match(line) or _TOC.match(line):
            continue
        label = _LABEL.match(line)
        if label:
            result.append(label.group(1).capitalize() + ":")
            continue
        if _DELIMITER.match(line):
            continue
        line = _substitute(line, attrs.values)
        line = _IMAGE.sub("", line)
        line = _XREF.sub(r"\1", line)
        line = _LINK.sub(lambda m: f"{m.group(2)} ({m.group(1)})" if m.group(2) else m.group(1), line)
        line = _PASS.sub(r"\1", line)
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
