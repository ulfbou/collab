"""Shared GitHub CLI transport with process-local request reuse."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .process import CommandError, CommandResult, run_command


class GitHubError(RuntimeError):
    """Actionable GitHub transport or response failure."""


@dataclass(frozen=True, order=True)
class RequestIdentity:
    operation: str
    arguments: tuple[str, ...]
    cwd: str

    @property
    def digest(self) -> str:
        payload = json.dumps(
            [self.operation, list(self.arguments), self.cwd],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ResponseEnvelope:
    identity: RequestIdentity
    value: Any
    complete: bool
    pages: int
    elapsed_milliseconds: int


@dataclass
class _Flight:
    condition: threading.Condition
    done: bool = False
    value: ResponseEnvelope | None = None
    error: BaseException | None = None


def discover_git_bash() -> str:
    override = os.environ.get("COLLAB_BASH_BIN")
    if override:
        if Path(override).is_file():
            return override
        raise GitHubError(f"COLLAB_BASH_BIN does not identify a file: {override}")
    candidates: list[Path] = []
    git = shutil.which("git.exe") or shutil.which("git")
    if git:
        parent = Path(git).resolve().parent.parent
        candidates.extend((parent / "bin" / "bash.exe", parent / "usr" / "bin" / "bash.exe"))
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.extend((Path(program_files) / "Git" / "bin" / "bash.exe", Path(program_files) / "Git" / "usr" / "bin" / "bash.exe"))
    candidates.extend((Path(r"C:\Program Files\Git\bin\bash.exe"), Path(r"C:\Program Files\Git\usr\bin\bash.exe")))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise GitHubError("Git Bash could not be located; set COLLAB_BASH_BIN to bash.exe")


def github_command() -> tuple[str, ...]:
    override = os.environ.get("COLLAB_GH_BIN")
    return (discover_git_bash(), override) if override else ("gh",)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _freeze(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_freeze(item) for item in value]
    return value


class GitHubClient:
    """One process-local GitHub transport, cache, and single-flight boundary."""

    def __init__(self, *, cwd: Path | None = None, command: Sequence[str] | None = None):
        self.cwd = (cwd or Path.cwd()).resolve()
        self.command = tuple(command or github_command())
        self._lock = threading.RLock()
        self._auth: dict[tuple[str, ...], bool] = {}
        self._cache: dict[RequestIdentity, ResponseEnvelope] = {}
        self._flights: dict[RequestIdentity, _Flight] = {}

    def identity(self, arguments: Sequence[str], *, operation: str = "json") -> RequestIdentity:
        normalized = tuple(str(item) for item in arguments)
        return RequestIdentity(operation, normalized, str(self.cwd))

    def authenticate(self) -> None:
        key = self.command
        with self._lock:
            if self._auth.get(key):
                return
            try:
                run_command([*self.command, "auth", "status"], cwd=self.cwd)
            except CommandError as exc:
                raise GitHubError("GitHub CLI authentication failed; run `gh auth login`") from exc
            self._auth[key] = True

    def request_json(self, arguments: Sequence[str], *, cache: bool = True) -> ResponseEnvelope:
        if not cache:
            raise GitHubError("request_json accepts read-only requests only; use mutate_json for mutations")
        self.authenticate()
        identity = self.identity(arguments)
        with self._lock:
            cached = self._cache.get(identity)
            if cached is not None:
                return self._copy(cached)
            flight = self._flights.get(identity)
            if flight is None:
                flight = _Flight(threading.Condition(self._lock))
                self._flights[identity] = flight
                leader = True
            else:
                leader = False
            if not leader:
                while not flight.done:
                    flight.condition.wait()
                if flight.error is not None:
                    raise GitHubError(str(flight.error)) from flight.error
                assert flight.value is not None
                return self._copy(flight.value)
        try:
            envelope = self._execute_json(identity, arguments)
        except BaseException as exc:
            with self._lock:
                flight.error = exc; flight.done = True
                self._flights.pop(identity, None); flight.condition.notify_all()
            raise
        with self._lock:
            self._cache[identity] = envelope
            flight.value = envelope; flight.done = True
            self._flights.pop(identity, None); flight.condition.notify_all()
        return self._copy(envelope)

    def mutate_json(self, arguments: Sequence[str]) -> ResponseEnvelope:
        self.authenticate()
        identity = self.identity(arguments, operation="mutation")
        return self._copy(self._execute_json(identity, arguments))

    def rest(self, endpoint: str, *, fields: Mapping[str, str] | None = None, paginate: bool = False) -> ResponseEnvelope:
        args = ["api", "--method", "GET", "-H", "X-GitHub-Api-Version: 2022-11-28"]
        if paginate: args.append("--paginate")
        args.append(endpoint)
        for key, value in sorted((fields or {}).items()): args.extend(("-f", f"{key}={value}"))
        envelope = self.request_json(args)
        return ResponseEnvelope(envelope.identity, envelope.value, True, 1, envelope.elapsed_milliseconds)

    def graphql(self, query: str, *, variables: Mapping[str, str] | None = None) -> ResponseEnvelope:
        args = ["api", "graphql", "-f", f"query={query}"]
        for key, value in sorted((variables or {}).items()): args.extend(("-F", f"{key}={value}"))
        return self.request_json(args)

    def _execute_json(self, identity: RequestIdentity, arguments: Sequence[str]) -> ResponseEnvelope:
        try:
            result = run_command([*self.command, *arguments], cwd=self.cwd)
        except CommandError as exc:
            raise GitHubError(f"GitHub command failed for request {identity.digest}: {exc}") from exc
        try:
            value = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubError(f"GitHub returned invalid JSON for request {identity.digest}") from exc
        return ResponseEnvelope(identity, _freeze(value), True, 1, result.elapsed_milliseconds)

    @staticmethod
    def _copy(envelope: ResponseEnvelope) -> ResponseEnvelope:
        return ResponseEnvelope(envelope.identity, copy.deepcopy(envelope.value), envelope.complete, envelope.pages, envelope.elapsed_milliseconds)
