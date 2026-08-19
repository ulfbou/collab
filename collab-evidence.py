#!/usr/bin/env python3
"""
collab-evidence.py

Shared Deterministic Evidence Collector
Generates strictly ordered JSON models for repository and GitHub facts.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def gh_command():
    override = os.environ.get("COLLAB_GH_BIN")
    return ["bash", override] if override else ["gh"]

def run_cmd(args, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
        return result.stdout.strip(), None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        return None, e

def atomic_write(filepath: str, content: str):
    if os.path.islink(filepath):
        raise ValueError(f"Unsafe output: {filepath} is a symlink")
    
    dir_name = os.path.dirname(filepath) or "."
    fd, temp_path = tempfile.mkstemp(dir=dir_name, text=True)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, filepath)
    except Exception:
        os.remove(temp_path)
        raise

# ---------------------------------------------------------------------------
# Git & GitHub Evidence Collection
# ---------------------------------------------------------------------------

def get_git_facts(root: str) -> dict:
    repo_name, _ = run_cmd(["git", "config", "--get", "remote.origin.url"], cwd=root)
    default_branch, _ = run_cmd(["git", "rev-parse", "--abbrev-ref", "origin/HEAD"], cwd=root)
    current_branch, _ = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    head_sha, _ = run_cmd(["git", "rev-parse", "HEAD"], cwd=root)
    
    status_porcelain, _ = run_cmd(["git", "status", "--porcelain"], cwd=root)
    is_clean = not bool(status_porcelain)
    
    tracked_tree_raw, _ = run_cmd(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=root)
    tracked_tree = tracked_tree_raw.splitlines() if tracked_tree_raw else []
    tracked_tree.sort() # Lexicographical sorting
    
    recent_commits_raw, _ = run_cmd(["git", "log", "-n", "10", "--oneline"], cwd=root)
    recent_commits = recent_commits_raw.splitlines() if recent_commits_raw else []

    return {
        "repository": repo_name.replace("git@github.com:", "").replace(".git", "") if repo_name else "local/repo",
        "defaultBranch": default_branch.replace("origin/", "") if default_branch else "main",
        "currentBranch": current_branch,
        "head": head_sha,
        "clean": is_clean,
        "trackedTree": tracked_tree,
        "recentCommits": recent_commits,
        "statusPorcelain": status_porcelain
    }

def get_github_facts(repo_name: str) -> dict:
    gh_available, _ = run_cmd([*gh_command(), "auth", "status"])
    
    if gh_available is None:
        return {
            "schemaVersion": "1.0",
            "repository": repo_name,
            "available": False,
            "queryStatus": {
                "openIssues": "unavailable",
                "openPullRequests": "unavailable",
                "recentlyMergedPullRequests": "unavailable",
                "labels": "unavailable",
                "milestones": "unavailable"
            },
            "errors": [],
            "data": {}
        }
    
    queries = {
        "openIssues": [*gh_command(), "issue", "list", "--state", "open", "--json", "number,title,body"],
        "openPullRequests": [*gh_command(), "pr", "list", "--state", "open", "--json", "number,title,url"],
        "recentlyMergedPullRequests": [*gh_command(), "pr", "list", "--state", "merged", "--limit", "10", "--json", "number,title,mergedAt"],
        "labels": [*gh_command(), "label", "list", "--json", "name,description"],
        "milestones": [*gh_command(), "api", f"repos/{repo_name}/milestones", "--jq", "[.[] | {title: .title, description: .description, dueOn: .due_on}]"]
    }
    
    status = {}
    data = {}
    errors = []
    
    for key, cmd in queries.items():
        output, err = run_cmd(cmd)
        if err:
            status[key] = "failed"
            errors.append({"section": key, "error": str(err)})
        else:
            status[key] = "ok"
            try:
                parsed = json.loads(output)
                # Stable identity sorting
                if key in ["openIssues", "openPullRequests", "recentlyMergedPullRequests"]:
                    parsed.sort(key=lambda x: x.get("number", 0))
                elif key == "labels":
                    parsed.sort(key=lambda x: x.get("name", ""))
                elif key == "milestones":
                    parsed.sort(key=lambda x: x.get("title", ""))
                data[key] = parsed
            except json.JSONDecodeError:
                data[key] = []

    # If every query failed, treat GitHub as unavailable (covers Windows PATH shadowing
    # where real gh.exe passes auth but mock gh.bat blocks queries)
    if status and all(v == "failed" for v in status.values()):
        return {
            "schemaVersion": "1.0",
            "repository": repo_name,
            "available": False,
            "queryStatus": {k: "unavailable" for k in queries},
            "errors": errors,
            "data": {}
        }

    return {
        "schemaVersion": "1.0",
        "repository": repo_name,
        "available": True,
        "queryStatus": status,
        "errors": errors,
        "data": data
    }

# ---------------------------------------------------------------------------
# File Selection
# ---------------------------------------------------------------------------

def is_binary(file_path: str) -> bool:
    try:
        data = Path(file_path).read_bytes()
        if b"\x00" in data:
            return True
        data.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True

def select_files(root: str, tracked: list, includes: list, excludes: list, max_bytes: int):
    selected = []
    excludes.append(".dx")
    
    for file_path in includes:
        if not any(file_path.startswith(t) for t in tracked) and file_path not in tracked:
             selected.append({"path": file_path, "status": "missing"})
             continue

    for file_path in tracked:
        if any(file_path.startswith(ex) for ex in excludes):
            continue
            
        if includes and not any(file_path.startswith(inc) for inc in includes):
            continue

        abs_path = os.path.join(root, file_path)
        if not os.path.exists(abs_path):
            continue

        size = os.path.getsize(abs_path)
        with open(abs_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        if size > max_bytes:
            selected.append({"path": file_path, "status": "omitted_size", "size": size, "sha256": file_hash})
            continue

        if is_binary(abs_path):
            selected.append({"path": file_path, "status": "omitted_binary", "size": size, "sha256": file_hash})
            continue

        selected.append({"path": file_path, "status": "included", "size": size, "sha256": file_hash})

    selected.sort(key=lambda x: x["path"])
    return selected

# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def generate_evidence_model(root: str, includes: list, excludes: list, max_bytes: int) -> dict:
    git_facts = get_git_facts(root)
    gh_facts = get_github_facts(git_facts["repository"])
    files = select_files(root, git_facts["trackedTree"], includes, excludes, max_bytes)
    
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "git": git_facts,
        "github": gh_facts,
        "selectedFiles": files,
        "relationships": {"providers": [], "consumers": []}
    }

def render_markdown_context(model: dict) -> str:
    md = [f"# Collaborative Context Report\nGenerated at: {model['generatedAt']}\n"]
    
    md.append("## Repository State")
    md.append(f"- **Repository**: {model['git']['repository']}")
    md.append(f"- **Branch**: {model['git']['currentBranch']}")
    md.append(f"- **HEAD**: {model['git']['head']}")
    md.append(f"- **Clean**: {model['git']['clean']}\n")
    
    md.append("## Selected Files")
    for f in model["selectedFiles"]:
        status_str = f"({f['status']})" if f["status"] != "included" else ""
        md.append(f"- `{f['path']}` {status_str}")
        
    # Additional markdown block logic mapping from `model` goes here...
    
    return "\n".join(md)

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Deterministic Evidence Collector")
    subparsers = parser.add_subparsers(dest="command")
    
    # Render Context Command
    render_parser = subparsers.add_parser("render-context")
    render_parser.add_argument("--root", default=".")
    render_parser.add_argument("--out", required=True)
    render_parser.add_argument("--include", action="append", default=[])
    render_parser.add_argument("--exclude", action="append", default=[])
    render_parser.add_argument("--max-bytes", type=int, default=50000)
    
    # Export JSON Command (for collab-chat.py)
    export_parser = subparsers.add_parser("export-json")
    export_parser.add_argument("--root", default=".")
    export_parser.add_argument("--out-dir", required=True)
    export_parser.add_argument("--include", action="append", default=[])
    
    args = parser.parse_args()
    
    if args.command == "render-context":
        model = generate_evidence_model(args.root, args.include, args.exclude, args.max_bytes)
        md_content = render_markdown_context(model)
        atomic_write(args.out, md_content)
        
    elif args.command == "export-json":
        model = generate_evidence_model(args.root, args.include, [], 50000)
        
        # Split output to prevent schema expansion
        state_model = {"branch": model["git"]["currentBranch"], "head": model["git"]["head"]} 
        facts_model = {"trackedTree": model["git"]["trackedTree"], "recentCommits": model["git"]["recentCommits"], "selectedFiles": model["selectedFiles"]}
        
        atomic_write(os.path.join(args.out_dir, "repository-state.json"), json.dumps(state_model, sort_keys=True, indent=2))
        atomic_write(os.path.join(args.out_dir, "repository-facts.json"), json.dumps(facts_model, sort_keys=True, indent=2))
        atomic_write(os.path.join(args.out_dir, "github-evidence.json"), json.dumps(model["github"], sort_keys=True, indent=2))

if __name__ == "__main__":
    main()