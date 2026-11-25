#!/usr/bin/env python3
"""Collect local Git state and optional hosted GitHub repository data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from collab.observations import (
    HostedQuery,
    HostedRepositoryCollector,
    observe_local_repository,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect repository observations as JSON. By default, the repository "
            "is resolved from the current directory with git rev-parse "
            "--show-toplevel."
        )
    )
    parser.add_argument(
        "-r",
        "--repo",
        type=Path,
        help="path inside the repository to observe (default: current directory)",
    )
    parser.add_argument(
        "-l",
        "--local-only",
        action="store_true",
        help="skip hosted GitHub collection",
    )
    parser.add_argument(
        "-k",
        "--query-kind",
        choices=("issue", "pr", "milestone", "branch", "commit"),
        help="kind of hosted object to collect in detail",
    )
    parser.add_argument(
        "-v",
        "--query-value",
        help="number, name, or SHA identifying the hosted object",
    )
    args = parser.parse_args()

    if bool(args.query_kind) != bool(args.query_value):
        parser.error("--query-kind and --query-value must be supplied together")
    if args.local_only and args.query_kind:
        parser.error("--query-kind and --query-value cannot be used with --local-only")

    return args


def main() -> None:
    args = parse_args()
    local = observe_local_repository(args.repo or Path.cwd())
    result = {"schemaVersion": "1.0", "local": local, "hosted": None}

    if not args.local_only:
        query = (
            HostedQuery(args.query_kind, args.query_value)
            if args.query_kind
            else None
        )
        result["hosted"] = HostedRepositoryCollector(local["repository"]).collect(query)

    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
