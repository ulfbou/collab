import copy
import json
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from collab.boundary_attempts import create_boundary_attempt, serialize_boundary_attempt
from collab.boundary_contracts import ContractResult

H=lambda c: c*64

class BoundaryAttemptsTests(unittest.TestCase):
    def setUp(self):
        self.boundary={"schema":"collab/boundary-descriptor/v1","boundaryId":"sha256:boundary:v1:"+H("1")}
        self.context={"candidateIdentity":"sha256:candidate:v1:"+H("2"),"configurationIdentity":"sha256:configuration:v1:"+H("3"),"validatorIdentity":"sha256:validator:v1:"+H("4")}
        self.plan=["prepare","validate","publish"]
        self.authority={"completenessEstablished":True,"scopeConformityEstablished":True}
        self.completed=[self.op("prepare",0,"COMPLETED"),self.op("validate",1,"COMPLETED"),self.op("publish",2,"COMPLETED")]
    def op(self,n,o,s,owner=None,receipt_ids=None):
        x={"operationId":n,"ordinal":o,"status":s,"receiptIds":receipt_ids or []}
        if s=="FAILED": x["failure"]={"code":"FAILED_CODE","owner":owner,"operationId":n,"message":"explanation only"}
        return x
    def make(self,ops=None,**kw):
        return create_boundary_attempt(boundary=kw.get("boundary",self.boundary),operation_plan=kw.get("plan",self.plan),operation_plan_authority=kw.get("authority",self.authority),operations=ops or self.completed,receipts=kw.get("receipts",()),applicability_context=kw.get("context",self.context))
    def expect_invalid(self,ops=None,**kw):
        with self.assertRaises((ValueError,TypeError)): self.make(ops,**kw)
    def receipt(self,candidate=None,rid="5"):
        return {"schema":"collab/receipt/v1","receiptId":"sha256:receipt:v1:"+H(rid),"boundaryId":self.boundary["boundaryId"],"candidateIdentity":candidate or self.context["candidateIdentity"],"applicability":{"configuration":self.context["configurationIdentity"],"validator":self.context["validatorIdentity"]}}


    def test_operation_plan_identity_fixed_expectation_and_representation(self):
        out=self.make()
        self.assertEqual("sha256:operation-plan:v1:602603d6b34fa250807820edd127fad81f12917bc3a38f7e9cbd634bc2352741",out["operationPlanIdentity"])
        self.assertEqual(self.authority,dict(out["operationPlanAuthority"]))
    def test_equivalent_plan_identity_is_stable(self):
        self.assertEqual(self.make(plan=tuple(self.plan))["operationPlanIdentity"],self.make(plan=list(self.plan))["operationPlanIdentity"])
    def test_material_plan_change_changes_plan_and_attempt_identity(self):
        plan=["prepare","validate","release"]
        ops=[self.op("prepare",0,"COMPLETED"),self.op("validate",1,"COMPLETED"),self.op("release",2,"COMPLETED")]
        changed=self.make(ops,plan=plan); original=self.make()
        self.assertNotEqual(original["operationPlanIdentity"],changed["operationPlanIdentity"])
        self.assertNotEqual(original["attemptId"],changed["attemptId"])
    def test_order_change_changes_plan_identity(self):
        plan=["validate","prepare","publish"]
        ops=[self.op("validate",0,"COMPLETED"),self.op("prepare",1,"COMPLETED"),self.op("publish",2,"COMPLETED")]
        self.assertNotEqual(self.make()["operationPlanIdentity"],self.make(ops,plan=plan)["operationPlanIdentity"])
    def test_operation_plan_authority_is_required_closed_true_and_boolean(self):
        invalid=[None,[],{}, {"scopeConformityEstablished":True}, {"completenessEstablished":True},
                 {"completenessEstablished":False,"scopeConformityEstablished":True},
                 {"completenessEstablished":True,"scopeConformityEstablished":False},
                 {"completenessEstablished":1,"scopeConformityEstablished":True},
                 {"completenessEstablished":True,"scopeConformityEstablished":"true"},
                 {"completenessEstablished":True,"scopeConformityEstablished":True,"extra":True}]
        for authority in invalid:
            with self.subTest(authority=authority): self.expect_invalid(authority=authority)
    def test_plan_and_authority_inputs_are_not_mutated(self):
        plan=list(self.plan); authority=dict(self.authority); before=copy.deepcopy((plan,authority))
        self.make(plan=plan,authority=authority)
        self.assertEqual(before,(plan,authority))

    def test_requires_exactly_one_boundary(self):
        for b in (None,{},[],[self.boundary,self.boundary]): self.expect_invalid(boundary=b)
    def test_boundary_identity_must_match(self):
        b=dict(self.boundary,boundaryId="wrong"); self.expect_invalid(boundary=b)
    def test_closed_ledger_ordering(self):
        cases=[]
        x=copy.deepcopy(self.completed); x[1]["operationId"]="prepare"; cases.append(x)
        x=copy.deepcopy(self.completed); x[1]["ordinal"]=0; cases.append(x)
        x=copy.deepcopy(self.completed); x[1]["ordinal"]=3; cases.append(x)
        x=[self.completed[1],self.completed[0],self.completed[2]]; cases.append(x)
        x=[self.op("prepare",0,"FAILED","WORKFLOW"),self.op("validate",1,"FAILED","WORKFLOW"),self.op("publish",2,"NOT_ATTEMPTED")]; cases.append(x)
        x=[self.op("prepare",0,"FAILED","WORKFLOW"),self.op("validate",1,"COMPLETED"),self.op("publish",2,"NOT_ATTEMPTED")]; cases.append(x)
        x=[self.op("prepare",0,"NOT_ATTEMPTED"),self.op("validate",1,"COMPLETED"),self.op("publish",2,"NOT_ATTEMPTED")]; cases.append(x)
        for case in cases:
            with self.subTest(case=case): self.expect_invalid(case)
    def test_late_failure_preserves_earlier_completion(self):
        fixture=json.loads(Path("tests/fixtures/boundary-attempt/late-failure.json").read_text())
        result=self.make(fixture["operations"])
        self.assertEqual("COMPLETED",result["operations"][0]["status"]); self.assertEqual("validate",result["resumeOperationId"])
    def test_failure_owner_enum_is_closed(self):
        for owner in ["CANDIDATE","WORKFLOW","ENVIRONMENT","AUTHORITY","CONSISTENCY"]:
            self.make([self.op("prepare",0,"FAILED",owner),self.op("validate",1,"NOT_ATTEMPTED"),self.op("publish",2,"NOT_ATTEMPTED")])
        self.expect_invalid([self.op("prepare",0,"FAILED","OTHER"),self.op("validate",1,"NOT_ATTEMPTED"),self.op("publish",2,"NOT_ATTEMPTED")])
    def test_owner_is_not_inferred_from_message(self):
        x=self.op("prepare",0,"FAILED","WORKFLOW"); del x["failure"]["owner"]; x["failure"]["message"]="candidate broke"; self.expect_invalid([x,self.op("validate",1,"NOT_ATTEMPTED"),self.op("publish",2,"NOT_ATTEMPTED")])
    def _preservation(self,owner):
        r=self.receipt(); ops=[self.op("prepare",0,"COMPLETED",receipt_ids=[r["receiptId"]]),self.op("validate",1,"FAILED",owner),self.op("publish",2,"NOT_ATTEMPTED")]
        out=self.make(ops,receipts=[r]); self.assertTrue(out["receiptConclusions"][0]["applicable"])
    def test_workflow_failure_preserves_applicable_receipts(self): self._preservation("WORKFLOW")
    def test_environment_failure_preserves_applicable_receipts(self): self._preservation("ENVIRONMENT")
    def test_candidate_failure_invalidates_only_candidate_bound_receipts(self):
        old=self.receipt(candidate="sha256:candidate:v1:"+H("9")); current=self.receipt(rid="6")
        ops=[self.op("prepare",0,"COMPLETED",receipt_ids=[old["receiptId"],current["receiptId"]]),self.op("validate",1,"FAILED","CANDIDATE"),self.op("publish",2,"NOT_ATTEMPTED")]
        out=self.make(ops,receipts=[old,current]); self.assertEqual([False,True],[x["applicable"] for x in out["receiptConclusions"]])
    def test_delegates_to_authoritative_evaluator(self):
        r=self.receipt(); ops=[self.op("prepare",0,"COMPLETED",receipt_ids=[r["receiptId"]]),self.op("validate",1,"COMPLETED"),self.op("publish",2,"COMPLETED")]
        fake=ContractResult("valid",{"receiptId":r["receiptId"],"applicable":True,"invalidators":[]},())
        with patch("collab.boundary_attempts.evaluate_receipt_applicability",return_value=fake) as evaluator:
            self.make(ops,receipts=[r]); evaluator.assert_called_once()
    def test_continuation_points_and_blocks(self):
        out=self.make([self.op("prepare",0,"COMPLETED"),self.op("validate",1,"NOT_ATTEMPTED"),self.op("publish",2,"NOT_ATTEMPTED")]); self.assertEqual("validate",out["resumeOperationId"])
        self.assertIsNone(self.make()["resumeOperationId"])
        for owner in ("AUTHORITY","CONSISTENCY"):
            out=self.make([self.op("prepare",0,"FAILED",owner),self.op("validate",1,"NOT_ATTEMPTED"),self.op("publish",2,"NOT_ATTEMPTED")]); self.assertEqual("prepare",out["resumeOperationId"]); self.assertFalse(out["automaticContinuationAllowed"])
    def test_determinism_and_order_identity(self):
        a=self.make(); b=self.make(); self.assertEqual(serialize_boundary_attempt(a),serialize_boundary_attempt(b)); self.assertEqual(a["attemptId"],b["attemptId"])
        plan=["validate","prepare","publish"]; ops=[self.op("validate",0,"COMPLETED"),self.op("prepare",1,"COMPLETED"),self.op("publish",2,"COMPLETED")]; c=self.make(ops,plan=plan); self.assertNotEqual(a["attemptId"],c["attemptId"])
    def test_input_immutability_and_output_immutability(self):
        b=copy.deepcopy(self.boundary); ops=copy.deepcopy(self.completed); before=copy.deepcopy((b,ops)); out=self.make(ops,boundary=b); self.assertEqual(before,(b,ops)); self.assertIsInstance(out,MappingProxyType)
        with self.assertRaises(TypeError): out["resumeOperationId"]="x"
    def test_schema_identity_and_unknown_properties(self):
        out=self.make(); self.assertEqual("collab/boundary-attempt/v1",out["schema"]); self.assertEqual("1",out["normalizationVersion"])
        x=copy.deepcopy(self.completed); x[0]["extra"]=True; self.expect_invalid(x)

if __name__=="__main__": unittest.main()