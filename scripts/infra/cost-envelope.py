#!/usr/bin/env python3
"""Calculate and enforce the bounded seven-day Stage A cost envelope."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys


def money(value: float) -> float:
    return round(value + 1e-12, 5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--plan-summary", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    plan = json.loads(args.plan_summary.read_text(encoding="utf-8"))
    selection = plan["selection"]
    if plan["mode"] == "initial":
        node_count = plan["resource_counts"].get("verda_instance", 0)
        data_volume_count = plan["resource_counts"].get("verda_volume", 0)
    else:
        node_count = config["topology"]["node_count"]
        data_volume_count = config["topology"]["data_volume_count"]

    topology = config["topology"]
    if node_count != topology["node_count"] or data_volume_count != topology["data_volume_count"]:
        print("[FAIL] Planned topology does not match the cost contract.", file=sys.stderr)
        return 1
    if selection["root_volume_size_gib"] != topology["root_volume_size_gib"]:
        print("[FAIL] Planned root volume does not match the cost contract.", file=sys.stderr)
        return 1
    if selection["data_volume_size_gib"] != topology["data_volume_size_gib"]:
        print("[FAIL] Planned data volume does not match the cost contract.", file=sys.stderr)
        return 1

    rates = config["rates_usd"]
    compute_hourly = node_count * rates["cpu_4v_16g_hour"]
    storage_gib = node_count * topology["root_volume_size_gib"] + (
        data_volume_count * topology["data_volume_size_gib"]
    )
    storage_hourly = storage_gib * rates["nvme_gib_month"] / rates["billing_hours_month"]
    hourly = compute_hourly + storage_hourly
    duration_hours = config["duration_hours"]
    projected = hourly * duration_hours
    with_contingency = projected * (1 + config["contingency_percent"] / 100)
    passed = with_contingency <= config["hard_budget_usd"]

    report = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_as_of": config["as_of"],
        "currency": "USD",
        "node_count": node_count,
        "root_volume_gib_total": node_count * topology["root_volume_size_gib"],
        "data_volume_gib_total": data_volume_count * topology["data_volume_size_gib"],
        "compute_hourly": money(compute_hourly),
        "storage_hourly": money(storage_hourly),
        "total_hourly": money(hourly),
        "total_daily": money(hourly * 24),
        "duration_hours": duration_hours,
        "projected_duration_cost": money(projected),
        "contingency_percent": config["contingency_percent"],
        "projected_with_contingency": money(with_contingency),
        "hard_budget_usd": config["hard_budget_usd"],
        "verified_balance_usd": config["verified_balance_usd"],
        "budget_gate": "PASS" if passed else "FAIL",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not passed:
        print("[FAIL] Seven-day Stage A cost exceeds the hard budget.", file=sys.stderr)
        return 1
    print(
        "[PASS] Cost envelope: "
        f"hourly=${report['total_hourly']:.5f} "
        f"seven-day-plus-contingency=${report['projected_with_contingency']:.5f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
