#!/usr/bin/env python3
"""Fail closed if immutable cluster CIDRs overlap each other or live routes."""

from __future__ import annotations

import argparse
import ipaddress
import json
import pathlib
import sys


def parse_named_network(value: str) -> tuple[str, ipaddress.IPv4Network]:
    try:
        name, raw = value.split("=", 1)
        network = ipaddress.ip_network(raw, strict=True)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError(f"invalid named CIDR: {value}") from error
    if not name or network.version != 4 or network.prefixlen == 0:
        raise argparse.ArgumentTypeError(f"invalid bounded IPv4 CIDR: {value}")
    return name, network


def parse_route(value: str) -> tuple[str, ipaddress.IPv4Network] | None:
    try:
        scope, raw = value.split("=", 1)
        if raw == "default":
            return None
        network = ipaddress.ip_network(raw, strict=False)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError(f"invalid scoped route: {value}") from error
    if network.version != 4 or network.prefixlen in (0, 32):
        return None
    return scope, network


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--planned", action="append", required=True, type=parse_named_network)
    parser.add_argument("--route", action="append", default=[], type=parse_route)
    parser.add_argument("--owned-route", action="append", default=[], type=parse_route)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plans: list[tuple[str, ipaddress.IPv4Network]] = args.planned
    routes = [route for route in args.route if route is not None]
    requested_owned_routes = {route for route in args.owned_route if route is not None}
    failures: list[str] = []
    plan_by_name = dict(plans)
    management_pods = plan_by_name.get("management-pods")
    owned_routes: set[tuple[str, ipaddress.IPv4Network]] = set()
    for scope, route in requested_owned_routes:
        if (
            management_pods is None
            or not scope.startswith("verda-mgmt-server-")
            or not route.subnet_of(management_pods)
        ):
            failures.append("an owned resume route is outside the management Cilium boundary")
        else:
            owned_routes.add((scope, route))
    for index, (left_name, left) in enumerate(plans):
        for right_name, right in plans[index + 1 :]:
            if left.overlaps(right):
                failures.append(f"planned ranges overlap: {left_name} and {right_name}")
        for scope, route in routes:
            if (scope, route) in owned_routes:
                continue
            if left.overlaps(route):
                failures.append(f"{left_name} overlaps an active {scope} route")
    report = {
        "schema_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "planned": {name: str(network) for name, network in plans},
        "observed_route_count": len(routes),
        "owned_route_count": len(owned_routes),
        "raw_observed_routes_recorded": False,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}", file=sys.stderr)
        return 1
    print("[PASS] Immutable management/workload CIDRs are pairwise disjoint and clear of live routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
