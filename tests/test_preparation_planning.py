import copy, json, unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from collab.preparation_planning import PreparationRequest, plan_preparation

ROOT=Path(__file__).resolve().parents[1]
class PreparationPlanningTests(unittest.TestCase):
 def setUp(self):
  self.boundary={"boundaryId":"sha256:boundary:v1:"+"1"*64,"status":"pending","objective":"issue-66"}
  self.items=[
   {"itemId":"state","domain":"state","byteSize":10,"artifactCount":1,"contextual":False},
   {"itemId":"intent-large","domain":"intent","byteSize":30,"artifactCount":1,"contextual":True},
   {"itemId":"intent-small","domain":"intent","byteSize":20,"artifactCount":1,"contextual":True},
   {"itemId":"other","domain":"context","byteSize":5,"artifactCount":1,"contextual":True,"boundaryIds":["other-boundary"]},]
  self.request={"schema":"collab/preparation-request/v1","boundary":self.boundary,"selection":"FOCUSED","requiredDomains":["state","intent"],"limits":{"bytes":100,"artifacts":4}}
  self.plan_validator=Draft202012Validator(json.loads((ROOT/'schemas/preparation-plan.schema.json').read_text(encoding='utf-8')))
 def test_focused_is_smallest_sufficient_and_deterministic(self):
  a=plan_preparation(self.request,self.items);b=plan_preparation(copy.deepcopy(self.request),list(reversed(self.items)))
  self.assertEqual("complete",a.status);self.assertEqual(a.value,b.value);self.plan_validator.validate(a.value)
  self.assertEqual(["intent-small","state"],[x["itemId"] for x in a.value["selectedItems"]])
  self.assertTrue(all(len(x["reasonCode"])>0 for x in a.value["selectedItems"]))
 def test_state_only_omits_context(self):
  req=copy.deepcopy(self.request);req["selection"]="STATE_ONLY";req["requiredDomains"]=["state"]
  result=plan_preparation(req,self.items);self.assertEqual(["state"],[x["itemId"] for x in result.value["selectedItems"]])
  self.assertIn("context-omitted-by-state-only",{x["reasonCode"] for x in result.value["omissions"]})
 def test_limits_yield_explicit_limitation(self):
  req=copy.deepcopy(self.request);req["limits"]={"bytes":10,"artifacts":1}
  result=plan_preparation(req,self.items);self.assertEqual("limited",result.status);self.assertEqual([{"domain":"intent","code":"required-domain-incomplete"}],result.value["limitations"])
 def test_broad_and_explicit_full(self):
  req=copy.deepcopy(self.request);req["selection"]="BROAD";self.assertEqual(3,len(plan_preparation(req,self.items).value["selectedItems"]))
  req["selection"]="EXPLICIT_FULL";req["explicitItemIds"]=["state","intent-large"]
  self.assertEqual({"state","intent-large"},{x["itemId"] for x in plan_preparation(req,self.items).value["selectedItems"]})
 def test_exactly_one_pending_boundary(self):
  for boundary in (None,[],{"boundaryId":"x","status":"completed"}):
   req=copy.deepcopy(self.request);req["boundary"]=boundary;self.assertEqual("invalid",plan_preparation(req,self.items).status)
 def test_pure_and_does_not_advance(self):
  req=copy.deepcopy(self.request);items=copy.deepcopy(self.items);before=(copy.deepcopy(req),copy.deepcopy(items))
  result=plan_preparation(req,items);self.assertEqual(before,(req,items));self.assertEqual("pending",result.value["boundary"]["status"])
  self.assertEqual({"writesPerformed":False,"boundaryAdvanced":False,"packageMaterialized":False},result.value["mutationSentinel"])
 def test_representation(self):
  req=PreparationRequest(self.boundary,"FOCUSED",("state",),10,1);self.assertEqual("collab/preparation-request/v1",req.as_mapping()["schema"])
if __name__=='__main__':unittest.main()
