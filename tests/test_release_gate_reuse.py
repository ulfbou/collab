from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from collab.filesystem import write_json_atomic, write_text_atomic
from collab.process import ExecutionClassification, run_process
from collab.repository import capture_git_state
from collab.dx_verification import verify_final_carrier

def test_atomic_text_and_json_values(tmp_path):
    write_text_atomic(tmp_path/'a.txt','å\n')
    assert (tmp_path/'a.txt').read_bytes()=='å\n'.encode()
    write_json_atomic(tmp_path/'a.json',{'z':1,'a':'å'})
    assert json.loads((tmp_path/'a.json').read_text())=={'a':'å','z':1}

def test_structured_process_result_and_evidence(tmp_path):
    result=run_process(command_id='ok',argv=(sys.executable,'-c','print("ok")'),cwd=tmp_path,evidence_directory=tmp_path/'evidence',timeout_seconds=10)
    assert result.classification is ExecutionClassification.SUCCESS
    assert Path(result.stdout_path).read_text().strip()=='ok'

def test_timeout_terminates_process_tree(tmp_path):
    result=run_process(command_id='timeout',argv=(sys.executable,'-c','import time; time.sleep(30)'),cwd=tmp_path,evidence_directory=tmp_path/'evidence',timeout_seconds=1)
    assert result.classification is ExecutionClassification.TIMEOUT
    assert result.timed_out and result.termination_actions

def test_git_state_capture(tmp_path):
    subprocess.run(('git','init','-q'),cwd=tmp_path,check=True)
    subprocess.run(('git','config','user.email','test@example.invalid'),cwd=tmp_path,check=True)
    subprocess.run(('git','config','user.name','Test'),cwd=tmp_path,check=True)
    (tmp_path/'a').write_text('a')
    subprocess.run(('git','add','a'),cwd=tmp_path,check=True)
    subprocess.run(('git','commit','-qm','fixture'),cwd=tmp_path,check=True)
    (tmp_path/'a').write_text('b')
    state=capture_git_state(tmp_path)
    assert state['head']
    assert state['status']
    assert state['tracked_diff']

def test_real_final_carrier_verification(tmp_path):
    root=Path(__file__).resolve().parents[1]
    payload=tmp_path/'payload'
    payload.mkdir()
    (payload/'a.txt').write_text('a\n')
    carrier=tmp_path/'final.dx.txt'
    completed=subprocess.run(
        (
            sys.executable,
            str(root/'dx.py'),
            'pack',
            str(payload),
            '--root',
            str(payload),
            '-o',
            str(carrier),
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode==0,completed.stderr
    verified=verify_final_carrier(carrier,repository_root=root)
    assert verified.verification=='STRUCTURE_VALID'
    assert len(verified.sha256)==64
