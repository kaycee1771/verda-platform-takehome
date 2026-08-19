#!/usr/bin/env python3
"""Fail-closed scalar reducers for the Phase 4 Hubble acceptance boundary."""

from __future__ import annotations

import argparse
import math
import re
import sys


LOST_EVENT_SOURCES = {
    "hubble_ring_buffer",
    "observer_events_queue",
    "perf_event_ring_buffer",
}
RELAY_STATES = {
    "CONNECTING",
    "IDLE",
    "NIL_CONNECTION",
    "READY",
    "SHUTDOWN",
    "TRANSIENT_FAILURE",
}
SAMPLE_RE = re.compile(
    r"^[A-Za-z_:][A-Za-z0-9_:]*\{(?P<labels>[^}]*)\}\s+"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$"
)


class MetricsGateError(RuntimeError):
    """A metric surface violated the pinned acceptance contract."""


def _sample(line: str) -> tuple[str, str, float] | None:
    if line.startswith("#") or not line.strip():
        return None
    match = SAMPLE_RE.fullmatch(line.strip())
    if not match:
        return None
    name = line.split("{", 1)[0]
    value = float(match.group("value"))
    if not math.isfinite(value) or value < 0:
        raise MetricsGateError("metric value is not a finite non-negative number")
    return name, match.group("labels"), value


def _label(labels: str, key: str) -> str:
    match = re.search(rf'(?:^|,){re.escape(key)}="([^"\\]*)"(?:,|$)', labels)
    if not match:
        raise MetricsGateError("required metric label is absent or malformed")
    return match.group(1)


def parse_lost_events(metrics: str) -> dict[str, float]:
    values = {source: 0.0 for source in LOST_EVENT_SOURCES}
    seen: set[str] = set()
    for line in metrics.splitlines():
        if not line.startswith("hubble_lost_events_total{"):
            continue
        sample = _sample(line)
        if sample is None or sample[0] != "hubble_lost_events_total":
            raise MetricsGateError("lost-event metric is malformed")
        source = _label(sample[1], "source")
        if source not in LOST_EVENT_SOURCES:
            raise MetricsGateError("lost-event source is not recognized by the pinned version")
        if source in seen:
            raise MetricsGateError("lost-event source is duplicated")
        seen.add(source)
        values[source] = sample[2]
    return values


def render_snapshot(agent_key: str, values: dict[str, float]) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", agent_key):
        raise MetricsGateError("agent key is malformed")
    return "\n".join(
        f"{agent_key}|{source}\t{values[source]}" for source in sorted(LOST_EVENT_SOURCES)
    )


def parse_snapshot(snapshot: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in snapshot.splitlines():
        try:
            key, raw_value = line.split("\t", 1)
            agent, source = key.rsplit("|", 1)
            value = float(raw_value)
        except (ValueError, TypeError) as error:
            raise MetricsGateError("lost-event snapshot is malformed") from error
        if (
            not agent
            or source not in LOST_EVENT_SOURCES
            or key in values
            or not math.isfinite(value)
            or value < 0
        ):
            raise MetricsGateError("lost-event snapshot violates the canonical schema")
        values[key] = value
    return values


def positive_delta_count(before: str, after: str, expected_series: int) -> int:
    before_values = parse_snapshot(before)
    after_values = parse_snapshot(after)
    if len(before_values) != expected_series or set(before_values) != set(after_values):
        raise MetricsGateError("Hubble agent/source series changed during validation")
    deltas = {
        key: after_values[key] - before_values[key] for key in before_values
    }
    if any(value < 0 for value in deltas.values()):
        raise MetricsGateError("a Hubble lost-event counter reset during validation")
    positive_by_source = {source: 0.0 for source in LOST_EVENT_SOURCES}
    for key, value in deltas.items():
        if value > 0:
            source = key.rsplit("|", 1)[1]
            positive_by_source[source] += value
    positive = sum(value > 0 for value in deltas.values())
    if positive:
        aggregates = " ".join(
            f"{source}={positive_by_source[source]:.15g}"
            for source in sorted(LOST_EVENT_SOURCES)
            if positive_by_source[source] > 0
        )
        raise MetricsGateError(
            "Hubble lost-event counters increased during validation; "
            f"positive-delta-by-source {aggregates}"
        )
    return positive


def parse_relay_peers(metrics: str) -> tuple[int, int]:
    values: dict[str, float] = {}
    for line in metrics.splitlines():
        if not line.startswith("hubble_relay_pool_peer_connection_status{"):
            continue
        sample = _sample(line)
        if sample is None or sample[0] != "hubble_relay_pool_peer_connection_status":
            raise MetricsGateError("Relay peer metric is malformed")
        status = _label(sample[1], "status")
        if status not in RELAY_STATES or status in values:
            raise MetricsGateError("Relay peer state is unknown or duplicated")
        values[status] = sample[2]
    if set(values) != RELAY_STATES:
        raise MetricsGateError("Relay peer state metrics are incomplete")
    healthy = values["IDLE"] + values["READY"]
    unavailable = sum(values[state] for state in RELAY_STATES - {"IDLE", "READY"})
    if healthy != 3 or unavailable != 0:
        raise MetricsGateError("Relay does not report three healthy peers")
    return int(healthy), int(unavailable)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = subparsers.add_parser("lost-snapshot", add_help=False)
    snapshot_parser.add_argument("--agent-key", required=True)
    delta_parser = subparsers.add_parser("lost-delta", add_help=False)
    delta_parser.add_argument("--before", required=True)
    delta_parser.add_argument("--after", required=True)
    delta_parser.add_argument("--expected-series", type=int, required=True)
    subparsers.add_parser("relay-peers", add_help=False)
    args = parser.parse_args()
    try:
        if args.command == "lost-snapshot":
            print(render_snapshot(args.agent_key, parse_lost_events(sys.stdin.read())))
        elif args.command == "lost-delta":
            print(positive_delta_count(args.before, args.after, args.expected_series))
        else:
            healthy, unavailable = parse_relay_peers(sys.stdin.read())
            print(f"healthy={healthy} unavailable={unavailable}")
    except MetricsGateError as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
