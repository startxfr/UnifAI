"""
Helpers for mutating stored blueprint ``spec_dict`` values as plain dicts.

Used by resource reference maintenance (replace / detach / cascade) where we
must persist specs that may still contain legacy keys or shapes the current
Pydantic ``BlueprintDraft`` no longer accepts — see ``BlueprintRepository.update_raw``.
"""

from __future__ import annotations

from typing import Any

from mas.core.enums import ResourceCategory

_CATALOGUE_KEYS = tuple(c.value for c in ResourceCategory)

_REF_PREFIX = "$ref:"


def extract_ref_ids_from_raw_spec(node: Any) -> set[str]:
    """Collect resource IDs referenced under *node*.

    Includes ``$ref:`` strings anywhere in the tree, plus raw ``rid`` values on
    the root catalogue lists (with or without the ``$ref:`` prefix). Bare
    catalogue IDs stay in ``rid_refs`` when a spec is rewritten.
    """
    bucket: set[str] = set()
    _scan_refs(node, bucket)
    if isinstance(node, dict):
        _collect_catalogue_rids(node, bucket)
    return bucket


def _collect_catalogue_rids(spec: dict, bucket: set[str]) -> None:
    """Add IDs stored on catalogue entry ``rid`` fields."""
    for cat_key in _CATALOGUE_KEYS:
        entries = spec.get(cat_key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rid = entry.get("rid")
            if not isinstance(rid, str) or not rid:
                continue
            if rid.startswith(_REF_PREFIX):
                bare = rid[len(_REF_PREFIX) :]
                if bare:
                    bucket.add(bare)
            else:
                bucket.add(rid)


def _scan_refs(node: Any, bucket: set[str]) -> None:
    if isinstance(node, str):
        if node.startswith(_REF_PREFIX):
            bucket.add(node[len(_REF_PREFIX) :])
    elif isinstance(node, dict):
        for v in node.values():
            _scan_refs(v, bucket)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _scan_refs(v, bucket)


# Plan step fields that hold a resource id (stored bare, without the ``$ref:`` prefix, by the operator and by
# API clients). ``after`` and ``branches`` hold step uids, never resource ids, and are left alone.
_PLAN_RID_KEYS = ("node", "exit_condition")


def remap_plan_rids(spec_dict: dict, mapping: dict[str, str]) -> dict:
    """Replace old resource ids by new ones in the bare ``node`` / ``exit_condition`` of the plan steps.

    ``RefRemapper`` only rewrites ``$ref:<rid>`` strings; a plan step that names its condition (or node) by the
    bare rid kept the deleted id after a ``replace``, and the graph build then failed with "Condition reference
    ... not found" (R-552, found on the live stack 2026-11-12). Returns a copy.
    """
    plan = spec_dict.get("plan")
    if not isinstance(plan, list):
        return spec_dict
    result = dict(spec_dict)
    steps = []
    for step in plan:
        if isinstance(step, dict):
            step = dict(step)
            for key in _PLAN_RID_KEYS:
                value = step.get(key)
                if isinstance(value, str) and value in mapping:
                    step[key] = mapping[value]
        steps.append(step)
    result["plan"] = steps
    return result


def remove_resource_ref_from_nested_dict(d: dict, rid: str) -> dict:
    """Remove ``$ref:rid`` from a nested dict (resource cfg_dict style).

    A field whose entire value is that reference is dropped. Leaving ``None``
    would persist a null config key that later schema validation rejects.
    """
    ref_str = f"$ref:{rid}"

    def walk(node):
        if isinstance(node, str):
            return None if node == ref_str else node
        if isinstance(node, dict):
            cleaned = {}
            for key, value in node.items():
                if isinstance(value, str) and value == ref_str:
                    continue
                cleaned[key] = walk(value)
            return cleaned
        if isinstance(node, list):
            return [walk(v) for v in node if not (isinstance(v, str) and v == ref_str)]
        return node

    return walk(d)


def remove_resource_ref_from_catalogue(spec_dict: dict, rid: str) -> dict:
    """Drop catalogue list entries whose ``rid`` equals ``$ref:<rid>``."""
    ref_str = f"$ref:{rid}"
    result = dict(spec_dict)
    for cat_key in _CATALOGUE_KEYS:
        entries = result.get(cat_key)
        if isinstance(entries, list):
            result[cat_key] = [
                e
                for e in entries
                if not (
                    isinstance(e, dict)
                    and e.get("rid") in (ref_str, rid)
                )
            ]
    return result


def dedupe_blueprint_catalogue(spec_dict: dict) -> dict:
    """Remove duplicate catalogue entries (same ``rid``) per catalogue list."""
    result = dict(spec_dict)
    for cat_key in _CATALOGUE_KEYS:
        entries = result.get(cat_key)
        if isinstance(entries, list):
            seen: set[str] = set()
            deduped = []
            for entry in entries:
                rid = entry.get("rid") if isinstance(entry, dict) else None
                if rid and rid in seen:
                    continue
                if rid:
                    seen.add(rid)
                deduped.append(entry)
            result[cat_key] = deduped
    return result
