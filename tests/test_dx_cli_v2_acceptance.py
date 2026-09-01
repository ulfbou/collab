"""Acceptance tests for the required dx.py v2.0 corrections.

Run from the repository root:
    python3 -m pytest -q /path/to/test_dx_cli_v2_acceptance.py

Override the executable when needed:
    DX_UNDER_TEST=/absolute/path/to/dx.py python3 -m pytest -q ...
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


DX = Path(os.environ.get("DX_UNDER_TEST", Path.cwd() / "dx.py")).resolve()


def run_dx(*args: object, cwd: Path | None = None, input_bytes: bytes | None = None,
           env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(DX), *(str(arg) for arg in args)],
        cwd=cwd,
        input=input_bytes,
        env=merged,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def assert_ok(result: subprocess.CompletedProcess[bytes]) -> None:
    assert result.returncode == 0, (
        f"return code: {result.returncode}\n"
        f"stdout:\n{result.stdout.decode('utf-8', 'replace')}\n"
        f"stderr:\n{result.stderr.decode('utf-8', 'replace')}"
    )


def pack_to_bytes(source: Path, *extra: object) -> bytes:
    result = run_dx("pack", source, "-o", "-", "-q", *extra)
    assert_ok(result)
    assert result.stderr == b""
    assert result.stdout.startswith(b"%%DX ")
    return result.stdout


def unpack_bytes(carrier: bytes, destination: Path, *extra: object):
    return run_dx("unpack", "-", destination, *extra, input_bytes=carrier)


def make_carrier(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    for relative, data in files.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    carrier = tmp_path / "carrier.dx.txt"
    result = run_dx("pack", source, "-o", carrier, "-q")
    assert_ok(result)
    return source, carrier


def parse_json(result: subprocess.CompletedProcess[bytes]) -> dict:
    try:
        return json.loads(result.stdout)
    except Exception as exc:
        raise AssertionError(
            f"stdout is not valid JSON: {result.stdout!r}; stderr={result.stderr!r}"
        ) from exc


@pytest.fixture(scope="session", autouse=True)
def executable_exists():
    assert DX.is_file(), f"dx.py not found: {DX}"
    result = run_dx("--version")
    assert_ok(result)


# 1. Single-file packing.
def test_single_file_pack_uses_basename_and_round_trips(tmp_path: Path):
    source = tmp_path / "nested" / "one.txt"
    source.parent.mkdir()
    source.write_bytes(b"one")
    carrier = pack_to_bytes(source)
    listing = run_dx("inspect", "-", "--list", input_bytes=carrier)
    assert_ok(listing)
    assert listing.stdout.decode().splitlines() == ["one.txt"]
    destination = tmp_path / "destination"
    result = unpack_bytes(carrier, destination, "-q")
    assert_ok(result)
    assert (destination / "one.txt").read_bytes() == b"one"


def test_single_file_pack_with_root_preserves_root_relative_path(tmp_path: Path):
    root = tmp_path / "root"
    source = root / "nested" / "one.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"one")
    result = run_dx("pack", source, "--root", root, "-o", "-", "-q")
    assert_ok(result)
    listing = run_dx("inspect", "-", "--list", input_bytes=result.stdout)
    assert_ok(listing)
    assert listing.stdout.decode().splitlines() == ["nested/one.txt"]


# 2. Correct skip-binary reporting.
def test_skip_binary_omits_and_reports_each_binary(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "text.txt").write_bytes(b"text\n")
    (source / "invalid.dat").write_bytes(b"\xff")
    (source / "zero.dat").write_bytes(b"a\x00b")
    result = run_dx("pack", source, "-o", tmp_path / "out.dx", "-B")
    assert_ok(result)
    stderr = result.stderr.decode()
    assert "invalid.dat" in stderr
    assert "zero.dat" in stderr
    assert "Skipped non-UTF-8: 2 files" in stderr
    listing = run_dx("inspect", tmp_path / "out.dx", "--list")
    assert_ok(listing)
    assert listing.stdout.decode().splitlines() == ["text.txt"]


# 3. Truly global quiet/verbose options and conflict handling.
@pytest.mark.parametrize("args", [
    ("-q", "pack"),
    ("pack", "-q"),
    ("--quiet", "pack"),
    ("pack", "--quiet"),
])
def test_quiet_is_accepted_before_or_after_command(tmp_path: Path, args: tuple[str, ...]):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"a")
    command = [*args, source, "--dry-run"] if args[0].startswith("-") else [args[0], source, *args[1:], "--dry-run"]
    result = run_dx(*command)
    assert_ok(result)
    assert result.stdout == b""
    assert result.stderr == b""


@pytest.mark.parametrize("command", ["pack", "unpack", "apply", "inspect"])
def test_quiet_verbose_conflict_is_usage_error(tmp_path: Path, command: str):
    if command == "pack":
        source = tmp_path / "source"
        source.mkdir()
        (source / "a.txt").write_bytes(b"a")
        args = ("-q", command, source, "--dry-run", "-v")
    else:
        _, carrier = make_carrier(tmp_path, {"a.txt": b"a"})
        if command in {"unpack", "apply"}:
            args = ("-q", command, carrier, tmp_path / "destination", "--dry-run", "-v")
        else:
            args = ("-q", command, carrier, "--summary", "-v")
    result = run_dx(*args)
    assert result.returncode == 2
    assert b"mutually exclusive" in result.stderr


# 4, 5, 6. Exact byte preservation, line endings, and BOM consistency.
@pytest.mark.parametrize("payload", [
    b"",
    b"hello",
    b"hello\n",
    b"hello\n\n",
    b"\n",
    b"\n\n",
    b"hello\r\n",
    b"hello\r",
    b"one\r\ntwo\r\n",
    b"\xef\xbb\xbfhello\n",
    b"a\x00b",
    b"\xff\xfe\x00",
])
def test_pack_unpack_is_byte_exact(tmp_path: Path, payload: bytes):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.dat").write_bytes(payload)
    carrier = pack_to_bytes(source)
    destination = tmp_path / "destination"
    result = unpack_bytes(carrier, destination, "-q")
    assert_ok(result)
    assert (destination / "sample.dat").read_bytes() == payload


@pytest.mark.parametrize("payload", [b"hello\r\n", b"hello\r", b"\xef\xbb\xbfhello"])
def test_noncanonical_utf8_is_reported_as_binary_in_dry_run(tmp_path: Path, payload: bytes):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.txt").write_bytes(payload)
    result = run_dx("pack", source, "--dry-run", "--json")
    assert_ok(result)
    data = parse_json(result)
    assert data["binary_files"] == 1
    assert data["text_files"] == 0


# 7. --force and --existing semantics.
def test_existing_default_is_skip(tmp_path: Path):
    _, carrier = make_carrier(tmp_path, {"a.txt": b"carrier"})
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "a.txt").write_bytes(b"local")
    result = run_dx("unpack", carrier, destination, "-q")
    assert_ok(result)
    assert (destination / "a.txt").read_bytes() == b"local"


@pytest.mark.parametrize("args", [
    ("--force",),
    ("--existing", "overwrite"),
    ("--force", "--existing", "overwrite"),
])
def test_existing_overwrite_variants(tmp_path: Path, args: tuple[str, ...]):
    _, carrier = make_carrier(tmp_path, {"a.txt": b"carrier"})
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "a.txt").write_bytes(b"local")
    result = run_dx("unpack", carrier, destination, "-q", *args)
    assert_ok(result)
    assert (destination / "a.txt").read_bytes() == b"carrier"


@pytest.mark.parametrize("policy", ["skip", "fail"])
def test_force_conflicts_with_nonoverwrite_policy(tmp_path: Path, policy: str):
    _, carrier = make_carrier(tmp_path, {"a.txt": b"carrier"})
    result = run_dx("unpack", carrier, tmp_path / "destination", "--force", "--existing", policy)
    assert result.returncode == 2
    message = result.stderr.lower()
    assert b"conflict" in message or b"contradictory" in message


# 8. Dry-run fail policy models the real operation.
def test_dry_run_existing_fail_returns_write_conflict_without_mutation(tmp_path: Path):
    _, carrier = make_carrier(tmp_path, {"a.txt": b"carrier"})
    destination = tmp_path / "destination"
    destination.mkdir()
    target = destination / "a.txt"
    target.write_bytes(b"local")
    before = hashlib.sha256(target.read_bytes()).digest()
    result = run_dx("unpack", carrier, destination, "--dry-run", "--existing", "fail")
    assert result.returncode == 5
    assert hashlib.sha256(target.read_bytes()).digest() == before


# 9 and 10. --check-extra and comparison exit codes in text and JSON modes.
@pytest.mark.parametrize("json_mode", [False, True])
def test_compare_check_extra_reports_extra_and_returns_one(tmp_path: Path, json_mode: bool):
    source, carrier = make_carrier(tmp_path, {"a.txt": b"a"})
    comparison = tmp_path / "comparison"
    shutil.copytree(source, comparison)
    (comparison / "extra.txt").write_bytes(b"extra")
    args: list[object] = ["inspect", carrier, "--compare", comparison, "--check-extra"]
    if json_mode:
        args.append("--json")
    result = run_dx(*args)
    assert result.returncode == 1
    if json_mode:
        data = parse_json(result)
        assert {"path": "extra.txt", "status": "D"} in data["differences"]
    else:
        assert "D extra.txt" in result.stdout.decode().splitlines()


@pytest.mark.parametrize("json_mode", [False, True])
def test_compare_match_returns_zero(tmp_path: Path, json_mode: bool):
    source, carrier = make_carrier(tmp_path, {"a.txt": b"a"})
    args: list[object] = ["inspect", carrier, "--compare", source]
    if json_mode:
        args.append("--json")
    result = run_dx(*args)
    assert_ok(result)
    if json_mode:
        assert parse_json(result)["differences"] == []


# 11 and 12. Structured verification failure and accurate structural wording.
def test_verify_json_failure_is_machine_readable(tmp_path: Path):
    carrier = tmp_path / "invalid.dx"
    carrier.write_text("%%DX v2.0.0\n", encoding="utf-8")
    result = run_dx("inspect", carrier, "--verify", "--json")
    assert result.returncode in {3, 6}
    assert result.stdout.strip(), "verification failure must emit JSON on stdout"
    data = parse_json(result)
    assert data["schema_version"] == 1
    assert data["command"] == "inspect"
    assert data["mode"] == "verify"
    assert data["valid"] is False
    assert isinstance(data["errors"], list) and data["errors"]


def test_verify_text_describes_structural_not_hash_integrity(tmp_path: Path):
    _, carrier = make_carrier(tmp_path, {"empty.txt": b""})
    result = run_dx("inspect", carrier, "--verify")
    assert_ok(result)
    message = result.stderr.decode().lower()
    assert "structure" in message
    assert "parsed" in message
    assert "content hashes" in message
    assert "no stored" in message or "not available" in message or "were available" in message
    assert "files verified" not in message


# 13. Strict handling after %%END.
@pytest.mark.parametrize("tail", [
    "junk\n",
    "%%FILE path=\"later.txt\"\n    later\n%%ENDBLOCK\n",
    "%%END\n",
])
def test_nonempty_content_after_end_is_invalid(tmp_path: Path, tail: str):
    carrier = tmp_path / "invalid.dx"
    carrier.write_text(f"%%DX v2.0.0\n%%END\n{tail}", encoding="utf-8")
    result = run_dx("inspect", carrier, "--verify", "-q")
    assert result.returncode == 3


def test_final_newline_after_end_is_valid(tmp_path: Path):
    carrier = tmp_path / "valid.dx"
    carrier.write_text("%%DX v2.0.0\n%%END\n", encoding="utf-8")
    result = run_dx("inspect", carrier, "--verify", "-q")
    assert_ok(result)


# 14. Strict directive attribute validation.
@pytest.mark.parametrize("directive", [
    '%%FILE path="a.txt" unknown="x"',
    '%%FILE path="a.txt" readonly="maybe"',
    '%%FILE path="a.txt" escaped="maybe"',
    '%%FILE path="a.txt" encoding="rot13"',
    '%%FILE path="a.txt" encoding="base64" escaped="true"',
    '%%FILE path="a.txt" path="b.txt"',
    '%%FILE path="a.txt" readonly="true" readonly="false"',
])
def test_invalid_or_duplicate_file_attributes_are_rejected(tmp_path: Path, directive: str):
    carrier = tmp_path / "invalid.dx"
    body = "    YQ==\n" if 'encoding="base64"' in directive else "    a\n"
    carrier.write_text(
        f"%%DX v2.0.0\n{directive}\n{body}%%ENDBLOCK\n%%END\n",
        encoding="utf-8",
    )
    result = run_dx("inspect", carrier, "--verify", "-q")
    assert result.returncode == 3, result.stderr.decode()


# 15. Carrier paths map to invalid-carrier, not usage, errors.
def test_unsafe_carrier_path_returns_invalid_carrier(tmp_path: Path):
    carrier = tmp_path / "invalid.dx"
    carrier.write_text(
        '%%DX v2.0.0\n%%FILE path="../escape.txt"\n    x\n%%ENDBLOCK\n%%END\n',
        encoding="utf-8",
    )
    result = run_dx("inspect", carrier, "--verify", "-q")
    assert result.returncode == 3
    assert b"unsafe" in result.stderr.lower()


# 16. Git-ignore failures must not silently fail open.
def test_gitignore_excludes_ignored_untracked_but_keeps_tracked(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("ignored.txt\ntracked-ignored.txt\n", encoding="utf-8")
    (repo / "ignored.txt").write_bytes(b"ignored")
    (repo / "tracked-ignored.txt").write_bytes(b"tracked")
    subprocess.run(["git", "-C", str(repo), "add", "-f", "tracked-ignored.txt"], check=True)
    carrier = pack_to_bytes(repo)
    listing = run_dx("inspect", "-", "--list", input_bytes=carrier)
    assert_ok(listing)
    paths = listing.stdout.decode().splitlines()
    assert "ignored.txt" not in paths
    assert "tracked-ignored.txt" in paths


def test_git_command_failure_inside_repository_is_not_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import importlib.util

    module_name = "dx_git_failure_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        DX,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(repo)],
        check=True,
    )
    (repo / "a.txt").write_bytes(b"a")

    real_run = module.subprocess.run

    def failing_run(command, *args, **kwargs):
        if (
            isinstance(command, (list, tuple))
            and command
            and command[0] == "git"
        ):
            return subprocess.CompletedProcess(
                command,
                73,
                stdout=b"",
                stderr=b"simulated-git-failure",
            )
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(
        module.subprocess,
        "run",
        failing_run,
    )

    with pytest.raises(module.IOErrorDx) as failure:
        module.apply_gitignore_filter(
            repo,
            {"a.txt"},
        )

    assert "simulated-git-failure" in str(failure.value)


# 17. Filtering precedence and maintainable behavioral contract.
def test_filter_precedence_explicit_exclude_wins_over_include(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "keep.txt").write_bytes(b"keep")
    (source / "drop.txt").write_bytes(b"drop")
    result = run_dx("pack", source, "-i", "*.txt", "-I", "drop.txt", "-o", "-", "-q")
    assert_ok(result)
    listing = run_dx("inspect", "-", "--list", input_bytes=result.stdout)
    assert_ok(listing)
    assert listing.stdout.decode().splitlines() == ["keep.txt"]


def test_explicit_include_restores_gitignored_file(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("restore.txt\n", encoding="utf-8")
    (repo / "restore.txt").write_bytes(b"restore")
    result = run_dx("pack", repo, "-i", "restore.txt", "-o", "-", "-q")
    assert_ok(result)
    listing = run_dx("inspect", "-", "--list", input_bytes=result.stdout)
    assert_ok(listing)
    assert listing.stdout.decode().splitlines() == ["restore.txt"]


def test_protected_git_directory_cannot_be_reincluded(tmp_path: Path):
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "config").write_bytes(b"secret")
    (source / "a.txt").write_bytes(b"a")
    result = run_dx("pack", source, "-i", "**", "-o", "-", "-q")
    assert_ok(result)
    listing = run_dx("inspect", "-", "--list", input_bytes=result.stdout)
    assert_ok(listing)
    assert all(not path.startswith(".git/") for path in listing.stdout.decode().splitlines())


# 18. Dry-run counts must be real values, never placeholders.
def test_dry_run_has_numeric_exclusion_counts_without_placeholders(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repo / "ignored.txt").write_bytes(b"ignored")
    (repo / "excluded.txt").write_bytes(b"excluded")
    (repo / "kept.txt").write_bytes(b"kept")
    result = run_dx("pack", repo, "--dry-run", "-I", "excluded.txt")
    assert_ok(result)
    text = result.stderr.decode()
    assert "(not computed)" not in text
    assert "Git-ignored files excluded: 1" in text
    assert "Explicitly excluded files: 1" in text


# 19. Pack dry-run may not create the default DX output directory.
def test_pack_dry_run_does_not_create_device_output_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"a")
    home = tmp_path / "home"
    downloads = home / "storage" / "downloads"
    downloads.mkdir(parents=True)
    env = {"HOME": str(home), "DX_DEVICE_DIR": str(downloads / "DX")}
    result = run_dx("pack", source, "--dry-run", env=env)
    assert_ok(result)
    assert not (downloads / "DX").exists()


# 20. Atomic extraction failure cleanup and symlink protection.
def test_overwrite_refuses_destination_symlink(tmp_path: Path):
    _, carrier = make_carrier(tmp_path, {"a.txt": b"carrier"})
    destination = tmp_path / "destination"
    destination.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    (destination / "a.txt").symlink_to(outside)
    result = run_dx("unpack", carrier, destination, "--existing", "overwrite")
    assert result.returncode == 5
    assert outside.read_bytes() == b"outside"
    assert (destination / "a.txt").is_symlink()


def test_normal_atomic_extract_leaves_no_temp_files(tmp_path: Path):
    _, carrier = make_carrier(tmp_path, {"nested/a.txt": b"carrier"})
    destination = tmp_path / "destination"
    result = run_dx("unpack", carrier, destination, "-q")
    assert_ok(result)
    assert (destination / "nested" / "a.txt").read_bytes() == b"carrier"
    assert not list(destination.rglob("*.tmp.*"))


# 21. Command-specific error usage.
@pytest.mark.parametrize("args, expected", [
    (("pack", "/definitely/missing/source"), "dx.py pack [SOURCE] [OPTIONS]"),
    (("unpack", "/definitely/missing/carrier"), "dx.py unpack CARRIER [DESTINATION] [OPTIONS]"),
    (("apply", "/definitely/missing/carrier"), "dx.py apply CARRIER [DESTINATION] [OPTIONS]"),
    (("inspect", "/definitely/missing/carrier"), "dx.py inspect CARRIER [OPTIONS]"),
])
def test_error_usage_is_command_specific(args: tuple[str, ...], expected: str):
    result = run_dx(*args)
    assert result.returncode != 0
    assert expected in result.stderr.decode()


# 22. Help handling must not use private argparse APIs.
def test_source_does_not_use_private_argparse_help_introspection():
    tree = ast.parse(DX.read_text(encoding="utf-8"), filename=str(DX))
    forbidden_attributes = {"_actions", "_subparsers", "_SubParsersAction"}
    found = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
    }
    assert not found, f"private argparse APIs remain: {sorted(found)}"


def test_command_help_is_complete_and_available():
    for command in ("pack", "unpack", "apply", "inspect"):
        result = run_dx(command, "-h")
        assert_ok(result)
        text = result.stdout.decode()
        assert "usage:" in text.lower()
        assert command in text.lower()
