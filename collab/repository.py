"""Git repository discovery and GitHub repository normalization."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from .process import run_command
from .validation import require_repository_slug

@dataclass(frozen=True)
class RepositoryIdentity:
    root: Path; origin_url: str; name_with_owner: str; head: str; current_branch: str; default_branch: str | None

def canonical_github_repository(value: str) -> str:
    value=re.sub(r'\.git$','',value.strip())
    for prefix in ('git@github.com:','https://github.com/','http://github.com/','ssh://git@github.com/'):
        if value.startswith(prefix): value=value[len(prefix):]; break
    return require_repository_slug(value,'repository')

def _text(argv,root): return run_command(argv,cwd=root).stdout.decode().strip()
def discover_repository(start: Path=Path.cwd()) -> RepositoryIdentity:
    root=Path(_text(['git','rev-parse','--show-toplevel'],start)).resolve()
    origin=_text(['git','remote','get-url','origin'],root)
    head=_text(['git','rev-parse','HEAD'],root)
    branch=_text(['git','branch','--show-current'],root)
    default_result=run_command(['git','symbolic-ref','--quiet','--short','refs/remotes/origin/HEAD'],cwd=root,accepted_exit_codes=(0,1))
    default=default_result.stdout.decode().strip().removeprefix('origin/') or None
    return RepositoryIdentity(root,origin,canonical_github_repository(origin),head,branch,default)


class GitStateError(RuntimeError):
    pass

def capture_git_state(repository_root: Path) -> dict[str, object]:
    """Capture immutable Git identity plus complete tracked and untracked status."""
    try:
        return {
            "head": _text(["git","rev-parse","HEAD"],repository_root),
            "branch": _text(["git","branch","--show-current"],repository_root),
            "detached": not bool(_text(["git","branch","--show-current"],repository_root)),
            "status": _text(["git","status","--porcelain=v1","-uall"],repository_root).splitlines(),
            "tracked_diff": _text(["git","diff","--no-ext-diff","--binary","HEAD","--","."],repository_root),
        }
    except CommandError as exc:
        raise GitStateError(str(exc)) from exc

def tracked_source_status(repository_root: Path) -> list[str]:
    try:
        return _text(["git","status","--porcelain=v1","--untracked-files=no"],repository_root).splitlines()
    except CommandError as exc:
        raise GitStateError(str(exc)) from exc
