"""Read-only loading and validation for repository manifest declarations."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

MANIFEST_PATH = ".repository/manifest.json"
SCHEMA_IDENTITY = "collab/repository-manifest/v1"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "repository-manifest.schema.json"
_BOUNDARY_NAMES = ("public", "internal", "generated", "historical", "readOnly")

@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}

@dataclass(frozen=True)
class ManifestResult:
    status: str
    manifest_path: str
    declaration: Mapping[str, Any] | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def valid(self) -> bool:
        return self.status == "valid"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "manifestPath": self.manifest_path,
            "declaration": self.declaration,
            "diagnostics": [d.as_dict() for d in self.diagnostics],
        }

def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code, path, message)

def _json_path(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result

def _schema_diagnostics(value: Any, schema_path: Path) -> list[Diagnostic]:
    try:
        import jsonschema
    except ImportError:
        return [_diagnostic("schema_validator_unavailable", "$", "JSON Schema validation is unavailable")]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [_diagnostic("schema_unavailable", "$", f"Manifest schema is unavailable: {exc}")]
    validator = jsonschema.Draft202012Validator(schema)
    return [
        _diagnostic("schema_violation", _json_path(error.absolute_path), error.message)
        for error in sorted(validator.iter_errors(value), key=lambda error: (_json_path(error.absolute_path), error.message))
    ]

def _is_within_root(root: Path, path: str) -> bool:
    try:
        candidate = (root / Path(*PurePosixPath(path).parts)).resolve(strict=False)
        candidate.relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False

def _path_exists(root: Path, path: str) -> bool:
    if not _is_within_root(root, path):
        return False
    return (root / Path(*PurePosixPath(path).parts)).exists()

def _duplicate_diagnostics(items: list[Mapping[str, Any]], collection: str) -> list[Diagnostic]:
    seen: dict[str, int] = {}
    result: list[Diagnostic] = []
    for index, item in enumerate(items):
        identifier = item.get("id")
        if isinstance(identifier, str):
            if identifier in seen:
                result.append(_diagnostic("duplicate_id", f"$.{collection}[{index}].id", f"Identifier {identifier!r} duplicates $.{collection}[{seen[identifier]}].id"))
            else:
                seen[identifier] = index
    return result

def _semantic_diagnostics(value: Mapping[str, Any], root: Path) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    collections = {
        "workspace.entryPoints": value["workspace"]["entryPoints"],
        "components": value["components"], "authorities": value["authorities"],
        "engineering.entryPoints": value["engineering"]["entryPoints"],
        "releaseUnits": value["releaseUnits"], "versionDomains": value["versionDomains"],
        "relationships": value["relationships"], "invariants": value["invariants"], "nonGoals": value["nonGoals"],
    }
    for name, items in collections.items():
        result.extend(_duplicate_diagnostics(items, name))

    component_ids = {item["id"] for item in value["components"]}
    version_ids = {item["id"] for item in value["versionDomains"]}
    authority_ids = {item["id"] for item in value["authorities"]}
    for index, component in enumerate(value["components"]):
        for dep_index, identifier in enumerate(component.get("dependencies", [])):
            if identifier not in component_ids:
                result.append(_diagnostic("unresolved_component", f"$.components[{index}].dependencies[{dep_index}]", f"Unknown component {identifier!r}"))
    for index, unit in enumerate(value["releaseUnits"]):
        for ref_index, identifier in enumerate(unit["components"]):
            if identifier not in component_ids:
                result.append(_diagnostic("unresolved_component", f"$.releaseUnits[{index}].components[{ref_index}]", f"Unknown component {identifier!r}"))
        if unit["versionDomain"] not in version_ids:
            result.append(_diagnostic("unresolved_version_domain", f"$.releaseUnits[{index}].versionDomain", f"Unknown version domain {unit['versionDomain']!r}"))
    for index, identifier in enumerate(value["policy"]["alignment"]["authorityIds"]):
        if identifier not in authority_ids:
            result.append(_diagnostic("unresolved_authority", f"$.policy.alignment.authorityIds[{index}]", f"Unknown authority {identifier!r}"))

    resolvable: list[tuple[str, str]] = []
    for index, item in enumerate(value["workspace"]["entryPoints"]): resolvable.append((f"$.workspace.entryPoints[{index}].path", item["path"]))
    for index, item in enumerate(value["engineering"]["entryPoints"]): resolvable.append((f"$.engineering.entryPoints[{index}].path", item["path"]))
    for index, item in enumerate(value["authorities"]): resolvable.append((f"$.authorities[{index}].path", item["path"]))
    for index, item in enumerate(value["versionDomains"]):
        if "sourcePath" in item: resolvable.append((f"$.versionDomains[{index}].sourcePath", item["sourcePath"]))
    for path, declared in resolvable:
        if not _path_exists(root, declared): result.append(_diagnostic("path_not_found", path, f"Declared repository path {declared!r} does not exist"))

    boundaries = value["boundaries"]
    owners: dict[str, str] = {}
    for name in _BOUNDARY_NAMES:
        for index, declared in enumerate(boundaries[name]):
            previous = owners.get(declared)
            if previous is not None:
                result.append(_diagnostic("contradictory_boundary", f"$.boundaries.{name}[{index}]", f"Path {declared!r} is also declared as {previous}"))
            else: owners[declared] = name
    return result

def validate_manifest(value: Any, repository_root: str | Path, *, schema_path: str | Path = SCHEMA_PATH) -> tuple[Diagnostic, ...]:
    """Validate a parsed declaration without mutating the repository."""
    schema_errors = _schema_diagnostics(value, Path(schema_path))
    if schema_errors:
        return tuple(schema_errors)
    return tuple(sorted(_semantic_diagnostics(value, Path(repository_root)), key=lambda d: (d.path, d.code, d.message)))

def load_repository_manifest(repository_root: str | Path, *, manifest_path: str = MANIFEST_PATH, schema_path: str | Path = SCHEMA_PATH) -> ManifestResult:
    """Load and validate the conventional manifest, preserving absence and failure states."""
    root = Path(repository_root)
    if not root.exists() or not root.is_dir():
        return ManifestResult("unavailable", manifest_path, None, (_diagnostic("repository_unavailable", "$", "Repository root is unavailable"),))
    target = root / Path(*PurePosixPath(manifest_path).parts)
    if not target.exists():
        return ManifestResult("not_declared", manifest_path, None, ())
    try:
        raw = target.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError) as exc:
        return ManifestResult("unavailable", manifest_path, None, (_diagnostic("manifest_unavailable", "$", f"Manifest cannot be read: {exc}"),))
    except json.JSONDecodeError as exc:
        return ManifestResult("invalid", manifest_path, None, (_diagnostic("invalid_json", "$", f"Invalid JSON at line {exc.lineno}, column {exc.colno}"),))
    diagnostics = validate_manifest(value, root, schema_path=schema_path)
    return ManifestResult("valid" if not diagnostics else "invalid", manifest_path, value, diagnostics)
