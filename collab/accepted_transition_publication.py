"""Atomic publication of Issue #71 accepted transitions (Issue #72)."""
from __future__ import annotations
import copy, hashlib, json, os, shutil, tempfile
from pathlib import Path
from typing import Any, Mapping
from jsonschema import Draft202012Validator
from .artifacts import canonical_json_bytes
from .filesystem import FilesystemError, reject_symlink

GATES=("structuralVerification","applicabilityVerification","scopeVerification","artifactVerification","receiptVerification","liveVerification")

def _canonical(value: object) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
def _identity(kind: str, value: object) -> str:
    return f"sha256:{kind}:v1:"+hashlib.sha256(_canonical(value)).hexdigest()
def _ordered(values): return sorted(set(values))
def _validate(schema_path: Path, value: object, label: str) -> None:
    errors=sorted(Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8"))).iter_errors(value),key=lambda e:list(e.path))
    if errors: raise ValueError(f"schema-invalid {label}: {errors[0].message}")
def _require_acceptance(a: Mapping[str,Any]) -> None:
    if a.get("outcome")!="ACCEPTED" or a.get("transitionEligible") is not True or a.get("lawfulContinuation")!="PUBLISH_TRANSITION" or a.get("diagnostics")!=[] or any(a.get(g)!="passed" for g in GATES):
        raise ValueError("acceptance decision is not transition eligible")

def construct_publication(*, prior_state: Mapping[str,Any], boundary: Mapping[str,Any], acceptance: Mapping[str,Any], proposed_state: Mapping[str,Any], attached_receipt_ids=(), invalidated_receipt_ids=()):
    _require_acceptance(acceptance)
    prior_id=prior_state.get("stateIdentity"); boundary_id=boundary.get("boundaryId")
    if acceptance.get("controllingStateId")!=prior_id: raise ValueError("stale prior state")
    ci=acceptance.get("controllingIdentities",{})
    if ci.get("boundary")!=boundary_id: raise ValueError("acceptance boundary mismatch")
    attached=_ordered(attached_receipt_ids); invalidated=_ordered(invalidated_receipt_ids)
    if set(attached)&set(invalidated): raise ValueError("receipt sets overlap")
    acceptance_id=acceptance.get("acceptanceId")
    if not acceptance_id: raise ValueError("acceptanceId is required")
    next_state=copy.deepcopy(dict(prior_state)); next_state.update(copy.deepcopy(dict(proposed_state)))
    material=copy.deepcopy(next_state); material.pop("stateIdentity",None); material.pop("captureId",None)
    next_id="sha256:v1:"+hashlib.sha256(_canonical(material)).hexdigest(); next_state["stateIdentity"]=next_id
    transition_material={"schema":"collab/state-transition/v1","normalizationVersion":"1","priorStateIdentity":prior_id,"priorState":dict(prior_state),"boundaryId":boundary_id,"attachedReceiptIds":attached,"invalidatedReceiptIds":invalidated,"proposedState":dict(proposed_state),"acceptanceState":"accepted","workflowAdvanced":True,"acceptanceDecisionId":acceptance_id,"nextStateIdentity":next_id}
    transition=dict(transition_material); transition["transitionId"]=_identity("state-transition",transition_material)
    history={"priorStateIdentity":prior_id,"acceptedBoundaryDescriptorIdentity":boundary_id,"acceptedCollaborationResultIdentity":acceptance["collaborationResultId"],"acceptanceReceiptIdentity":acceptance_id,"satisfiedNormalizedObligationIdentities":[],"resultingStateIdentity":next_id}
    next_state["acceptedHistory"]=list(prior_state.get("acceptedHistory",[]))+[history]
    constituents={"acceptance.json":dict(acceptance),"transition.json":transition,"current-state.json":next_state}
    records={name:{"sha256":hashlib.sha256(canonical_json_bytes(value)).hexdigest(),"size":len(canonical_json_bytes(value))} for name,value in constituents.items()}
    manifest_material={"schema":"collab/accepted-transition-publication/v1","priorStateIdentity":prior_id,"acceptanceDecisionId":acceptance_id,"transitionId":transition["transitionId"],"nextStateIdentity":next_id,"constituents":records}
    manifest=dict(manifest_material); manifest["publicationId"]=_identity("accepted-transition-publication",manifest_material)
    return constituents,manifest

def publish_accepted_transition(root: Path, *, schemas: Path, prior_state, boundary, acceptance, proposed_state, attached_receipt_ids=(), invalidated_receipt_ids=(), fail_before_commit=False):
    root=Path(root); reject_symlink(root,description="publication root"); root.mkdir(parents=True,exist_ok=True)
    stable=root/"CURRENT"; reject_symlink(stable,description="stable reference")
    constituents,manifest=construct_publication(prior_state=prior_state,boundary=boundary,acceptance=acceptance,proposed_state=proposed_state,attached_receipt_ids=attached_receipt_ids,invalidated_receipt_ids=invalidated_receipt_ids)
    for name,value in constituents.items(): _validate(schemas/{"acceptance.json":"result-acceptance.schema.json","transition.json":"state-transition.schema.json","current-state.json":"current-state.schema.json"}[name],value,name)
    _validate(schemas/"accepted-transition-publication.schema.json",manifest,"manifest")
    publication_id=manifest["publicationId"]; units=root/"units"; units.mkdir(exist_ok=True); final=units/publication_id
    if final.exists():
        if json.loads((final/"manifest.json").read_text())==manifest:
            if stable.exists() and stable.read_text().strip()==publication_id: return {"status":"already-complete","publicationId":publication_id}
        raise ValueError("conflicting replay")
    temp=Path(tempfile.mkdtemp(prefix=".publication-",dir=units))
    try:
        for name,value in constituents.items(): (temp/name).write_bytes(canonical_json_bytes(value))
        (temp/"manifest.json").write_bytes(canonical_json_bytes(manifest))
        for name,record in manifest["constituents"].items():
            data=(temp/name).read_bytes()
            if hashlib.sha256(data).hexdigest()!=record["sha256"] or len(data)!=record["size"]: raise ValueError("constituent verification failed")
        os.replace(temp,final)
        if fail_before_commit: raise RuntimeError("injected pre-commit failure")
        fd,tmp=tempfile.mkstemp(prefix="CURRENT.tmp.",dir=root)
        try:
            with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as h: h.write(publication_id+"\n"); h.flush(); os.fsync(h.fileno())
            os.replace(tmp,stable)
        finally:
            try: os.unlink(tmp)
            except FileNotFoundError: pass
    except Exception:
        shutil.rmtree(temp,ignore_errors=True); raise
    return {"status":"published","publicationId":publication_id,"unit":str(final)}
