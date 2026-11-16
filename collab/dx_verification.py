"""Repository-owned final DX carrier verification."""
from __future__ import annotations
import hashlib, sys
from dataclasses import dataclass
from pathlib import Path
from .process import run_command

@dataclass(frozen=True)
class CarrierVerification:
    path: str; size: int; sha256: str; verification: str

def verify_final_carrier(carrier: Path, *, repository_root: Path, dx_cli: Path|None=None) -> CarrierVerification:
    carrier=Path(carrier)
    if not carrier.is_file() or carrier.stat().st_size==0: raise ValueError(f"carrier is missing or empty: {carrier}")
    if not carrier.name.endswith(".dx.txt"): raise ValueError(f"carrier filename must end in .dx.txt: {carrier.name}")
    cli=Path(dx_cli or Path(repository_root)/"dx.py")
    run_command((sys.executable,str(cli),"inspect",str(carrier),"--verify"),cwd=repository_root)
    return CarrierVerification(carrier.as_posix(),carrier.stat().st_size,hashlib.sha256(carrier.read_bytes()).hexdigest(),"STRUCTURE_VALID")
