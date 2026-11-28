import copy,json,hashlib
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator
from collab.result_acceptance import accept_collaboration_result,CODES

def I(name):return ("sha256:boundary:v1:" if name=="boundary" else "sha256:")+hashlib.sha256(name.encode()).hexdigest()
def result(outcome="completed"):
 app={k:I(k) for k in ("intent","authority","obligation","candidate","baseline","configuration","policy","validator","repositoryManifest")}
 v={"schema":"collab/collaboration-result/v1","normalizationVersion":"1","boundaryId":I("boundary"),"boundaryResponsibility":"IMPLEMENT_CANDIDATE","inputCaptureId":I("capture"),"semanticStateId":I("state"),"applicabilityIdentities":app,"responsibility":"IMPLEMENT_CANDIDATE","outcome":outcome,"claims":[{"id":"claim","description":"Räksmörgås"}],"reportedObservations":[{"id":"obs","description":"observed"}],"candidates":[],"artifacts":[],"receipts":[],"verificationEvidence":[],"changedPaths":["collab/result_acceptance.py"],"mutationEvidence":[],"diagnostics":[],"obligationClaims":[],"completeness":"complete" if outcome=="completed" else "partial","limitations":[],"documentationImpact":[],"requestedNextResponsibility":{"responsibility":"ASSESS_RESULT","prerequisites":(["wait"] if outcome=="blocked" else []),"advisory":True}}
 if outcome=="failed":v["diagnostics"]=[{"id":"d","description":"failed"}]
 if outcome=="blocked":v["limitations"]=["external prerequisite missing"]
 if outcome=="not-applicable":v["completeness"]="none";v["limitations"]=["boundary mismatch"]
 return v
def control():
 ids={k:I(k) for k in ("intent","authority","obligation","candidate","baseline","configuration","policy","validator","repositoryManifest")};ids.update(state=I("state"),boundary=I("boundary"),responsibility="IMPLEMENT_CANDIDATE")
 return {"identities":ids,"authorizedPaths":["collab/result_acceptance.py"],"liveEvidence":[{"subject":"repository","passed":True}],"changedPathEvidence":{"passed":True,"paths":["collab/result_acceptance.py"]},"prohibitedEffectEvidence":{"passed":True},"obligations":[]}
def codes(v):return {d["code"] for d in v["diagnostics"]}
def test_accepted_is_only_transition_eligible_outcome():
 d=accept_collaboration_result(result(),control()).value;assert d["outcome"]=="ACCEPTED" and d["transitionEligible"] and d["lawfulContinuation"]=="PUBLISH_TRANSITION" and "stateTransition" not in d
@pytest.mark.parametrize("outcome,expected",[("blocked","BLOCKED_EVIDENCE_RETAINED"),("failed","FAILED_EVIDENCE_RETAINED"),("not-applicable","PARTIAL_EVIDENCE_RETAINED")])
def test_noncomplete_retains_truthful_evidence(outcome,expected):
 d=accept_collaboration_result(result(outcome),control()).value;assert d["outcome"]==expected and not d["transitionEligible"] and d["retainedPartialEvidence"]
def test_structural_validation_is_canonical_issue70():
 v=result();v["acceptance"]={};d=accept_collaboration_result(v,control()).value;assert d["outcome"]=="STRUCTURALLY_INVALID" and d["diagnostics"][0]["code"]=="self-acceptance"
@pytest.mark.parametrize("key",list(CODES))
def test_each_controlling_identity_has_distinct_diagnostic(key):
 c=control();c["identities"][key]=I("other-"+key);d=accept_collaboration_result(result(),c).value;assert CODES[key] in codes(d) and not d["transitionEligible"]
def test_capture_change_does_not_invalidate_unchanged_material_state():
 v=result();v["inputCaptureId"]=I("later-capture");assert accept_collaboration_result(v,control()).value["outcome"]=="ACCEPTED"
def test_missing_applicability_identity_is_explicit():
 c=control();del c["identities"]["policy"];assert "APPLICABILITY_EVIDENCE_MISSING" in codes(accept_collaboration_result(result(),c).value)
def test_scope_excess_and_read_only_mutation():
 v=result();v["changedPaths"]=["README.md"];assert "SCOPE_EXCESS" in codes(accept_collaboration_result(v,control()).value)
 c=control();c["readOnly"]=True;assert "SCOPE_EXCESS" in codes(accept_collaboration_result(result(),c).value)
def test_missing_changed_path_evidence_not_no_mutation():
 c=control();del c["changedPathEvidence"];d=accept_collaboration_result(result(),c).value;assert "CHANGED_PATH_EVIDENCE_MISSING" in codes(d) and not d["transitionEligible"]
def test_artifact_missing_and_mismatch():
 c=control();c["requiredArtifacts"]=["a"];assert "ARTIFACT_DECLARATION_MISSING" in codes(accept_collaboration_result(result(),c).value)
 v=result();v["artifacts"]=[{"id":"a","description":"a","identity":I("wrong")}];c=control();c["requiredArtifacts"]=["a"];c["artifactIntegrityEvidence"]={"a":{"identity":I("right")}};assert "ARTIFACT_INTEGRITY_EVIDENCE_MALFORMED" in codes(accept_collaboration_result(v,c).value)
def test_stale_receipt_not_reused():
 c=control();c["requiredReceipts"]=["r"];assert "RECEIPT_MISSING" in codes(accept_collaboration_result(result(),c).value)
def test_missing_and_failed_live_evidence_are_distinct():
 c=control();del c["liveEvidence"];d=accept_collaboration_result(result(),c).value;assert d["outcome"]=="REQUIRES_LIVE_REOBSERVATION"
 c=control();c["liveEvidence"]=[{"subject":"hosted","passed":False}];d=accept_collaboration_result(result(),c).value;assert "LIVE_VERIFICATION_FAILED" in codes(d)
def test_determinism_order_unicode_and_semantic_change():
 a=result();c=control();x=accept_collaboration_result(a,c).value;a["claims"].append({"id":"z","description":"Å"});a["claims"].reverse();y=accept_collaboration_result(a,c).value;a["claims"].reverse();z=accept_collaboration_result(a,c).value;assert y==z and x["acceptanceDecisionId"]!=y["acceptanceDecisionId"]
def test_supplied_decision_identity_is_verified():
 d=accept_collaboration_result(result(),control()).value;assert accept_collaboration_result(result(),control(),d["acceptanceDecisionId"]).accepted
 with pytest.raises(ValueError):accept_collaboration_result(result(),control(),I("bad"))
def test_operation_is_pure():
 r=result();c=control();rr=copy.deepcopy(r);cc=copy.deepcopy(c);accept_collaboration_result(r,c);assert r==rr and c==cc
def test_schema_accepts_all_generated_outcomes_and_rejects_unknown():
 schema=json.loads((Path(__file__).parents[1]/"schemas/result-acceptance.schema.json").read_text());v=Draft202012Validator(schema)
 decisions=[accept_collaboration_result(result(x),control()).value for x in ("completed","blocked","failed","not-applicable")]
 bad=result();bad["acceptance"]={};decisions.append(accept_collaboration_result(bad,control()).value)
 for d in decisions:assert not list(v.iter_errors(d))
 x=copy.deepcopy(decisions[0]);x["unknown"]=1;assert list(v.iter_errors(x))

def asserted_rejected(v,c,code):
 d=accept_collaboration_result(v,c).value
 assert d["outcome"]!="ACCEPTED" and d["transitionEligible"] is False and code in codes(d)
 return d

def test_adversarial_required_controls_fail_closed():
 for key in list(control()["identities"]):
  c=control();del c["identities"][key];asserted_rejected(result(),c,"APPLICABILITY_EVIDENCE_MISSING")
 c=control();c["identities"]["authority"]=None;asserted_rejected(result(),c,"APPLICABILITY_EVIDENCE_MISSING")
 c=control();c["identities"]["authority"]=I("conflict");asserted_rejected(result(),c,"AUTHORITY_CHANGED")

def test_adversarial_artifact_independent_integrity():
 v=result();v["artifacts"]=[{"id":"a","description":"a","identity":I("a")}]
 c=control();c["requiredArtifacts"]=["a"];asserted_rejected(v,c,"ARTIFACT_INTEGRITY_EVIDENCE_MISSING")
 c["artifactIntegrityEvidence"]={"a":{"identity":I("different")}};asserted_rejected(v,c,"ARTIFACT_INTEGRITY_EVIDENCE_MALFORMED")

def test_adversarial_live_and_scope_negative_evidence():
 for live,code in [(None,"LIVE_EVIDENCE_REQUIRED"),([],"LIVE_EVIDENCE_REQUIRED"),([{}],"LIVE_EVIDENCE_MALFORMED"),([{"subject":"repo","passed":False}],"LIVE_VERIFICATION_FAILED")]:
  c=control();c["liveEvidence"]=live;asserted_rejected(result(),c,code)
 v=result();v["changedPaths"]=[];c=control();del c["changedPathEvidence"];asserted_rejected(v,c,"CHANGED_PATH_EVIDENCE_MISSING")
 c=control();del c["prohibitedEffectEvidence"];asserted_rejected(result(),c,"PROHIBITED_EFFECT_EVIDENCE_MISSING")
 c=control();c["prohibitedEffectEvidence"]={"passed":False};asserted_rejected(result(),c,"PROHIBITED_EFFECT_VERIFICATION_FAILED")

def test_noncompleted_cannot_complete_boundary_and_obligations_require_evidence():
 for outcome in ("blocked","failed","not-applicable"):
  d=accept_collaboration_result(result(outcome),control()).value
  assert not d["transitionEligible"] and d["acceptedClaims"]==[] and d["lawfulContinuation"]=="PARTIAL_CONTINUATION"

def test_issue72_publication_payload_is_structurally_rejected():
 v=result();v["stateTransition"]={};d=accept_collaboration_result(v,control()).value
 assert d["structuralVerification"]=="failed" and not d["transitionEligible"]

from collab.collaboration_results import normalize_collaboration_result
from collab.result_acceptance import OUTCOMES,CONTINUATIONS,RECEIPT_BINDINGS

def _rid(v): return normalize_collaboration_result(v).value["resultId"]
def _artifact_case():
 v=result(); sha="a"*64; v["artifacts"]=[{"id":"a","description":"artifact","identity":I("artifact-immutable"),"details":json.dumps({"sha256":sha,"byteSize":7},sort_keys=True,separators=(",",":"))}]
 rid=_rid(v); c=control(); c.update(operationId=I("operation"),requiredArtifacts=["a"])
 c["artifactIntegrityEvidence"]={"a":{"artifactId":"a","immutableIdentity":I("artifact-immutable"),"sha256":sha,"byteSize":7,"resultId":rid,"operationId":I("operation"),"boundaryId":I("boundary"),"candidateId":I("candidate"),"verifiedBy":I("independent-verifier"),"verificationMethod":"REHASHED_BYTES"}}
 return v,c

def _receipt_case():
 v=result(); sha="b"*64; v["receipts"]=[{"id":"r","description":"receipt","identity":I("receipt-immutable"),"details":json.dumps({"sha256":sha,"byteSize":9},sort_keys=True,separators=(",",":"))}]
 c=control(); c.update(operationId=I("operation"),requiredReceipts=["r"]); ids=c["identities"]
 e={"receiptId":"r","immutableIdentity":I("receipt-immutable"),"sha256":sha,"byteSize":9,"issuerIdentity":I("issuer"),"verifiedBy":I("independent-verifier")}
 expected={"operation":c["operationId"],"boundary":ids["boundary"],"materialState":ids["state"],"candidate":ids["candidate"],"baseline":ids["baseline"],"authority":ids["authority"],"obligation":ids["obligation"],"configuration":ids["configuration"],"policy":ids["policy"],"validator":ids["validator"],"repositoryManifest":ids["repositoryManifest"]}
 e.update({k+"Id":x for k,x in expected.items()}); c["receiptIntegrityEvidence"]={"r":e}; return v,c

def test_complete_independent_artifact_and_receipt_evidence_accepts():
 v,c=_artifact_case(); d=accept_collaboration_result(v,c).value; assert d["outcome"]=="ACCEPTED" and d["artifactVerification"]=="passed"
 v,c=_receipt_case(); d=accept_collaboration_result(v,c).value; assert d["outcome"]=="ACCEPTED" and d["receiptVerification"]=="passed"

@pytest.mark.parametrize("field,value,code",[("sha256","A"*64,"ARTIFACT_INTEGRITY_EVIDENCE_MALFORMED"),("byteSize",-1,"ARTIFACT_INTEGRITY_EVIDENCE_MALFORMED"),("byteSize",1.5,"ARTIFACT_INTEGRITY_EVIDENCE_MALFORMED"),("immutableIdentity",None,"ARTIFACT_INTEGRITY_EVIDENCE_MALFORMED"),("sha256","c"*64,"ARTIFACT_HASH_MISMATCH"),("byteSize",8,"ARTIFACT_SIZE_MISMATCH"),("immutableIdentity",I("other"),"ARTIFACT_IDENTITY_MISMATCH"),("resultId",I("other"),"ARTIFACT_RESULT_BINDING_MISMATCH"),("operationId",I("other"),"ARTIFACT_OPERATION_BINDING_MISMATCH"),("boundaryId",I("other"),"ARTIFACT_BOUNDARY_BINDING_MISMATCH"),("candidateId",I("other"),"ARTIFACT_CANDIDATE_BINDING_MISMATCH"),("verifiedBy",None,"ARTIFACT_INTEGRITY_EVIDENCE_MALFORMED")])
def test_artifact_integrity_failures(field,value,code):
 v,c=_artifact_case(); c["artifactIntegrityEvidence"]["a"][field]=value; d=asserted_rejected(v,c,code); assert d["artifactVerification"]=="failed" and d["lawfulContinuation"]=="REPAIR_CANDIDATE"

@pytest.mark.parametrize("field,value,code",[("sha256","bad","RECEIPT_INTEGRITY_EVIDENCE_MALFORMED"),("byteSize",-1,"RECEIPT_INTEGRITY_EVIDENCE_MALFORMED"),("immutableIdentity",None,"RECEIPT_INTEGRITY_EVIDENCE_MALFORMED"),("sha256","c"*64,"RECEIPT_CONTENT_HASH_MISMATCH"),("byteSize",10,"RECEIPT_SIZE_MISMATCH"),("immutableIdentity",I("other"),"RECEIPT_IMMUTABLE_IDENTITY_MISMATCH"),("receiptId","other","RECEIPT_IDENTITY_MISMATCH")])
def test_receipt_integrity_failures(field,value,code):
 v,c=_receipt_case(); c["receiptIntegrityEvidence"]["r"][field]=value; d=asserted_rejected(v,c,code); assert d["receiptVerification"]=="failed" and d["lawfulContinuation"]=="REPAIR_CANDIDATE"

@pytest.mark.parametrize("binding",RECEIPT_BINDINGS)
def test_each_receipt_applicability_binding_fails_closed(binding):
 v,c=_receipt_case(); c["receiptIntegrityEvidence"]["r"][binding+"Id"]=I("stale-"+binding); code="OPERATION_MISMATCH" if binding=="operation" else binding.upper()+"_MISMATCH"; d=asserted_rejected(v,c,code); assert d["receiptVerification"]=="failed" and d["acceptedReceipts"]==[]

def test_schema_complete_outcome_and_continuation_vocabulary_and_implications():
 schema=json.loads((Path(__file__).parents[1]/"schemas/result-acceptance.schema.json").read_text()); val=Draft202012Validator(schema)
 assert set(schema["properties"]["outcome"]["enum"])==set(OUTCOMES); assert set(schema["properties"]["lawfulContinuation"]["enum"])==set(CONTINUATIONS)
 generated=[]
 for x in ("completed","partial","blocked","failed","not-applicable"): generated.append(accept_collaboration_result(result(x),control()).value)
 c=control(); del c["identities"]["state"]; generated.append(accept_collaboration_result(result(),c).value)
 c=control(); del c["liveEvidence"]; generated.append(accept_collaboration_result(result(),c).value)
 c=control(); c["requiredArtifacts"]=["a"]; generated.append(accept_collaboration_result(result(),c).value)
 bad=result(); bad["acceptance"]={}; generated.append(accept_collaboration_result(bad,control()).value)
 assert set(d["outcome"] for d in generated)==set(OUTCOMES)
 for d in generated: assert not list(val.iter_errors(d))
 accepted=generated[0]
 mutations=[("applicabilityVerification","failed"),("diagnostics",[{"code":"X","path":"x"}]),("lawfulContinuation","REPAIR_CANDIDATE")]
 for k,x in mutations:
  q=copy.deepcopy(accepted); q[k]=x; assert list(val.iter_errors(q))
 for outcome in set(OUTCOMES)-{"ACCEPTED"}:
  q=copy.deepcopy(accepted); q["outcome"]=outcome; assert list(val.iter_errors(q))
 q=copy.deepcopy(accepted);q["outcome"]="REQUIRES_CANDIDATE_REPAIR";q["transitionEligible"]=False; assert list(val.iter_errors(q))
 q=copy.deepcopy(accepted);q["outcome"]="UNKNOWN";assert list(val.iter_errors(q))
 q=copy.deepcopy(accepted);q["lawfulContinuation"]="UNKNOWN";assert list(val.iter_errors(q))
