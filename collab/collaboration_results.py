"""Pure deterministic Collaboration Result contract for Issue #70."""
from __future__ import annotations

import copy
import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from typing import Any, Mapping

RESULT_SCHEMA = "collab/collaboration-result/v1"
NORMALIZATION_VERSION = "1"
OUTCOMES = {"completed", "failed", "blocked", "not-applicable"}
IDENTITY = re.compile(r"^sha256:(?:[a-z][a-z0-9-]*:v1:)?[0-9a-f]{64}$")
BOUNDARY_ID = re.compile(r"^sha256:boundary:v1:[0-9a-f]{64}$")
RESULT_ID = re.compile(r"^sha256:collaboration-result:v1:[0-9a-f]{64}$")

@dataclass(frozen=True)
class ContractResult:
    status: str
    value: Mapping[str, Any] | None
    diagnostics: tuple[Mapping[str, str], ...]
    @property
    def valid(self) -> bool:
        return self.status == "valid"

def _diag(code: str, path: str, message: str) -> ContractResult:
    return ContractResult("invalid", None, ({"code": code, "path": path, "message": message},))

def _text(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None

def _canonical(v: Any) -> bytes:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _result_id(v: Any) -> str:
    return "sha256:collaboration-result:v1:" + hashlib.sha256(_canonical(v)).hexdigest()

def _strings(v: Any, path: str, *, paths: bool = False) -> tuple[list[str] | None, ContractResult | None]:
    if not isinstance(v, list):
        return None, _diag("type", path, "must be an array")
    out: list[str] = []
    for i, item in enumerate(v):
        text = _text(item)
        if text is None:
            return None, _diag("text", f"{path}/{i}", "must be a non-empty string")
        if paths:
            text = posixpath.normpath(text.replace("\\", "/"))
            if text in {".", ".."} or text.startswith("../") or text.startswith("/"):
                return None, _diag("path", f"{path}/{i}", "must be workspace-relative")
        out.append(text)
    if len(set(out)) != len(out):
        return None, _diag("duplicate", path, "contains duplicate entries")
    return sorted(out), None

def _records(v: Any, path: str, kind: str) -> tuple[list[dict[str, Any]] | None, ContractResult | None]:
    if not isinstance(v, list):
        return None, _diag("type", path, "must be an array")
    out: list[dict[str, Any]] = []
    ids: set[str] = set()
    for i, raw in enumerate(v):
        if not isinstance(raw, Mapping):
            return None, _diag("type", f"{path}/{i}", "must be an object")
        allowed = {"id", "description", "artifactRefs", "receiptRefs", "obligationRefs", "status", "path", "identity", "mediaType", "details"}
        unknown = set(raw) - allowed
        if unknown:
            return None, _diag("unknown-field", f"{path}/{i}", f"unknown fields: {sorted(unknown)}")
        rid = _text(raw.get("id"))
        desc = _text(raw.get("description"))
        if not rid or not desc:
            return None, _diag("required", f"{path}/{i}", "id and description are required")
        if rid in ids:
            return None, _diag("duplicate-id", f"{path}/{i}/id", f"duplicate id {rid}")
        ids.add(rid)
        rec: dict[str, Any] = {"id": rid, "description": desc}
        for key in ("artifactRefs", "receiptRefs", "obligationRefs"):
            vals, err = _strings(raw.get(key, []), f"{path}/{i}/{key}")
            if err: return None, err
            rec[key] = vals
        for key in ("status", "identity", "mediaType", "details"):
            if key in raw:
                val = _text(raw[key])
                if val is None: return None, _diag("text", f"{path}/{i}/{key}", "must be non-empty")
                rec[key] = val
        if "path" in raw:
            vals, err = _strings([raw["path"]], f"{path}/{i}/path", paths=True)
            if err: return None, err
            rec["path"] = vals[0]
        if kind in {"artifact", "receipt"} and "identity" not in rec:
            return None, _diag("required", f"{path}/{i}/identity", "identity is required")
        if "identity" in rec and not IDENTITY.fullmatch(rec["identity"]):
            return None, _diag("identity", f"{path}/{i}/identity", "invalid identity")
        out.append(rec)
    return sorted(out, key=lambda x: x["id"]), None

def normalize_collaboration_result(value: Any) -> ContractResult:
    if not isinstance(value, Mapping): return _diag("type", "", "result must be an object")
    allowed = {"schema","normalizationVersion","resultId","boundaryId","boundaryResponsibility","inputCaptureId","semanticStateId","applicabilityIdentities","responsibility","outcome","claims","reportedObservations","candidates","artifacts","receipts","verificationEvidence","changedPaths","mutationEvidence","diagnostics","obligationClaims","completeness","limitations","documentationImpact","requestedNextResponsibility","acceptance","stateTransition"}
    unknown = set(value) - allowed
    if unknown: return _diag("unknown-field", "", f"unknown fields: {sorted(unknown)}")
    if value.get("schema") != RESULT_SCHEMA: return _diag("schema", "/schema", f"must equal {RESULT_SCHEMA}")
    if value.get("normalizationVersion") != NORMALIZATION_VERSION: return _diag("version", "/normalizationVersion", "unsupported normalization version")
    if "acceptance" in value: return _diag("self-acceptance", "/acceptance", "a result cannot declare its own acceptance")
    if "stateTransition" in value: return _diag("durable-transition", "/stateTransition", "a result cannot contain a State Transition")
    boundary = _text(value.get("boundaryId"))
    if not boundary or not BOUNDARY_ID.fullmatch(boundary): return _diag("boundary-id", "/boundaryId", "invalid Boundary Descriptor identity")
    br = _text(value.get("boundaryResponsibility")); responsibility = _text(value.get("responsibility"))
    if not br or not responsibility: return _diag("required", "/responsibility", "boundaryResponsibility and responsibility are required")
    if br != responsibility: return _diag("responsibility-mismatch", "/responsibility", "responsibility must match its Boundary Descriptor")
    outcome = value.get("outcome")
    if outcome not in OUTCOMES: return _diag("outcome", "/outcome", "unsupported outcome")
    capture = _text(value.get("inputCaptureId")); semantic = _text(value.get("semanticStateId"))
    if not capture or not IDENTITY.fullmatch(capture): return _diag("identity", "/inputCaptureId", "invalid identity")
    if not semantic or not IDENTITY.fullmatch(semantic): return _diag("identity", "/semanticStateId", "invalid identity")
    app = value.get("applicabilityIdentities")
    if not isinstance(app, Mapping) or not app: return _diag("required", "/applicabilityIdentities", "at least one applicability identity is required")
    appn: dict[str,str] = {}
    for k,v in app.items():
        key=_text(k); ident=_text(v)
        if not key or not ident or not IDENTITY.fullmatch(ident): return _diag("identity", f"/applicabilityIdentities/{k}", "invalid identity")
        appn[key]=ident
    collections: dict[str,list[dict[str,Any]]] = {}
    for key,kind in (("claims","claim"),("reportedObservations","observation"),("candidates","candidate"),("artifacts","artifact"),("receipts","receipt"),("verificationEvidence","verification"),("diagnostics","diagnostic"),("obligationClaims","obligation")):
        recs,err=_records(value.get(key,[]),f"/{key}",kind)
        if err:return err
        collections[key]=recs
    artifact_ids={x["id"] for x in collections["artifacts"]}|{x["id"] for x in collections["candidates"]}
    receipt_ids={x["id"] for x in collections["receipts"]}|{x["id"] for x in collections["verificationEvidence"]}
    for group in ("claims","reportedObservations","obligationClaims"):
        for rec in collections[group]:
            missing=set(rec["artifactRefs"])-artifact_ids
            if missing:return _diag("unresolved-artifact-ref",f"/{group}/{rec['id']}/artifactRefs",f"unresolved references: {sorted(missing)}")
            missing=set(rec["receiptRefs"])-receipt_ids
            if missing:return _diag("unresolved-receipt-ref",f"/{group}/{rec['id']}/receiptRefs",f"unresolved references: {sorted(missing)}")
    claim_text={x["description"].casefold() for x in collections["claims"]}
    if any(("not " + t) in claim_text for t in claim_text): return _diag("contradictory-claims","/claims","contains directly contradictory claims")
    completeness=_text(value.get("completeness"))
    if completeness not in {"complete","partial","none"}: return _diag("completeness","/completeness","must be complete, partial, or none")
    limitations,err=_strings(value.get("limitations",[]),"/limitations")
    if err:return err
    docs,err=_strings(value.get("documentationImpact",[]),"/documentationImpact",paths=True)
    if err:return err
    changed,err=_strings(value.get("changedPaths",[]),"/changedPaths",paths=True)
    if err:return err
    mutation,err=_strings(value.get("mutationEvidence",[]),"/mutationEvidence")
    if err:return err
    if responsibility.startswith("READ_ONLY") and (changed or mutation): return _diag("read-only-mutation","/mutationEvidence","read-only responsibility cannot report mutation")
    if outcome == "completed" and completeness != "complete": return _diag("outcome-completeness","/completeness","completed requires complete")
    if outcome == "blocked" and not limitations: return _diag("blocked-prerequisite","/limitations","blocked requires a missing prerequisite or external condition")
    if outcome == "not-applicable" and (completeness != "none" or not limitations): return _diag("not-applicable","/outcome","not-applicable requires no completion and an explicit mismatch")
    nxt=value.get("requestedNextResponsibility")
    if not isinstance(nxt,Mapping): return _diag("required","/requestedNextResponsibility","object required")
    if nxt.get("advisory") is not True: return _diag("next-advisory","/requestedNextResponsibility/advisory","must be true")
    nname=_text(nxt.get("responsibility")); prereqs,err=_strings(nxt.get("prerequisites",[]),"/requestedNextResponsibility/prerequisites")
    if err:return err
    if not nname:return _diag("required","/requestedNextResponsibility/responsibility","required")
    normalized={"schema":RESULT_SCHEMA,"normalizationVersion":NORMALIZATION_VERSION,"boundaryId":boundary,"boundaryResponsibility":br,"inputCaptureId":capture,"semanticStateId":semantic,"applicabilityIdentities":dict(sorted(appn.items())),"responsibility":responsibility,"outcome":outcome,**collections,"changedPaths":changed,"mutationEvidence":mutation,"completeness":completeness,"limitations":limitations,"documentationImpact":docs,"requestedNextResponsibility":{"responsibility":nname,"prerequisites":prereqs,"advisory":True}}
    supplied=value.get("resultId")
    core=copy.deepcopy(normalized)
    rid=_result_id(core)
    if supplied is not None and (not isinstance(supplied,str) or not RESULT_ID.fullmatch(supplied) or supplied != rid): return _diag("result-id","/resultId","does not match canonical normalized content")
    normalized["resultId"]=rid
    return ContractResult("valid", normalized, ())

def validate_collaboration_result(value: Any) -> ContractResult:
    return normalize_collaboration_result(value)

def render_legacy_result(value: Any, role: str) -> ContractResult:
    result=normalize_collaboration_result(value)
    if not result.valid:return result
    role_name=_text(role)
    if not role_name:return _diag("role","/role","legacy role is required")
    v=result.value
    return ContractResult("valid", {"role":role_name,"status":v["outcome"],"summary":[x["description"] for x in v["claims"]],"resultId":v["resultId"]}, ())
