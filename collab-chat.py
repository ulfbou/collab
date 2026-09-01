#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, subprocess, sys, tempfile
from pathlib import Path, PurePosixPath

DECISIONS={"START_EXISTING_ISSUE","REFINE_EXISTING_ISSUE","CREATE_WORK_ITEM","REPAIR_PLANNING_STRUCTURE","USER_DECISION_REQUIRED"}
PLACEHOLDER=re.compile(r'(?i)\b(?:TODO|TBD|PLACEHOLDER|FIXME)\b')
BRANCH=re.compile(r'^(?:feat|fix|test|docs|refactor|chore|build|ci|perf)/[a-z0-9][a-z0-9._-]*$')
SHA=re.compile(r'^[0-9a-f]{40}$')
REPO=re.compile(r'^[^/\s]+/[^/\s]+$')

class Error(Exception): pass

def gh_command():
    override=os.environ.get('COLLAB_GH_BIN')
    return ('bash',override) if override else ('gh',)

def run(*args,cwd=None,ok=(0,),stdin=None):
    p=subprocess.run(args,cwd=cwd,input=stdin,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode not in ok: raise Error(f"command failed ({p.returncode}): {' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout

def atomic_write(path:Path,data:bytes):
    if path.is_symlink(): raise Error(f"refusing to replace symlink: {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.tmp.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def jbytes(obj): return (json.dumps(obj,indent=2,ensure_ascii=False,sort_keys=True)+'\n').encode()

def state_tool(root):
    path=root/'collab-state.py'
    return path if path.is_file() and not path.is_symlink() else None

def record_artifact(root,tool,artifact,profile=None,values=None):
    state=state_tool(root)
    if not state: return
    if profile and values is not None:
        run('python3',str(state),'save',profile,'--json',json.dumps(values,separators=(',',':')),cwd=root)
    run_id=run('python3',str(state),'run-id',cwd=root).strip()
    started=str(int(dt.datetime.now(dt.timezone.utc).timestamp()*1_000_000_000))
    head=run('git','rev-parse','HEAD',cwd=root).strip()
    run('python3',str(state),'record','--run-id',run_id,'--tool',tool,'--status','success','--exit-status','0','--started',started,'--start-head',head,'--artifact',str(artifact),cwd=root)

def normalize_text_file(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")

def safe_rel(s):
    p=PurePosixPath(s.replace('\\','/'))
    if p.is_absolute() or '..' in p.parts or not p.parts or str(p)=='.' or '\x00' in s: raise Error(f"unsafe repository-relative path: {s}")
    return str(p)

def dx_pack(files:dict[str,bytes],readonly=True):
    out=[b'%%DX v1.3.1\n']
    for name in sorted(files):
        safe_rel(name)
        data=files[name]
        if b'\x00' in data: raise Error(f"DX file is binary: {name}")
        try: text=data.decode('utf-8')
        except UnicodeDecodeError: raise Error(f"DX file is not UTF-8: {name}")
        if '\r' in text: raise Error(f"DX file contains CR: {name}")
        attrs=' readonly="true"' if readonly else ''
        out.append(f'%%FILE path="{name}"{attrs}\n'.encode())
        for line in text.splitlines(keepends=True): out.append(b'    '+line.encode())
        if text and not text.endswith('\n'): out.append(b'\n')
        out.append(b'%%ENDBLOCK\n')
    out.append(b'%%END\n')
    return b''.join(out)

def dx_parse(path:Path):
    raw=path.read_bytes()
    try: text=raw.decode('utf-8')
    except UnicodeDecodeError: raise Error('DX package is not UTF-8')
    if '\r' in text: raise Error('DX package must use LF line endings')
    lines=text.splitlines(); files={}; readonly={}; i=0
    attr_re=re.compile(r'(\w+)="([^"]*)"')
    while i<len(lines):
        line=lines[i]
        if line.startswith('%%END') and line!='%%ENDBLOCK': break
        if line.startswith('%%FILE'):
            attrs=dict(attr_re.findall(line)); name=attrs.get('path')
            if not name: raise Error('DX FILE lacks path')
            safe_rel(name)
            if name in files: raise Error(f'duplicate DX path: {name}')
            i+=1; content=[]
            while i<len(lines) and lines[i] != '%%ENDBLOCK':
                if not lines[i].startswith('    '): raise Error(f'non-indented DX payload line in {name}')
                content.append(lines[i][4:]); i+=1
            if i>=len(lines): raise Error(f'unclosed DX block: {name}')
            files[name]=('\n'.join(content)+'\n').encode(); readonly[name]=attrs.get('readonly')=='true'
        i+=1
    if not files: raise Error('DX package contains no files')
    return files,readonly

def repo_root(): return Path(run('git','rev-parse','--show-toplevel').strip())
def origin_repo(root):
    url=run('git','remote','get-url','origin',cwd=root).strip()
    url=re.sub(r'\.git$','',url)
    for p in ('git@github.com:','https://github.com/','http://github.com/','ssh://git@github.com/'):
        if url.startswith(p): url=url[len(p):]; break
    if not REPO.match(url): raise Error('cannot derive GitHub OWNER/REPO from origin; use --repo')
    return url

def collect_git(root,repo,github,recent_closed,recent_commits=20,relationships=None):
    head=run('git','rev-parse','HEAD',cwd=root).strip()
    if not SHA.match(head): raise Error('repository has no valid HEAD commit; create the initial commit first')
    current=run('git','branch','--show-current',cwd=root).strip()
    default=run('git','symbolic-ref','--quiet','--short','refs/remotes/origin/HEAD',cwd=root,ok=(0,1)).strip()
    default=default.removeprefix('origin/') or current
    status=run('git','status','--porcelain=v1','--untracked-files=all',cwd=root)

    # Deterministic file sorting (Issue 10)
    tracked=run('git','ls-files','-z',cwd=root).split('\0'); tracked=[x for x in tracked if x]
    tracked.sort()

    if not tracked: raise Error('repository has no tracked files; add and commit the tool sources first')
    state={"schemaVersion":"1.0","generatedAt":dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z'),"repository":{"nameWithOwner":repo,"defaultBranch":default,"currentBranch":current,"head":head,"workingTree":"CLEAN" if not status else "DIRTY"},"planning":{"githubAvailable":github,"openIssues":[],"openMilestones":[],"openPullRequests":[],"recentlyMergedPullRequests":[]},"evidence":{"repositoryFiles":"repository-evidence.dx.txt","githubData":"github-evidence.json","collaborationContract":"collaboration-contract.dx.txt"},"relationships":relationships or {"providers":[],"consumers":[]},"recentCommits":run('git','log','-n',str(recent_commits),'--format=%H%x09%cI%x09%s',cwd=root).splitlines(),"repositoryTree":tracked,"requestedOutcome":{"mode":"SELECT_OR_PREPARE_NEXT_WORK","maximumConcurrentSelections":1}}
    ghdata={"repository":repo,"available":github,"errors":[]}
    if github:
        queries={
          'repository':['gh','repo','view',repo,'--json','nameWithOwner,description,url,defaultBranchRef,isPrivate,visibility'],
          'openIssues':['gh','issue','list','--repo',repo,'--state','open','--limit','100','--json','number,title,body,state,labels,milestone,assignees,author,createdAt,updatedAt,url'],
          'openPullRequests':['gh','pr','list','--repo',repo,'--state','open','--limit','100','--json','number,title,body,state,isDraft,baseRefName,headRefName,headRefOid,labels,milestone,mergeable,statusCheckRollup,url'],
          'recentlyMergedPullRequests':['gh','pr','list','--repo',repo,'--state','merged','--limit',str(recent_closed),'--json','number,title,body,baseRefName,headRefName,headRefOid,mergeCommit,mergedAt,labels,milestone,author,url'],
          'labels':['gh','label','list','--repo',repo,'--limit','100','--json','name,color,description'],
          'milestones':['gh','api','--paginate',f'repos/{repo}/milestones?state=open&per_page=100']}
        for k,q in queries.items():
            try:
                res = json.loads(run(*q,cwd=root))
                # Deterministic GitHub data sorting (Issue 10)
                if isinstance(res, list):
                    if k in ('openIssues', 'openPullRequests', 'recentlyMergedPullRequests'):
                        res.sort(key=lambda x: x.get('number', 0))
                    elif k == 'labels':
                        res.sort(key=lambda x: x.get('name', ''))
                    elif k == 'milestones':
                        res.sort(key=lambda x: x.get('title', ''))
                ghdata[k] = res
            except Exception as e: ghdata['errors'].append({"section":k,"error":str(e)})
        state['planning']['openIssues']=ghdata.get('openIssues',[])
        state['planning']['openMilestones']=ghdata.get('milestones',[])
        state['planning']['openPullRequests']=ghdata.get('openPullRequests',[])
        state['planning']['recentlyMergedPullRequests']=ghdata.get('recentlyMergedPullRequests',[])
    return state,ghdata,tracked

def selected_tracked(tracked,includes):
    if not includes: return tracked
    selected=[]
    for raw in includes:
        rel=safe_rel(raw).rstrip('/')
        matches=[x for x in tracked if x==rel or x.startswith(rel+'/')]
        if not matches: raise Error(f'included path is not a tracked file or directory: {raw}')
        for item in matches:
            if item not in selected: selected.append(item)
    return selected

def repo_evidence(root,tracked,max_bytes,excludes,includes=None):
    files={}
    for rel in selected_tracked(tracked,includes or []):
        p=root/rel
        if any(rel==x or rel.startswith(x.rstrip('/')+'/') for x in excludes): continue
        if not p.is_file() or p.is_symlink(): continue
        data=p.read_bytes()
        if len(data)>max_bytes or b'\x00' in data:
            files[f'metadata/{rel}.json']=jbytes({"path":rel,"size":len(data),"sha256":hashlib.sha256(data).hexdigest(),"omitted":True})
            continue
        try: data.decode('utf-8')
        except UnicodeDecodeError:
            files[f'metadata/{rel}.json']=jbytes({"path":rel,"size":len(data),"sha256":hashlib.sha256(data).hexdigest(),"omitted":True}); continue
        normalized = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        files["repository/" + rel] = normalized if not normalized or normalized.endswith(b"\n") else normalized + b"\n"
    return dx_pack(files,True)

LEAD='''# Lead Developer Instructions\n\nRead every file in this package before deciding. Assess planning readiness and select or prepare exactly one bounded work item. Prefer accepted roadmap, milestone, issue, PR, and source evidence. Do not implement. Do not return a menu. Do not ask what the user wants unless a genuine product choice cannot be derived. Return one complete Lead decision and one writable DX v1.3.1 package named `lead-selection.dx.txt`.\n'''
WORKFLOW='''# Conversation Workflow\n\nThe user is the sole local operator and courier. The Lead must return exactly one decision: `START_EXISTING_ISSUE`, `REFINE_EXISTING_ISSUE`, `CREATE_WORK_ITEM`, `REPAIR_PLANNING_STRUCTURE`, or `USER_DECISION_REQUIRED`. For implementation-ready work, the return package contains `selection.json`, `decision.md`, `delivery-brief.md`, `senior-kickstart.md`, and `required-evidence.json`. For planning decisions it contains `selection.json`, `decision.md`, and a complete `planning-change.md`. The first response must begin with `LEAD DECISION`. End with exact user actions and stop.\n'''
KICK='''# Lead Developer Chat Bootstrap\n\nTreat this one DX document as a virtual read-only workspace. Parse every contained file. Repository facts are in `repository-state.json`; complete source evidence is in `repository-evidence.dx.txt`; GitHub evidence is in `github-evidence.json`. Start immediately. Do not ask the user to re-upload embedded evidence. Produce exactly one normalized decision under the output contract.\n'''
SENIOR='''# Senior Developer Instructions\n\nTreat the accepted Lead delivery brief as the fixed PR boundary. Produce complete files with no placeholders and exact runnable commands. Use existing collab tools instead of recreating coordinator phases. Take the shortest safe path through one `collab-delivery-run.sh` cycle. Return exact files for Lead assessment and stop before PR creation.\n'''

def start(args):
    root=repo_root(); repo=args.repo or origin_repo(root)
    github=False
    if not args.no_github:
        try: run(*gh_command(),'auth','status',cwd=root); github=True
        except Exception: github=False
    relationships={"providers":[],"consumers":[]}
    if args.consumer_root:
        croot=(root/args.consumer_root).resolve()
        if not croot.is_dir(): raise Error(f"consumer root not found: {args.consumer_root}")
        relationships["consumers"].append({"repository":origin_repo(croot),"root":os.path.relpath(croot,root).replace(os.sep,"/")})
    state,ghdata,tracked=collect_git(root,repo,github,args.recent_closed,args.recent_commits,relationships)
    out=Path(args.out); out=out if out.is_absolute() else root/out
    planned=[str(out),f'{len(tracked)} tracked files',f'GitHub evidence: {"available" if github else "unavailable"}']
    if args.dry_run:
        print('Would generate one Lead chat package:'); print('\n'.join('- '+x for x in planned)); return
    contract=b''
    candidate=root/'.dx/collab.dx.txt'
    if candidate.is_file() and not candidate.is_symlink():
        contract = candidate.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    else:
        contract = dx_pack({"workflow.md": WORKFLOW.encode()}, True)
    repo_dx=repo_evidence(root,tracked,args.max_file_bytes,args.exclude,args.include)
    output_contract={"schemaVersion":"1.0","requiredFirstHeading":"LEAD DECISION","decisions":sorted(DECISIONS),"returnPackage":"lead-selection.dx.txt","implementationFiles":["selection.json","decision.md","delivery-brief.md","senior-kickstart.md","required-evidence.json"],"planningFiles":["selection.json","decision.md","planning-change.md"]}
    manifest={"schemaVersion":"1.0","packageType":"LEAD_CHAT_START","repository":repo,"evidenceHead":state['repository']['head'],"files":["kickstart.md","lead-developer.md","workflow.md","repository-state.json","repository-evidence.dx.txt","github-evidence.json","collaboration-contract.dx.txt","output-contract.json"]}
    package=dx_pack({"manifest.json":jbytes(manifest),"kickstart.md":KICK.encode(),"lead-developer.md":LEAD.encode(),"workflow.md":WORKFLOW.encode(),"repository-state.json":jbytes(state),"repository-evidence.dx.txt":repo_dx,"github-evidence.json":jbytes(ghdata),"collaboration-contract.dx.txt":contract,"output-contract.json":jbytes(output_contract)},True)
    atomic_write(out,package)
    record_artifact(root,'chat-start',out,'conversation',{'packageType':'LEAD_CHAT_START','artifact':str(out.relative_to(root)),'evidenceHead':state['repository']['head']})
    print('=== LEAD CHAT READY ==='); print(f'Upload: {out}'); print('Send exactly: Start.'); print(f'SHA-256: {hashlib.sha256(package).hexdigest()}')

def exact_keys(o,keys,where):
    if set(o)!=set(keys): raise Error(f'{where} fields differ; expected {sorted(keys)}, got {sorted(o)}')
def strings(v,name,nonempty=True):
    if not isinstance(v,list) or any(not isinstance(x,str) or (nonempty and not x.strip()) for x in v): raise Error(f'{name} must be an array of non-empty strings')
    for x in v:
        if PLACEHOLDER.search(x): raise Error(f'{name} contains placeholder text')

def require_text(value,name):
    if not isinstance(value,str) or not value.strip() or PLACEHOLDER.search(value): raise Error(f'{name} is empty or contains placeholder text')

def validate_selection(o,repo,head):
    exact_keys(o,{'schemaVersion','decision','repository','evidenceHead','summary','nextConversation','details'},'selection')
    if o['schemaVersion']!='1.0' or o['decision'] not in DECISIONS: raise Error('unsupported selection schema or decision')
    if o['repository']!=repo: raise Error(f"selection repository {o['repository']} differs from {repo}")
    if not SHA.match(o['evidenceHead']): raise Error('evidenceHead must be a 40-character lowercase SHA')
    if o['evidenceHead']!=head: raise Error(f"selection is stale: evidence HEAD {o['evidenceHead']} differs from current HEAD {head}")
    require_text(o['summary'],'summary')
    if not isinstance(o['details'],dict): raise Error('details must be an object')
    d=o['details']; decision=o['decision']
    if decision=='START_EXISTING_ISSUE':
        exact_keys(d,{'issue','work','pr','verification'},'details')
        exact_keys(d['issue'],{'number','title'},'issue'); exact_keys(d['work'],{'objective','nonGoals','allowedPaths'},'work'); exact_keys(d['pr'],{'branch','title'},'pr'); exact_keys(d['verification'],{'focusedTests','providerSolution','requiredConsumers'},'verification')
        if not isinstance(d['issue']['number'],int) or isinstance(d['issue']['number'],bool) or d['issue']['number']<1: raise Error('issue.number must be positive integer')
        require_text(d['issue']['title'],'issue.title'); require_text(d['work']['objective'],'work.objective'); require_text(d['pr']['title'],'pr.title')
        if not BRANCH.match(d['pr']['branch']) or re.search(r'(?:^|[-_/])\d+(?:$|[-_/])',d['pr']['branch']): raise Error('PR branch must use generic type/scope form without an issue number')
        strings(d['work']['nonGoals'],'work.nonGoals'); strings(d['work']['allowedPaths'],'work.allowedPaths')
        if not d['work']['allowedPaths']: raise Error('work.allowedPaths must not be empty')
        for value in d['work']['allowedPaths']: safe_rel(value)
        strings(d['verification']['focusedTests'],'verification.focusedTests',False)
        for value in d['verification']['focusedTests']: safe_rel(value)
        if not isinstance(d['verification']['providerSolution'],str): raise Error('verification.providerSolution must be string')
        consumers=d['verification']['requiredConsumers']
        if not isinstance(consumers,list): raise Error('verification.requiredConsumers must be array')
        for i,c in enumerate(consumers):
            exact_keys(c,{'repository','root','solution'},f'requiredConsumers[{i}]')
            if not REPO.match(c['repository']): raise Error('consumer repository is invalid')
            safe_rel(c['root']); safe_rel(c['solution'])
        if o['nextConversation']!='SENIOR': raise Error('implementation decision must set nextConversation to SENIOR')
    elif decision=='REFINE_EXISTING_ISSUE':
        exact_keys(d,{'issue','title','body','acceptanceCriteria','dependencies','labels','milestone','reasonToWait'},'details'); exact_keys(d['issue'],{'number','title'},'issue')
        if not isinstance(d['issue']['number'],int) or isinstance(d['issue']['number'],bool) or d['issue']['number']<1: raise Error('issue.number must be positive integer')
        for key in ('title','body','reasonToWait'): require_text(d[key],f'details.{key}')
        for key in ('acceptanceCriteria','dependencies','labels'): strings(d[key],f'details.{key}',key!='labels')
        if not isinstance(d['milestone'],str) or o['nextConversation']!='LEAD': raise Error('invalid refinement continuation')
    elif decision=='CREATE_WORK_ITEM':
        exact_keys(d,{'title','body','acceptanceCriteria','dependencies','labels','milestone','nonGoals','expectedPrBoundary'},'details')
        for key in ('title','body','expectedPrBoundary'): require_text(d[key],f'details.{key}')
        for key in ('acceptanceCriteria','dependencies','labels','nonGoals'): strings(d[key],f'details.{key}',key!='labels')
        if not isinstance(d['milestone'],str) or o['nextConversation']!='LEAD': raise Error('invalid work-item continuation')
    elif decision=='REPAIR_PLANNING_STRUCTURE':
        exact_keys(d,{'title','body','changes'},'details'); require_text(d['title'],'details.title'); require_text(d['body'],'details.body'); strings(d['changes'],'details.changes')
        if o['nextConversation']!='LEAD': raise Error('planning repair must continue to LEAD')
    else:
        exact_keys(d,{'question','whyUnresolved','options','recommendation'},'details')
        for key in ('question','whyUnresolved','recommendation'): require_text(d[key],f'details.{key}')
        if not isinstance(d['options'],list) or len(d['options'])<2: raise Error('details.options requires at least two options')
        for i,opt in enumerate(d['options']):
            exact_keys(opt,{'name','consequences'},f'options[{i}]'); require_text(opt['name'],f'options[{i}].name'); strings(opt['consequences'],f'options[{i}].consequences')
        if o['nextConversation']!='NONE': raise Error('user decision must set nextConversation to NONE')

def accept(args):
    root=repo_root(); repo=origin_repo(root); head=run('git','rev-parse','HEAD',cwd=root).strip(); path=Path(args.package)
    if path.is_symlink() or not path.is_file(): raise Error(f'selection package is missing or unsafe: {path}')
    files,ro=dx_parse(path)
    for req in ('selection.json','decision.md'):
        if req not in files: raise Error(f'missing required return file: {req}')
    try: selection=json.loads(files['selection.json'])
    except Exception as e: raise Error(f'invalid selection.json: {e}')
    validate_selection(selection,repo,head)
    decision=selection['decision']
    if decision=='START_EXISTING_ISSUE': needed=('delivery-brief.md','senior-kickstart.md','required-evidence.json')
    elif decision in {'REFINE_EXISTING_ISSUE','CREATE_WORK_ITEM','REPAIR_PLANNING_STRUCTURE'}: needed=('planning-change.md',)
    else: needed=()
    for req in needed:
        if req not in files: raise Error(f'missing required return file: {req}')
        if PLACEHOLDER.search(files[req].decode('utf-8')): raise Error(f'{req} contains placeholder text')
    if decision=='START_EXISTING_ISSUE':
        try: required=json.loads(files['required-evidence.json'])
        except Exception as e: raise Error(f'invalid required-evidence.json: {e}')
        if not isinstance(required,dict) or set(required)!={'files'}: raise Error('required-evidence.json must contain exactly a files array')
        strings(required['files'],'required-evidence.files')
        for value in required['files']: safe_rel(value)
        github_available=False
        try: run(*gh_command(),'auth','status',cwd=root); github_available=True
        except (FileNotFoundError,Error): pass
        if github_available:
            try: issue=json.loads(run(*gh_command(),'issue','view',str(selection['details']['issue']['number']),'--repo',repo,'--json','number,title,state',cwd=root))
            except Exception as e: raise Error(f'selected issue cannot be verified: {e}')
            if issue.get('state')!='OPEN': raise Error(f"selected issue #{issue.get('number')} is not open")
            if issue.get('title')!=selection['details']['issue']['title']: raise Error('selected issue title differs from current GitHub state')
    if args.dry_run:
        print(f'VALID: {decision}'); print('No files or profiles were written.'); return
    outdir=root/'.dx/collab'; outdir.mkdir(parents=True,exist_ok=True)
    accepted=outdir/'accepted-selection.dx.txt'; atomic_write(accepted,path.read_bytes())
    record_artifact(root,'chat-accept',accepted,'selection',{'decision':decision,'artifact':str(accepted.relative_to(root)),'evidenceHead':head,'acceptedAt':dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')})
    if decision=='START_EXISTING_ISSUE':
        state,ghdata,tracked=collect_git(root,repo,False,20,20)
        manifest={"schemaVersion":"1.0","packageType":"SENIOR_CHAT_START","repository":repo,"evidenceHead":head,"decision":decision}
        senior=dx_pack({"manifest.json":jbytes(manifest),"kickstart.md":files['senior-kickstart.md'],"senior-developer.md":SENIOR.encode(),"delivery-brief.md":files['delivery-brief.md'],"selection.json":files['selection.json'],"repository-state.json":jbytes(state),"repository-evidence.dx.txt":repo_evidence(root,tracked,262144,[]),"collaboration-contract.dx.txt":normalize_text_file(root/'.dx/collab.dx.txt') if (root/'.dx/collab.dx.txt').is_file() else dx_pack({"workflow.md":WORKFLOW.encode()},True)},True)
        out=outdir/'senior-chat-start.dx.txt'; atomic_write(out,senior)
        print('=== SENIOR CHAT READY ==='); print(f'Upload: {out}'); print('Send exactly: Start.')
    elif decision in {'REFINE_EXISTING_ISSUE','CREATE_WORK_ITEM','REPAIR_PLANNING_STRUCTURE'}:
        out=outdir/'planning-change.md'; atomic_write(out,files['planning-change.md'])
        d=selection['details']; body=outdir/'proposed-issue-body.md'
        if decision in {'REFINE_EXISTING_ISSUE','CREATE_WORK_ITEM'}:
            atomic_write(body,(d['body'].rstrip()+'\n').encode())
            if decision=='REFINE_EXISTING_ISSUE':
                cmd=f"gh issue edit {d['issue']['number']} --repo {repo} --title {json.dumps(d['title'])} --body-file {body.relative_to(root)}"
            else:
                cmd=f"gh issue create --repo {repo} --title {json.dumps(d['title'])} --body-file {body.relative_to(root)}"
            if d['milestone']: cmd+=f" --milestone {json.dumps(d['milestone'])}"
            for label in d['labels']: cmd+=f" --label {json.dumps(label)}"
        else:
            cmd=f"Review and apply the complete planning repair in {out.relative_to(root)} using the applicable gh issue or gh api command."
        print('=== PLANNING CHANGE READY ==='); print(f'Review: {out}'); print('Run:'); print(cmd); print('After the GitHub planning change, run: collab-chat-start.sh')
    else:
        print('=== USER DECISION REQUIRED ==='); print(selection['details']['question']); print('Recommendation: '+selection['details']['recommendation'])

# Issue 10 compatibility adapters: all production collection belongs to collab-evidence.py.
def _evidence_module():
    import importlib.util
    path=Path(__file__).with_name('collab-evidence.py')
    spec=importlib.util.spec_from_file_location('collab_evidence',path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def collect_git(
    root,
    repo,
    github,
    recent_closed,
    recent_commits=20,
    relationships=None,
):
    evidence = _evidence_module()
    model = evidence.collect(
        root=root,
        repo=repo,
        includes=[],
        excludes=[],
        max_bytes=262144,
        recent=recent_commits,
        github=github,
        relationships=relationships,
        recent_closed=recent_closed,
    )
    return (
        evidence.repository_state(model),
        model["github"],
        model["git"]["trackedTree"],
    )

def repo_evidence(root,tracked,max_bytes,excludes,includes=None):
    e=_evidence_module(); return e.dx_files(e.selected(Path(root),tracked,includes or [],excludes,max_bytes))

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('start'); s.add_argument('--repo'); s.add_argument('--out',default='.dx/collab/lead-chat-start.dx.txt'); s.add_argument('--max-file-bytes',type=int,default=262144); s.add_argument('--recent-closed',type=int,default=20); s.add_argument('--recent-commits',type=int,default=20); s.add_argument('--consumer-root'); s.add_argument('--include',action='append',default=[]); s.add_argument('--exclude',action='append',default=['.dx']); s.add_argument('--no-github',action='store_true'); s.add_argument('--dry-run',action='store_true')
    a=sub.add_parser('accept'); a.add_argument('package'); a.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    try:
        if args.cmd=='start': start(args)
        else: accept(args)
    except Error as e: print(f'ERROR: {e}',file=sys.stderr); return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
