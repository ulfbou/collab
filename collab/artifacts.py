"""Artifact identity and deterministic JSON helpers."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, asdict
from pathlib import Path
from .filesystem import reject_symlink

@dataclass(frozen=True)
class ArtifactRecord:
    path: str
    size: int
    sha256: str

def describe_artifact(path: Path, *, display_path: str | None = None) -> ArtifactRecord:
    reject_symlink(path, description="artifact")
    if not path.is_file(): raise FileNotFoundError(f"artifact is missing: {path}")
    data=path.read_bytes()
    return ArtifactRecord(display_path or str(path),len(data),hashlib.sha256(data).hexdigest())

def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value,indent=2,ensure_ascii=False,sort_keys=True)+'\n').encode('utf-8')

def manifest(tool: str, version: str, records: list[ArtifactRecord]) -> dict[str, object]:
    return {'schemaVersion':'1.0','producer':{'tool':tool,'version':version},'artifacts':[asdict(x) for x in records]}
