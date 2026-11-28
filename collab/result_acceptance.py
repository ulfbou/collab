"""Pure, deterministic, read-only CollaborationResult acceptance (Issue #71)."""
from __future__ import annotations
import hashlib, json, posixpath, re
from dataclasses import dataclass
from typing import Any, Mapping
from .collaboration_results import normalize_collaboration_result

SCHEMA="collab/result-acceptance/v1"; VERSION="1"
OUTCOMES=("ACCEPTED","PARTIAL_EVIDENCE_RETAINED","BLOCKED_EVIDENCE_RETAINED","FAILED_EVIDENCE_RETAINED","STALE_REJECTED","STRUCTURALLY_INVALID","REQUIRES_LIVE_REOBSERVATION","REQUIRES_CANDIDATE_REPAIR")
CONTINUATIONS=("PUBLISH_TRANSITION","PARTIAL_CONTINUATION","LIVE_REOBSERVATION","REPAIR_CANDIDATE","NEW_BOUNDARY")
CODES={"state":"STALE_STATE","boundary":"BOUNDARY_MISMATCH","responsibility":"RESPONSIBILITY_MISMATCH","intent":"INTENT_CHANGED","authority":"AUTHORITY_CHANGED","obligation":"OBLIGATIONS_CHANGED","candidate":"CANDIDATE_CHANGED","baseline":"BASELINE_CHANGED","configuration":"CONFIGURATION_CHANGED","policy":"POLICY_CHANGED","validator":"VALIDATOR_CHANGED","repositoryManifest":"REPOSITORY_MANIFEST_CHANGED"}
RECEIPT_BINDINGS=("operation","boundary","materialState","candidate","baseline","authority","obligation","configuration","policy","validator","repositoryManifest")
SHA=re.compile(r"^[0-9a-f]{64}$")
@dataclass(frozen=True)
class AcceptanceResult:
    status:str; value:Mapping[str,Any]
    @property
    def accepted(self): return self.status=="accepted"
def _canon(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
def _id(v): return "sha256:result-acceptance:v1:"+hashlib.sha256(_canon(v)).hexdigest()
def _norm(v):
    if not isinstance(v,list): return []
    u={json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")):x for x in v}
    return [u[k] for k in sorted(u)]
def _diag(code,path): return {"code":code,"path":path}
def _identity(v): return isinstance(v,str) and bool(v.strip())
def _hash(v): return isinstance(v,str) and bool(SHA.fullmatch(v))
def _size(v): return isinstance(v,int) and not isinstance(v,bool) and v>=0
def _structural(control, diagnostics):
    b={"schema":SCHEMA,"normalizationVersion":VERSION,"structuralVerification":"failed","applicabilityVerification":"not-performed","scopeVerification":"not-performed","artifactVerification":"not-performed","receiptVerification":"not-performed","liveVerification":"not-performed","outcome":"STRUCTURALLY_INVALID","transitionEligible":False,"acceptedClaims":[],"acceptedObservations":[],"acceptedArtifacts":[],"acceptedReceipts":[],"retainedPartialEvidence":[],"satisfiedObligations":[],"unsatisfiedObligations":_norm(control.get("obligations",[])),"limitations":[],"diagnostics":_norm(diagnostics),"lawfulContinuation":"REPAIR_CANDIDATE"}
    b["acceptanceDecisionId"]=_id(b); return b

def _details(d):
    try: return json.loads(d.get("details","{}")) if isinstance(d.get("details","{}"),str) else {}
    except (ValueError,TypeError): return {}

def _artifact_checks(r, control, ds):
    declared={x.get("id"):x for x in r.get("artifacts",[]) if isinstance(x,Mapping) and isinstance(x.get("id"),str)}
    evidence=control.get("artifactIntegrityEvidence",{}); accepted=[]; failed=False
    for aid in sorted(set(control.get("requiredArtifacts",[]))):
        d=declared.get(aid); path=f"artifacts.{aid}"
        if d is None: ds.append(_diag("ARTIFACT_DECLARATION_MISSING",path)); failed=True; continue
        e=evidence.get(aid) if isinstance(evidence,Mapping) else None
        if e is None: ds.append(_diag("ARTIFACT_INTEGRITY_EVIDENCE_MISSING",path)); failed=True; continue
        required=("artifactId","immutableIdentity","sha256","byteSize","resultId","operationId","boundaryId","verifiedBy","verificationMethod")
        if not isinstance(e,Mapping) or any(k not in e for k in required) or not _identity(e.get("immutableIdentity")) or not _hash(e.get("sha256")) or not _size(e.get("byteSize")) or not _identity(e.get("verifiedBy")) or e.get("verificationMethod") not in ("REHASHED_BYTES","IMMUTABLE_BACKING_ATTESTATION"):
            ds.append(_diag("ARTIFACT_INTEGRITY_EVIDENCE_MALFORMED",path)); failed=True; continue
        checks=((e.get("artifactId")==aid,"ARTIFACT_IDENTITY_MISMATCH"),(d.get("identity")==e.get("immutableIdentity"),"ARTIFACT_IDENTITY_MISMATCH"),(_details(d).get("sha256")==e.get("sha256"),"ARTIFACT_HASH_MISMATCH"),(_details(d).get("byteSize")==e.get("byteSize"),"ARTIFACT_SIZE_MISMATCH"),(e.get("resultId")==r.get("resultId"),"ARTIFACT_RESULT_BINDING_MISMATCH"),(e.get("operationId")==control.get("operationId"),"ARTIFACT_OPERATION_BINDING_MISMATCH"),(e.get("boundaryId")==control.get("identities",{}).get("boundary"),"ARTIFACT_BOUNDARY_BINDING_MISMATCH"))
        if control.get("identities",{}).get("candidate") is not None: checks += ((e.get("candidateId")==control["identities"]["candidate"],"ARTIFACT_CANDIDATE_BINDING_MISMATCH"),)
        bad=[code for ok,code in checks if not ok]
        if bad: ds.extend(_diag(code,path) for code in bad); failed=True
        else: accepted.append(d)
    return failed,_norm(accepted)

def _receipt_checks(r, control, ds):
    declared={x.get("id"):x for x in r.get("receipts",[]) if isinstance(x,Mapping) and isinstance(x.get("id"),str)}
    evidence=control.get("receiptIntegrityEvidence",{}); accepted=[]; failed=False; ids=control.get("identities",{})
    expected={"operation":control.get("operationId"),"boundary":ids.get("boundary"),"materialState":ids.get("state"),"candidate":ids.get("candidate"),"baseline":ids.get("baseline"),"authority":ids.get("authority"),"obligation":ids.get("obligation"),"configuration":ids.get("configuration"),"policy":ids.get("policy"),"validator":ids.get("validator"),"repositoryManifest":ids.get("repositoryManifest")}
    for rid in sorted(set(control.get("requiredReceipts",[]))):
        d=declared.get(rid); path=f"receipts.{rid}"
        if d is None: ds.append(_diag("RECEIPT_MISSING",path)); failed=True; continue
        e=evidence.get(rid) if isinstance(evidence,Mapping) else None
        if e is None: ds.append(_diag("RECEIPT_INTEGRITY_EVIDENCE_MISSING",path)); failed=True; continue
        required=("receiptId","immutableIdentity","sha256","byteSize","issuerIdentity","verifiedBy")+tuple(k+"Id" for k in RECEIPT_BINDINGS)
        if not isinstance(e,Mapping) or any(k not in e for k in required) or not _identity(e.get("immutableIdentity")) or not _hash(e.get("sha256")) or not _size(e.get("byteSize")) or not _identity(e.get("issuerIdentity")) or not _identity(e.get("verifiedBy")):
            ds.append(_diag("RECEIPT_INTEGRITY_EVIDENCE_MALFORMED",path)); failed=True; continue
        checks=[(e.get("receiptId")==rid,"RECEIPT_IDENTITY_MISMATCH"),(d.get("identity")==e.get("immutableIdentity"),"RECEIPT_IMMUTABLE_IDENTITY_MISMATCH"),(_details(d).get("sha256")==e.get("sha256"),"RECEIPT_CONTENT_HASH_MISMATCH"),(_details(d).get("byteSize")==e.get("byteSize"),"RECEIPT_SIZE_MISMATCH")]
        for k in RECEIPT_BINDINGS: checks.append((e.get(k+"Id")==expected[k],("OPERATION_MISMATCH" if k=="operation" else k.upper()+"_MISMATCH")))
        if "resultId" in e: checks.append((e["resultId"]==r.get("resultId"),"RECEIPT_RESULT_BINDING_MISMATCH"))
        bad=[code for ok,code in checks if not ok]
        if bad: ds.extend(_diag(code,path) for code in bad); failed=True
        else: accepted.append(d)
    return failed,_norm(accepted)

def accept_collaboration_result(result:Any, control:Mapping[str,Any], decision_id:str|None=None)->AcceptanceResult:
    structural=normalize_collaboration_result(result)
    if not structural.valid: return AcceptanceResult("rejected",_structural(control,list(structural.diagnostics)))
    r=dict(structural.value); ds=[]; expected=control.get("identities")
    if not isinstance(expected,Mapping): expected={}; ds.append(_diag("APPLICABILITY_EVIDENCE_MISSING","identities"))
    actual=dict(r.get("applicabilityIdentities",{})); direct={"boundary":r.get("boundaryId"),"responsibility":r.get("responsibility"),"state":r.get("semanticStateId")}
    for key,code in CODES.items():
        e=expected.get(key); a=direct.get(key,actual.get(key))
        if not _identity(e): ds.append(_diag("APPLICABILITY_EVIDENCE_MISSING",key))
        elif not _identity(a): ds.append(_diag("APPLICABILITY_IDENTITY_MALFORMED",key))
        elif a!=e: ds.append(_diag(code,key))
    applicability_failed=any(d["code"] in set(CODES.values())|{"APPLICABILITY_EVIDENCE_MISSING","APPLICABILITY_IDENTITY_MALFORMED"} for d in ds)
    allowed={posixpath.normpath(x.replace("\\","/")) for x in control.get("authorizedPaths",[]) if isinstance(x,str)}
    raw=r.get("changedPaths"); changed={posixpath.normpath(x.replace("\\","/")) for x in raw} if isinstance(raw,list) and all(isinstance(x,str) for x in raw) else set(); pe=control.get("changedPathEvidence"); scope_failed=False
    if not isinstance(pe,Mapping) or pe.get("passed") is not True or not isinstance(pe.get("paths"),list): ds.append(_diag("CHANGED_PATH_EVIDENCE_MISSING","changedPaths")); scope_failed=True
    elif {posixpath.normpath(str(x).replace("\\","/")) for x in pe["paths"]}!=changed: ds.append(_diag("CHANGED_PATH_EVIDENCE_MISMATCH","changedPaths")); scope_failed=True
    if (control.get("readOnly") and changed) or not changed.issubset(allowed): ds.append(_diag("SCOPE_EXCESS","changedPaths")); scope_failed=True
    neg=control.get("prohibitedEffectEvidence")
    if not isinstance(neg,Mapping): ds.append(_diag("PROHIBITED_EFFECT_EVIDENCE_MISSING","prohibitedEffects")); scope_failed=True
    elif neg.get("passed") is not True: ds.append(_diag("PROHIBITED_EFFECT_VERIFICATION_FAILED","prohibitedEffects")); scope_failed=True
    artifact_failed,accepted_artifacts=_artifact_checks(r,control,ds); receipt_failed,accepted_receipts=_receipt_checks(r,control,ds)
    live=control.get("liveEvidence"); live_missing=not isinstance(live,list) or not live; live_malformed=False; live_failed=False
    if live_missing: ds.append(_diag("LIVE_EVIDENCE_REQUIRED","liveEvidence"))
    else:
        live_malformed=any(not isinstance(x,Mapping) or not isinstance(x.get("subject"),str) or not isinstance(x.get("passed"),bool) for x in live)
        live_failed=not live_malformed and any(not x["passed"] for x in live)
        if live_malformed: ds.append(_diag("LIVE_EVIDENCE_MALFORMED","liveEvidence"))
        if live_failed: ds.append(_diag("LIVE_VERIFICATION_FAILED","liveEvidence"))
    failures=applicability_failed or scope_failed or artifact_failed or receipt_failed or live_missing or live_malformed or live_failed
    if failures:
        if live_missing or live_malformed: outcome,continuation="REQUIRES_LIVE_REOBSERVATION","LIVE_REOBSERVATION"
        elif scope_failed or artifact_failed or receipt_failed: outcome,continuation="REQUIRES_CANDIDATE_REPAIR","REPAIR_CANDIDATE"
        else: outcome,continuation="STALE_REJECTED","NEW_BOUNDARY"
    else:
        outcome={"completed":"ACCEPTED","partial":"PARTIAL_EVIDENCE_RETAINED","blocked":"BLOCKED_EVIDENCE_RETAINED","failed":"FAILED_EVIDENCE_RETAINED","not-applicable":"PARTIAL_EVIDENCE_RETAINED"}[r["outcome"]]
        continuation="PUBLISH_TRANSITION" if outcome=="ACCEPTED" else "PARTIAL_CONTINUATION"
    eligible=outcome=="ACCEPTED"; diagnostics=_norm(ds); retained=[] if eligible else _norm(r.get("claims",[])+r.get("reportedObservations",[])+accepted_artifacts+accepted_receipts)
    obligations=_norm(control.get("obligations",[])); satisfied=_norm(control.get("satisfiedObligations",[])) if eligible else []
    b={"schema":SCHEMA,"normalizationVersion":VERSION,"controllingStateId":expected.get("state",r.get("semanticStateId","")),"captureId":r.get("inputCaptureId",""),"collaborationResultId":r["resultId"],"controllingIdentities":dict(sorted(expected.items())),"structuralVerification":"passed","applicabilityVerification":"failed" if applicability_failed else "passed","scopeVerification":"failed" if scope_failed else "passed","artifactVerification":"failed" if artifact_failed else "passed","receiptVerification":"failed" if receipt_failed else "passed","liveVerification":"missing" if live_missing else "failed" if live_malformed or live_failed else "passed","outcome":outcome,"transitionEligible":eligible,"acceptedClaims":_norm(r.get("claims",[])) if eligible else [],"acceptedObservations":_norm(r.get("reportedObservations",[])) if eligible else [],"acceptedArtifacts":accepted_artifacts if eligible else [],"acceptedReceipts":accepted_receipts if eligible else [],"retainedPartialEvidence":retained,"satisfiedObligations":satisfied,"unsatisfiedObligations":sorted(set(obligations)-set(satisfied)),"limitations":_norm(r.get("limitations",[])),"diagnostics":diagnostics,"lawfulContinuation":continuation}
    b["acceptanceDecisionId"]=_id(b)
    if decision_id is not None and decision_id!=b["acceptanceDecisionId"]: raise ValueError("acceptance-decision-id mismatch")
    return AcceptanceResult("accepted" if eligible else "rejected",b)
