"""Deterministic, read-only planning of one bounded chat projection.

The planner selects references to already available evidence.  It never
materializes a package, writes files, or advances the represented boundary.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

REQUEST_SCHEMA = "collab/preparation-request/v1"
PLAN_SCHEMA = "collab/preparation-plan/v1"
SELECTION_MODES = ("STATE_ONLY", "FOCUSED", "BROAD", "EXPLICIT_FULL")


@dataclass(frozen=True)
class PreparationRequest:
    boundary: Mapping[str, Any]
    selection: str
    required_domains: tuple[str, ...]
    byte_limit: int
    artifact_limit: int
    explicit_item_ids: tuple[str, ...] = field(default_factory=tuple)

    def as_mapping(self) -> Mapping[str, Any]:
        value: dict[str, Any] = {
            "schema": REQUEST_SCHEMA,
            "boundary": copy.deepcopy(dict(self.boundary)),
            "selection": self.selection,
            "requiredDomains": list(self.required_domains),
            "limits": {"bytes": self.byte_limit, "artifacts": self.artifact_limit},
        }
        if self.explicit_item_ids:
            value["explicitItemIds"] = list(self.explicit_item_ids)
        return value


@dataclass(frozen=True)
class PreparationPlan:
    value: Mapping[str, Any]

    def as_mapping(self) -> Mapping[str, Any]:
        return copy.deepcopy(dict(self.value))


@dataclass(frozen=True)
class PlanningResult:
    status: str
    value: Mapping[str, Any] | None
    diagnostics: tuple[Mapping[str, str], ...]

    @property
    def valid(self) -> bool:
        return self.status in ("complete", "limited") and self.value is not None


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _invalid(code: str, path: str, message: str) -> PlanningResult:
    return PlanningResult("invalid", None, ({"code": code, "path": path, "message": message},))


def _nonempty_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique_texts(value: Any) -> list[str] | None:
    if not isinstance(value, (list, tuple)):
        return None
    texts = [_nonempty_text(item) for item in value]
    if any(item is None for item in texts) or len(set(texts)) != len(texts):
        return None
    return sorted(texts)  # canonical selection is independent of caller order


def plan_preparation(
    request: PreparationRequest | Mapping[str, Any],
    available_items: Sequence[Mapping[str, Any]],
) -> PlanningResult:
    """Return a pure plan for the smallest sufficient bounded projection."""
    source = request.as_mapping() if isinstance(request, PreparationRequest) else copy.deepcopy(request)
    items_source = copy.deepcopy(available_items)
    if not isinstance(source, Mapping):
        return _invalid("invalid_request", "$", "request must be an object")
    boundary = source.get("boundary")
    if not isinstance(boundary, Mapping):
        return _invalid("invalid_boundary", "$.boundary", "exactly one boundary object is required")
    boundary_id = _nonempty_text(boundary.get("boundaryId"))
    if not boundary_id:
        return _invalid("invalid_boundary", "$.boundary.boundaryId", "boundaryId is required")
    if boundary.get("status") != "pending":
        return _invalid("boundary_not_pending", "$.boundary.status", "the represented boundary must be pending")

    selection = source.get("selection")
    if selection not in SELECTION_MODES:
        return _invalid("invalid_selection", "$.selection", "unsupported selection mode")
    required = _unique_texts(source.get("requiredDomains"))
    if required is None or not required:
        return _invalid("invalid_required_domains", "$.requiredDomains", "at least one unique domain is required")
    limits = source.get("limits")
    if not isinstance(limits, Mapping):
        return _invalid("invalid_limits", "$.limits", "byte and artifact limits are required")
    byte_limit, artifact_limit = limits.get("bytes"), limits.get("artifacts")
    if not isinstance(byte_limit, int) or isinstance(byte_limit, bool) or byte_limit < 0:
        return _invalid("invalid_byte_limit", "$.limits.bytes", "bytes must be a non-negative integer")
    if not isinstance(artifact_limit, int) or isinstance(artifact_limit, bool) or artifact_limit < 0:
        return _invalid("invalid_artifact_limit", "$.limits.artifacts", "artifacts must be a non-negative integer")
    explicit = _unique_texts(source.get("explicitItemIds", []))
    if explicit is None:
        return _invalid("invalid_explicit_items", "$.explicitItemIds", "explicit item ids must be unique strings")
    if selection == "EXPLICIT_FULL" and not explicit:
        return _invalid("explicit_selection_required", "$.explicitItemIds", "EXPLICIT_FULL requires explicit item ids")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items_source):
        if not isinstance(raw, Mapping):
            return _invalid("invalid_item", f"$.availableItems[{index}]", "item must be an object")
        item_id, domain = _nonempty_text(raw.get("itemId")), _nonempty_text(raw.get("domain"))
        size, artifacts = raw.get("byteSize"), raw.get("artifactCount", 1)
        if not item_id or item_id in seen or not domain:
            return _invalid("invalid_item_identity", f"$.availableItems[{index}]", "unique itemId and domain are required")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or not isinstance(artifacts, int) or isinstance(artifacts, bool) or artifacts < 1:
            return _invalid("invalid_item_limits", f"$.availableItems[{index}]", "byteSize and positive artifactCount are required")
        contextual = raw.get("contextual", True)
        if not isinstance(contextual, bool):
            return _invalid("invalid_item_context", f"$.availableItems[{index}].contextual", "contextual must be boolean")
        boundary_ids = _unique_texts(raw.get("boundaryIds", []))
        if boundary_ids is None:
            return _invalid("invalid_item_boundaries", f"$.availableItems[{index}].boundaryIds", "boundaryIds must be unique strings")
        seen.add(item_id)
        normalized.append({"itemId": item_id, "domain": domain, "byteSize": size, "artifactCount": artifacts, "contextual": contextual, "boundaryIds": boundary_ids})
    normalized.sort(key=lambda i: (i["byteSize"], i["artifactCount"], i["itemId"]))

    selected: list[dict[str, Any]] = []
    omitted: dict[str, str] = {}
    used_bytes = used_artifacts = 0
    covered: set[str] = set()

    def eligible(item: Mapping[str, Any]) -> tuple[bool, str]:
        if item["boundaryIds"] and boundary_id not in item["boundaryIds"]:
            return False, "different-boundary"
        if selection == "STATE_ONLY" and item["contextual"]:
            return False, "context-omitted-by-state-only"
        if selection == "EXPLICIT_FULL" and item["itemId"] not in explicit:
            return False, "not-explicitly-selected"
        if selection != "EXPLICIT_FULL" and item["domain"] not in required:
            return False, "domain-not-required"
        return True, ""

    candidates: list[dict[str, Any]] = []
    for item in normalized:
        ok, reason = eligible(item)
        if ok:
            candidates.append(item)
        else:
            omitted[item["itemId"]] = reason

    if selection in ("FOCUSED", "STATE_ONLY"):
        chosen: list[dict[str, Any]] = []
        for domain in required:
            match = next((item for item in candidates if item["domain"] == domain), None)
            if match is not None:
                chosen.append(match)
        candidate_ids = {item["itemId"] for item in chosen}
        for item in candidates:
            if item["itemId"] not in candidate_ids:
                omitted[item["itemId"]] = "smaller-sufficient-item-selected"
        candidates = chosen
    elif selection == "EXPLICIT_FULL":
        missing_explicit = sorted(set(explicit) - seen)
        if missing_explicit:
            return _invalid("explicit_item_unavailable", "$.explicitItemIds", "one or more explicit items are unavailable")

    for item in candidates:
        if used_bytes + item["byteSize"] > byte_limit:
            omitted[item["itemId"]] = "byte-limit"
            continue
        if used_artifacts + item["artifactCount"] > artifact_limit:
            omitted[item["itemId"]] = "artifact-limit"
            continue
        reason = "state-record" if selection == "STATE_ONLY" else ("explicit-full" if selection == "EXPLICIT_FULL" else ("required-domain" if selection == "FOCUSED" else "broad-boundary-context"))
        selected.append({"itemId": item["itemId"], "domain": item["domain"], "byteSize": item["byteSize"], "artifactCount": item["artifactCount"], "reasonCode": reason})
        used_bytes += item["byteSize"]
        used_artifacts += item["artifactCount"]
        covered.add(item["domain"])

    missing_domains = sorted(set(required) - covered)
    limitations = [{"domain": domain, "code": "required-domain-incomplete"} for domain in missing_domains]
    omissions = [{"itemId": item_id, "reasonCode": omitted[item_id]} for item_id in sorted(omitted)]
    core = {
        "schema": PLAN_SCHEMA,
        "boundary": {"boundaryId": boundary_id, "status": "pending"},
        "selection": selection,
        "selectedItems": sorted(selected, key=lambda item: item["itemId"]),
        "omissions": omissions,
        "requiredDomains": [{"domain": domain, "status": "complete" if domain in covered else "limited"} for domain in required],
        "limitations": limitations,
        "limits": {"bytes": byte_limit, "artifacts": artifact_limit},
        "totals": {"bytes": used_bytes, "artifacts": used_artifacts},
        "mutationSentinel": {"writesPerformed": False, "boundaryAdvanced": False, "packageMaterialized": False},
    }
    core["planId"] = "sha256:preparation-plan:v1:" + hashlib.sha256(_canonical(core)).hexdigest()
    return PlanningResult("limited" if limitations else "complete", core, ())
