"""Deterministic Development Intent and AuthoritySet resolution.

This module is read-only. It derives applicability identities from supplied
issue or accepted operational authority and resolves durable documentation
authority without treating declarations as observations or implementation.

Status contract for AuthoritySet resolution:

- Input-layer failures (invalid ``repository``, unavailable
  ``repositoryRoot``) return ``ResolutionResult("invalid", None,
  diagnostics)``. No partial AuthoritySet is emitted. This mirrors
  ``derive_issue_intent`` and ``derive_operational_intent`` at the input
  boundary.
- Content-layer failures (structurally invalid declared authorities,
  unrecognized manifest status, unsafe authority paths, absent required
  authorities, unavailable or unreadable authority content, declaration
  versus observation conflicts) return a complete AuthoritySet value whose
  ``status`` is ``"incomplete"`` or ``"conflicted"``. ``diagnostics``
  carries a flat list of structured errors; every unresolved category
  contributes at least one diagnostic. The ``invalidDeclarations``,
  ``absentDeclarations``, ``incompleteEvidence``, and ``conflicts`` ledgers
  group them by role inside the AuthoritySet. ``ResolutionResult.valid`` is
  False whenever ``status != "resolved"``.
- Only fully-resolved sets return ``ResolutionResult("resolved", value, ())``.

Authority path classification follows the contract: an unsafe authority
path (absolute, drive-qualified, traversal, backslash, or otherwise
structurally invalid) is a declaration defect and is recorded in
``invalidDeclarations``; a missing path, a path that is not a regular file,
and unreadable content are recorded in ``incompleteEvidence`` with distinct
reasons (``authority-content-missing``, ``authority-content-not-file``,
``authority-content-unreadable``).

The absence of a repository manifest is recorded in ``provenance`` with
``status: "not_declared"``. It does not by itself produce ``"incomplete"``;
that status is reserved for actual evidence gaps and conflicts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

INTENT_SCHEMA = "collab/development-intent/v1"
AUTHORITY_SET_SCHEMA = "collab/authority-set/v1"
INTENT_NORMALIZATION_VERSION = "1"
AUTHORITY_NORMALIZATION_VERSION = "1"

ISSUE_FIELDS = (
    "repository",
    "number",
    "title",
    "body",
    "state",
    "labels",
    "milestone",
)
OPERATIONAL_FIELDS = (
    "repository",
    "authorizationId",
    "objective",
    "expectedBoundary",
    "allowedMutation",
    "changedPathScope",
    "exclusions",
    "acceptanceConditions",
    "dependencies",
)

AUTHORITY_KINDS = frozenset(
    {"policy", "contract", "schema", "decision", "documentation"}
)


@dataclass(frozen=True, order=True)
class Diagnostic:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class ResolutionResult:
    status: str
    value: Mapping[str, Any] | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def valid(self) -> bool:
        return self.status == "resolved"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "value": self.value,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code, path, message)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _identity(prefix: str, version: str, value: Any) -> str:
    digest = hashlib.sha256(_canonical(value)).hexdigest()
    return f"sha256:{prefix}:v{version}:{digest}"


def _ordered_diagnostics(items: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    return tuple(sorted(items, key=lambda item: (item.path, item.code, item.message)))


def _string_list(
    value: Any,
    path: str,
    *,
    required: bool = False,
) -> tuple[tuple[str, ...], tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    if value is None:
        if required:
            diagnostics.append(
                _diagnostic("missing_required", path, "Required string array is missing")
            )
        return (), tuple(diagnostics)
    if not isinstance(value, list):
        return (), (
            _diagnostic("invalid_type", path, "Value must be an array of strings"),
        )

    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            diagnostics.append(
                _diagnostic(
                    "invalid_string",
                    f"{path}[{index}]",
                    "Value must be a non-empty string",
                )
            )
        else:
            result.append(item.strip())
    return tuple(result), _ordered_diagnostics(diagnostics)


def _labels(value: Any) -> tuple[tuple[str, ...], tuple[Diagnostic, ...]]:
    if value is None:
        return (), ()
    if not isinstance(value, list):
        return (), (
            _diagnostic("invalid_type", "$.issue.labels", "Labels must be an array"),
        )

    diagnostics: list[Diagnostic] = []
    result: list[str] = []
    for index, item in enumerate(value):
        name = item.get("name") if isinstance(item, Mapping) else item
        if not isinstance(name, str) or not name.strip():
            diagnostics.append(
                _diagnostic(
                    "invalid_label",
                    f"$.issue.labels[{index}]",
                    "Label must contain a non-empty name",
                )
            )
        else:
            result.append(name.strip())
    return tuple(sorted(set(result))), _ordered_diagnostics(diagnostics)


def _milestone(value: Any) -> tuple[Mapping[str, Any] | None, tuple[Diagnostic, ...]]:
    if value is None:
        return None, ()
    if not isinstance(value, Mapping):
        return None, (
            _diagnostic(
                "invalid_type",
                "$.issue.milestone",
                "Milestone must be an object or null",
            ),
        )
    number = value.get("number")
    title = value.get("title")
    if not isinstance(number, int) or number < 1:
        return None, (
            _diagnostic(
                "invalid_milestone",
                "$.issue.milestone.number",
                "Milestone number must be a positive integer",
            ),
        )
    if not isinstance(title, str) or not title.strip():
        return None, (
            _diagnostic(
                "invalid_milestone",
                "$.issue.milestone.title",
                "Milestone title must be a non-empty string",
            ),
        )
    return {"number": number, "title": title.strip()}, ()


def _repository(value: Any, path: str) -> tuple[str | None, tuple[Diagnostic, ...]]:
    if not isinstance(value, str):
        return None, (
            _diagnostic(
                "invalid_repository",
                path,
                "Repository must be a string in owner/name form",
            ),
        )
    parts = value.split("/")
    if (
        len(parts) != 2
        or not parts[0]
        or not parts[1]
        or any(character.isspace() for character in value)
    ):
        return None, (
            _diagnostic(
                "invalid_repository",
                path,
                "Repository must use the owner/name form without whitespace",
            ),
        )
    return value, ()


def derive_issue_intent(
    issue: Mapping[str, Any],
    *,
    authority_set: Mapping[str, Any] | None = None,
) -> ResolutionResult:
    """Derive intent from a complete hosted issue observation."""

    if not isinstance(issue, Mapping):
        return ResolutionResult(
            "invalid",
            None,
            (_diagnostic("invalid_type", "$.issue", "Issue must be an object"),),
        )

    diagnostics: list[Diagnostic] = []
    repository, found = _repository(issue.get("repository"), "$.issue.repository")
    diagnostics.extend(found)

    number = issue.get("number")
    if not isinstance(number, int) or number < 1:
        diagnostics.append(
            _diagnostic(
                "invalid_issue_number",
                "$.issue.number",
                "Issue number must be a positive integer",
            )
        )

    title = issue.get("title")
    if not isinstance(title, str) or not title.strip():
        diagnostics.append(
            _diagnostic(
                "missing_required",
                "$.issue.title",
                "Issue title must be a non-empty string",
            )
        )

    body = issue.get("body")
    if not isinstance(body, str) or not body.strip():
        diagnostics.append(
            _diagnostic(
                "missing_required",
                "$.issue.body",
                "Issue body must be a non-empty string",
            )
        )

    state = issue.get("state")
    if state not in {"OPEN", "CLOSED"}:
        diagnostics.append(
            _diagnostic(
                "unknown_issue_state",
                "$.issue.state",
                "Issue state must be OPEN or CLOSED",
            )
        )

    labels, found = _labels(issue.get("labels"))
    diagnostics.extend(found)
    milestone, found = _milestone(issue.get("milestone"))
    diagnostics.extend(found)

    content = {
        "repository": repository,
        "number": number,
        "title": title.strip() if isinstance(title, str) else title,
        "body": body if isinstance(body, str) else body,
        "state": state,
        "labels": list(labels),
        "milestone": milestone,
    }
    content_identity = _identity("issue-content", "1", content)

    authority_set_id = None
    if authority_set is not None:
        authority_set_id = authority_set.get("authoritySetId")
        if not isinstance(authority_set_id, str):
            diagnostics.append(
                _diagnostic(
                    "invalid_authority_set",
                    "$.authoritySet.authoritySetId",
                    "AuthoritySet must contain authoritySetId",
                )
            )

    ordered = _ordered_diagnostics(diagnostics)
    if ordered:
        return ResolutionResult("invalid", None, ordered)

    identity_material = {
        "kind": "issue",
        "repository": repository,
        "number": number,
        "contentIdentity": content_identity,
        "authoritySetId": authority_set_id,
    }
    value = {
        "schema": INTENT_SCHEMA,
        "normalizationVersion": INTENT_NORMALIZATION_VERSION,
        "intentId": _identity("development-intent", "1", identity_material),
        "sourceKind": "issue",
        "source": {
            "repository": repository,
            "number": number,
            "contentIdentity": content_identity,
        },
        "objective": title.strip(),
        "expectedBoundary": "bounded-product-change",
        "hostedState": {
            "state": state,
            "labels": list(labels),
            "milestone": milestone,
        },
        "authoritySetId": authority_set_id,
        "provenance": [
            {
                "kind": "hosted-issue-observation",
                "identity": content_identity,
                "repository": repository,
                "number": number,
            }
        ],
        "limitations": [],
    }
    return ResolutionResult("resolved", value, ())


def derive_operational_intent(
    authorization: Mapping[str, Any],
    *,
    authority_set: Mapping[str, Any] | None = None,
) -> ResolutionResult:
    """Derive issue-independent intent from explicit accepted authorization."""

    if not isinstance(authorization, Mapping):
        return ResolutionResult(
            "invalid",
            None,
            (
                _diagnostic(
                    "invalid_type",
                    "$.authorization",
                    "Authorization must be an object",
                ),
            ),
        )

    diagnostics: list[Diagnostic] = []
    repository, found = _repository(
        authorization.get("repository"),
        "$.authorization.repository",
    )
    diagnostics.extend(found)

    authorization_id = authorization.get("authorizationId")
    if not isinstance(authorization_id, str) or not authorization_id.strip():
        diagnostics.append(
            _diagnostic(
                "missing_required",
                "$.authorization.authorizationId",
                "Accepted authorization identity is required",
            )
        )

    accepted = authorization.get("accepted")
    if accepted is not True:
        diagnostics.append(
            _diagnostic(
                "authorization_not_accepted",
                "$.authorization.accepted",
                "Operational authorization must be explicitly accepted",
            )
        )

    text_fields: dict[str, str | None] = {}
    for field in ("objective", "expectedBoundary"):
        value = authorization.get(field)
        if not isinstance(value, str) or not value.strip():
            diagnostics.append(
                _diagnostic(
                    "missing_required",
                    f"$.authorization.{field}",
                    f"{field} must be a non-empty string",
                )
            )
            text_fields[field] = None
        else:
            text_fields[field] = value.strip()

    allowed_mutation = authorization.get("allowedMutation")
    if not isinstance(allowed_mutation, bool):
        diagnostics.append(
            _diagnostic(
                "invalid_type",
                "$.authorization.allowedMutation",
                "allowedMutation must be boolean",
            )
        )

    arrays: dict[str, tuple[str, ...]] = {}
    for field, required in (
        ("changedPathScope", False),
        ("exclusions", False),
        ("acceptanceConditions", True),
        ("dependencies", False),
    ):
        values, found = _string_list(
            authorization.get(field),
            f"$.authorization.{field}",
            required=required,
        )
        arrays[field] = values
        diagnostics.extend(found)

    # ``required=True`` above only rejects a missing (``None``) value. The
    # operational-intent schema also requires ``acceptanceConditions`` to be
    # non-empty, so an explicitly empty array must be rejected here as well;
    # otherwise derivation could emit a value that its own schema rejects.
    if (
        authorization.get("acceptanceConditions") is not None
        and not arrays["acceptanceConditions"]
    ):
        diagnostics.append(
            _diagnostic(
                "missing_required",
                "$.authorization.acceptanceConditions",
                "acceptanceConditions must contain at least one condition",
            )
        )

    authority_set_id = None
    if authority_set is not None:
        authority_set_id = authority_set.get("authoritySetId")
        if not isinstance(authority_set_id, str):
            diagnostics.append(
                _diagnostic(
                    "invalid_authority_set",
                    "$.authoritySet.authoritySetId",
                    "AuthoritySet must contain authoritySetId",
                )
            )

    ordered = _ordered_diagnostics(diagnostics)
    if ordered:
        return ResolutionResult("invalid", None, ordered)

    normalized = {
        "repository": repository,
        "authorizationId": authorization_id.strip(),
        "objective": text_fields["objective"],
        "expectedBoundary": text_fields["expectedBoundary"],
        "allowedMutation": allowed_mutation,
        "changedPathScope": sorted(set(arrays["changedPathScope"])),
        "exclusions": sorted(set(arrays["exclusions"])),
        "acceptanceConditions": sorted(set(arrays["acceptanceConditions"])),
        "dependencies": sorted(set(arrays["dependencies"])),
        "authoritySetId": authority_set_id,
    }
    authorization_identity = _identity("accepted-authorization", "1", normalized)
    value = {
        "schema": INTENT_SCHEMA,
        "normalizationVersion": INTENT_NORMALIZATION_VERSION,
        "intentId": _identity("development-intent", "1", normalized),
        "sourceKind": "accepted-operational-authorization",
        "source": {
            "repository": repository,
            "authorizationId": authorization_id.strip(),
            "contentIdentity": authorization_identity,
        },
        "objective": text_fields["objective"],
        "expectedBoundary": text_fields["expectedBoundary"],
        "allowedMutation": allowed_mutation,
        "changedPathScope": normalized["changedPathScope"],
        "exclusions": normalized["exclusions"],
        "acceptanceConditions": normalized["acceptanceConditions"],
        "dependencies": normalized["dependencies"],
        "authoritySetId": authority_set_id,
        "provenance": [
            {
                "kind": "accepted-operational-authorization",
                "identity": authorization_identity,
            }
        ],
        "limitations": [],
    }
    return ResolutionResult("resolved", value, ())


def _is_safe_authority_path(value: str) -> bool:
    """Return True for a structurally safe repository-relative path.

    Rejects: empty values, absolute paths (POSIX and drive-qualified),
    backslashes, NUL, CR, LF, and any empty, ``.``, or ``..`` component.
    This is a pure string check — filesystem availability is classified
    separately by ``_classify_authority_content``.
    """
    if not value:
        return False
    if "\x00" in value or "\r" in value or "\n" in value:
        return False
    if "\\" in value:
        return False
    if value.startswith("/"):
        return False
    if len(value) >= 2 and value[0].isalpha() and value[1] == ":":
        return False
    for part in value.split("/"):
        if part in ("", ".", ".."):
            return False
    return True


def _classify_authority_content(root: Path, value: str) -> tuple[str, Path | None]:
    """Classify a structurally safe authority path against the filesystem.

    Returns ``(status, resolved_path)`` where ``status`` is one of:

    - ``"resolved"``: the path resolves to a regular file within ``root``;
    - ``"missing"``: the path does not exist (and is not a symlink);
    - ``"not-file"``: the path exists but does not resolve to a regular file
      within ``root`` (directory, broken symlink, or symlink escaping ``root``).

    Read failures after successful resolution are classified separately as
    ``authority-content-unreadable``.
    """
    lexical = root / Path(*PurePosixPath(value).parts)
    try:
        if not lexical.exists() and not lexical.is_symlink():
            return ("missing", None)
    except OSError:
        return ("not-file", None)
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return ("not-file", None)
    if not resolved.is_file():
        return ("not-file", None)
    return ("resolved", resolved)


def _normalize_authority_candidate(
    item: Any,
    *,
    source: str,
    path_index: int,
    path_prefix: str,
) -> tuple[Mapping[str, Any] | None, tuple[Diagnostic, ...]]:
    """Validate and normalize one declared authority.

    Returns ``(candidate, ())`` for a structurally valid declaration, or
    ``(None, diagnostics)`` for one that must be recorded in
    ``invalid_declarations``. An unsafe authority path is a declaration
    defect and is classified here; filesystem availability is classified
    separately by the caller so that missing or non-file targets remain
    incomplete evidence rather than invalid declarations.
    """

    if not isinstance(item, Mapping):
        return None, (
            _diagnostic(
                "invalid_authority_declaration",
                f"{path_prefix}[{path_index}]",
                "Authority declaration must be an object",
            ),
        )

    diagnostics: list[Diagnostic] = []

    identifier = item.get("id")
    if not isinstance(identifier, str) or not identifier:
        diagnostics.append(
            _diagnostic(
                "invalid_authority_id",
                f"{path_prefix}[{path_index}].id",
                "Authority id must be a non-empty string",
            )
        )

    kind = item.get("kind")
    if kind not in AUTHORITY_KINDS:
        diagnostics.append(
            _diagnostic(
                "unknown_authority_kind",
                f"{path_prefix}[{path_index}].kind",
                "Authority kind is not recognized",
            )
        )

    path = item.get("path")
    if not isinstance(path, str) or not path:
        diagnostics.append(
            _diagnostic(
                "invalid_authority_path",
                f"{path_prefix}[{path_index}].path",
                "Authority path must be a non-empty string",
            )
        )
    elif not _is_safe_authority_path(path):
        diagnostics.append(
            _diagnostic(
                "unsafe_authority_path",
                f"{path_prefix}[{path_index}].path",
                "Authority path violates the repository-relative contract",
            )
        )

    scope_raw = item.get("scope", [])
    scope: list[str] = []
    if not isinstance(scope_raw, list):
        diagnostics.append(
            _diagnostic(
                "invalid_authority_scope",
                f"{path_prefix}[{path_index}].scope",
                "Authority scope must be an array of strings",
            )
        )
    else:
        for scope_index, scope_item in enumerate(scope_raw):
            if not isinstance(scope_item, str):
                diagnostics.append(
                    _diagnostic(
                        "invalid_authority_scope",
                        f"{path_prefix}[{path_index}].scope[{scope_index}]",
                        "Authority scope entry must be a string",
                    )
                )
            else:
                scope.append(scope_item)

    read_only_raw = item.get("readOnly", False)
    if not isinstance(read_only_raw, bool):
        diagnostics.append(
            _diagnostic(
                "invalid_authority_read_only",
                f"{path_prefix}[{path_index}].readOnly",
                "Authority readOnly must be a boolean",
            )
        )

    if diagnostics:
        return None, _ordered_diagnostics(diagnostics)

    return (
        {
            "id": identifier,
            "kind": kind,
            "path": path,
            "scope": sorted(set(scope)),
            "readOnly": read_only_raw,
            "source": source,
        },
        (),
    )


def resolve_authority_set(
    *,
    repository: str,
    repository_root: str | Path,
    required_authority_ids: Sequence[str] = (),
    manifest_result: Any | None = None,
    document_declarations: Sequence[Mapping[str, Any]] = (),
    observed_documents: Mapping[str, Mapping[str, Any]] | None = None,
) -> ResolutionResult:
    """Resolve durable authorities without mutating or overclaiming state."""

    diagnostics: list[Diagnostic] = []
    repository_value, found = _repository(repository, "$.repository")
    diagnostics.extend(found)
    if repository_value is None:
        return ResolutionResult("invalid", None, _ordered_diagnostics(diagnostics))

    root = Path(repository_root)
    if not root.exists() or not root.is_dir():
        diagnostics.append(
            _diagnostic(
                "repository_unavailable",
                "$.repositoryRoot",
                "Repository root is unavailable",
            )
        )
        return ResolutionResult("invalid", None, _ordered_diagnostics(diagnostics))

    observations = observed_documents or {}

    declared: list[Mapping[str, Any]] = []
    invalid_declarations: list[Mapping[str, Any]] = []
    absent_declarations: list[Mapping[str, Any]] = []
    incomplete_evidence: list[Mapping[str, Any]] = []
    conflicts: list[Mapping[str, Any]] = []
    provenance: list[Mapping[str, Any]] = []

    manifest_status = "not_supplied"
    manifest_path = None
    manifest_declaration: Mapping[str, Any] | None = None
    manifest_diagnostics: Sequence[Any] = ()

    if manifest_result is not None:
        manifest_status = getattr(manifest_result, "status", None)
        manifest_path = getattr(manifest_result, "manifest_path", None)
        manifest_declaration = getattr(manifest_result, "declaration", None)
        manifest_diagnostics = getattr(manifest_result, "diagnostics", ())

        if manifest_status == "valid" and isinstance(manifest_declaration, Mapping):
            for index, item in enumerate(manifest_declaration.get("authorities", [])):
                candidate, item_diagnostics = _normalize_authority_candidate(
                    item,
                    source="repository-manifest",
                    path_index=index,
                    path_prefix="$.repositoryManifest.authorities",
                )
                if candidate is None:
                    diagnostics.extend(item_diagnostics)
                    invalid_declarations.append(
                        {
                            "source": "repository-manifest",
                            "index": index,
                            "reason": "structural-invalidity",
                            "codes": sorted({d.code for d in item_diagnostics}),
                        }
                    )
                    continue
                declared.append(candidate)
            provenance.append(
                {
                    "kind": "repository-manifest-declaration",
                    "path": manifest_path,
                    "status": "valid",
                }
            )
        elif manifest_status == "not_declared":
            provenance.append(
                {
                    "kind": "repository-manifest-declaration",
                    "path": manifest_path,
                    "status": "not_declared",
                }
            )
        elif manifest_status in {"invalid", "unavailable"}:
            reason = (
                "manifest-invalid"
                if manifest_status == "invalid"
                else "manifest-unavailable"
            )
            invalid_declarations.append(
                {
                    "source": "repository-manifest",
                    "path": manifest_path,
                    "status": manifest_status,
                    "reason": reason,
                    "diagnostics": [
                        item.as_dict() if hasattr(item, "as_dict") else str(item)
                        for item in manifest_diagnostics
                    ],
                }
            )
            diagnostics.append(
                _diagnostic(
                    f"manifest_{manifest_status}",
                    "$.manifest",
                    f"Repository manifest is {manifest_status}",
                )
            )
        else:
            diagnostics.append(
                _diagnostic(
                    "unknown_manifest_status",
                    "$.manifest.status",
                    "Manifest status is not recognized",
                )
            )
            invalid_declarations.append(
                {
                    "source": "repository-manifest",
                    "path": manifest_path,
                    "status": manifest_status,
                    "reason": "unknown-manifest-status",
                }
            )

    for index, item in enumerate(document_declarations):
        candidate, item_diagnostics = _normalize_authority_candidate(
            item,
            source="explicit-document",
            path_index=index,
            path_prefix="$.documentDeclarations",
        )
        if candidate is None:
            diagnostics.extend(item_diagnostics)
            invalid_declarations.append(
                {
                    "source": "explicit-document",
                    "index": index,
                    "reason": "structural-invalidity",
                    "codes": sorted({d.code for d in item_diagnostics}),
                }
            )
            continue
        declared.append(candidate)

    by_id: dict[str, list[tuple[Mapping[str, Any], Path | None]]] = {}
    for index, candidate in enumerate(declared):
        identifier = candidate["id"]
        path = candidate["path"]
        status, resolved_path = _classify_authority_content(root, path)
        if status == "missing":
            diagnostics.append(
                _diagnostic(
                    "authority_content_missing",
                    f"$.declaredAuthorities[{index}].path",
                    "Declared authority path does not exist",
                )
            )
            incomplete_evidence.append(
                {
                    "authorityId": identifier,
                    "reason": "authority-content-missing",
                    "path": path,
                }
            )
        elif status == "not-file":
            diagnostics.append(
                _diagnostic(
                    "authority_content_not_file",
                    f"$.declaredAuthorities[{index}].path",
                    "Declared authority path is not a regular file",
                )
            )
            incomplete_evidence.append(
                {
                    "authorityId": identifier,
                    "reason": "authority-content-not-file",
                    "path": path,
                }
            )
        by_id.setdefault(identifier, []).append((candidate, resolved_path))

    for identifier, entries in sorted(by_id.items()):
        candidates = [entry[0] for entry in entries]
        material = {
            (
                candidate.get("kind"),
                candidate.get("path"),
                tuple(candidate.get("scope", [])),
                candidate.get("readOnly"),
            )
            for candidate in candidates
        }
        if len(material) > 1:
            conflicts.append(
                {
                    "authorityId": identifier,
                    "kind": "conflicting-declarations",
                    "claims": sorted(
                        candidates,
                        key=lambda value: _canonical(value),
                    ),
                }
            )

    required = sorted(set(required_authority_ids))
    for index, identifier in enumerate(required):
        if identifier not in by_id:
            absent_declarations.append(
                {
                    "authorityId": identifier,
                    "reason": "required-authority-not-declared",
                }
            )
            diagnostics.append(
                _diagnostic(
                    "required_authority_not_declared",
                    f"$.requiredAuthorityIds[{index}]",
                    f"Required authority {identifier!r} has no declaration",
                )
            )

    resolved: list[Mapping[str, Any]] = []
    for identifier, entries in sorted(by_id.items()):
        if any(item.get("authorityId") == identifier for item in conflicts):
            continue
        candidate, file = entries[0]
        if file is None:
            continue
        path = candidate["path"]

        try:
            data = file.read_bytes()
        except OSError as error:
            diagnostics.append(
                _diagnostic(
                    "authority_content_unreadable",
                    f"$.declaredAuthorities[{identifier}].path",
                    "Declared authority content could not be read",
                )
            )
            incomplete_evidence.append(
                {
                    "authorityId": identifier,
                    "reason": "authority-content-unreadable",
                    "path": path,
                    "errorClass": type(error).__name__,
                }
            )
            continue

        observed = observations.get(path, {})
        observed_identity = observed.get("contentIdentity")
        actual_identity = "sha256:" + hashlib.sha256(data).hexdigest()
        if observed_identity is not None and observed_identity != actual_identity:
            conflicts.append(
                {
                    "authorityId": identifier,
                    "kind": "declaration-observation-conflict",
                    "declaredPath": path,
                    "observedContentIdentity": observed_identity,
                    "repositoryContentIdentity": actual_identity,
                }
            )
            continue

        resolved.append(
            {
                "id": identifier,
                "kind": candidate["kind"],
                "path": path,
                "scope": candidate["scope"],
                "readOnly": candidate["readOnly"],
                "source": candidate["source"],
                "primaryOwner": "durable-documentation",
                "contentIdentity": actual_identity,
                "implementationStatus": "not-established-by-authority-resolution",
                "currentStateStatus": "not-established-by-authority-resolution",
            }
        )
        provenance.append(
            {
                "kind": "observed-authority-content",
                "authorityId": identifier,
                "path": path,
                "contentIdentity": actual_identity,
            }
        )

    diagnostics.extend(
        _diagnostic(
            "authority_conflict",
            f"$.conflicts[{index}]",
            f"Authority {item.get('authorityId')!r} has unresolved conflicting claims",
        )
        for index, item in enumerate(conflicts)
    )

    sorted_provenance = sorted(provenance, key=lambda item: _canonical(item))
    identity_material = {
        "repository": repository_value,
        "normalizationVersion": AUTHORITY_NORMALIZATION_VERSION,
        "declaredAuthorities": sorted(declared, key=lambda item: _canonical(item)),
        "resolvedAuthorities": sorted(resolved, key=lambda item: item["id"]),
        "conflicts": sorted(conflicts, key=lambda item: _canonical(item)),
        "absentDeclarations": sorted(
            absent_declarations,
            key=lambda item: _canonical(item),
        ),
        "invalidDeclarations": sorted(
            invalid_declarations,
            key=lambda item: _canonical(item),
        ),
        "incompleteEvidence": sorted(
            incomplete_evidence,
            key=lambda item: _canonical(item),
        ),
        "provenance": sorted_provenance,
    }
    authority_set_id = _identity(
        "authority-set",
        AUTHORITY_NORMALIZATION_VERSION,
        identity_material,
    )

    value = {
        "schema": AUTHORITY_SET_SCHEMA,
        "normalizationVersion": AUTHORITY_NORMALIZATION_VERSION,
        "authoritySetId": authority_set_id,
        "repository": repository_value,
        "status": (
            "conflicted"
            if conflicts
            else "incomplete"
            if absent_declarations or invalid_declarations or incomplete_evidence
            else "resolved"
        ),
        "declaredAuthorities": sorted(declared, key=lambda item: _canonical(item)),
        "resolvedAuthorities": sorted(resolved, key=lambda item: item["id"]),
        "conflicts": sorted(conflicts, key=lambda item: _canonical(item)),
        "absentDeclarations": sorted(
            absent_declarations,
            key=lambda item: _canonical(item),
        ),
        "invalidDeclarations": sorted(
            invalid_declarations,
            key=lambda item: _canonical(item),
        ),
        "incompleteEvidence": sorted(
            incomplete_evidence,
            key=lambda item: _canonical(item),
        ),
        "provenance": sorted_provenance,
        "limitations": [
            "authority resolution does not establish implementation, current state, validation success, acceptance, or mutation authority"
        ],
    }

    ordered = _ordered_diagnostics(diagnostics)
    return ResolutionResult(value["status"], value, ordered)
