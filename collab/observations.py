"""Read-only, provenance-bearing local and hosted repository observations."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

MANIFEST_PATH = ".collab/repository-manifest.json"

class ObservationError(RuntimeError):
    pass

def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

def _run(argv: Sequence[str], cwd: Path) -> bytes:
    try:
        return subprocess.run(argv,cwd=cwd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout
    except (OSError,subprocess.CalledProcessError) as exc:
        detail=getattr(exc,"stderr",b"")
        if isinstance(detail,bytes): detail=detail.decode("utf-8","replace").strip()
        raise ObservationError(detail or f"command failed: {' '.join(argv)}") from exc

def _git(root,*args): return _run(("git",*args),Path(root))
def _z(raw): return sorted(x.decode("utf-8","surrogateescape") for x in raw.split(b"\0") if x)
def _identity(value):
    data=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return "sha256:"+hashlib.sha256(data).hexdigest()

def observe_manifest(root: Path, path: str=MANIFEST_PATH):
    file=root/path
    result={"path":path,"status":"not_declared","limitations":[]}
    if not file.is_file(): return result
    data=file.read_bytes()
    result.update(status="observed",byteLength=len(data),contentIdentity="sha256:"+hashlib.sha256(data).hexdigest())
    try: value=json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        result.update(structuralValidation="invalid",declaredSchemaIdentity=None,diagnostics=[f"invalid JSON: {exc}"])
        return result
    result.update(structuralValidation="json_valid",declaredSchemaIdentity=value.get("$schema") if isinstance(value,dict) else None,
                  limitations=["schema conformance and semantic authority are owned by Issue #85"])
    return result

def observe_local_repository(start: Path|str=Path.cwd()):
    start=Path(start)
    root=Path(_git(start,"rev-parse","--show-toplevel").decode().strip()).resolve()
    origin=_git(root,"remote","get-url","origin").decode().strip()
    slug=origin.removesuffix(".git")
    for prefix in ("git@github.com:","https://github.com/","http://github.com/","ssh://git@github.com/"):
        if slug.startswith(prefix): slug=slug[len(prefix):]; break
    git_dir_raw=_git(root,"rev-parse","--git-dir").decode().strip()
    git_dir=(root/git_dir_raw).resolve() if not os.path.isabs(git_dir_raw) else Path(git_dir_raw)
    branch=_git(root,"branch","--show-current").decode().strip() or None
    head=_git(root,"rev-parse","--verify","HEAD").decode().strip()
    tree=subprocess.run(("git","write-tree"),cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    default=subprocess.run(("git","symbolic-ref","--quiet","--short","refs/remotes/origin/HEAD"),cwd=root,stdout=subprocess.PIPE)
    markers={"merge":"MERGE_HEAD","cherryPick":"CHERRY_PICK_HEAD","revert":"REVERT_HEAD","bisect":"BISECT_LOG","rebaseMerge":"rebase-merge","rebaseApply":"rebase-apply"}
    active=sorted(k for k,v in markers.items() if (git_dir/v).exists())
    status={
      "staged":_z(_git(root,"diff","--cached","--name-only","-z","--diff-filter=ACDMRTUXB")),
      "unstaged":_z(_git(root,"diff","--name-only","-z","--diff-filter=ACDMRTUXB")),
      "untracked":_z(_git(root,"ls-files","--others","--exclude-standard","-z")),
      "conflicted":_z(_git(root,"diff","--name-only","-z","--diff-filter=U")),
    }
    default_branch=default.stdout.decode().strip().removeprefix("origin/") or None
    return {"schemaVersion":"1.0","kind":"LocalRepositoryObservation","captureSessionId":"local:"+uuid.uuid4().hex,
      "capturedAt":_now(),"repository":slug,"root":str(root),"branch":branch,"head":head,
      "indexTree":tree.stdout.decode().strip() if tree.returncode==0 else None,"defaultBranch":default_branch,
      "status":status,"operationState":{"active":active,"inProgress":bool(active)},"complete":True,
      "limitations":[] if default_branch else ["origin default branch is not available locally"],"manifest":observe_manifest(root)}

@dataclass(frozen=True)
class HostedQuery:
    kind: str
    value: str

class HostedRepositoryCollector:
    def __init__(self,repository:str,*,gh="gh",cwd=Path.cwd(),execute:Callable[[Sequence[str],Path],bytes]=_run):
        self.repository=repository; self.gh=gh; self.cwd=Path(cwd); self.execute=execute; self.session="hosted:"+uuid.uuid4().hex
    def _api(self,endpoint,paginate=False):
        args=[self.gh,"api","--method","GET","-H","X-GitHub-Api-Version: 2022-11-28"]
        if paginate: args += ["--paginate","--slurp"]
        args.append(endpoint)
        try: value=json.loads(self.execute(args,self.cwd).decode("utf-8"))
        except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ObservationError(f"invalid GitHub JSON for {endpoint}") from exc
        if not paginate: return value
        pages=value if isinstance(value,list) else [value]; items=[]
        for page in pages: items.extend(page if isinstance(page,list) else [page])
        return {"items":items,"pageCount":len(pages),"itemCount":len(items),"complete":True,"sourceIdentity":_identity(items)}
    def collect(self,query:HostedQuery|None=None):
        owner,name=self.repository.split("/",1); base=f"repos/{owner}/{name}"; repo=self._api(base)
        domains={"repository":{"content":repo,"pageCount":1,"itemCount":1,"complete":True,"sourceIdentity":_identity(repo)}}
        for key,endpoint in {"issues":"issues?state=open&per_page=100","pullRequests":"pulls?state=open&per_page=100","milestones":"milestones?state=open&per_page=100","branches":"branches?per_page=100"}.items():
            domains[key]=self._api(f"{base}/{endpoint}",True)
        selected=None
        if query:
            endpoints={"issue":"issues","pr":"pulls","milestone":"milestones","branch":"branches","commit":"commits"}
            if query.kind not in endpoints: raise ObservationError("bounded query kind must be issue, pr, milestone, branch, or commit")
            content=self._api(f"{base}/{endpoints[query.kind]}/{query.value}")
            selected={"kind":query.kind,"value":query.value,"content":content,"complete":True,"sourceIdentity":_identity(content)}
        return {"schemaVersion":"1.0","kind":"HostedRepositoryObservation","captureSessionId":self.session,"capturedAt":_now(),
          "repository":self.repository,"transport":"github-rest-via-gh","fallbackReason":None,"defaultBranchRef":repo.get("default_branch"),
          "domains":domains,"boundedQuery":selected,"complete":True,"limitations":[]}
