import copy, io, json, os, socket, subprocess, unittest, urllib.request
from pathlib import Path
from unittest import mock
from jsonschema import Draft202012Validator, ValidationError
from collab.boundary_contracts import create_boundary_descriptor, issue_receipt
from collab.continuation_classification import CLASSIFIER_VERSION, CONTINUATION_DECISION_SCHEMA, DECISIONS, ClassificationError, classify_continuation

ROOT=Path(__file__).resolve().parents[1]
SCHEMA=json.loads((ROOT/'schemas/continuation-decision.schema.json').read_text(encoding='utf-8'))
VALIDATOR=Draft202012Validator(SCHEMA)
def ident(domain,ch): return f'sha256:{domain}:v1:'+ch*64

def evidence():
 ids={name:ident(name,str(i)) for i,name in enumerate(('baseline','configuration','validator','state','intent','authority','obligation','subject'),1)}
 boundary=create_boundary_descriptor(responsibility='Issue 68',scope=['collab','schemas'],identities=ids,limitations=[]).value
 candidate=ident('candidate','9')
 receipt=issue_receipt(boundary,candidate_identity=candidate,mutation_identity=ident('mutation','8'),completion_identity=ident('completion','7'),evidence_identities=[ident('evidence','6')]).value
 return {'boundary':boundary,'receipt':receipt,'candidateIdentity':candidate,'configurationIdentity':ids['configuration'],'validatorIdentity':ids['validator']}

class ContinuationTests(unittest.TestCase):
 def result(self,**changes):
  x=evidence(); x.update(changes); y=classify_continuation(x); VALIDATOR.validate(y); return y
 def test_all_nine_decisions_are_distinct_and_schema_valid(self):
  cases={'REUSE_RECEIPT':{},'EXECUTE_BOUNDARY':{'receipt':None},'REQUEST_EVIDENCE':{'missingDomains':['candidate']},'REQUEST_DECISION':{'authorityState':'RESERVED'},'WAIT_FOR_HOSTED_STATE':{'hostedState':'INCOMPLETE'},'REOBSERVE_STATE':{'authorityState':'CONFLICTING'},'REJECT_INCONSISTENT_STATE':{'inconsistencyState':'IRRECONCILABLE'},'RESUME_PARTIAL_BOUNDARY':{'attemptState':'PARTIAL'},'REPAIR_NARROW_FAILURE':{'attemptState':'NARROW_FAILURE'}}
  self.assertEqual(set(DECISIONS),set(cases))
  for expected,patch in cases.items(): self.assertEqual(expected,self.result(**patch)['decision'])
 def test_issue65_boundary_receipt_reused_unchanged(self):
  x=evidence(); before=copy.deepcopy(x); y=classify_continuation(x)
  self.assertEqual('REUSE_RECEIPT',y['decision']); self.assertEqual(before,x); self.assertTrue(y['applicability']['applicable'])
 def test_issue65_material_invalidators(self):
  cases=('candidateIdentity','configurationIdentity','validatorIdentity')
  for field in cases:
   x=evidence(); x[field]=ident(field.replace('Identity','').lower(),'a'); y=classify_continuation(x)
   self.assertEqual('EXECUTE_BOUNDARY',y['decision']); self.assertFalse(y['applicability']['applicable'])
  x=evidence(); ids=dict(x['boundary']['identities']); ids['baseline']=ident('baseline','a')
  x['boundary']=create_boundary_descriptor(responsibility=x['boundary']['responsibility'],scope=x['boundary']['scope'],identities=ids,limitations=[]).value
  y=classify_continuation(x); self.assertEqual('EXECUTE_BOUNDARY',y['decision']); self.assertIn('boundaryId',[z['field'] for z in y['applicability']['invalidators']])
 def test_malformed_predecessor_evidence_fails_closed(self):
  for patch in ({'boundary':{}},{'receipt':{}},{'receipt':[]},{'boundary':[]}):
   x=evidence(); x.update(patch)
   with self.assertRaises(ClassificationError): classify_continuation(x)
 def test_exact_missing_domains_and_closed_input(self):
  y=self.result(missingDomains=['validator','candidate']); self.assertEqual(['candidate','validator'],y['missingDomains']); self.assertEqual(['candidate','validator'],y['diagnostics'][0]['domains'])
  x=evidence(); x['extra']=1
  with self.assertRaises(ClassificationError): classify_continuation(x)
  x=evidence(); x['missingDomains']=['x','x']
  with self.assertRaises(ClassificationError): classify_continuation(x)
 def test_recoverable_conflicts_reobserve_and_explicit_irreconcilable_rejects(self):
  for patch in ({'authorityState':'CONFLICTING'},{'observationState':'CONFLICTING'},{'hostedState':'CONFLICTING'},{'inconsistencyState':'RECOVERABLE'}): self.assertEqual('REOBSERVE_STATE',self.result(**patch)['decision'])
  self.assertEqual('REJECT_INCONSISTENT_STATE',self.result(inconsistencyState='IRRECONCILABLE')['decision'])
 def test_boundary_identity_and_deterministic_identity(self):
  x=evidence(); a=classify_continuation(x); self.assertEqual(x['boundary']['boundaryId'],a['boundaryIdentity']); self.assertEqual(a,classify_continuation(copy.deepcopy(x)))
  p=evidence(); p['missingDomains']=['validator','candidate']; q=evidence(); q['missingDomains']=['candidate','validator']; self.assertEqual(classify_continuation(p),classify_continuation(q))
  for field in ('candidateIdentity','configurationIdentity','validatorIdentity'):
   changed=evidence(); changed[field]=ident('changed','a'); self.assertNotEqual(a['classifierIdentity'],classify_continuation(changed)['classifierIdentity'])
 def test_enum_parity_closed_schema_and_diagnostics_order(self):
  self.assertEqual(set(DECISIONS),set(SCHEMA['properties']['decision']['enum'])); self.assertEqual('collab/continuation-decision/v1',CONTINUATION_DECISION_SCHEMA); self.assertEqual(1,CLASSIFIER_VERSION); self.assertFalse(SCHEMA['additionalProperties'])
  y=self.result(blockedOperations=['z','a']); self.assertEqual(['a','z'],y['blockedOperations']); self.assertTrue(y['diagnostics'])
  bad=dict(y); bad['extra']=1
  with self.assertRaises(ValidationError): VALIDATOR.validate(bad)
 def test_execute_has_no_fabricated_execution_blocker(self):
  y=self.result(receipt=None); self.assertEqual('EXECUTE_BOUNDARY',y['decision']); self.assertEqual([],y['blockedOperations'])
  y=self.result(receipt=None,blockedOperations=['hosted-mutation']); self.assertEqual(['hosted-mutation'],y['blockedOperations'])
 def test_no_io_process_git_network_hosted_or_path_traversal(self):
  paths=['../escape','/absolute','C:\\Windows\\x','\\\\server\\share','symlink-looking']
  for value in paths:
   x=evidence(); x['missingDomains']=[value]
   with mock.patch('builtins.open',side_effect=AssertionError('read/write')), mock.patch.object(io,'open',side_effect=AssertionError('io')), mock.patch.object(Path,'open',side_effect=AssertionError('path')), mock.patch.object(Path,'read_text',side_effect=AssertionError('read')), mock.patch.object(Path,'write_text',side_effect=AssertionError('write')), mock.patch.object(subprocess,'run',side_effect=AssertionError('process')), mock.patch.object(subprocess,'Popen',side_effect=AssertionError('process')), mock.patch.object(subprocess,'check_call',side_effect=AssertionError('process')), mock.patch.object(subprocess,'check_output',side_effect=AssertionError('process')), mock.patch.object(os,'system',side_effect=AssertionError('git')), mock.patch.object(os,'popen',side_effect=AssertionError('git')), mock.patch.object(socket,'create_connection',side_effect=AssertionError('network')), mock.patch.object(socket,'socket',side_effect=AssertionError('network')), mock.patch.object(urllib.request,'urlopen',side_effect=AssertionError('http')):
    self.assertEqual('REQUEST_EVIDENCE',classify_continuation(x)['decision'])
 def test_no_issue69_capability_or_successor_import(self):
  text=(ROOT/'collab/continuation_classification.py').read_text(encoding='utf-8')
  self.assertNotIn('BoundaryAttempt',text); self.assertNotIn('issue69',text.lower()); self.assertNotIn('attempt_ledger',text)

if __name__=='__main__': unittest.main()
