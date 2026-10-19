#!/usr/bin/env python3
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess

from collab.artifacts import canonical_json_bytes
from collab.github import GitHubClient, GitHubError
import secrets
import tempfile
from pathlib import Path, PurePosixPath


class Error(Exception):
    pass


CURRENT_STATE_SCHEMA_VERSION = '1.0'
STATE_IDENTITY_NORMALIZATION_VERSION = '1'
STATE_IDENTITY_PREFIX = f'sha256:v{STATE_IDENTITY_NORMALIZATION_VERSION}:'
HOSTED_DOMAIN_NAMES = (
    'repository',
    'openIssues',
    'openPullRequests',
    'recentlyMergedPullRequests',
    'labels',
    'milestones',
    'selectedIssue',
)


def run(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise Error(p.stderr.strip() or f"command failed ({p.returncode}): {' '.join(args)}")
    return p.stdout


def git_bash():
    override = os.environ.get('COLLAB_BASH_BIN')
    if override:
        path = Path(override)
        if not path.is_file():
            raise Error(f'COLLAB_BASH_BIN does not identify a file: {override}')
        return str(path)

    candidates = []
    git = shutil.which('git.exe') or shutil.which('git')
    if git:
        git_path = Path(git)
        candidates.extend([
            git_path.parent.parent / 'bin' / 'bash.exe',
            git_path.parent.parent / 'usr' / 'bin' / 'bash.exe',
        ])

    program_files = os.environ.get('ProgramFiles')
    if program_files:
        candidates.extend([
            Path(program_files) / 'Git' / 'bin' / 'bash.exe',
            Path(program_files) / 'Git' / 'usr' / 'bin' / 'bash.exe',
        ])

    candidates.extend([
        Path(r'C:\Program Files\Git\bin\bash.exe'),
        Path(r'C:\Program Files\Git\usr\bin\bash.exe'),
    ])

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    checked = ', '.join(str(c) for c in candidates)
    raise Error('Git Bash could not be located; set COLLAB_BASH_BIN to the full '
                f'path of bash.exe. Checked: {checked}')


def gh_bin():
    override = os.environ.get('COLLAB_GH_BIN')
    if override:
        return [git_bash(), override] if os.name == 'nt' else [override]
    return ['gh']


def safe(raw):
    p = PurePosixPath(raw.replace('\\', '/'))
    if p.is_absolute() or not p.parts or '..' in p.parts or str(p) == '.' or '\0' in raw:
        raise Error(f'unsafe path: {raw}')
    return str(p).rstrip('/')


def atomic(path: Path, data: bytes):
    # Check the target path itself, not after resolving symlinks.
    if path.is_symlink():
        raise Error(f'refusing to replace symlink: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise Error(f'refusing unsafe output parent: {path.parent}')
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.tmp.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def repo_name(root):
    u = run(['git', 'remote', 'get-url', 'origin'], root).strip()
    u = re.sub(r'\.git$', '', u)
    for p in ('git@github.com:', 'https://github.com/', 'http://github.com/', 'ssh://git@github.com/'):
        if u.startswith(p):
            u = u[len(p):]
            break
    if u.count('/') != 1:
        raise Error(f'cannot derive repository from origin: {u}')
    return u


def cached_default_branch(root: Path):
    process = subprocess.run(
        ['git', 'symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD'],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        return None
    value = process.stdout.strip()
    if not value:
        return None
    return value.removeprefix('origin/')


def github_default_branch(github):
    if not isinstance(github, dict):
        return None
    data = github.get('data')
    if not isinstance(data, dict):
        return None
    repository = data.get('repository')
    if not isinstance(repository, dict):
        return None
    default_ref = repository.get('defaultBranchRef')
    if not isinstance(default_ref, dict):
        return None
    value = default_ref.get('name')
    if not isinstance(value, str) or not value:
        return None
    return value


def git_model(root: Path, repo=None, recent=20):
    root = root.resolve()
    origin_url = run(['git', 'remote', 'get-url', 'origin'], root).strip()
    repo = repo or repo_name(root)
    head = run(['git', 'rev-parse', 'HEAD'], root).strip()
    branch = run(['git', 'branch', '--show-current'], root).strip()
    default = cached_default_branch(root)
    tree = sorted(
        path
        for path in run(['git', 'ls-files', '-z'], root).split('\0')
        if path
    )
    status = run(['git', 'status', '--porcelain=v1', '--untracked-files=all'], root)
    commits = []
    for line in run(['git', 'log', '-n', str(recent), '--format=%H%x09%cI%x09%s'], root).splitlines():
        sha, date, subject = line.split('\t', 2)
        commits.append({'sha': sha, 'date': date, 'subject': subject})
    return {
        'repository': repo,
        'origin': origin_url,
        'root': str(root),
        'defaultBranch': default,
        'currentBranch': branch,
        'head': head,
        'workingTree': 'CLEAN' if not status else 'DIRTY',
        'statusPorcelain': status,
        'trackedTree': tree,
        'recentCommits': commits,
    }


def github_model(repo, root, recent_closed, selected_issue=None):
    keys = ('repository', 'openIssues', 'openPullRequests',
            'recentlyMergedPullRequests', 'labels', 'milestones')
    client = GitHubClient(cwd=root, command=gh_bin())
    try:
        client.authenticate()
    except Exception as e:
        return {
            'schemaVersion': '1.0',
            'repository': repo,
            'requested': True,
            'available': False,
            'selectedIssueRequested': selected_issue is not None,
            'queryStatus': {k: 'unavailable' for k in keys},
            'errors': [{'section': 'authentication', 'error': str(e)}],
            'data': {}
        }

    q = {
        'repository': gh_bin() + ['repo', 'view', repo,
                                  '--json', 'nameWithOwner,description,url,defaultBranchRef,isPrivate,visibility'],
        'openIssues': gh_bin() + ['issue', 'list', '--repo', repo,
                                  '--state', 'open', '--limit', '100',
                                  '--json', 'number,title,body,state,labels,milestone,assignees,author,createdAt,updatedAt,url'],
        'openPullRequests': gh_bin() + ['pr', 'list', '--repo', repo,
                                        '--state', 'open', '--limit', '100',
                                        '--json', 'number,title,body,state,isDraft,baseRefName,headRefName,headRefOid,labels,milestone,url'],
        'recentlyMergedPullRequests': gh_bin() + ['pr', 'list', '--repo', repo,
                                                  '--state', 'merged',
                                                  '--limit', str(recent_closed),
                                                  '--json', 'number,title,body,baseRefName,headRefName,headRefOid,mergeCommit,mergedAt,labels,milestone,author,url'],
        'labels': gh_bin() + ['label', 'list', '--repo', repo,
                              '--limit', '100',
                              '--json', 'name,color,description'],
        'milestones': gh_bin() + ['api', '--paginate',
                                  f'repos/{repo}/milestones?state=open&per_page=100'],
    }

    st = {}
    data = {}
    errors = []
    for k, c in q.items():
        try:
            v = client.request_json(c[len(gh_bin()):]).value
            st[k] = 'ok'
            if isinstance(v, list):
                if k in ('openIssues', 'openPullRequests', 'recentlyMergedPullRequests'):
                    v.sort(key=lambda x: x.get('number', 0))
                elif k == 'labels':
                    v.sort(key=lambda x: x.get('name', ''))
                elif k == 'milestones':
                    v.sort(key=lambda x: (x.get('title', ''), x.get('number', 0)))
            data[k] = v
        except Exception as e:
            st[k] = 'failed'
            errors.append({'section': k, 'error': str(e)})

    # Selected issue, if requested
    selected_issue_data = None
    if selected_issue is not None:
        try:
            selected_issue_data = client.request_json([
                'issue', 'view', str(selected_issue), '--repo', repo, '--json',
                'number,title,body,state,labels,milestone,assignees,author,createdAt,updatedAt,closedAt,url',
            ]).value
            st['selectedIssue'] = 'ok'
        except Exception as e:
            st['selectedIssue'] = 'failed'
            errors.append({'section': 'selectedIssue', 'error': str(e)})

    return {
        'schemaVersion': '1.0',
        'repository': repo,
        'requested': True,
        'available': True,
        'selectedIssueRequested': selected_issue is not None,
        'queryStatus': st,
        'errors': errors,
        'data': data,
        'selectedIssue': selected_issue_data,
    }


def prefix(path, p):
    return path == p or path.startswith(p + '/')


def selected(root, tracked, includes, excludes, max_bytes, with_files=True):
    if not with_files:
        # File content collection disabled: return empty list to avoid reading files.
        return []

    inc = [safe(x) for x in includes]
    exc = [safe(x) for x in excludes] + ['.dx']
    out = []
    matched = set()
    for path in tracked:
        if inc and not any(prefix(path, x) for x in inc):
            continue
        if any(prefix(path, x) for x in exc):
            continue
        for x in inc:
            if prefix(path, x):
                matched.add(x)
        p = root / path
        if not p.is_file() or p.is_symlink():
            continue
        b = p.read_bytes()
        rec = {'path': path, 'size': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
        if len(b) > max_bytes:
            rec.update(status='omitted', reason='oversized')
        elif b'\0' in b:
            rec.update(status='omitted', reason='binary')
        else:
            try:
                rec['content'] = b.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
                rec['status'] = 'included'
            except UnicodeDecodeError:
                rec.update(status='omitted', reason='non-utf8')
        out.append(rec)
    for x in inc:
        if x not in matched:
            out.append({'path': x, 'status': 'missing', 'reason': 'not-tracked'})
    return sorted(out, key=lambda x: x['path'])


def classification_entry(value, evidence, *, rule_id, rule_version='1'):
    return {
        'value': value,
        'evidence': list(evidence),
        'rule': {
            'id': rule_id,
            'version': rule_version,
        },
    }


def completeness_entry(status, evidence, *, requested, reason=None, rule_id='hosted-domain-completeness', rule_version='1'):
    entry = {
        'status': status,
        'requested': requested,
        'evidence': list(evidence),
        'rule': {
            'id': rule_id,
            'version': rule_version,
        },
    }
    if reason is not None:
        entry['reason'] = reason
    return entry


def _field_path(prefix, *parts):
    return '.'.join((prefix, *parts))


def _project_labels(labels):
    out = []
    for item in labels or []:
        if isinstance(item, dict):
            out.append({'name': item.get('name'), 'color': item.get('color')})
    return sorted(out, key=lambda x: x.get('name') or '')


def _project_milestone(value):
    if not isinstance(value, dict):
        return None
    return {
        'number': value.get('number'),
        'title': value.get('title'),
        'state': value.get('state'),
    }


def _project_repository(value):
    if not isinstance(value, dict):
        return None
    default_ref = value.get('defaultBranchRef')
    default_branch = default_ref.get('name') if isinstance(default_ref, dict) else None
    return {
        'nameWithOwner': value.get('nameWithOwner'),
        'defaultBranch': default_branch,
    }


def _project_issue(value):
    if not isinstance(value, dict):
        return None
    return {
        'number': value.get('number'),
        'state': value.get('state'),
        'title': value.get('title'),
        'labels': _project_labels(value.get('labels')),
        'milestone': _project_milestone(value.get('milestone')),
        'assignees': sorted(
            [item.get('login') for item in value.get('assignees', []) if isinstance(item, dict) and item.get('login')],
        ),
    }


def _project_issue_collection(items):
    projected = [_project_issue(item) for item in items or [] if isinstance(item, dict)]
    return sorted(projected, key=lambda x: (x.get('number') or 0, x.get('title') or ''))


def _project_pull_request(value):
    if not isinstance(value, dict):
        return None
    return {
        'number': value.get('number'),
        'state': value.get('state'),
        'title': value.get('title'),
        'baseRefName': value.get('baseRefName'),
        'headRefName': value.get('headRefName'),
        'headRefOid': value.get('headRefOid'),
        'mergedAt': value.get('mergedAt'),
        'labels': _project_labels(value.get('labels')),
        'milestone': _project_milestone(value.get('milestone')),
        'author': value.get('author', {}).get('login') if isinstance(value.get('author'), dict) else None,
    }


def _project_pull_request_collection(items):
    projected = [_project_pull_request(item) for item in items or [] if isinstance(item, dict)]
    return sorted(
        projected,
        key=lambda x: (
            x.get('number') or 0,
            x.get('headRefOid') or '',
            x.get('title') or '',
        ),
    )


def _project_github_domains(github):
    data = github.get('data') if isinstance(github, dict) else {}
    return {
        'repository': _project_repository(data.get('repository')),
        'openIssues': _project_issue_collection(data.get('openIssues', [])),
        'openPullRequests': _project_pull_request_collection(data.get('openPullRequests', [])),
        'recentlyMergedPullRequests': _project_pull_request_collection(data.get('recentlyMergedPullRequests', [])),
        'labels': sorted([item.get('name') for item in data.get('labels', []) if isinstance(item, dict) and item.get('name')]),
        'milestones': sorted(
            [
                {
                    'number': item.get('number'),
                    'title': item.get('title'),
                    'state': item.get('state'),
                }
                for item in data.get('milestones', [])
                if isinstance(item, dict)
            ],
            key=lambda x: (x.get('title') or '', x.get('number') or 0),
        ),
    }


def hosted_domain_completeness(github):
    requested = bool(github.get('requested')) if isinstance(github, dict) else False
    available = bool(github.get('available')) if isinstance(github, dict) else False
    query_status = github.get('queryStatus') if isinstance(github, dict) else {}
    selected_requested = bool(github.get('selectedIssueRequested')) if isinstance(github, dict) else False

    domains = {}
    for domain in HOSTED_DOMAIN_NAMES:
        if not requested:
            domains[domain] = completeness_entry(
                'not_requested',
                [f'observations.hostedState.requested'],
                requested=False,
                reason='github-not-requested',
            )
            continue
        if not available:
            domains[domain] = completeness_entry(
                'unavailable',
                [f'observations.hostedState.available', f'observations.hostedState.queryStatus.{domain}'],
                requested=True,
                reason='github-unavailable',
            )
            continue

        if domain == 'selectedIssue' and not selected_requested:
            domains[domain] = completeness_entry(
                'not_applicable',
                [f'observations.hostedState.selectedIssueRequested'],
                requested=False,
                reason='selected-issue-not-requested',
            )
            continue

        status = 'observed' if query_status.get(domain) == 'ok' else 'failed'
        reason = None if status == 'observed' else 'requested-domain-failed'
        evidence = [f'observations.hostedState.queryStatus.{domain}']
        if status == 'observed':
            evidence.append(f'observations.hostedState.data.{domain}')
        domains[domain] = completeness_entry(status, evidence, requested=True, reason=reason)

    overall = 'observed'
    if not requested:
        overall = 'not_requested'
    elif not available:
        overall = 'unavailable'
    elif any(entry['status'] == 'failed' for entry in domains.values()):
        overall = 'partial'
    return {'overall': overall, 'domains': domains}


def mutation_sentinel():
    return {
        'contractVersion': '1',
        'operation': 'current-state-capture-and-projection',
        'evidenceType': 'test-evidence',
        'prohibitedSurfaces': [
            'tracked-content',
            'index',
            'working-tree',
            'branch',
            'HEAD',
            'hosted-state',
            'accepted-history',
        ],
        'unmeasuredSurfaces': [
            'live-telemetry',
        ],
        'limitations': [
            'non-mutation is established by implementation contract and focused tests, not by embedded runtime telemetry',
        ],
    }


def hosted_state_classification(github, completeness):
    if not github.get('requested'):
        return classification_entry(
            'not_requested',
            ['observations.hostedState.requested'],
            rule_id='hosted-state-classification',
        )
    if not github.get('available'):
        return classification_entry(
            'unavailable',
            ['observations.hostedState.available', 'observations.hostedState.queryStatus'],
            rule_id='hosted-state-classification',
        )
    if completeness['overall'] == 'partial':
        return classification_entry(
            'partial',
            ['completeness.hosted'],
            rule_id='hosted-state-classification',
        )
    return classification_entry(
        'available',
        ['observations.hostedState.available', 'completeness.hosted'],
        rule_id='hosted-state-classification',
    )


def selected_issue_classification(github, completeness):
    domain = completeness['domains']['selectedIssue']
    return classification_entry(
        domain['status'],
        ['observations.hostedState.selectedIssue', 'completeness.hosted.domains.selectedIssue'],
        rule_id='selected-issue-classification',
    )


def selected_files_classification(selected_files):
    value = 'present' if selected_files else 'absent'
    return classification_entry(
        value,
        ['observations.selectedFiles'],
        rule_id='selected-files-classification',
    )


def working_tree_classification(git):
    return classification_entry(
        git['workingTree'],
        ['observations.git.statusPorcelain', 'observations.git.workingTree'],
        rule_id='working-tree-classification',
    )


def hosted_semantic_projection(record):
    hosted = record['observations']['hostedState']
    completeness = record['completeness']['hosted']
    return {
        'requested': hosted['requested'],
        'available': hosted['available'],
        'domains': _project_github_domains(hosted),
        'completeness': completeness,
    }


def current_state_capture_id() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    return f'capture:{stamp}-{secrets.token_hex(4)}'


def current_state_semantic_projection(record):
    return {
        'stateIdentityNormalizationVersion': STATE_IDENTITY_NORMALIZATION_VERSION,
        'observations': {
            'repository': record['observations']['repository'],
            'git': record['observations']['git'],
            'hostedState': hosted_semantic_projection(record),
            'selectedFiles': record['observations']['selectedFiles'],
            'configuration': record['observations']['configuration'],
        },
        'relationships': record['relationships'],
        'controllingState': record['controllingState'],
        'workingState': record['workingState'],
        'candidate': record['candidate'],
        'classifications': record['classifications'],
        'acceptedHistory': record['acceptedHistory'],
        'completeness': record['completeness'],
        'consistency': record['consistency'],
    }


def current_state_identity(record):
    digest = hashlib.sha256(canonical_json_bytes(current_state_semantic_projection(record))).hexdigest()
    return STATE_IDENTITY_PREFIX + digest


def current_state_record(m, *, capture_id=None, output_path=None, rendering=None):
    git = copy.deepcopy(m['git'])
    github = copy.deepcopy(m['github'])
    selected_files = copy.deepcopy(m['selectedFiles'])
    relationships = copy.deepcopy(m['relationships'])
    configuration = copy.deepcopy(m.get('configuration', {}))
    repository = {
        'nameWithOwner': git['repository'],
        'origin': git['origin'],
        'defaultBranch': git['defaultBranch'],
    }
    observations = {
        'capturedAt': m['generatedAt'],
        'repository': copy.deepcopy(repository),
        'git': {
            'currentBranch': git['currentBranch'],
            'head': git['head'],
            'workingTree': git['workingTree'],
            'statusPorcelain': git['statusPorcelain'],
            'trackedTree': git['trackedTree'],
            'recentCommits': git['recentCommits'],
        },
        'hostedState': github,
        'selectedFiles': copy.deepcopy(selected_files),
        'configuration': copy.deepcopy(configuration),
    }
    if output_path is not None:
        observations['outputPath'] = output_path
    if rendering is not None:
        observations['rendering'] = copy.deepcopy(rendering)
    completeness = {
        'hosted': hosted_domain_completeness(github),
        'selectedFiles': {
            'status': 'observed' if selected_files else 'observed',
            'requested': True,
            'evidence': ['observations.selectedFiles'],
            'rule': {
                'id': 'selected-files-completeness',
                'version': '1',
            },
        },
        'configuration': {
            'status': 'observed',
            'requested': True,
            'evidence': ['observations.configuration'],
            'rule': {
                'id': 'configuration-completeness',
                'version': '1',
            },
        },
    }
    classifications = {
        'workingTree': working_tree_classification(git),
        'hostedState': hosted_state_classification(github, completeness['hosted']),
        'selectedIssue': selected_issue_classification(github, completeness['hosted']),
        'selectedFiles': selected_files_classification(selected_files),
    }
    record = {
        'schemaVersion': CURRENT_STATE_SCHEMA_VERSION,
        'captureId': capture_id or current_state_capture_id(),
        'stateIdentityNormalizationVersion': STATE_IDENTITY_NORMALIZATION_VERSION,
        'observations': observations,
        'relationships': relationships,
        'controllingState': {
            'repository': copy.deepcopy(repository),
            'git': {
                'currentBranch': git['currentBranch'],
                'defaultBranch': git['defaultBranch'],
                'head': git['head'],
                'workingTree': git['workingTree'],
            },
            'hostedState': {
                'available': github.get('available'),
                'requested': github.get('requested'),
                'selectedIssue': copy.deepcopy(github.get('selectedIssue')),
            },
        },
        'workingState': {
            'selectedFiles': copy.deepcopy(selected_files),
            'statusPorcelain': git['statusPorcelain'],
            'trackedTree': git['trackedTree'],
        },
        'candidate': {
            'selectedIssue': copy.deepcopy(github.get('selectedIssue')),
            'selectedFiles': copy.deepcopy(selected_files),
            'configuration': copy.deepcopy(configuration),
        },
        'classifications': classifications,
        'acceptedHistory': [],
        'verification': {
            'identityNormalization': f'sha256:v{STATE_IDENTITY_NORMALIZATION_VERSION}',
            'compatibilityProjection': 'repository-state.json',
            'mutationSentinel': mutation_sentinel(),
        },
        'completeness': completeness,
        'consistency': {
            'status': 'consistent',
            'conflicts': [],
        },
        'limitations': (
            [
                {
                    'scope': 'hostedState',
                    'section': item.get('section'),
                    'error': item.get('error'),
                }
                for item in github.get('errors', [])
            ] + (
                [] if github.get('available') else [{
                    'scope': 'hostedState',
                    'reason': 'github-unavailable',
                }]
            )
        ),
    }
    record['stateIdentity'] = current_state_identity(record)
    return record


def consumer(root: Path, includes, max_bytes, with_files=True):
    g = git_model(root)
    return {
        'repository': g['repository'],
        'root': str(root.resolve()),
        'origin': g['origin'],
        'defaultBranch': g['defaultBranch'],
        'currentBranch': g['currentBranch'],
        'head': g['head'],
        'workingTree': g['workingTree'],
        'selectedFiles': selected(root, g['trackedTree'], includes, [], max_bytes, with_files),
    }


def collect(
    root='.',
    repo=None,
    includes=None,
    excludes=None,
    max_bytes=262144,
    recent=20,
    github=True,
    consumer_root=None,
    consumer_includes=None,
    relationships=None,
    with_files=True,
    selected_issue=None,
    recent_closed=20,
):
    root = Path(root).resolve()
    # Derive actual origin repo
    actual_repo = repo_name(root)
    if repo is not None and repo != actual_repo:
        raise Error(f'origin is {actual_repo}, expected {repo}')
    repo = actual_repo

    g = git_model(root, repo, recent)

    if github:
        gh = github_model(repo, root, recent_closed, selected_issue)
    else:
        gh = {
            'schemaVersion': '1.0',
            'repository': repo,
            'requested': False,
            'available': False,
            'selectedIssueRequested': selected_issue is not None,
            'queryStatus': {},
            'errors': [],
            'data': {},
            'selectedIssue': None,
        }

    if not g['defaultBranch']:
        remote_default = github_default_branch(gh)
        if remote_default:
            g['defaultBranch'] = remote_default

    rel = relationships or {'providers': [], 'consumers': []}
    if not isinstance(rel, dict):
        raise Error('relationships must be an object')
    if set(rel) != {'providers', 'consumers'}:
        raise Error('relationships must contain exactly providers and consumers')
    if not isinstance(rel['providers'], list):
        raise Error('relationships.providers must be an array')
    if not isinstance(rel['consumers'], list):
        raise Error('relationships.consumers must be an array')
    rel = {
        'providers': list(rel['providers']),
        'consumers': list(rel['consumers']),
    }

    if consumer_root:
        rel['consumers'].append(
            consumer(Path(consumer_root).resolve(), consumer_includes or [], max_bytes, with_files)
        )

    configuration = {
        'includes': list(includes or []),
        'excludes': list(excludes or []),
        'maxBytes': max_bytes,
        'recentCommits': recent,
        'github': github,
        'consumerRoot': str(Path(consumer_root).resolve()) if consumer_root else None,
        'consumerIncludes': list(consumer_includes or []),
        'withFiles': with_files,
        'selectedIssue': selected_issue,
        'recentClosed': recent_closed,
    }

    selected_files = selected(root, g['trackedTree'], includes or [], excludes or [],
                              max_bytes, with_files)

    return {
        'schemaVersion': '1.0',
        'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'git': g,
        'github': gh,
        'selectedFiles': selected_files,
        'relationships': rel,
        'configuration': configuration,
        'selectedIssue': gh.get('selectedIssue'),
    }


def repository_state(m):
    record = m if isinstance(m, dict) and 'stateIdentity' in m and 'observations' in m else current_state_record(m)
    d = record['observations']['hostedState']['data']
    git = record['controllingState']['git']
    repository = record['controllingState']['repository']
    return {
        'schemaVersion': '1.0',
        'generatedAt': record['observations']['capturedAt'],
        'repository': {
            'nameWithOwner': repository['nameWithOwner'],
            'defaultBranch': repository['defaultBranch'],
            'currentBranch': git['currentBranch'],
            'head': git['head'],
            'workingTree': git['workingTree'],
        },
        'planning': {
            'githubAvailable': record['observations']['hostedState']['available'],
            'openIssues': d.get('openIssues', []),
            'openMilestones': d.get('milestones', []),
            'openPullRequests': d.get('openPullRequests', []),
            'recentlyMergedPullRequests': d.get('recentlyMergedPullRequests', []),
        },
        'evidence': {
            'repositoryFiles': 'repository-evidence.dx.txt',
            'githubData': 'github-evidence.json',
            'collaborationContract': 'collaboration-contract.dx.txt',
        },
        'relationships': record['relationships'],
        'requestedOutcome': {
            'mode': 'SELECT_OR_PREPARE_NEXT_WORK',
            'maximumConcurrentSelections': 1,
        },
    }


def dx_files(items):
    out = [b'%%DX v1.3.1\n']
    for x in items:
        name = ('repository/' + x['path']) if x['status'] == 'included' else ('metadata/' + x['path'] + '.json')
        if x['status'] == 'included':
            if 'content' not in x:
                raise Error(f'Included file {x["path"]} has no content; cannot pack.')
            data = x['content'].encode()
        else:
            data = (json.dumps({k: v for k, v in x.items() if k != 'content'}, sort_keys=True, indent=2) + '\n').encode()
        if data and not data.endswith(b'\n'):
            data += b'\n'
        out.append(f'%%FILE path="{name}" readonly="true"\n'.encode())
        out.extend(b'    ' + z for z in data.splitlines(keepends=True))
        out.append(b'%%ENDBLOCK\n')
    out.append(b'%%END\n')
    return b''.join(out)


def validate_delivery_brief(path: Path) -> str:
    """Read and validate a delivery brief file. Raises Error on failure."""
    if path.is_symlink():
        raise Error(f'delivery brief is a symlink: {path}')
    if not path.is_file():
        raise Error(f'delivery brief not found: {path}')
    try:
        content = path.read_text(encoding='utf-8')
    except UnicodeDecodeError as e:
        raise Error(f'delivery brief is not UTF-8: {path}: {e}')
    except OSError as e:
        raise Error(f'cannot read delivery brief: {path}: {e}')
    if not content.strip():
        raise Error(f'delivery brief is empty: {path}')
    return content


def render_file_record(f, prefix='', indent=0, with_content=True):
    """Return a list of Markdown lines for one file record."""
    lines = []
    path_display = f"{prefix}{f['path']}" if prefix else f['path']
    if f['status'] == 'missing':
        lines.append(f'- Missing requested path: `{path_display}`')
        return lines

    lines.append(f'### `{path_display}`')
    lines.append('')
    if f['status'] == 'omitted':
        lines.append(f'- Omitted: `{f["reason"]}`')
        lines.append(f'- Size: `{f["size"]}` bytes')
        lines.append(f'- SHA-256: `{f["sha256"]}`')
        lines.append('')
        return lines

    # included
    lines.append(f'- Size: `{f["size"]}` bytes')
    lines.append(f'- SHA-256: `{f["sha256"]}`')
    lines.append('')
    if with_content and 'content' in f:
        ext = Path(f['path']).suffix
        fence = {
            '.sh': 'bash', '.bash': 'bash',
            '.cs': 'csharp',
            '.csproj': 'xml', '.props': 'xml', '.targets': 'xml', '.slnx': 'xml', '.xml': 'xml',
            '.json': 'json',
            '.yml': 'yaml', '.yaml': 'yaml',
            '.md': 'markdown',
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.html': 'html',
            '.css': 'css',
        }.get(ext, 'text')
        lines.append(f'````{fence}')
        lines.append(f['content'])
        lines.append('````')
        lines.append('')
    else:
        lines.append('_(content not shown)_')
        lines.append('')
    return lines


def render_context_markdown(m, options):
    """Render the complete standalone Markdown context report."""
    g = m['git']
    gh = m['github']
    lines = [
        '# Collaboration Context',
        '',
        f'- Role: `{options.role}`',
        f'- Generated UTC: `{m["generatedAt"]}`',
        f'- Repository root: `{g["root"]}`',
        f'- GitHub repository: `{g["repository"]}`',
        f'- Primary issue: `{options.issue if options.issue is not None else "not specified"}`',
        '- Format: `standalone Markdown evidence, not a DX carrier`',
        '',
        '## Operator Model',
        '',
        'The user is the sole local repository operator and courier between the Lead Developer and Senior Developer conversations. This report is evidence only and cannot be applied to a working tree.',
        '',
        '## Repository State',
        '',
        '````text',
        f'Repository: {g["repository"]}',
        f'Origin: {g["origin"]}',
        f'Root: {g["root"]}',
        f'Branch: {g["currentBranch"]}',
        f'HEAD: {g["head"]}',
        f'Default branch: {g["defaultBranch"]}',
        'Status:',
        g['statusPorcelain'],
        '',
        'Recent commits:',
        *[f"{c['sha']}\t{c['date']}\t{c['subject']}" for c in g['recentCommits']],
        '````',
        '',
        '## Tracked Repository Tree',
        '',
        '````text',
        *g['trackedTree'],
        '````',
        '',
    ]

    # Delivery brief
    if options.delivery_brief_content is not None:
        lines += [
            '## Lead Developer Delivery Brief',
            '',
            '````markdown',
            options.delivery_brief_content.rstrip('\n'),
            '````',
            '',
        ]

    # GitHub collection
    if not gh['requested']:
        lines += ['## GitHub Collection', '', '_GitHub was not requested._', '']
    elif not gh['available']:
        lines += ['## GitHub Collection', '', '_GitHub authentication unavailable._', '']
    else:
        lines += ['## GitHub Collection', '', '_GitHub is available._', '']
        # We'll render each section with explicit query status

        def render_query_section(title, key, data_key=None):
            lines.append(f'## {title}')
            lines.append('')
            if key not in gh['queryStatus']:
                lines.append('_Not queried._')
                lines.append('')
                return
            status = gh['queryStatus'][key]
            if status == 'failed':
                lines.append('_Query failed._')
                lines.append('')
                return
            # status == 'ok'
            data = gh['data'].get(data_key or key, [])
            if not data:
                lines.append('_No records._')
                lines.append('')
                return
            lines.append('````json')
            lines.append(json.dumps(data, indent=2, ensure_ascii=False))
            lines.append('````')
            lines.append('')

        render_query_section('GitHub Repository Metadata', 'repository', 'repository')
        if options.issue is not None:
            # Selected issue
            lines.append('## Primary Issue')
            lines.append('')
            if 'selectedIssue' not in gh['queryStatus']:
                lines.append('_Not queried._')
                lines.append('')
            elif gh['queryStatus']['selectedIssue'] == 'failed':
                lines.append('_Query failed._')
                lines.append('')
            else:
                sel = gh.get('selectedIssue')
                if sel:
                    lines.append('````json')
                    lines.append(json.dumps(sel, indent=2, ensure_ascii=False))
                    lines.append('````')
                else:
                    lines.append('_No data._')
                lines.append('')
        # Open issues
        lines.append('## Open Issues')
        lines.append('')
        if 'openIssues' not in gh['queryStatus']:
            lines.append('_Not queried._')
        elif gh['queryStatus']['openIssues'] == 'failed':
            lines.append('_Query failed._')
        else:
            issues = gh['data'].get('openIssues', [])
            if not issues:
                lines.append('_No open issues._')
            else:
                if options.all_open_issue_bodies:
                    # Show full bodies
                    for issue in issues:
                        lines.append(f'### #{issue["number"]}: {issue["title"]}')
                        lines.append('')
                        lines.append('````json')
                        lines.append(json.dumps(issue, indent=2, ensure_ascii=False))
                        lines.append('````')
                        lines.append('')
                else:
                    # Summaries only
                    summary = [{'number': i['number'], 'title': i['title'], 'state': i['state']}
                               for i in issues]
                    lines.append('````json')
                    lines.append(json.dumps(summary, indent=2, ensure_ascii=False))
                    lines.append('````')
                    lines.append('')
        # Milestones
        render_query_section('Open Milestones', 'milestones', 'milestones')
        # Open PRs
        render_query_section('Open Pull Requests', 'openPullRequests', 'openPullRequests')
        # Recently merged PRs (limit already applied in query)
        render_query_section('Recently Merged Pull Requests', 'recentlyMergedPullRequests',
                             'recentlyMergedPullRequests')
        # Labels
        render_query_section('Labels', 'labels', 'labels')
        # Errors
        if gh['errors']:
            lines.append('## GitHub Query Errors')
            lines.append('')
            lines.append('````json')
            lines.append(json.dumps(gh['errors'], indent=2, ensure_ascii=False))
            lines.append('````')
            lines.append('')

    # Selected repository files
    lines.append('## Selected Repository Files')
    lines.append('')
    if options.no_files:
        lines.append('_File content collection was disabled (`--no-files`). No file records are shown._')
        lines.append('')
    else:
        files = m['selectedFiles']
        if not files:
            lines.append('_No files were selected._')
            lines.append('')
        else:
            for f in files:
                lines.extend(render_file_record(f, with_content=not options.no_files))
                # render_file_record already adds blank lines

    # Consumer repository
    if options.consumer_root:
        lines.append('## Consumer Repository')
        lines.append('')
        consumers = m['relationships'].get('consumers', [])
        # Find the matching consumer (by root)
        consumer_info = None
        target_root = str(Path(options.consumer_root).resolve())
        for c in consumers:
            if c.get('root') == target_root:
                consumer_info = c
                break
        if not consumer_info:
            lines.append(f'_Consumer root `{options.consumer_root}` not found in collected model._')
            lines.append('')
        else:
            lines.append('````text')
            lines.append(f'Root: {consumer_info["root"]}')
            lines.append(f'Origin: {consumer_info.get("origin", "unknown")}')
            lines.append(f'Branch: {consumer_info["currentBranch"]}')
            lines.append(f'HEAD: {consumer_info["head"]}')
            lines.append(f'Working tree: {consumer_info["workingTree"]}')
            lines.append('````')
            lines.append('')
            lines.append('### Selected Consumer Files')
            lines.append('')
            if options.no_files:
                lines.append('_File content collection was disabled for the consumer._')
                lines.append('')
            else:
                consumer_files = consumer_info.get('selectedFiles', [])
                if not consumer_files:
                    lines.append('_No consumer files were selected._')
                    lines.append('')
                else:
                    for f in consumer_files:
                        lines.extend(render_file_record(f, prefix='consumer/', with_content=not options.no_files))

    # Relationships
    lines.append('## Repository Relationships')
    lines.append('')
    rel = m['relationships']
    # Providers
    lines.append('### Providers')
    lines.append('')
    if rel.get('providers'):
        lines.append('````json')
        lines.append(json.dumps(rel['providers'], indent=2, ensure_ascii=False))
        lines.append('````')
    else:
        lines.append('_None._')
    lines.append('')
    # Consumers
    lines.append('### Consumers')
    lines.append('')
    if rel.get('consumers'):
        lines.append('````json')
        lines.append(json.dumps(rel['consumers'], indent=2, ensure_ascii=False))
        lines.append('````')
    else:
        lines.append('_None._')
    lines.append('')

    # Collection summary
    lines += [
        '## Collection Summary',
        '',
        f'- GitHub requested: `{"yes" if gh["requested"] else "no"}`',
        f'- GitHub available: `{"yes" if gh["available"] else "no"}`',
        f'- Complete file contents requested: `{"no" if options.no_files else "yes"}`',
        f'- Maximum included file size: `{options.max_bytes}` bytes',
        f'- Recent commits limit: `{options.recent_commits}`',
        f'- Recently merged PR limit: `{options.recent_closed}`',
        f'- All open issue bodies requested: `{"yes" if options.all_open_issue_bodies else "no"}`',
        f'- Selected file records: `{len(m["selectedFiles"])}`',
        '',
    ]
    return '\n'.join(lines) + '\n'


def non_negative_int(value: str) -> int:
    try:
        v = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be an integer: {value}")
    if v < 0:
        raise argparse.ArgumentTypeError(f"must be non-negative: {value}")
    return v


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)

    # model command
    model_parser = subparsers.add_parser('model')
    model_parser.add_argument('--root', default='.')
    model_parser.add_argument('--repo')
    model_parser.add_argument('--out', required=True)
    model_parser.add_argument('--include', action='append', default=[])
    model_parser.add_argument('--exclude', action='append', default=[])
    model_parser.add_argument('--max-bytes', type=non_negative_int, default=262144)
    model_parser.add_argument('--recent-commits', type=non_negative_int, default=20)
    model_parser.add_argument('--no-github', action='store_true')
    model_parser.add_argument('--consumer-root')
    model_parser.add_argument('--consumer-include', action='append', default=[])

    # render-context command
    context_parser = subparsers.add_parser('render-context')
    context_parser.add_argument('--root', default='.')
    context_parser.add_argument('--repo')
    context_parser.add_argument('--role', required=True, choices=['lead', 'senior'])
    context_parser.add_argument('--issue', type=non_negative_int)
    context_parser.add_argument('--out', required=True)
    context_parser.add_argument('--include', action='append', default=[])
    context_parser.add_argument('--exclude', action='append', default=[])
    context_parser.add_argument('--max-bytes', type=non_negative_int, default=262144)
    context_parser.add_argument('--recent-commits', type=non_negative_int, default=20)
    context_parser.add_argument('--recent-closed', type=non_negative_int, default=20)
    context_parser.add_argument('--no-github', action='store_true')
    context_parser.add_argument('--no-files', action='store_true')
    context_parser.add_argument('--all-open-issue-bodies', action='store_true')
    context_parser.add_argument('--delivery-brief')
    context_parser.add_argument('--consumer-root')
    context_parser.add_argument('--consumer-include', action='append', default=[])

    # export-json command
    export_parser = subparsers.add_parser('export-json')
    export_parser.add_argument('--root', default='.')
    export_parser.add_argument('--repo')
    export_parser.add_argument('--out-dir', required=True)
    export_parser.add_argument('--include', action='append', default=[])
    export_parser.add_argument('--exclude', action='append', default=[])
    export_parser.add_argument('--max-bytes', type=non_negative_int, default=262144)
    export_parser.add_argument('--recent-commits', type=non_negative_int, default=20)
    export_parser.add_argument('--no-github', action='store_true')
    export_parser.add_argument('--consumer-root')
    export_parser.add_argument('--consumer-include', action='append', default=[])

    args = parser.parse_args()

    try:
        if args.command == 'model':
            m = collect(
                root=args.root,
                repo=args.repo,
                includes=args.include,
                excludes=args.exclude,
                max_bytes=args.max_bytes,
                recent=args.recent_commits,
                github=not args.no_github,
                consumer_root=args.consumer_root,
                consumer_includes=args.consumer_include,
                with_files=True,
                recent_closed=20,  # not used for model
            )
            atomic(Path(args.out), (json.dumps(m, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode())

        elif args.command == 'render-context':
            # Validate delivery brief before collection
            brief_content = None
            if args.delivery_brief:
                brief_content = validate_delivery_brief(Path(args.delivery_brief))

            # Collect with appropriate flags
            m = collect(
                root=args.root,
                repo=args.repo,
                includes=args.include,
                excludes=args.exclude,
                max_bytes=args.max_bytes,
                recent=args.recent_commits,
                github=not args.no_github,
                consumer_root=args.consumer_root,
                consumer_includes=args.consumer_include,
                with_files=not args.no_files,
                selected_issue=args.issue,
                recent_closed=args.recent_closed,
            )

            # Build options object for renderer
            class RenderOptions:
                pass
            opts = RenderOptions()
            opts.role = args.role
            opts.issue = args.issue
            opts.delivery_brief_content = brief_content
            opts.all_open_issue_bodies = args.all_open_issue_bodies
            opts.recent_closed = args.recent_closed
            opts.no_files = args.no_files
            opts.max_bytes = args.max_bytes
            opts.recent_commits = args.recent_commits
            opts.consumer_root = args.consumer_root
            opts.no_github = args.no_github

            markdown = render_context_markdown(m, opts)
            atomic(Path(args.out), markdown.encode())

        elif args.command == 'export-json':
            m = collect(
                root=args.root,
                repo=args.repo,
                includes=args.include,
                excludes=args.exclude,
                max_bytes=args.max_bytes,
                recent=args.recent_commits,
                github=not args.no_github,
                consumer_root=args.consumer_root,
                consumer_includes=args.consumer_include,
                with_files=True,
                recent_closed=20,
            )
            directory = Path(args.out_dir)
            atomic(directory / 'repository-state.json',
                   (json.dumps(repository_state(m), indent=2, sort_keys=True) + '\n').encode())
            repository_facts = {
                'trackedTree': m['git']['trackedTree'],
                'recentCommits': m['git']['recentCommits'],
                'selectedFiles': m['selectedFiles'],
                'relationships': m['relationships'],
            }
            atomic(directory / 'repository-facts.json',
                   (json.dumps(repository_facts, indent=2, sort_keys=True) + '\n').encode())
            atomic(directory / 'github-evidence.json',
                   (json.dumps(m['github'], indent=2, sort_keys=True) + '\n').encode())
            atomic(directory / 'repository-evidence.dx.txt', dx_files(m['selectedFiles']))

        return 0

    except Error as e:
        print(f'ERROR: {e}', file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
