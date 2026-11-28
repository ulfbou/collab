import copy
from pathlib import Path
import pytest
import collab.accepted_transition_publication as p

I=lambda n: 'sha256:'+n+':v1:'+'a'*64

def inputs():
 prior={'stateIdentity':'sha256:v1:'+'b'*64,'captureId':'capture:20261017T000000.000000Z-aaaa1111','acceptedHistory':[]}
 boundary={'boundaryId':I('boundary')}
 acceptance={'acceptanceId':I('result-acceptance'),'outcome':'ACCEPTED','transitionEligible':True,'lawfulContinuation':'PUBLISH_TRANSITION','diagnostics':[],'controllingStateId':prior['stateIdentity'],'collaborationResultId':I('collaboration-result'),'controllingIdentities':{'boundary':boundary['boundaryId']},**{g:'passed' for g in p.GATES}}
 return prior,boundary,acceptance,{}

def test_deterministic_and_order_independent():
 a=p.construct_publication(prior_state=inputs()[0],boundary=inputs()[1],acceptance=inputs()[2],proposed_state={},attached_receipt_ids=[I('r2'),I('r1')])
 b=p.construct_publication(prior_state=inputs()[0],boundary=inputs()[1],acceptance=inputs()[2],proposed_state={},attached_receipt_ids=[I('r1'),I('r2')])
 assert a==b

def test_rejects_nonaccepted_stale_mismatch_and_overlap():
 prior,boundary,acceptance,next_state=inputs()
 for change,needle in [({'outcome':'FAILED_EVIDENCE_RETAINED'},'not transition eligible'),({'controllingStateId':I('stale')},'stale'),({'controllingIdentities':{'boundary':I('other')}},'boundary')]:
  bad=copy.deepcopy(acceptance); bad.update(change)
  with pytest.raises(ValueError,match=needle): p.construct_publication(prior_state=prior,boundary=boundary,acceptance=bad,proposed_state=next_state)
 with pytest.raises(ValueError,match='overlap'): p.construct_publication(prior_state=prior,boundary=boundary,acceptance=acceptance,proposed_state=next_state,attached_receipt_ids=[I('r')],invalidated_receipt_ids=[I('r')])

def test_atomic_pointer_replay_failure_and_symlink(tmp_path,monkeypatch):
 monkeypatch.setattr(p,'_validate',lambda *a: None)
 prior,boundary,acceptance,next_state=inputs(); root=tmp_path/'state'
 first=p.publish_accepted_transition(root,schemas=tmp_path,prior_state=prior,boundary=boundary,acceptance=acceptance,proposed_state=next_state)
 assert (root/'CURRENT').read_text().strip()==first['publicationId']
 again=p.publish_accepted_transition(root,schemas=tmp_path,prior_state=prior,boundary=boundary,acceptance=acceptance,proposed_state=next_state)
 assert again['status']=='already-complete'
 other=tmp_path/'other'; other.mkdir()
 with pytest.raises(RuntimeError,match='injected'):
  p.publish_accepted_transition(other,schemas=tmp_path,prior_state=prior,boundary=boundary,acceptance=acceptance,proposed_state=next_state,fail_before_commit=True)
 assert not (other/'CURRENT').exists()
 unsafe=tmp_path/'unsafe'; unsafe.mkdir(); (unsafe/'CURRENT').symlink_to(tmp_path/'target')
 with pytest.raises(OSError,match='symlink'):
  p.publish_accepted_transition(unsafe,schemas=tmp_path,prior_state=prior,boundary=boundary,acceptance=acceptance,proposed_state=next_state)
