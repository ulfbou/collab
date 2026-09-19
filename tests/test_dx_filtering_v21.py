from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
DX=Path(__file__).resolve().parents[1]/'dx.py'
def run(*args,cwd=None): return subprocess.run([sys.executable,str(DX),*map(str,args)],cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
def listing(result):
 p=run('inspect','-','--list'); return p

def test_path_hard_exclude_and_positive_union(tmp_path):
 r=tmp_path/'r';(r/'src/cache').mkdir(parents=True);(r/'src/a.py').write_text('a');(r/'src/cache/x.py').write_text('x');(r/'README.MD').write_text('m')
 p=run('pack',r,'--path','src','--path','README.MD','--include','src/','--include-extension','.md','--exclude','src/cache/','-o','-','-q')
 assert p.returncode==0,p.stderr
 q=subprocess.run([sys.executable,str(DX),'inspect','-','--list'],input=p.stdout,stdout=subprocess.PIPE)
 assert q.stdout.splitlines()==[b'README.MD',b'src/a.py']
def test_exact_json_counts_and_only_isolation(tmp_path):
 r=tmp_path/'r';r.mkdir();(r/'a~').write_text('a');(r/'b').write_text('b')
 p=run('pack',r,'--dry-run','--json'); d=json.loads(p.stdout); assert d['candidate_count']==sum(d['filter_counts'].values())
 p=run('pack',r,'--only','a~','-o','-','-q'); assert p.returncode==0,p.stderr
def test_output_protection_and_compound_extension(tmp_path):
 r=tmp_path/'r';r.mkdir();(r/'x.TAR.GZ').write_text('x');out=r/'out.dx'
 p=run('pack',r,'--include-extension','tar.gz','-o',out);assert p.returncode==0,p.stderr
 q=run('inspect',out,'--list');assert q.stdout.splitlines()==[b'x.TAR.GZ']
def test_unsafe_git_gate(tmp_path):
 r=tmp_path/'r';(r/'.git').mkdir(parents=True);(r/'.git/config').write_text('x')
 p=run('pack',r,'--only','.git/config','--unsafe-include-git','-o','-');assert p.returncode==2

def test_path_scope_respects_gitignore(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()

    initialized = subprocess.run(
        ["git", "init", "-q"],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr

    (repository / ".gitignore").write_text(
        "__pycache__/\nbin/\nobj/\n",
        encoding="utf-8",
    )
    (repository / "keep.py").write_text("keep\n", encoding="utf-8")

    for relative in (
        "__pycache__/cached.pyc",
        "bin/generated.dll",
        "obj/generated.assets.json",
    ):
        artifact = repository / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("artifact\n", encoding="utf-8")

    packed = run(
        "pack",
        repository,
        "--path",
        ".",
        "--output",
        "-",
        "--quiet",
    )
    assert packed.returncode == 0, packed.stderr

    listed = subprocess.run(
        [sys.executable, str(DX), "inspect", "-", "--list"],
        input=packed.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.splitlines() == [b".gitignore", b"keep.py"]


def test_positive_filter_overrides_path_scope_gitignore(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()

    initialized = subprocess.run(
        ["git", "init", "-q"],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr

    (repository / ".gitignore").write_text(
        "generated/\n",
        encoding="utf-8",
    )
    required = repository / "generated" / "required.json"
    required.parent.mkdir()
    required.write_text("{}\n", encoding="utf-8")

    packed = run(
        "pack",
        repository,
        "--path",
        ".",
        "--include",
        "generated/required.json",
        "--output",
        "-",
        "--quiet",
    )
    assert packed.returncode == 0, packed.stderr

    listed = subprocess.run(
        [sys.executable, str(DX), "inspect", "-", "--list"],
        input=packed.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.splitlines() == [b"generated/required.json"]
