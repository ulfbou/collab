import copy, json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator
from collab.collaboration_results import normalize_collaboration_result, render_legacy_result

H="0"*64
I=lambda domain="": "sha256:"+(domain+":v1:" if domain else "")+H

def base(outcome="completed"):
    return {"schema":"collab/collaboration-result/v1","normalizationVersion":"1","boundaryId":I("boundary"),"boundaryResponsibility":"IMPLEMENT_CANDIDATE","inputCaptureId":I("capture"),"semanticStateId":I("state"),"applicabilityIdentities":{"authority":I("authority"),"obligation":I("obligation")},"responsibility":"IMPLEMENT_CANDIDATE","outcome":outcome,"claims":[],"reportedObservations":[],"candidates":[],"artifacts":[],"receipts":[],"verificationEvidence":[],"changedPaths":[],"mutationEvidence":[],"diagnostics":[],"obligationClaims":[],"completeness":"complete" if outcome=="completed" else "partial","limitations":[],"documentationImpact":[],"requestedNextResponsibility":{"responsibility":"ASSESS_RESULT","prerequisites":[],"advisory":True}}

def code(v):
    r=normalize_collaboration_result(v); assert not r.valid; return r.diagnostics[0]["code"]

def test_minimal_completed_and_legacy_adapter():
    r=normalize_collaboration_result(base()); assert r.valid and r.value["resultId"].startswith("sha256:collaboration-result:v1:")
    assert render_legacy_result(base(),"Senior").value["status"]=="completed"

def test_complete_valid_result_and_internal_references():
    v=base(); v["artifacts"]=[{"id":"a","description":"candidate","identity":I("artifact"),"path":"out\\x.txt"}]; v["receipts"]=[{"id":"r","description":"receipt","identity":I("receipt")}]; v["claims"]=[{"id":"c","description":"done","artifactRefs":["a"],"receiptRefs":["r"]}]; v["changedPaths"]=["b.py","a.py"]
    r=normalize_collaboration_result(v); assert r.valid; assert r.value["changedPaths"]==["a.py","b.py"] and r.value["artifacts"][0]["path"]=="out/x.txt"
@pytest.mark.parametrize("outcome",["failed","blocked"])
def test_partial_evidence_preserved(outcome):
    v=base(outcome); v["artifacts"]=[{"id":"partial","description":"partial output","identity":I("artifact")}]
    if outcome=="blocked": v["limitations"]=["missing authority"]
    r=normalize_collaboration_result(v); assert r.valid and r.value["artifacts"][0]["id"]=="partial"
def test_not_applicable_requires_mismatch_and_no_completion():
    v=base("not-applicable");v["completeness"]="none";v["limitations"]=["boundary mismatch"];assert normalize_collaboration_result(v).valid
@pytest.mark.parametrize("field,value,expected",[("schema","wrong","schema"),("normalizationVersion","2","version"),("boundaryId","x","boundary-id")])
def test_invalid_schema_version_boundary(field,value,expected):
    v=base();v[field]=value;assert code(v)==expected
def test_incompatible_responsibility():
    v=base();v["responsibility"]="OTHER";assert code(v)=="responsibility-mismatch"
@pytest.mark.parametrize("kind,ref,expected",[("artifactRefs","missing","unresolved-artifact-ref"),("receiptRefs","missing","unresolved-receipt-ref")])
def test_unresolved_references(kind,ref,expected):
    v=base();v["claims"]=[{"id":"c","description":"x",kind:[ref]}];assert code(v)==expected
def test_duplicate_ids():
    v=base();v["claims"]=[{"id":"x","description":"a"},{"id":"x","description":"b"}];assert code(v)=="duplicate-id"
def test_contradictory_claims():
    v=base();v["claims"]=[{"id":"a","description":"ready"},{"id":"b","description":"not ready"}];assert code(v)=="contradictory-claims"
@pytest.mark.parametrize("field,expected",[("acceptance","self-acceptance"),("stateTransition","durable-transition")])
def test_forbidden_self_authority(field,expected):
    v=base();v[field]={"status":"accepted"};assert code(v)==expected
def test_read_only_mutation_rejected():
    v=base();v["responsibility"]=v["boundaryResponsibility"]="READ_ONLY_VALIDATE";v["changedPaths"]=["x"];assert code(v)=="read-only-mutation"
def test_reordering_set_like_input_is_stable():
    a=base();a["limitations"]=["z","a"];a["claims"]=[{"id":"b","description":"Î²"},{"id":"a","description":"Ã¥"}];b=copy.deepcopy(a);b["limitations"].reverse();b["claims"].reverse();ra=normalize_collaboration_result(a).value;rb=normalize_collaboration_result(b).value;assert ra==rb

def test_semantic_change_changes_identity_and_unicode_stable():
    a=base();a["claims"]=[{"id":"a","description":"RÃ¤ksmÃ¶rgÃ¥s"}];b=copy.deepcopy(a);b["claims"][0]["description"]="RÃ¤ksmÃ¶rgÃ¥s!";assert normalize_collaboration_result(a).value["resultId"]!=normalize_collaboration_result(b).value["resultId"]
def test_supplied_identity_must_match():
    v=base();v["resultId"]=I("collaboration-result");assert code(v)=="result-id"
def test_outcome_payload_rules():
    v=base("blocked");assert code(v)=="blocked-prerequisite";v=base();v["completeness"]="partial";assert code(v)=="outcome-completeness"
def test_schema_fixtures_use_canonical_validator():
    root=Path(__file__).parents[1]; schema=json.loads((root/'schemas/collaboration-result.schema.json').read_text()); validator=Draft202012Validator(schema)
    for p in (root/'tests/fixtures/collaboration-result').glob('*.json'):
        data=json.loads(p.read_text()); assert not list(validator.iter_errors(data)), p
