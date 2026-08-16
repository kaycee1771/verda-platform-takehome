#!/usr/bin/env python3
"""Verify every remote GitHub Action reference against versions.lock.yaml."""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=ROOT / "versions.lock.yaml")
    parser.add_argument("--workflows", type=Path, default=ROOT / ".github" / "workflows")
    return parser.parse_args()


def action_references(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "uses" and isinstance(child, str):
                yield child
            else:
                yield from action_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from action_references(child)


def workflow_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted((*path.rglob("*.yml"), *path.rglob("*.yaml")))


def main() -> int:
    args = arguments()
    failures: list[str] = []

    lock = yaml.safe_load(args.lock.read_text(encoding="utf-8"))
    locked_actions = lock.get("ci_actions")
    if not isinstance(locked_actions, dict) or not locked_actions:
        print("[FAIL] versions lock has no ci_actions mapping")
        return 1

    by_repository: dict[str, dict[str, str]] = {}
    for name, item in locked_actions.items():
        if not isinstance(item, dict):
            failures.append(f"ci_actions.{name}: expected a mapping")
            continue
        repository = item.get("uses")
        release = item.get("release")
        sha = item.get("sha")
        if not isinstance(repository, str) or not repository:
            failures.append(f"ci_actions.{name}: missing uses repository")
            continue
        if repository in by_repository:
            failures.append(f"ci_actions.{name}: duplicate lock for {repository}")
            continue
        if not isinstance(release, str) or not release:
            failures.append(f"ci_actions.{name}: missing release")
        if not isinstance(sha, str) or FULL_SHA.fullmatch(sha) is None:
            failures.append(f"ci_actions.{name}: sha must be 40 lowercase hexadecimal characters")
            continue
        by_repository[repository] = {"name": str(name), "release": str(release), "sha": sha}

    files = workflow_files(args.workflows)
    if not files:
        failures.append(f"no workflow files found under {args.workflows}")

    used: set[str] = set()
    reference_count = 0
    for path in files:
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            failures.append(f"{path}: invalid YAML: {error}")
            continue
        for reference in action_references(workflow):
            if reference.startswith(("./", "docker://")):
                continue
            reference_count += 1
            if "@" not in reference:
                failures.append(f"{path}: remote action has no ref: {reference}")
                continue
            repository, ref = reference.rsplit("@", 1)
            item = by_repository.get(repository)
            if item is None:
                failures.append(f"{path}: {repository} is not declared in ci_actions")
                continue
            used.add(repository)
            if FULL_SHA.fullmatch(ref) is None:
                failures.append(f"{path}: {repository} uses floating/non-SHA ref {ref!r}")
            elif ref != item["sha"]:
                failures.append(
                    f"{path}: {repository}@{ref} differs from locked {item['sha']}"
                )

    for repository, item in by_repository.items():
        if repository not in used:
            failures.append(
                f"ci_actions.{item['name']}: {repository}@{item['sha']} is locked but unused"
            )

    if failures:
        print("[FAIL] GitHub Action lock violations:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(
        f"[PASS] {reference_count} GitHub Action reference(s) match "
        f"{len(by_repository)} immutable lock entries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
