#!/usr/bin/env bash
set -Eeuo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
TOOL="$HERE/collab-actions-evidence.py"
[[ -f "$TOOL" && ! -L "$TOOL" ]] || {
  printf 'ERROR: collector is missing or unsafe: %s\n' "$TOOL" >&2
  exit 1
}

python3 -m py_compile "$TOOL"
python3 "$TOOL" --version | grep -Fxq 'collab-actions-evidence.py 1.0.0'

python3 - "$TOOL" <<'PY'
import datetime as dt
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

tool=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('collab_actions_evidence',tool)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)

def failure(run_id, repository='ulfbou/collab', evidence='ERROR assertion failed expected 2 actual 3'):
    fingerprint=module.exact_fingerprint('Validate','tests (python 3.12)','Run tests',evidence)
    return module.FailureObservation(
        repository=repository,
        run_id=run_id,
        attempt=1,
        run_number=run_id,
        workflow='Validate',
        workflow_path='.github/workflows/validate.yml',
        branch='feat/action-analysis',
        event='push',
        commit=('a' if run_id == 1 else 'b') * 40,
        title='fixture',
        actor='tester',
        created_at=f'2026-08-2{run_id}T10:00:00Z',
        conclusion='failure',
        url=f'https://example.invalid/{run_id}',
        job_id=1000 + run_id,
        job='tests (python 3.12)',
        matrix='python 3.12',
        runner_name='fixture-runner',
        runner_group='fixture',
        step_number=1,
        step='Run tests',
        evidence=evidence,
        evidence_sha256=hashlib.sha256(evidence.encode()).hexdigest(),
        evidence_retrieval_status='ok',
        exact_fingerprint=fingerprint,
    )

first=failure(1)
second=failure(2,'ulfbou/prototype-knowledge')
third=failure(3,evidence='2026-08-25T11:22:33Z ERROR assertion failed expected 2 actual 3 run id 987654')

# Volatile timestamps, SHAs, identifiers, durations, and workspace paths normalize.
normalized=module.normalize_line(
    '2026-08-25T11:22:33Z ERROR deadbeef run id 987654 after 1200ms '
    '/home/runner/work/collab/collab/file.py'
)
assert '<sha>' in normalized
assert '<id>' in normalized or '<number>' in normalized
assert '<duration>' in normalized
assert '<workspace>' in normalized

# Stable diagnostic vocabulary and recovery classification.
diagnostic=module.classify_diagnostic(first)
assert diagnostic.code == 'TEST_ASSERTION_FAILURE'
assert diagnostic.category == 'VERIFICATION'
assert diagnostic.action['kind'] == 'EMIT_DX_FIRST_DIAGNOSTIC'
assert diagnostic.mechanicallyRepairable is False
assert module.responsibility_layer(diagnostic) == 'TEST'
vocabulary=module.diagnostic_vocabulary()
codes={entry['code'] for entry in vocabulary['codes']}
assert {'TEST_ASSERTION_FAILURE','UNCLASSIFIED_ACTION_FAILURE'} <= codes
assert vocabulary['compatibilityPolicy']['stableContract'] == 'code'

# Exact, approximate, and systemic layers remain distinct and explainable.
assert first.exact_fingerprint == second.exact_fingerprint
families=module.cluster_approximate([first,second,third],0.55,True)
assert len(families) == 1, families
family=families[0]
assert len(family.occurrences) == 3
assert 0.55 <= family.cohesion <= 1.0
systemic=module.cluster_systemic(families)
assert len(systemic) == 1
assert systemic[0].occurrence_count == 3
assert set(systemic[0].repositories) == {'ulfbou/collab','ulfbou/prototype-knowledge'}

# Decision-support record separates observation, diagnosis, recovery, and knowledge candidate.
since=dt.datetime(2026,8,18,tzinfo=dt.timezone.utc)
until=dt.datetime(2026,8,25,23,59,tzinfo=dt.timezone.utc)
record=module.decision_record(family,[],since,until)
assert record['observation']['occurrenceCount'] == 3
assert record['diagnostic']['code'] == 'TEST_ASSERTION_FAILURE'
assert record['classification']['responsibilityLayer'] == 'TEST'
assert record['recovery']['automaticActionPerformed'] is False
assert record['knowledgeCandidate']['candidate'] is True
assert 'REPEATED_FAILURE' in record['knowledgeCandidate']['triggers']
assert 'CROSS_REPOSITORY' in record['knowledgeCandidate']['triggers']
assert record['knowledgeCandidate']['requiresHumanAcceptance'] is True

# Complete outputs are internally consistent; readonly DX is reparsed and byte-compared.
with tempfile.TemporaryDirectory() as temporary:
    directory=Path(temporary)/'analysis'
    report=module.build_report(
        ['ulfbou/collab','ulfbou/prototype-knowledge'],
        since,until,[],[first,second,third],families,systemic,None,
        {'readOnly':True,'similarityModelVersion':'1.0'},
    )
    artifacts=module.write_output(directory,report)
    expected={
        'actions-report.json','actions-report.md','diagnostic-vocabulary.json',
        'evidence.dx.txt','families.json','lessons-candidates.json','manifest.json',
    }
    assert set(artifacts) == expected
    parsed=json.loads((directory/'actions-report.json').read_text(encoding='utf-8'))
    assert parsed['summary']['failureOccurrences'] == 3
    assert parsed['summary']['knowledgeCandidates'] == 1
    lessons=json.loads((directory/'lessons-candidates.json').read_text(encoding='utf-8'))
    assert len(lessons['candidates']) == 1
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    for name,identity in manifest['artifacts'].items():
        data=(directory/name).read_bytes()
        assert len(data) == identity['size']
        assert hashlib.sha256(data).hexdigest() == identity['sha256']
    carrier=(directory/'evidence.dx.txt').read_text(encoding='utf-8')
    assert carrier.startswith('%%DX v1.3.1\n')
    assert carrier.endswith('%%END\n')
    assert '\r' not in carrier
    assert carrier.count('%%FILE ') == 4
    assert carrier.count(' readonly="true"') == 4
    assert carrier.count('%%ENDBLOCK') == 4

# Atomic output refuses a symlink and preserves the target.
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary)
    target=root/'target'
    target.write_text('sentinel\n',encoding='utf-8')
    link=root/'link'
    link.symlink_to(target)
    try:
        module.atomic_write(link,b'replacement\n')
    except module.AppError:
        pass
    else:
        raise AssertionError('atomic_write accepted a symlink output')
    assert target.read_text(encoding='utf-8') == 'sentinel\n'

print('PASS: Actions evidence decision-support, similarity, knowledge, DX, and safety contracts')
PY