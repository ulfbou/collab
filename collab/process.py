"""Typed subprocess execution, retained evidence, and process-tree termination."""
from __future__ import annotations
import os, signal, subprocess, time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Collection, Mapping, Sequence

class CommandError(RuntimeError): pass
class ExecutionClassification(str, Enum):
    SUCCESS="SUCCESS"; NONZERO_EXIT="NONZERO_EXIT"; TIMEOUT="TIMEOUT"
    EXECUTABLE_NOT_FOUND="EXECUTABLE_NOT_FOUND"; START_FAILURE="START_FAILURE"

@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str,...]; returncode: int; stdout: bytes; stderr: bytes; elapsed_milliseconds: int

@dataclass(frozen=True)
class ProcessResult:
    command_id: str; argv: tuple[str,...]; cwd: str; started_utc: str; finished_utc: str
    duration_seconds: float; exit_code: int|None; classification: ExecutionClassification
    timed_out: bool; termination_actions: tuple[str,...]; stdout_path: str; stderr_path: str
    def to_dict(self):
        value=asdict(self); value["classification"]=self.classification.value; return value

def utc_now(): return datetime.now(timezone.utc).isoformat()

def terminate_process_tree(process: subprocess.Popen) -> tuple[str,...]:
    actions=[]
    if process.poll() is not None: return tuple(actions)
    if os.name=="nt":
        first=subprocess.run(("taskkill","/PID",str(process.pid),"/T"),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
        actions.append(f"taskkill:{first.returncode}")
        if process.poll() is None:
            forced=subprocess.run(("taskkill","/PID",str(process.pid),"/T","/F"),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
            actions.append(f"taskkill-force:{forced.returncode}")
        return tuple(actions)
    try: os.killpg(process.pid,signal.SIGTERM); actions.append("sigterm-process-group")
    except ProcessLookupError: return tuple(actions)
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try: os.killpg(process.pid,signal.SIGKILL); actions.append("sigkill-process-group")
        except ProcessLookupError: pass
    return tuple(actions)

def run_process(*, command_id: str, argv: Sequence[str], cwd: Path, evidence_directory: Path,
                timeout_seconds: int, environment: Mapping[str,str]|None=None) -> ProcessResult:
    directory=Path(evidence_directory)/"commands"/command_id; directory.mkdir(parents=True,exist_ok=True)
    stdout_path=directory/"stdout.txt"; stderr_path=directory/"stderr.txt"
    started=utc_now(); tick=time.monotonic(); timed_out=False; actions=(); code=None
    env=os.environ.copy(); env.update(environment or {})
    options={"creationflags":subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=="nt" else {"start_new_session":True}
    try:
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            process=subprocess.Popen(list(argv),cwd=cwd,env=env,stdout=out,stderr=err,**options)
            try: code=process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out=True; actions=terminate_process_tree(process)
                try: code=process.wait(timeout=10)
                except subprocess.TimeoutExpired: code=None
    except FileNotFoundError: classification=ExecutionClassification.EXECUTABLE_NOT_FOUND
    except OSError: classification=ExecutionClassification.START_FAILURE
    else:
        classification=ExecutionClassification.TIMEOUT if timed_out else ExecutionClassification.SUCCESS if code==0 else ExecutionClassification.NONZERO_EXIT
    return ProcessResult(command_id,tuple(argv),str(cwd),started,utc_now(),round(time.monotonic()-tick,6),code,classification,timed_out,actions,stdout_path.as_posix(),stderr_path.as_posix())

def run_command(argv: Sequence[str], *, cwd: Path|None=None, stdin: bytes|None=None,
                accepted_exit_codes: Collection[int]=(0,)) -> CommandResult:
    started=time.monotonic_ns()
    try: completed=subprocess.run(list(argv),cwd=cwd,input=stdin,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    except FileNotFoundError as exc: raise CommandError(f"required command not found: {argv[0]}") from exc
    result=CommandResult(tuple(argv),completed.returncode,completed.stdout,completed.stderr,max(0,(time.monotonic_ns()-started)//1_000_000))
    if completed.returncode not in accepted_exit_codes:
        detail=completed.stderr.decode("utf-8","replace").strip(); suffix=f"\n{detail}" if detail else ""
        raise CommandError(f"command failed ({completed.returncode}): {' '.join(argv)}{suffix}")
    return result
