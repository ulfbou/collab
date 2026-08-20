#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, shutil, subprocess, tempfile
from pathlib import Path, PurePosixPath
class Error(Exception): pass
def run(args,cwd=None):
 p=subprocess.run(args,cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if p.returncode: raise Error(p.stderr.strip() or f"command failed ({p.returncode}): {' '.join(args)}")
 return p.stdout
def git_bash():
 override=os.environ.get('COLLAB_BASH_BIN')
 if override:
  path=Path(override)
  if not path.is_file():
   raise Error(
    f'COLLAB_BASH_BIN does not identify a file: {override}'
   )
  return str(path)

 candidates=[]

 git=shutil.which('git.exe') or shutil.which('git')
 if git:
  git_path=Path(git)
  candidates.extend([
   git_path.parent.parent/'bin'/'bash.exe',
   git_path.parent.parent/'usr'/'bin'/'bash.exe',
  ])

 program_files=os.environ.get('ProgramFiles')
 if program_files:
  candidates.extend([
   Path(program_files)/'Git'/'bin'/'bash.exe',
   Path(program_files)/'Git'/'usr'/'bin'/'bash.exe',
  ])

 candidates.extend([
  Path(r'C:\Program Files\Git\bin\bash.exe'),
  Path(r'C:\Program Files\Git\usr\bin\bash.exe'),
 ])

 for candidate in candidates:
  if candidate.is_file():
   return str(candidate)

 checked=', '.join(str(candidate) for candidate in candidates)
 raise Error(
  'Git Bash could not be located; set COLLAB_BASH_BIN to the full '
  f'path of bash.exe. Checked: {checked}'
 )

def gh_bin():
 override=os.environ.get('COLLAB_GH_BIN')
 if override:
  return [git_bash(),override]
 return ['gh']

def safe(raw):
 p=PurePosixPath(raw.replace('\\','/'))
 if p.is_absolute() or not p.parts or '..' in p.parts or str(p)=='.' or '\0' in raw: raise Error(f'unsafe path: {raw}')
 return str(p).rstrip('/')
def atomic(path:Path,data:bytes):
 if path.is_symlink(): raise Error(f'refusing to replace symlink: {path}')
 path.parent.mkdir(parents=True,exist_ok=True)
 if path.parent.is_symlink(): raise Error(f'refusing unsafe output parent: {path.parent}')
 fd,tmp=tempfile.mkstemp(prefix=path.name+'.tmp.',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp): os.unlink(tmp)
def repo_name(root):
 u=run(['git','remote','get-url','origin'],root).strip(); u=re.sub(r'\.git$','',u)
 for p in ('git@github.com:','https://github.com/','http://github.com/','ssh://git@github.com/'):
  if u.startswith(p): u=u[len(p):]; break
 if u.count('/')!=1: raise Error(f'cannot derive repository from origin: {u}')
 return u

def cached_default_branch(root:Path):
 process=subprocess.run(
  [
   'git',
   'symbolic-ref',
   '--quiet',
   '--short',
   'refs/remotes/origin/HEAD',
  ],
  cwd=root,
  text=True,
  stdout=subprocess.PIPE,
  stderr=subprocess.PIPE,
  check=False,
 )
 if process.returncode!=0:
  return None

 value=process.stdout.strip()
 if not value:
  return None

 return value.removeprefix('origin/')

def github_default_branch(github):
 if not isinstance(github,dict):
  return None

 data=github.get('data')
 if not isinstance(data,dict):
  return None

 repository=data.get('repository')
 if not isinstance(repository,dict):
  return None

 default_ref=repository.get('defaultBranchRef')
 if not isinstance(default_ref,dict):
  return None

 value=default_ref.get('name')
 if not isinstance(value,str) or not value:
  return None

 return value

def git_model(root:Path,repo=None,recent=20):
 repo=repo or repo_name(root)
 head=run(['git','rev-parse','HEAD'],root).strip()
 branch=run(['git','branch','--show-current'],root).strip()
 default=cached_default_branch(root)
 tree=sorted(
  path
  for path in run(['git','ls-files','-z'],root).split('\0')
  if path
 )
 status=run(
  ['git','status','--porcelain=v1','--untracked-files=all'],
  root,
 )
 commits=[]
 for line in run(
  [
   'git',
   'log',
   '-n',
   str(recent),
   '--format=%H%x09%cI%x09%s',
  ],
  root,
 ).splitlines():
  sha,date,subject=line.split('\t',2)
  commits.append({
   'sha':sha,
   'date':date,
   'subject':subject,
  })

 return {
  'repository':repo,
  'defaultBranch':default,
  'currentBranch':branch,
  'head':head,
  'workingTree':'CLEAN' if not status else 'DIRTY',
  'statusPorcelain':status,
  'trackedTree':tree,
  'recentCommits':commits,
 }

def github_model(repo,root):
 keys=('repository','openIssues','openPullRequests','recentlyMergedPullRequests','labels','milestones')
 try: run(gh_bin()+['auth','status'],root)
 except Exception as e: return {'schemaVersion':'1.0','repository':repo,'available':False,'queryStatus':{k:'unavailable' for k in keys},'errors':[{'section':'authentication','error':str(e)}],'data':{}}
 q={
 'repository':gh_bin()+['repo','view',repo,'--json','nameWithOwner,description,url,defaultBranchRef,isPrivate,visibility'],
 'openIssues':gh_bin()+['issue','list','--repo',repo,'--state','open','--limit','100','--json','number,title,body,state,labels,milestone,assignees,author,createdAt,updatedAt,url'],
 'openPullRequests':gh_bin()+['pr','list','--repo',repo,'--state','open','--limit','100','--json','number,title,body,state,isDraft,baseRefName,headRefName,headRefOid,labels,milestone,url'],
 'recentlyMergedPullRequests':gh_bin()+['pr','list','--repo',repo,'--state','merged','--limit','100','--json','number,title,body,baseRefName,headRefName,headRefOid,mergeCommit,mergedAt,labels,milestone,author,url'],
 'labels':gh_bin()+['label','list','--repo',repo,'--limit','100','--json','name,color,description'],
 'milestones':gh_bin()+['api','--paginate',f'repos/{repo}/milestones?state=open&per_page=100']}
 st={}; data={}; errors=[]
 for k,c in q.items():
  try:
   v=json.loads(run(c,root)); st[k]='ok'
   if isinstance(v,list):
    if k in ('openIssues','openPullRequests','recentlyMergedPullRequests'): v.sort(key=lambda x:x.get('number',0))
    elif k=='labels': v.sort(key=lambda x:x.get('name',''))
    elif k=='milestones': v.sort(key=lambda x:(x.get('title',''),x.get('number',0)))
   data[k]=v
  except Exception as e: st[k]='failed'; errors.append({'section':k,'error':str(e)})
 return {'schemaVersion':'1.0','repository':repo,'available':True,'queryStatus':st,'errors':errors,'data':data}
def prefix(path,p): return path==p or path.startswith(p+'/')
def selected(root,tracked,includes,excludes,max_bytes):
 inc=[safe(x) for x in includes]; exc=[safe(x) for x in excludes]+['.dx']; out=[]; matched=set()
 for path in tracked:
  if inc and not any(prefix(path,x) for x in inc): continue
  if any(prefix(path,x) for x in exc): continue
  for x in inc:
   if prefix(path,x): matched.add(x)
  p=root/path
  if not p.is_file() or p.is_symlink(): continue
  b=p.read_bytes(); rec={'path':path,'size':len(b),'sha256':hashlib.sha256(b).hexdigest()}
  if len(b)>max_bytes: rec.update(status='omitted',reason='oversized')
  elif b'\0' in b: rec.update(status='omitted',reason='binary')
  else:
   try: rec['content']=b.decode('utf-8').replace('\r\n','\n').replace('\r','\n'); rec['status']='included'
   except UnicodeDecodeError: rec.update(status='omitted',reason='non-utf8')
  out.append(rec)
 for x in inc:
  if x not in matched: out.append({'path':x,'status':'missing','reason':'not-tracked'})
 return sorted(out,key=lambda x:x['path'])
def consumer(root:Path,includes,max_bytes):
 g=git_model(root); return {'repository':g['repository'],'root':str(root),'defaultBranch':g['defaultBranch'],'currentBranch':g['currentBranch'],'head':g['head'],'workingTree':g['workingTree'],'selectedFiles':selected(root,g['trackedTree'],includes,[],max_bytes)}

def collect(root='.',repo=None,includes=None,excludes=None,max_bytes=262144,recent=20,github=True,consumer_root=None,consumer_includes=None):
 root=Path(root).resolve()
 g=git_model(root,repo,recent)

 if github:
  gh=github_model(g['repository'],root)
 else:
  gh={
   'schemaVersion':'1.0',
   'repository':g['repository'],
   'available':False,
   'queryStatus':{},
   'errors':[],
   'data':{},
  }

 if not g['defaultBranch']:
  remote_default=github_default_branch(gh)
  if remote_default:
   g['defaultBranch']=remote_default

 rel={
  'providers':[],
  'consumers':[],
 }

 if consumer_root:
  rel['consumers'].append(
   consumer(
    Path(consumer_root).resolve(),
    consumer_includes or [],
    max_bytes,
   )
  )

 return {
  'schemaVersion':'1.0',
  'generatedAt':dt.datetime.now(
   dt.timezone.utc
  ).isoformat().replace('+00:00','Z'),
  'git':g,
  'github':gh,
  'selectedFiles':selected(
   root,
   g['trackedTree'],
   includes or [],
   excludes or [],
   max_bytes,
  ),
  'relationships':rel,
 }

def repository_state(m):
 d=m['github']['data']; return {'schemaVersion':'1.0','generatedAt':m['generatedAt'],'repository':{'nameWithOwner':m['git']['repository'],'defaultBranch':m['git']['defaultBranch'],'currentBranch':m['git']['currentBranch'],'head':m['git']['head'],'workingTree':m['git']['workingTree']},'planning':{'githubAvailable':m['github']['available'],'openIssues':d.get('openIssues',[]),'openMilestones':d.get('milestones',[]),'openPullRequests':d.get('openPullRequests',[]),'recentlyMergedPullRequests':d.get('recentlyMergedPullRequests',[])},'evidence':{'repositoryFiles':'repository-evidence.dx.txt','githubData':'github-evidence.json','collaborationContract':'collaboration-contract.dx.txt'},'requestedOutcome':{'mode':'SELECT_OR_PREPARE_NEXT_WORK','maximumConcurrentSelections':1}}
def dx_files(items):
 out=[b'%%DX v1.3.1\n']
 for x in items:
  name=('repository/'+x['path']) if x['status']=='included' else ('metadata/'+x['path']+'.json')
  data=(x['content'].encode() if x['status']=='included' else (json.dumps({k:v for k,v in x.items() if k!='content'},sort_keys=True,indent=2)+'\n').encode())
  if data and not data.endswith(b'\n'): data+=b'\n'
  out.append(f'%%FILE path="{name}" readonly="true"\n'.encode()); out.extend(b'    '+z for z in data.splitlines(keepends=True)); out.append(b'%%ENDBLOCK\n')
 out.append(b'%%END\n'); return b''.join(out)
def render_markdown(m):
 g=m['git']; a=['# Collaboration Context','',f'- Repository: `{g["repository"]}`',f'- Default branch: `{g["defaultBranch"]}`',f'- Current branch: `{g["currentBranch"]}`',f'- HEAD: `{g["head"]}`',f'- Working tree: `{g["workingTree"]}`','','## Tracked Repository Tree','','````text',*g['trackedTree'],'````','','## Recent Commits','','````json',json.dumps(g['recentCommits'],indent=2,ensure_ascii=False),'````']
 for title,key in [('Open Issues','openIssues'),('Open Milestones','milestones'),('Open Pull Requests','openPullRequests'),('Recently Merged Pull Requests','recentlyMergedPullRequests'),('Labels','labels')]: a += ['',f'## {title}','','````json',json.dumps(m['github']['data'].get(key,[]),indent=2,ensure_ascii=False),'````']
 a += ['','## Selected Repository Files','']
 for x in m['selectedFiles']: a.append(f'- `{x["path"]}`: `{x["status"]}`'+(f' ({x.get("reason")})' if x.get('reason') else ''))
 return '\n'.join(a)+'\n'
def main():
 p=argparse.ArgumentParser()
 p.add_argument(
  'command',
  choices=['model','render-context','export-json'],
 )
 p.add_argument('--root',default='.')
 p.add_argument('--repo')
 p.add_argument('--out')
 p.add_argument('--out-dir')
 p.add_argument('--include',action='append',default=[])
 p.add_argument('--exclude',action='append',default=[])
 p.add_argument('--max-bytes',type=int,default=262144)
 p.add_argument('--recent-commits',type=int,default=20)
 p.add_argument('--no-github',action='store_true')
 p.add_argument('--consumer-root')
 p.add_argument('--consumer-include',action='append',default=[])
 a=p.parse_args()

 try:
  m=collect(
   a.root,
   a.repo,
   a.include,
   a.exclude,
   a.max_bytes,
   a.recent_commits,
   not a.no_github,
   a.consumer_root,
   a.consumer_include,
  )

  if a.command=='model':
   if not a.out:
    raise Error('--out is required')

   atomic(
    Path(a.out),
    (
     json.dumps(
      m,
      indent=2,
      sort_keys=True,
      ensure_ascii=False,
     )+'\n'
    ).encode(),
   )

  elif a.command=='render-context':
   if not a.out:
    raise Error('--out is required')

   atomic(
    Path(a.out),
    render_markdown(m).encode(),
   )

  else:
   if not a.out_dir:
    raise Error('--out-dir is required')

   directory=Path(a.out_dir)

   atomic(
    directory/'repository-state.json',
    (
     json.dumps(
      repository_state(m),
      indent=2,
      sort_keys=True,
     )+'\n'
    ).encode(),
   )

   repository_facts={
    'trackedTree':m['git']['trackedTree'],
    'recentCommits':m['git']['recentCommits'],
    'selectedFiles':m['selectedFiles'],
    'relationships':m['relationships'],
   }

   atomic(
    directory/'repository-facts.json',
    (
     json.dumps(
      repository_facts,
      indent=2,
      sort_keys=True,
     )+'\n'
    ).encode(),
   )

   atomic(
    directory/'github-evidence.json',
    (
     json.dumps(
      m['github'],
      indent=2,
      sort_keys=True,
     )+'\n'
    ).encode(),
   )

   atomic(
    directory/'repository-evidence.dx.txt',
    dx_files(m['selectedFiles']),
   )

  return 0

 except Error as e:
  print(
   f'ERROR: {e}',
   file=__import__('sys').stderr,
  )
  return 1

if __name__=='__main__':
 raise SystemExit(main())
