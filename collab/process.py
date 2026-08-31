"""Typed subprocess execution with actionable failures."""
from __future__ import annotations
import subprocess, time
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Sequence

class CommandError(RuntimeError): pass
@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str,...]; returncode: int; stdout: bytes; stderr: bytes; elapsed_milliseconds: int

def run_command(argv: Sequence[str], *, cwd: Path | None=None, stdin: bytes | None=None, accepted_exit_codes: Collection[int]=(0,)) -> CommandResult:
    started=time.monotonic_ns()
    try: p=subprocess.run(list(argv),cwd=cwd,input=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    except FileNotFoundError as exc: raise CommandError(f"required command not found: {argv[0]}") from exc
    result=CommandResult(tuple(argv),p.returncode,p.stdout,p.stderr,max(0,(time.monotonic_ns()-started)//1_000_000))
    if p.returncode not in accepted_exit_codes:
        detail=p.stderr.decode('utf-8','replace').strip()
        suffix=f"\n{detail}" if detail else ''
        raise CommandError(f"command failed ({p.returncode}): {' '.join(argv)}{suffix}")
    return result
