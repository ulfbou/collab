import copy,json,unittest
from pathlib import Path
from jsonschema import Draft202012Validator,ValidationError
from collab.obligation_normalization import normalize_obligation_set
class Tests(unittest.TestCase):
 def setUp(self):
  self.cid='sha256:issue-content:v1:'+'1'*64;self.aid='sha256:authority-set:v1:'+'2'*64;self.did='sha256:'+'4'*64
  self.intent={'schema':'collab/development-intent/v1','normalizationVersion':'1','intentId':'sha256:development-intent:v1:'+'3'*64,'source':{'contentIdentity':self.cid},'authoritySetId':self.aid,'provenance':[{'identity':self.cid}],'limitations':[]}
  self.auth={'authoritySetId':self.aid,'status':'resolved','declaredAuthorities':[],'resolvedAuthorities':[{'kind':'contract','path':'docs/c.md','contentIdentity':self.did}],'invalidDeclarations':[],'absentDeclarations':[],'incompleteEvidence':[],'conflicts':[],'provenance':[],'limitations':[]}
  self.issue={'role':'change-authorization','sourceKind':'issue','sourceId':'#64','location':'issue:64','contentIdentity':self.cid};self.durable={'role':'durable-authority','sourceKind':'contract','sourceId':'c','location':'docs/c.md','contentIdentity':self.did};self.observed={'role':'observed-evidence','sourceKind':'repository-observation','sourceId':'tree','location':'HEAD','contentIdentity':'sha256:repository-observation:v1:'+'5'*64}
  self.req={'sourceRequirementId':'R1','statement':'Preserve provenance.','affectedScope':['b','a'],'requiredEvidence':['e2','e1'],'verification':{'kind':'comparison','target':'output','successCondition':'represented','requiredCapabilities':['read'],'mutating':False},'limitations':['not executed']}
  self.v=Draft202012Validator(json.loads(Path('schemas/obligation-set.schema.json').read_text()))
 def runn(self,s=None,r=None,a=None,i=None):return normalize_obligation_set(self.intent if i is None else i,self.auth if a is None else a,[{'source':self.issue if s is None else s,'requirements':[self.req if r is None else r]}])
 def test_deterministic_schema_and_no_execution(self):
  x=self.runn();self.assertEqual(x.value,self.runn().value);self.v.validate(x.value);self.assertEqual('normalized',x.status);self.assertFalse(x.value['verificationExecuted']);self.assertEqual('not-performed',x.value['acceptanceDecision'])
 def test_invalid_inputs_fail_closed(self):
  self.assertEqual('invalid',self.runn(i={}).status);self.assertEqual('invalid',self.runn(a={}).status);i=copy.deepcopy(self.intent);i['authoritySetId']='sha256:authority-set:v1:'+'9'*64;self.assertEqual('invalid',self.runn(i=i).status)
 def test_inputs_not_mutated(self):
  before=copy.deepcopy((self.intent,self.auth,self.req));self.runn();self.assertEqual(before,(self.intent,self.auth,self.req))
 def test_provenance_roles_distinct_and_observation_not_authority(self):
  x=normalize_obligation_set(self.intent,self.auth,[{'source':self.issue,'requirements':[self.req]},{'source':self.durable,'requirements':[dict(self.req,sourceRequirementId='R2')]}]);self.assertEqual({'change-authorization','durable-authority'},{p['role'] for p in x.value['provenance']});self.assertIn('authoritativeSource',self.runn(s=self.observed).value['incompleteObligations'][0]['missingFields'])
 def test_order_does_not_change_identities(self):
  q=copy.deepcopy(self.req);q['affectedScope'].reverse();q['requiredEvidence'].reverse();self.assertEqual(self.runn().value['obligationSetId'],self.runn(r=q).value['obligationSetId'])
 def test_material_fields_change_identity(self):
  base=self.runn().value['obligations'][0]['obligationId']
  for k,v in [('statement','x'),('affectedScope',['x']),('requiredEvidence',['x']),('limitations',['x'])]:q=copy.deepcopy(self.req);q[k]=v;self.assertNotEqual(base,self.runn(r=q).value['obligations'][0]['obligationId'])
  q=copy.deepcopy(self.req);q['verification']['target']='x';self.assertNotEqual(base,self.runn(r=q).value['obligations'][0]['obligationId'])
 def test_source_content_changes_identity(self):
  s=copy.deepcopy(self.issue);s['contentIdentity']='sha256:issue-content:v1:'+'8'*64;i=copy.deepcopy(self.intent);i['source']['contentIdentity']=s['contentIdentity'];i['provenance'][0]['identity']=s['contentIdentity'];self.assertNotEqual(self.runn().value['obligationSetId'],self.runn(s=s,i=i).value['obligationSetId'])
 def test_missing_fields_explicit(self):
  for f in ('statement','affectedScope','requiredEvidence','verification','limitations'):
   q=copy.deepcopy(self.req);q.pop(f);x=self.runn(r=q);self.v.validate(x.value);self.assertIn(f,x.value['incompleteObligations'][0]['missingFields'])
 def test_unavailable_content_explicit(self):
  a=copy.deepcopy(self.auth);a['resolvedAuthorities']=[];a['status']='incomplete';self.assertIn('authoritativeSource',self.runn(s=self.durable,a=a).value['incompleteObligations'][0]['missingFields'])
 def test_upstream_conflict_no_precedence(self):
  a=copy.deepcopy(self.auth);a['status']='conflicted';a['conflicts']=[{'authorityId':'x'}];x=self.runn(a=a);self.v.validate(x.value);self.assertEqual('conflicted',x.status);self.assertEqual('not-inferred',x.value['conflicts'][0]['precedence'])
 def test_every_requirement_accounted_for(self):
  q=copy.deepcopy(self.req);q.pop('statement');q['sourceRequirementId']='R2';x=normalize_obligation_set(self.intent,self.auth,[{'source':self.issue,'requirements':[self.req,q]}]);self.assertEqual({'R1','R2'},{r['sourceRequirementId'] for r in x.value['obligations']+x.value['incompleteObligations']})
 def test_mutating_verification_not_accepted(self):
  q=copy.deepcopy(self.req);q['verification']['mutating']=True;self.assertIn('verification',self.runn(r=q).value['incompleteObligations'][0]['missingFields'])
 def test_invalid_status_combination_rejected(self):
  x=copy.deepcopy(self.runn().value);x['status']='incomplete'
  with self.assertRaises(ValidationError):self.v.validate(x)
 def test_package_root_not_expanded(self):
  import collab;self.assertFalse(hasattr(collab,'normalize_obligation_set'))
if __name__=='__main__':unittest.main()
