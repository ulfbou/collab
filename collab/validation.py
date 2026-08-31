"""Small, dependency-free validation primitives shared by Collab tools."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Collection, Mapping

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_PLACEHOLDER = re.compile(r"(?i)\b(?:TODO|TBD|PLACEHOLDER|FIXME)\b")

class ValidationError(ValueError):
    pass

def require_exact_keys(value: Mapping[str, object], expected: Collection[str], location: str) -> None:
    if set(value) != set(expected):
        raise ValidationError(f"{location} fields differ; expected {sorted(expected)}, got {sorted(value)}")

def require_nonempty_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{location} must be non-empty text")
    return value

def require_string_list(value: object, location: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValidationError(f"{location} must be an array of non-empty strings")
    if not allow_empty and not value:
        raise ValidationError(f"{location} must not be empty")
    return value

def require_positive_integer(value: object, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValidationError(f"{location} must be a positive integer")
    return value

def require_non_negative_integer(value: object, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValidationError(f"{location} must be a non-negative integer")
    return value

def require_sha1(value: object, location: str) -> str:
    if not isinstance(value, str) or not _SHA1.fullmatch(value):
        raise ValidationError(f"{location} must be a 40-character lowercase SHA")
    return value

def require_repository_slug(value: object, location: str) -> str:
    if not isinstance(value, str) or not _REPOSITORY.fullmatch(value):
        raise ValidationError(f"{location} must use OWNER/REPO form")
    return value

def require_safe_relative_path(value: object, location: str = "path") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{location} must be text")
    normalized=value.replace('\\','/')
    parts=normalized.split('/')
    if (not normalized or normalized.startswith('/') or '"' in normalized or '\0' in normalized or '\n' in normalized or '\r' in normalized or any(part in ('','.','..') for part in parts)):
        raise ValidationError(f"unsafe {location}: {value!r}")
    return PurePosixPath(normalized).as_posix()

def reject_placeholder_text(value: str, location: str) -> None:
    if _PLACEHOLDER.search(value):
        raise ValidationError(f"{location} contains placeholder text")
