#!/usr/bin/env python3
"""Fail-closed static checks for the Phase 4 management-cluster boundary."""

from __future__ import annotations

import importlib.util
import gzip
import io
import json
import pathlib
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


def executable_temp_directory() -> tempfile.TemporaryDirectory[str]:
    """Create fake-CLI fixtures outside the quality container's noexec /tmp."""
    root = ROOT / ".local" / "test-tmp"
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=root)


def cilium_connectivity_commands(script: str) -> list[str]:
    """Return complete shell commands that directly invoke Cilium connectivity."""
    lines = script.splitlines()
    commands: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if '"${cilium}" connectivity test' not in line:
            index += 1
            continue
        command = [line.strip()]
        while command[-1].endswith("\\"):
            index += 1
            if index >= len(lines):
                break
            command.append(lines[index].strip())
        commands.append(" ".join(part.removesuffix("\\").strip() for part in command))
        index += 1
    return commands


class Phase4ContractTests(unittest.TestCase):
    def test_exact_artifacts_and_component_versions_are_pinned(self) -> None:
        lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text())
        rke2 = lock["rke2"]
        self.assertEqual(rke2["version"], "v1.35.7+rke2r1")
        self.assertEqual(rke2["kubernetes_version"], "v1.35.7")
        self.assertEqual(rke2["cilium_version"], "v1.19.6")
        self.assertEqual(rke2["traefik_version"], "v3.7.8")
        for key in (
            "installer_sha256",
            "linux_amd64_tarball_sha256",
            "images_core_linux_amd64_sha256",
            "images_cilium_linux_amd64_sha256",
            "cilium_chart_sha256",
            "traefik_chart_sha256",
        ):
            self.assertRegex(rke2[key], r"^[0-9a-f]{64}$")
        self.assertNotIn("stable", rke2["linux_amd64_tarball"])
        self.assertIn("rke2-images-core.linux-amd64.tar.zst", rke2["images_core_linux_amd64"])
        self.assertIn("rke2-images-cilium.linux-amd64.tar.zst", rke2["images_cilium_linux_amd64"])

    def test_immutable_cidrs_and_critical_values_are_explicit(self) -> None:
        values = yaml.safe_load(
            (ROOT / "infra/ansible/inventories/group_vars/management_servers.yml").read_text()
        )
        self.assertEqual(values["phase4_management_pod_cidr"], "10.42.0.0/16")
        self.assertEqual(values["phase4_management_service_cidr"], "10.43.0.0/16")
        self.assertEqual(values["phase4_workload_pod_cidr"], "10.44.0.0/16")
        self.assertEqual(values["phase4_workload_service_cidr"], "10.45.0.0/16")
        self.assertEqual(values["phase4_management_cluster_dns"], "10.43.0.10")
        self.assertEqual(values["phase4_cilium_mtu"], 1370)

    def test_token_and_s3_credentials_never_enter_config_or_cli_arguments(self) -> None:
        role = (ROOT / "infra/ansible/roles/rke2_server/tasks/main.yml").read_text()
        common = (
            ROOT / "infra/ansible/roles/rke2_server/templates/rke2-common.yaml.j2"
        ).read_text()
        backup = (ROOT / "infra/ansible/roles/etcd_backup/tasks/main.yml").read_text()
        self.assertIn("token-file:", common)
        self.assertNotRegex(common, r"(?m)^token:")
        self.assertIn("no_log: true", role)
        self.assertIn("stdin:", backup)
        for forbidden in ("--s3-access-key", "--s3-secret-key", "etcd-s3-access-key:"):
            self.assertNotIn(forbidden, common)

    def test_prepare_path_does_not_start_rke2(self) -> None:
        role = (ROOT / "infra/ansible/roles/rke2_server/tasks/main.yml").read_text()
        start_block = role.split("- name: Start or retain the selected RKE2 server", 1)[1]
        self.assertIn("phase4_action == 'start'", start_block)
        prepare_prefix = role.split("- name: Start or retain the selected RKE2 server", 1)[0]
        self.assertNotIn("state: started", prepare_prefix)
        self.assertIn("Refuse an online CIS sysctl replacement", role)
        self.assertIn("Stage the exact official RKE2 air-gap image archives", role)
        self.assertIn("/var/lib/rancher/rke2/agent/images/.cache.json", role)

    def test_runtime_umask_preserves_non_root_static_pod_traversal(self) -> None:
        role = (ROOT / "infra/ansible/roles/rke2_server/tasks/main.yml").read_text()
        override = role.split("[Service]", 1)[1].split("dest:", 1)[0]
        self.assertIn("UMask=0022", override)
        self.assertNotIn("UMask=0027", override)
        host_parents = role.split("- name: Preserve root-only host data path parents", 1)[
            1
        ].split("- name: Create the restricted RKE2 administrator group", 1)[0]
        self.assertIn("group: root", host_parents)
        self.assertIn('mode: "0750"', host_parents)

    def test_staged_start_allows_activation_but_full_verify_requires_active(self) -> None:
        role = (ROOT / "infra/ansible/roles/rke2_server/tasks/main.yml").read_text()
        lifecycle = role.split("- name: Read RKE2 service activation", 1)[1].split(
            "- name: Compute the sanitized common-config parity hash", 1
        )[0]
        self.assertIn("['activating', 'active']", lifecycle)
        self.assertIn("phase4_action == 'verify'", lifecycle)
        self.assertIn("stdout == 'active'", lifecycle)

    def test_etcdctl_runs_from_the_pinned_hardened_etcd_container(self) -> None:
        role = (ROOT / "infra/ansible/roles/rke2_server/tasks/main.yml").read_text()
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        wrapper = (ROOT / "scripts/cluster/etcdctl-local.sh").read_text()
        self.assertIn("scripts/cluster/etcdctl-local.sh", role)
        self.assertIn("--config \"${cri_config}\" ps --name etcd --quiet", wrapper)
        self.assertIn("Expected exactly one running local etcd container", wrapper)
        self.assertIn("/usr/local/bin/etcdctl", wrapper)
        self.assertNotIn("/var/lib/rancher/rke2/bin/etcdctl", controller)
        self.assertIn("tls/etcd/server-client.crt", controller)
        self.assertNotIn("tls/etcd/client.crt", controller)

    def test_management_verifier_asserts_etcd_leader_disk_and_audit_behavior(self) -> None:
        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        self.assertIn("endpoint status --cluster --write-out=json", verifier)
        self.assertIn('leader-count=1', verifier)
        self.assertIn('etcd_disk_{}_bucket', verifier)
        self.assertIn('"backend_commit_duration_seconds": 0.032', verifier)
        self.assertIn('"wal_fsync_duration_seconds": 0.016', verifier)
        self.assertIn('event.get("requestURI")=="/version"', verifier)
        self.assertIn("hubble-relay-metrics:9966", verifier)
        self.assertIn("service/hubble-relay 4245:80", verifier)
        self.assertIn("--hubble=false --test-namespace cilium-test --cleanup", verifier)
        self.assertIn("--hubble=true", verifier)
        self.assertIn("--hubble-server 127.0.0.1:4245", verifier)
        self.assertIn("--flow-validation strict", verifier)
        self.assertIn("trap cleanup_connectivity_best_effort EXIT", verifier)

    def test_cilium_acceptance_has_unfiltered_functional_and_anchored_strict_lanes(
        self,
    ) -> None:
        """Keep complete functional coverage separate from bounded strict flow proof.

        Cilium CLI v0.19.7 applies --test regexes to the exact
        ``test/scenario`` name below. The strict lane is intentionally a minimal
        direct pod-flow canary; the Hubble-disabled unfiltered lane remains the
        source of complete official functional coverage without patching or
        rebuilding the CLI. This separation keeps the lost-event interval scoped
        exactly to the strict Hubble canary.
        """
        lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text())
        self.assertEqual(lock["future_phase_clis"]["cilium"]["version"], "v0.19.7")

        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        commands = [
            command
            for command in cilium_connectivity_commands(verifier)
            if "--cleanup" not in command
        ]
        self.assertEqual(
            len(commands),
            2,
            "expected exactly one functional lane and one strict-flow lane",
        )

        functional = [
            command
            for command in commands
            if "--hubble=false" in command and "--flow-validation disabled" in command
        ]
        strict = [
            command
            for command in commands
            if "--hubble=true" in command and "--flow-validation strict" in command
        ]
        self.assertEqual(len(functional), 1)
        self.assertEqual(len(strict), 1)
        functional_lane = functional[0]
        strict_lane = strict[0]

        self.assertNotRegex(functional_lane, r"(?:^|\s)--test(?:=|\s)")
        self.assertNotIn("--single-node", functional_lane)
        self.assertNotIn("--hubble=true", functional_lane)
        self.assertNotIn("--hubble-server", functional_lane)
        self.assertEqual(functional_lane.count("--test-concurrency 1"), 1)
        self.assertNotIn("--test-concurrency 2", functional_lane)

        self.assertRegex(strict_lane, r"(?:^|\s)--test(?:=|\s)")
        self.assertIn("^no-policies/pod-to-pod$", strict_lane)
        self.assertEqual(len(re.findall(r"(?:^|\s)--test(?:=|\s)", strict_lane)), 1)
        self.assertIn("--hubble=true", strict_lane)
        self.assertIn("--hubble-server 127.0.0.1:4245", strict_lane)
        self.assertEqual(strict_lane.count("--test-concurrency 1"), 1)

        for command in commands:
            self.assertNotIn("--exit-zero-on-failure", command)
            self.assertNotIn("--print-flows", command)
            self.assertNotIn("--all-flows", command)
            self.assertNotIn("|| true", command)

        before_position = verifier.index("lost_events_before_by_agent_source=")
        functional_position = verifier.index("--flow-validation disabled")
        strict_position = verifier.index("--flow-validation strict")
        after_position = verifier.index("lost_events_after_by_agent_source=")
        self.assertLess(functional_position, before_position)
        self.assertLess(before_position, strict_position)
        self.assertLess(strict_position, after_position)
        self.assertEqual(verifier.count("lost_events_before_by_agent_source="), 1)
        self.assertEqual(verifier.count("lost_events_after_by_agent_source="), 1)
        self.assertIn("hubble-event-buffer-capacity=8191", verifier)
        self.assertIn("hubble-lost-event-window=strict-canary", verifier)
        self.assertIn("hubble-lost-event-positive-deltas=0", verifier)

    def test_cilium_strict_lane_has_fail_closed_scalar_runtime_gates(self) -> None:
        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        metrics_gate = (ROOT / "scripts/cluster/hubble-metrics-gate.py").read_text()
        combined = verifier + metrics_gate

        # v0.19.7 itself reads this runtime file to detect monitor aggregation.
        # The acceptance wrapper separately proves the release-supported medium
        # value rather than silently accepting an arbitrary runtime drift.
        for required_runtime_probe in (
            "agent-runtime-config.json",
            "MonitorAggregation",
            "cilium status -o json",
            'replacement=status.get("kube-proxy-replacement")',
            'replacement.get("mode")=="False"',
            "component=kube-proxy",
            "hubble_lost_events_total",
        ):
            self.assertIn(required_runtime_probe, combined)

        # Require the fail-closed assertions that make the emitted summaries
        # trustworthy without forcing implementation-specific label spelling.
        for scalar_assertion in (
            'assert len(pods)==3, "expected exactly three Cilium agents"',
            'assert config.get("MonitorAggregation")=="medium"',
            "monitor_medium=$((monitor_medium + 1))",
            "kpr_false=$((kpr_false + 1))",
            'assert len(pods)==3, "expected exactly three kube-proxy pods"',
            'assert ready==3, "expected all three kube-proxy pods Ready"',
            'if healthy != 3 or unavailable != 0:',
            'if len(before_values) != expected_series or set(before_values) != set(after_values):',
            "deltas = {",
            'if any(value < 0 for value in deltas.values()):',
            "positive_by_source = {source: 0.0 for source in LOST_EVENT_SOURCES}",
            'f"positive-delta-by-source {aggregates}"',
        ):
            self.assertIn(scalar_assertion, combined)

        # Only sanitized scalar summaries may be promoted into acceptance
        # evidence; no peer identity, agent identity, endpoint, or flow is output.
        for sanitized_summary in (
            "cilium-agents=3 monitor-aggregation-medium=3 kpr-false=3 kube-proxy-ready=3/3",
            "hubble-relay-replicas=2 healthy-peers-per-replica=3 unavailable-peers=0",
            "hubble-lost-event-window=strict-canary hubble-lost-event-positive-deltas=0",
        ):
            self.assertIn(sanitized_summary, verifier)

        self.assertIn('"IDLE"', metrics_gate)
        self.assertIn('"READY"', metrics_gate)
        self.assertIn("lost_events_before_by_agent_source", verifier)
        self.assertIn("lost_events_after_by_agent_source", verifier)
        self.assertIn("lost_event_positive_deltas", verifier)

        strict_position = verifier.index("--flow-validation strict")
        self.assertLess(verifier.index("agent-runtime-config.json"), strict_position)
        self.assertLess(verifier.index('replacement=status.get("kube-proxy-replacement")'), strict_position)
        self.assertLess(verifier.index("component=kube-proxy"), strict_position)

        role = (ROOT / "infra/ansible/roles/rke2_server/tasks/main.yml").read_text()
        self.assertIn("scripts/cluster/hubble-metrics-gate.py", role)
        self.assertIn("/usr/local/libexec/verda-phase4/hubble-metrics-gate", role)

    def test_hubble_metric_reducers_are_behavioral_and_fail_closed(self) -> None:
        path = ROOT / "scripts/cluster/hubble-metrics-gate.py"
        spec = importlib.util.spec_from_file_location("hubble_metrics_gate", path)
        assert spec and spec.loader
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)

        expected_zero = {source: 0.0 for source in gate.LOST_EVENT_SOURCES}
        self.assertEqual(gate.parse_lost_events(""), expected_zero)
        subset = 'hubble_lost_events_total{source="observer_events_queue"} 2\n'
        subset_values = gate.parse_lost_events(subset)
        self.assertEqual(subset_values["observer_events_queue"], 2.0)
        self.assertEqual(subset_values["hubble_ring_buffer"], 0.0)
        complete = "\n".join(
            f'hubble_lost_events_total{{source="{source}"}} {index}'
            for index, source in enumerate(sorted(gate.LOST_EVENT_SOURCES), 1)
        )
        self.assertEqual(len(gate.parse_lost_events(complete)), 3)

        malformed = (
            'hubble_lost_events_total{source="unknown"} 1',
            'hubble_lost_events_total{source="hubble_ring_buffer"} 1\n'
            'hubble_lost_events_total{source="hubble_ring_buffer"} 2',
            'hubble_lost_events_total{source="hubble_ring_buffer"} NaN',
            'hubble_lost_events_total{source="hubble_ring_buffer"} +Inf',
            'hubble_lost_events_total{source="hubble_ring_buffer"} -1',
        )
        for fixture in malformed:
            with self.subTest(fixture=fixture):
                with self.assertRaises(gate.MetricsGateError):
                    gate.parse_lost_events(fixture)

        before = gate.render_snapshot("agent-1", expected_zero)
        after = gate.render_snapshot("agent-1", expected_zero)
        self.assertEqual(gate.positive_delta_count(before, after, 3), 0)
        increased = gate.render_snapshot(
            "agent-1", {**expected_zero, "hubble_ring_buffer": 1.0}
        )
        with self.assertRaises(gate.MetricsGateError):
            gate.positive_delta_count(before, increased, 3)
        with self.assertRaises(gate.MetricsGateError):
            gate.positive_delta_count(increased, before, 3)
        with self.assertRaises(gate.MetricsGateError):
            gate.positive_delta_count(before, before.replace("agent-1", "agent-2"), 3)

        second_before = gate.render_snapshot("agent-2", expected_zero)
        first_increased = gate.render_snapshot(
            "agent-1",
            {
                **expected_zero,
                "hubble_ring_buffer": 1.0,
                "observer_events_queue": 2.0,
            },
        )
        second_increased = gate.render_snapshot(
            "agent-2", {**expected_zero, "hubble_ring_buffer": 3.0}
        )
        with self.assertRaises(gate.MetricsGateError) as diagnostic:
            gate.positive_delta_count(
                f"{before}\n{second_before}",
                f"{second_increased}\n{first_increased}",
                6,
            )
        self.assertEqual(
            str(diagnostic.exception),
            "Hubble lost-event counters increased during validation; "
            "positive-delta-by-source hubble_ring_buffer=4 "
            "observer_events_queue=2",
        )
        self.assertNotIn("agent-1", str(diagnostic.exception))
        self.assertNotIn("agent-2", str(diagnostic.exception))

        def relay_metrics(idle: int = 3, ready: int = 0, connecting: int = 0) -> str:
            values = {state: 0 for state in gate.RELAY_STATES}
            values.update(IDLE=idle, READY=ready, CONNECTING=connecting)
            return "\n".join(
                'hubble_relay_pool_peer_connection_status{status="%s"} %s'
                % (state, values[state])
                for state in sorted(values)
            )

        self.assertEqual(gate.parse_relay_peers(relay_metrics()), (3, 0))
        self.assertEqual(gate.parse_relay_peers(relay_metrics(idle=0, ready=3)), (3, 0))
        with self.assertRaises(gate.MetricsGateError):
            gate.parse_relay_peers(relay_metrics(idle=2, connecting=1))
        with self.assertRaises(gate.MetricsGateError):
            gate.parse_relay_peers("\n".join(relay_metrics().splitlines()[:-1]))

    def test_live_cilium_conformance_gate_is_scalar_and_precedes_lost_baseline(self) -> None:
        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        function = verifier.split("assert_cilium_live_conformance() {", 1)[1].split(
            "capture_hubble_lost_events()", 1
        )[0]
        for required_check in (
            "get daemonset cilium -o json",
            'status.get("observedGeneration")==generation',
            '"desiredNumberScheduled"',
            '"currentNumberScheduled"',
            '"updatedNumberScheduled"',
            '"numberReady"',
            '"numberAvailable"',
            'status.get("numberUnavailable", 0)',
            'strategy.get("type")=="RollingUpdate"',
            'str(max_unavailable)=="1"',
            "get configmap cilium-config -o json",
            'data.get("hubble-event-buffer-capacity")=="8191"',
            "get pods -l k8s-app=cilium -o json",
            'conditions.get("Ready")=="True"',
            'containers.get("cilium-agent", {}).get("ready") is True',
            "cat /tmp/cilium/config-map/hubble-event-buffer-capacity",
            '[[ "${effective_capacity}" == "8191" ]]',
            "[[ ${verified_agents} -eq 3 ]]",
        ):
            self.assertIn(required_check, function)

        marker = (
            "[PASS] cilium-live-conformance observed-generation=true desired=3 "
            "current=3 updated=3 ready=3 available=3 unavailable=0 "
            "strategy=RollingUpdate max-unavailable=1 "
            "hubble-event-buffer-capacity=8191 effective-agent-capacity=8191 "
            "effective-agents=3"
        )
        self.assertIn(marker, function)
        self.assertEqual(function.count("echo '[PASS]"), 1)
        conformance_position = verifier.index("assert_cilium_live_conformance\n")
        functional_position = verifier.index("--flow-validation disabled")
        baseline_position = verifier.index(
            "lost_events_before_by_agent_source=$(capture_hubble_lost_events)"
        )
        self.assertLess(conformance_position, functional_position)
        self.assertLess(functional_position, baseline_position)

    def test_live_cilium_conformance_gate_is_behavioral_and_fail_closed(self) -> None:
        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        start = "assert_cilium_live_conformance() {"
        function = start + verifier.split(start, 1)[1].split(
            "capture_hubble_lost_events()", 1
        )[0]
        marker = "[PASS] cilium-live-conformance"

        def bash_path(path: pathlib.Path) -> str:
            rendered = path.resolve().as_posix()
            if os.name == "nt":
                return f"/mnt/{rendered[0].lower()}{rendered[2:]}"
            return rendered

        with executable_temp_directory() as directory:
            root = pathlib.Path(directory)
            fake_kubectl = root / "kubectl"
            daemonset_file = root / "daemonset.json"
            config_map_file = root / "config-map.json"
            pods_file = root / "pods.json"
            fake_kubectl.write_bytes(
                """#!/usr/bin/env bash
set -euo pipefail
arguments=" $* "
if [[ ${arguments} == *" get daemonset cilium -o json "* ]]; then
  cat "${FAKE_DAEMONSET_JSON:?}"
elif [[ ${arguments} == *" get configmap cilium-config -o json "* ]]; then
  cat "${FAKE_CONFIG_MAP_JSON:?}"
elif [[ ${arguments} == *" get pods -l k8s-app=cilium -o json "* ]]; then
  cat "${FAKE_PODS_JSON:?}"
elif [[ ${arguments} == *" exec "* ]]; then
  if [[ ${FAKE_EXEC_FAILURE:-false} == true ]]; then
    exit 65
  fi
  if [[ -n ${FAKE_BAD_EFFECTIVE_POD:-} && ${arguments} == *" exec ${FAKE_BAD_EFFECTIVE_POD} "* ]]; then
    printf '4095\n'
  else
    printf '8191\n'
  fi
else
  exit 64
fi
""".encode("utf-8"),
            )
            fake_kubectl.chmod(0o755)

            daemonset = {
                "metadata": {"generation": 7},
                "spec": {
                    "updateStrategy": {
                        "type": "RollingUpdate",
                        "rollingUpdate": {"maxUnavailable": 1},
                    }
                },
                "status": {
                    "observedGeneration": 7,
                    "desiredNumberScheduled": 3,
                    "currentNumberScheduled": 3,
                    "updatedNumberScheduled": 3,
                    "numberReady": 3,
                    "numberAvailable": 3,
                    "numberUnavailable": 0,
                },
            }
            config_map = {"data": {"hubble-event-buffer-capacity": "8191"}}
            pods = {
                "items": [
                    {
                        "metadata": {"name": f"agent-{index}"},
                        "status": {
                            "phase": "Running",
                            "conditions": [{"type": "Ready", "status": "True"}],
                            "containerStatuses": [
                                {"name": "cilium-agent", "ready": True}
                            ],
                        },
                    }
                    for index in range(1, 4)
                ]
            }
            harness = (
                "set -euo pipefail\n"
                "kubectl=$1\nkubeconfig=/tmp/test-kubeconfig\n"
                "export FAKE_DAEMONSET_JSON=$2 FAKE_CONFIG_MAP_JSON=$3 FAKE_PODS_JSON=$4\n"
                "export FAKE_BAD_EFFECTIVE_POD=$5 FAKE_EXEC_FAILURE=$6\n"
                f"{function}\nassert_cilium_live_conformance\n"
            )

            def run_gate(
                daemonset_fixture: dict[str, object] | str = daemonset,
                config_fixture: dict[str, object] | str = config_map,
                pods_fixture: dict[str, object] | str = pods,
                bad_effective_pod: str = "",
                exec_failure: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                for path, fixture in (
                    (daemonset_file, daemonset_fixture),
                    (config_map_file, config_fixture),
                    (pods_file, pods_fixture),
                ):
                    path.write_text(
                        fixture if isinstance(fixture, str) else json.dumps(fixture),
                        encoding="utf-8",
                    )
                completed = subprocess.run(
                    [
                        "bash",
                        "-s",
                        "--",
                        bash_path(fake_kubectl),
                        bash_path(daemonset_file),
                        bash_path(config_map_file),
                        bash_path(pods_file),
                        bad_effective_pod,
                        "true" if exec_failure else "false",
                    ],
                    input=harness.encode("utf-8"),
                    capture_output=True,
                    check=False,
                )
                return subprocess.CompletedProcess(
                    completed.args,
                    completed.returncode,
                    completed.stdout.decode("utf-8", errors="replace"),
                    completed.stderr.decode("utf-8", errors="replace"),
                )

            success = run_gate()
            self.assertEqual(success.returncode, 0, success.stderr)
            expected_marker = next(
                line for line in function.splitlines() if line.startswith("  echo '[PASS]")
            ).removeprefix("  echo '").removesuffix("'")
            self.assertEqual(success.stdout.strip(), expected_marker)
            for agent_name in ("agent-1", "agent-2", "agent-3"):
                self.assertNotIn(agent_name, success.stdout)

            stale = json.loads(json.dumps(daemonset))
            stale["status"]["observedGeneration"] = 6
            oversized = json.loads(json.dumps(config_map))
            oversized["data"]["hubble-event-buffer-capacity"] = "16383"
            unready = json.loads(json.dumps(pods))
            unready["items"][1]["status"]["conditions"][0]["status"] = "False"
            for failure in (
                run_gate(daemonset_fixture=stale),
                run_gate(config_fixture=oversized),
                run_gate(pods_fixture=unready),
                run_gate(bad_effective_pod="agent-2"),
                run_gate(exec_failure=True),
                run_gate(daemonset_fixture="{not-json"),
            ):
                self.assertNotEqual(failure.returncode, 0)
                self.assertNotIn(marker, failure.stdout)

    def test_hubble_port_forward_and_namespace_cleanup_are_bounded_and_fail_closed(self) -> None:
        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        self.assertIn("stop_hubble_port_forward()", verifier)
        self.assertIn("cleanup_connectivity_required()", verifier)
        self.assertIn("cleanup_connectivity_required\ntrap - EXIT", verifier)
        self.assertIn("kill -KILL \"${hubble_port_forward_pid}\"", verifier)
        self.assertIn("for _ in $(seq 1 10)", verifier)
        self.assertIn("for _ in $(seq 1 5)", verifier)
        self.assertIn("PHASE4_NAMESPACE_CLEANUP_HELPER", verifier)
        self.assertIn('"${namespace_cleanup_helper}" cilium', verifier)
        self.assertIn("Cilium connectivity test namespaces removed", verifier)
        self.assertIn("Local Hubble Relay port 4245 was already in use", verifier)
        self.assertIn("port-forward exited after the readiness probe", verifier)
        required_cleanup = verifier.split("cleanup_connectivity_namespaces_required()", 1)[1].split(
            "cleanup_connectivity_required()", 1
        )[0]
        self.assertNotIn("--cleanup >/dev/null 2>&1 || true", required_cleanup)
        self.assertNotIn('"${namespace_cleanup_helper}" cilium >/dev/null', required_cleanup)
        best_effort = verifier.split("cleanup_connectivity_best_effort()", 1)[1].split(
            "cleanup_connectivity_namespaces_required()", 1
        )[0]
        self.assertIn('"${namespace_cleanup_helper}" cilium >/dev/null 2>&1 || true', best_effort)

        function_source = "cleanup_connectivity_namespaces_required()" + verifier.split(
            "cleanup_connectivity_namespaces_required()", 1
        )[1].split("cleanup_connectivity_required()", 1)[0]
        with executable_temp_directory() as directory:
            root = pathlib.Path(directory)
            invocation_log = root / "helper.log"
            fake_cilium = root / "cilium"
            fake_helper = root / "cleanup-helper"
            fake_cilium.write_text(
                "#!/usr/bin/env bash\nexit \"${FAKE_CILIUM_EXIT:-0}\"\n",
                encoding="utf-8",
            )
            fake_helper.write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >>\"${FAKE_HELPER_LOG:?}\"\nexit \"${FAKE_HELPER_EXIT:-0}\"\n",
                encoding="utf-8",
            )
            fake_cilium.chmod(0o755)
            fake_helper.chmod(0o755)
            harness = root / "required-cleanup.sh"
            harness.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                'cilium=${CILIUM:?}\nkubeconfig=/tmp/test-kubeconfig\n'
                'namespace_cleanup_helper=${PHASE4_NAMESPACE_CLEANUP_HELPER:?}\n'
                + function_source
                + "\ncleanup_connectivity_namespaces_required\n",
                encoding="utf-8",
            )
            harness.chmod(0o755)

            def run_cleanup(cilium_exit: int, helper_exit: int) -> subprocess.CompletedProcess[str]:
                invocation_log.unlink(missing_ok=True)
                return subprocess.run(
                    ["bash", harness.as_posix()],
                    env={
                        **os.environ,
                        "CILIUM": fake_cilium.as_posix(),
                        "PHASE4_NAMESPACE_CLEANUP_HELPER": fake_helper.as_posix(),
                        "FAKE_CILIUM_EXIT": str(cilium_exit),
                        "FAKE_HELPER_EXIT": str(helper_exit),
                        "FAKE_HELPER_LOG": invocation_log.as_posix(),
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )

            self.assertEqual(run_cleanup(0, 0).returncode, 0)
            self.assertEqual(invocation_log.read_text().splitlines(), ["cilium"])
            self.assertNotEqual(run_cleanup(42, 0).returncode, 0)
            self.assertFalse(invocation_log.exists())
            self.assertNotEqual(run_cleanup(0, 43).returncode, 0)
            self.assertEqual(invocation_log.read_text().splitlines(), ["cilium"])

    def test_cilium_and_traefik_stay_on_the_conservative_supported_path(self) -> None:
        cilium = (
            ROOT / "infra/ansible/roles/rke2_server/templates/rke2-cilium-config.yaml.j2"
        ).read_text()
        traefik = (
            ROOT / "infra/ansible/roles/rke2_server/templates/rke2-traefik-config.yaml.j2"
        ).read_text()
        outer_config = yaml.safe_load(cilium)
        cilium_values = yaml.safe_load(
            outer_config["spec"]["valuesContent"].replace(
                "{{ phase4_cilium_mtu }}", "1450"
            )
        )
        self.assertEqual(
            cilium_values["updateStrategy"],
            {
                "type": "RollingUpdate",
                "rollingUpdate": {"maxUnavailable": 1},
            },
        )
        event_buffer_capacity = cilium_values["hubble"]["eventBufferCapacity"]
        self.assertEqual(event_buffer_capacity, "8191")
        self.assertRegex(event_buffer_capacity, r"^[1-9][0-9]*$")
        self.assertLessEqual(int(event_buffer_capacity), 8191)
        self.assertIn('kubeProxyReplacement: "false"', cilium)
        self.assertIn("rollOutCiliumPods: true", cilium)
        self.assertIn("bpf:\n      monitorAggregation: medium", cilium)
        self.assertIn("routingMode: tunnel", cilium)
        self.assertIn("tunnelProtocol: vxlan", cilium)
        self.assertIn("MTU: {{ phase4_cilium_mtu }}", cilium)
        self.assertIn("ui:\n        enabled: false", cilium)
        self.assertIn("kind: DaemonSet", traefik)
        self.assertIn("dashboard:\n        enabled: false", traefik)
        self.assertIn("type: ClusterIP", traefik)

    def test_hubble_metrics_policy_allows_only_cluster_nodes_on_relay_metrics(self) -> None:
        policy_path = (
            ROOT
            / "infra/ansible/roles/rke2_server/templates/hubble-relay-node-metrics-policy.yaml.j2"
        )
        policy = policy_path.read_text()
        tasks = (ROOT / "infra/ansible/roles/rke2_server/tasks/main.yml").read_text()
        self.assertIn("kind: CiliumNetworkPolicy", policy)
        self.assertIn("k8s-app: hubble-relay", policy)
        self.assertIn("fromEntities:\n        - host\n        - remote-node", policy)
        self.assertIn('- port: "9966"', policy)
        self.assertNotIn("fromEntities:\n        - world", policy)
        self.assertIn(policy_path.name, tasks)

    def test_hubble_metrics_gate_is_bounded_and_uses_service_proxy(self) -> None:
        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        self.assertIn("wait_for_metric_prefix()", verifier)
        self.assertIn("local deadline=$((SECONDS + 120))", verifier)
        self.assertIn("hubble-metrics:9965", verifier)
        self.assertIn("hubble-relay-metrics:9966", verifier)
        self.assertIn("did not become reachable through the Kubernetes service proxy", verifier)

    def test_firewall_opens_only_admin_api_and_precise_pod_forwarding(self) -> None:
        firewall = (
            ROOT / "infra/ansible/roles/firewall/templates/90-verda-platform.nft.j2"
        ).read_text()
        self.assertIn("@admin_ipv4 tcp dport 6443", firewall)
        self.assertNotIn("tcp dport 9345", firewall)
        self.assertIn('"cilium_vxlan"', firewall)
        self.assertIn("phase4_management_pod_cidr", firewall)
        self.assertIn('iifname { "cilium_host", "cilium_vxlan", "lxc*" }', firewall)
        self.assertIn("meta mark & 0x0f00 == 0x0200 accept", firewall)
        self.assertIn("tcp dport { 4244, 6443, 10250 }", firewall)
        public_ingress_guard = (
            'ct direction original iifname != "{{ phase3_wireguard_interface }}" '
            'meta l4proto tcp ct status dnat '
            'ct original ip daddr {{ ansible_host }} ct original proto-dst { 80, 443 } drop'
        )
        self.assertIn(public_ingress_guard, firewall)
        self.assertEqual(firewall.count("ct original proto-dst { 80, 443 } drop"), 1)
        forward_chain = firewall.split("chain forward", 1)[1]
        self.assertLess(
            forward_chain.index("ct original proto-dst { 80, 443 } drop"),
            forward_chain.index("ct state { established, related } accept"),
        )

    def test_system_pod_gate_accepts_only_ready_or_successfully_completed_pods(self) -> None:
        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        self.assertIn('if phase == "Succeeded"', verifier)
        self.assertIn('phase != "Running"', verifier)
        self.assertIn('all(item.get("ready") for item in statuses)', verifier)
        self.assertNotIn("wait pod --all --for=condition=Ready", verifier)

    def test_upstream_cilium_suite_uses_only_ephemeral_psa_exempt_namespaces(self) -> None:
        verifier = (ROOT / "scripts/cluster/verify-management.sh").read_text()
        self.assertIn("--test-namespace cilium-test", verifier)
        self.assertIn("--namespace-labels", verifier)
        for mode in ("enforce", "audit", "warn"):
            self.assertIn(f"pod-security.kubernetes.io/{mode}=privileged", verifier)
        self.assertNotIn("--test-concurrency 2", verifier)
        self.assertEqual(verifier.count("--test-concurrency 1"), 2)
        self.assertIn("--timeout 45m", verifier)
        self.assertIn("--test-namespace cilium-test --cleanup", verifier)
        self.assertIn("--log-check-only-test-time", verifier)
        self.assertNotIn("label namespace default", verifier)
        self.assertNotIn("label namespace kube-system", verifier)

    def test_live_verifier_persists_failure_output_before_raising(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        checked = controller.split("function Invoke-RemoteChecked", 1)[1].split(
            "function Invoke-SingleNodeFailureTests", 1
        )[0]
        self.assertIn("[string]$OutputPath", checked)
        self.assertLess(checked.index("Set-Content"), checked.index("throw $Failure"))
        for report in (
            "management-verification.txt",
            "network-smoke.txt",
        ):
            self.assertIn(f"-OutputPath (Join-Path $reportRoot '{report}')", controller)
        self.assertIn('"cis-self-assessment-$($node.name).txt"', controller)

    def test_fault_drills_prove_cilium_health_and_complete_primary_recovery(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        failure = controller.split("function Invoke-SingleNodeFailureTests", 1)[1].split(
            "function Export-SanitizedSupportBundle", 1
        )[0]
        stopper = controller.split("function Stop-Rke2ForFailureDrill", 1)[1].split(
            "function Wait-CiliumStackAfterFailureDrill", 1
        )[0]
        recovery_waiter = controller.split("function Wait-CiliumStackAfterFailureDrill", 1)[
            1
        ].split("function Reconcile-CiliumComponentsBeforeVerification", 1)[0]
        self.assertIn("/usr/local/bin/rke2-killall.sh", stopper)
        self.assertIn("systemctl stop rke2-server.service", stopper)
        self.assertIn("systemctl is-active --quiet rke2-server.service", stopper)
        self.assertEqual(failure.count("Stop-Rke2ForFailureDrill"), 2)
        self.assertIn("deadline=$((SECONDS + 120))", failure)
        for marker in ("api=true", "quorum=true", "cilium=true", "workload=true"):
            self.assertIn(marker, failure)
        self.assertIn("non-primary-outage.txt", failure)
        self.assertEqual(failure.count("Wait-CiliumStackAfterFailureDrill"), 2)
        self.assertNotIn("Reconcile-CiliumAgentAfterFailureDrill", controller)
        self.assertIn("reconcile-cilium-agent 'post-drill-ready'", recovery_waiter)
        self.assertIn("without erasing expected restart history", recovery_waiter)
        self.assertNotIn("delete", recovery_waiter.lower())
        reconciliation_script = (
            ROOT / "scripts/cluster/reconcile-cilium-agent.sh"
        ).read_text()
        self.assertIn("restartCount", reconciliation_script)
        self.assertIn('"cilium-agent", "cilium-operator", "hubble-relay"', reconciliation_script)
        self.assertIn('"cilium-agent": 3, "cilium-operator": 2, "hubble-relay": 2', reconciliation_script)
        self.assertEqual(reconciliation_script.count('status.get("initContainerStatuses", [])'), 2)
        self.assertEqual(reconciliation_script.count('status.get("containerStatuses", [])'), 3)
        self.assertIn("${node_name} != all", reconciliation_script)
        self.assertIn('get_args+=(--field-selector "spec.nodeName=${node_name}")', reconciliation_script)
        self.assertIn("wait_for_all_components_ready()", reconciliation_script)
        self.assertGreaterEqual(reconciliation_script.count("wait_for_all_components_ready"), 3)
        self.assertIn("The bounded Cilium stack did not restore full replica readiness", reconciliation_script)
        self.assertIn("collect_residual_pods()", reconciliation_script)
        self.assertIn('residual=${residual_pods[0]}', reconciliation_script)
        self.assertNotIn('for residual in "${residual_pods[@]}"', reconciliation_script)
        self.assertIn("maximum_replacements=14", reconciliation_script)
        self.assertIn("replacement_attempts=$((replacement_attempts + 1))", reconciliation_script)
        self.assertIn("exhausted its replacement budget", reconciliation_script)
        post_drill = reconciliation_script.split(
            "if [[ ${node_name} == post-drill-ready ]]", 1
        )[1].split("replacement_attempts=0", 1)[0]
        self.assertIn("wait_for_api_ready", post_drill)
        self.assertIn("wait_for_all_components_ready", post_drill)
        self.assertIn('"${cilium}" status', post_drill)
        self.assertIn("restart_history_preserved=true", post_drill)
        self.assertIn("exit 0", post_drill)
        self.assertNotIn("delete", post_drill)
        self.assertIn("Reconcile-CiliumComponentsBeforeVerification", controller)
        self.assertIn("reconcile-cilium-agent 'all'", controller)
        self.assertIn("zero-restart component baseline", controller)
        self.assertIn("restart_count=0", reconciliation_script)
        self.assertIn('--field-selector=\"spec.nodeName=${node}\"', failure)
        self.assertIn("cilium_remaining_nodes = $true", failure)
        self.assertIn("foreach ($config in $directConfigs)", failure)
        self.assertIn("-HostAlias $primaryAlias -HostAddress $Nodes[0].public_address", failure)
        self.assertIn("$endpointLossDeadline = [Diagnostics.Stopwatch]::StartNew()", failure)
        self.assertIn("[TimeSpan]::FromMinutes(2)", failure)
        self.assertIn("$defaultEndpointUnavailable", failure)
        self.assertIn("'--request-timeout=3s'", failure)
        self.assertIn("failed after designated-primary recovery", failure)
        self.assertIn("post-drill API and exact Cilium/Hubble stack", recovery_waiter)
        self.assertIn("direct_node_paths = 3", failure)
        self.assertEqual(
            set(re.findall(r"Join-Path \$reportRoot '([^']+)'", failure)),
            {"non-primary-outage.txt", "single-node-failure.json"},
        )

        verification = controller.split("function Invoke-FullVerification", 1)[1].split(
            "$paths = Get-ExternalPaths", 1
        )[0]
        self.assertLess(
            verification.index("Reconcile-CiliumComponentsBeforeVerification"),
            verification.index("verify-management"),
        )
        self.assertLess(
            verification.index("Invoke-SingleNodeFailureTests"),
            verification.index("stability-window"),
        )

    def test_cilium_reconciliation_never_compounds_degraded_availability(self) -> None:
        reconciler = ROOT / "scripts/cluster/reconcile-cilium-agent.sh"
        with executable_temp_directory() as directory:
            root = pathlib.Path(directory)
            fake_kubectl = root / "kubectl"
            fake_kubectl.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [[ " $* " == *" get pod -o json "* ]]; then
  python3 - <<'PY'
import json
import os
import pathlib

scenario = os.environ["FAKE_SCENARIO"]
replaced = pathlib.Path(os.environ["FAKE_STATE"]).exists()
degraded = scenario == "degraded-initial" or (scenario == "degraded-after-first" and replaced)

def pod(name, component, restart=0, ready=True):
    return {
        "metadata": {"name": name, "labels": {"app.kubernetes.io/name": component}},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "initContainerStatuses": [],
            "containerStatuses": [{"ready": ready, "restartCount": restart}],
        },
    }

first_agent = pod("cilium-a-new", "cilium-agent") if replaced else pod("cilium-a", "cilium-agent", restart=1)
items = [
    first_agent,
    pod("cilium-b", "cilium-agent", restart=1),
    pod("cilium-c", "cilium-agent"),
    pod("operator-a", "cilium-operator"),
    pod("operator-b", "cilium-operator"),
    pod("relay-a", "hubble-relay"),
    pod("relay-b", "hubble-relay", ready=not degraded),
]
json.dump({"items": items}, os.sys.stdout)
PY
  exit 0
fi
if [[ " $* " == *" delete pod/"* ]]; then
  printf '%s\n' "$*" >>"${FAKE_DELETE_LOG:?}"
  : >"${FAKE_STATE:?}"
  exit 0
fi
exit 64
""",
                encoding="utf-8",
            )
            fake_kubectl.chmod(0o755)

            def run_scenario(name: str) -> list[str]:
                state = root / f"{name}.state"
                delete_log = root / f"{name}.deletes"
                environment = {
                    **os.environ,
                    "KUBECTL": fake_kubectl.as_posix(),
                    "KUBECONFIG_PATH": (root / "kubeconfig").as_posix(),
                    "RECONCILE_READINESS_TIMEOUT_SECONDS": "0",
                    "RECONCILE_POLL_INTERVAL_SECONDS": "0",
                    "FAKE_SCENARIO": name,
                    "FAKE_STATE": state.as_posix(),
                    "FAKE_DELETE_LOG": delete_log.as_posix(),
                }
                result = subprocess.run(
                    ["bash", reconciler.as_posix(), "all"],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                return delete_log.read_text().splitlines() if delete_log.exists() else []

            self.assertEqual(run_scenario("degraded-initial"), [])
            deletes = run_scenario("degraded-after-first")
            self.assertEqual(len(deletes), 1)
            self.assertIn("delete pod/cilium-a", deletes[0])

    def test_post_drill_recovery_wait_preserves_restart_history_without_deletion(self) -> None:
        reconciler = ROOT / "scripts/cluster/reconcile-cilium-agent.sh"
        with executable_temp_directory() as directory:
            root = pathlib.Path(directory)
            fake_kubectl = root / "kubectl"
            fake_cilium = root / "cilium"
            pods_file = root / "pods.json"
            delete_log = root / "deletes.log"
            cilium_log = root / "cilium.log"
            fake_kubectl.write_bytes(
                """#!/usr/bin/env bash
set -euo pipefail
if [[ " $* " == *" get --raw=/readyz "* ]]; then
  [[ ${FAKE_API_READY:-true} == true ]]
elif [[ " $* " == *" get pod -o json "* ]]; then
  cat "${FAKE_PODS_JSON:?}"
elif [[ " $* " == *" delete pod/"* ]]; then
  printf '%s\n' "$*" >>"${FAKE_DELETE_LOG:?}"
else
  exit 64
fi
""".encode("utf-8")
            )
            fake_cilium.write_bytes(
                """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_CILIUM_LOG:?}"
[[ ${FAKE_CILIUM_READY:-true} == true ]]
""".encode("utf-8")
            )
            fake_kubectl.chmod(0o755)
            fake_cilium.chmod(0o755)

            def pod(name: str, component: str, ready: bool = True) -> dict[str, object]:
                return {
                    "metadata": {
                        "name": name,
                        "labels": {"app.kubernetes.io/name": component},
                    },
                    "status": {
                        "phase": "Running",
                        "conditions": [
                            {"type": "Ready", "status": "True" if ready else "False"}
                        ],
                        "containerStatuses": [
                            {"name": component, "ready": ready, "restartCount": 4}
                        ],
                    },
                }

            ready_pods = {
                "items": [
                    *(pod(f"cilium-{index}", "cilium-agent") for index in range(3)),
                    *(pod(f"operator-{index}", "cilium-operator") for index in range(2)),
                    *(pod(f"relay-{index}", "hubble-relay") for index in range(2)),
                ]
            }

            def run_wait(
                pods: dict[str, object] = ready_pods,
                api_ready: bool = True,
                cilium_ready: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                pods_file.write_text(json.dumps(pods), encoding="utf-8")
                delete_log.unlink(missing_ok=True)
                cilium_log.unlink(missing_ok=True)
                return subprocess.run(
                    ["bash", reconciler.as_posix(), "post-drill-ready"],
                    env={
                        **os.environ,
                        "KUBECTL": fake_kubectl.as_posix(),
                        "CILIUM": fake_cilium.as_posix(),
                        "KUBECONFIG_PATH": (root / "kubeconfig").as_posix(),
                        "RECONCILE_READINESS_TIMEOUT_SECONDS": "0",
                        "RECONCILE_POLL_INTERVAL_SECONDS": "0",
                        "FAKE_PODS_JSON": pods_file.as_posix(),
                        "FAKE_DELETE_LOG": delete_log.as_posix(),
                        "FAKE_CILIUM_LOG": cilium_log.as_posix(),
                        "FAKE_API_READY": str(api_ready).lower(),
                        "FAKE_CILIUM_READY": str(cilium_ready).lower(),
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )

            success = run_wait()
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertIn("restart_history_preserved=true", success.stdout)
            self.assertFalse(delete_log.exists())
            self.assertIn("status --kubeconfig", cilium_log.read_text())

            unready_pods = json.loads(json.dumps(ready_pods))
            unready_pods["items"][0]["status"]["conditions"][0]["status"] = "False"
            excess_pods = json.loads(json.dumps(ready_pods))
            excess_pods["items"].append(pod("cilium-extra", "cilium-agent"))
            for scenario in (
                {"pods": unready_pods},
                {"pods": excess_pods},
                {"api_ready": False},
                {"cilium_ready": False},
            ):
                failure = run_wait(**scenario)
                self.assertNotEqual(failure.returncode, 0)
                self.assertNotIn("restart_history_preserved=true", failure.stdout)
                self.assertFalse(delete_log.exists())

    def test_external_kubectl_uses_the_current_locked_aqua_manifest(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        external = controller.split("function Invoke-ExternalKubectl", 1)[1].split(
            "function Test-TcpPort", 1
        )[0]
        self.assertIn("$aquaConfig = Join-Path $repoRoot 'aqua.yaml'", external)
        self.assertIn('"${aquaConfig}:/workspace/aqua.yaml:ro"', external)
        self.assertLess(external.index("aqua.yaml:ro"), external.index("$qualityImage, 'kubectl'"))
        self.assertIn("$HostAlias -cne \"$HostAddress.sslip.io\"", external)
        self.assertIn("AddressFamily]::InterNetwork", external)
        self.assertEqual(external.count("'--add-host'"), 1)
        self.assertIn('"${HostAlias}:${HostAddress}"', external)

    def test_protected_kubeconfigs_use_direct_addresses_and_complete_tls_sans(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        exporter = controller.split("function Export-ProtectedKubeconfigs", 1)[1].split(
            "function Invoke-ExternalKubectl", 1
        )[0]
        self.assertIn('Endpoint = "$($Nodes[0].public_address).sslip.io"', exporter)
        self.assertIn("Endpoint = $node.public_address", exporter)
        self.assertNotIn("Endpoint = \"$($node.public_address).sslip.io\"", exporter)

        common = (
            ROOT / "infra/ansible/roles/rke2_server/templates/rke2-common.yaml.j2"
        ).read_text()
        self.assertIn("- {{ hostvars[host].ansible_host | quote }}", common)
        self.assertIn("hostvars[host].ansible_host ~ '.sslip.io'", common)
        for node in (
            "verda-mgmt-server-01",
            "verda-mgmt-server-02",
            "verda-mgmt-server-03",
        ):
            self.assertIn(f"phase3_wireguard_addresses['{node}']", common)

    def test_cis_assessment_runs_on_every_server_with_separate_reports(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        verification = controller.split("function Invoke-FullVerification", 1)[1].split(
            "$paths = Get-ExternalPaths", 1
        )[0]
        self.assertIn("foreach ($node in $Nodes)", verification)
        self.assertIn("cis-self-assessment-$($node.name).txt", verification)
        self.assertNotIn("'cis-self-assessment.txt'", verification)

    def test_ephemeral_namespace_cleanup_is_fail_closed_and_proves_absence(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        cleanup_path = ROOT / "scripts/cluster/cleanup-test-namespaces.sh"
        cleanup = cleanup_path.read_text()
        role = (ROOT / "infra/ansible/roles/rke2_server/tasks/main.yml").read_text()
        self.assertIn("function Remove-CiliumTestNamespaces", controller)
        self.assertIn("cleanup-test-namespaces cilium", controller)
        self.assertIn("Cilium connectivity-test namespace cleanup or absence proof failed", controller)
        self.assertIn("function Remove-NetworkTestNamespace", controller)
        self.assertIn("cleanup-test-namespaces network-smoke", controller)
        self.assertIn("Phase 4 network-test namespace cleanup or absence proof failed", controller)
        self.assertIn("scripts/cluster/cleanup-test-namespaces.sh", role)
        self.assertIn("namespace_list=$(\"${kubectl}\"", cleanup)
        self.assertIn("post_namespace_list=$(\"${kubectl}\"", cleanup)
        self.assertNotIn("get namespace -o name |", cleanup)
        self.assertIn("grep -Eq '^namespace/cilium-test(-|$)'", cleanup)
        self.assertIn("grep -Fxq 'namespace/phase4-network-test'", cleanup)
        verification = controller.split("function Invoke-FullVerification", 1)[1].split(
            "$paths = Get-ExternalPaths", 1
        )[0]
        self.assertIn("Remove-CiliumTestNamespaces -Paths $Paths -Primary $Nodes[0]", verification)
        self.assertIn("finally {\n        Remove-CiliumTestNamespaces", verification)
        self.assertIn("$networkNamespaceCleanupRequired = $true", verification)
        self.assertIn("if ($networkNamespaceCleanupRequired)", verification)

        with executable_temp_directory() as directory:
            root = pathlib.Path(directory)
            fake_kubectl = root / "kubectl"
            fake_kubectl.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [[ ${FAKE_API_FAIL:-0} == 1 && \" $* \" == *\" get namespace \"* ]]; then
  exit 42
fi
if [[ \" $* \" == *\" get namespace -o name \"* ]]; then
  if [[ ! -e ${FAKE_STATE:?} ]]; then
    printf '%s\\n' namespace/cilium-test-1 namespace/phase4-network-test
  fi
  exit 0
fi
if [[ \" $* \" == *\" delete \"* ]]; then
  : >\"${FAKE_STATE:?}\"
  exit 0
fi
exit 64
""",
                encoding="utf-8",
            )
            fake_kubectl.chmod(0o755)
            for mode in ("cilium", "network-smoke"):
                state = root / f"{mode}.state"
                environment = {
                    **os.environ,
                    "KUBECTL": fake_kubectl.as_posix(),
                    "KUBECONFIG_PATH": (root / "kubeconfig").as_posix(),
                    "FAKE_STATE": state.as_posix(),
                }
                result = subprocess.run(
                    ["bash", cleanup_path.as_posix(), mode],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                state.unlink()
                environment["FAKE_API_FAIL"] = "1"
                result = subprocess.run(
                    ["bash", cleanup_path.as_posix(), mode],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_snapshot_acceptance_requires_both_local_and_s3_locations(self) -> None:
        backup = (ROOT / "infra/ansible/roles/etcd_backup/tasks/main.yml").read_text()
        evidence = (ROOT / "scripts/cluster/snapshot-evidence.sh").read_text()
        self.assertIn("'file://' in etcd_backup_phase4_snapshot_list.stdout", backup)
        self.assertIn("'s3://' in etcd_backup_phase4_snapshot_list.stdout", backup)
        self.assertIn("etcd.k3s.cattle.io/s3-config-secret", backup)
        self.assertIn("regex_replace('^https://', '')", backup)
        self.assertIn('locations == {"local", "off-cluster-s3"}', evidence)
        self.assertIn('raw_locations_recorded', evidence)
        self.assertIn("etcd-snapshot-compress: true", evidence)

    def test_stability_and_idempotency_gates_are_fail_closed(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        stability = (ROOT / "scripts/cluster/stability-window.sh").read_text()
        self.assertIn("function Assert-PrepareIdempotency", controller)
        self.assertIn("changed=0", controller)
        self.assertIn("management-snapshots.json", controller)
        self.assertIn("stability-window.json", controller)
        self.assertIn("for sample in $(seq 1 10)", stability)
        self.assertIn("current==baseline", stability)
        self.assertGreaterEqual(stability.count("cilium status"), 2)
        self.assertIn('status.get("initContainerStatuses", [])', stability)
        self.assertIn('(pod["metadata"]["uid"], status_class, item["name"])', stability)
        self.assertIn("endpoint health --cluster", stability)

    def test_phase_four_scripts_clean_up_and_sanitize(self) -> None:
        smoke = (ROOT / "scripts/cluster/network-smoke.sh").read_text()
        support = (ROOT / "scripts/collect-rke2-diagnostics.sh").read_text()
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        self.assertIn("trap cleanup EXIT", smoke)
        self.assertIn("same_node == 3 && cross_node == 6", smoke)

        for term in (
            "REDACTED_ENDPOINT",
            "REDACTED_S3_LOCATION",
            "REDACTED_IP",
            "REDACTED_ID",
        ):
            self.assertIn(term, support)
        for capture in ("etcd-health", "etcd-endpoints", "etcd-members", "etcd-alarms"):
            self.assertIn(f"capture {capture}", support)
        self.assertIn("([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", support)
        self.assertIn("verda\\.storage#[REDACTED_ENDPOINT]#gI", support)
        self.assertIn("verda-takehome-mgmt-etcd-[[:alnum:]-]+#[REDACTED_S3_LOCATION]#gI", support)
        self.assertIn("--sanitize-stdin", support)
        self.assertIn("capture routes ip -4 route show", support)
        for forbidden in ("cat /etc/rancher/rke2/rke2.yaml", "cat /var/lib/rancher/rke2/server/token"):
            self.assertNotIn(forbidden, support)
        self.assertIn("function Assert-SanitizedSupportBundle", controller)
        self.assertIn("scripts\\cluster\\check_support_bundle.py", controller)
        self.assertIn("bounded fail-closed safety checker", controller)
        self.assertIn("--remove-unvalidated", controller)
        self.assertIn("Unvalidated local support-bundle cleanup failed closed", controller)

    def test_support_bundle_sanitizer_and_checker_are_behavioral(self) -> None:
        sanitizer = ROOT / "scripts/collect-rke2-diagnostics.sh"
        synthetic = (
            "service retry Objects.Example.Verda.Storage result=continuing\n"
            "journal Verda-Takehome-Mgmt-Etcd-Synthetic123 result=retained\n"
        )
        filtered = subprocess.run(
            ["bash", str(sanitizer), "--sanitize-stdin"],
            input=synthetic,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertNotIn("Objects.Example.Verda.Storage", filtered)
        self.assertNotIn("Verda-Takehome-Mgmt-Etcd-Synthetic123", filtered)
        self.assertIn("[REDACTED_ENDPOINT]", filtered)
        self.assertIn("[REDACTED_S3_LOCATION]", filtered)
        self.assertIn("service retry", filtered)
        self.assertIn("result=retained", filtered)

        checker = ROOT / "scripts/cluster/check_support_bundle.py"
        checker_spec = importlib.util.spec_from_file_location("phase4_support_checker", checker)
        self.assertIsNotNone(checker_spec)
        self.assertIsNotNone(checker_spec.loader)
        checker_module = importlib.util.module_from_spec(checker_spec)
        checker_spec.loader.exec_module(checker_module)
        collector_source = sanitizer.read_text()
        declared_captures = set(
            re.findall(r"(?:^|\s)capture ([a-z0-9-]+) ", collector_source, re.MULTILINE)
        )
        expected_captures = {
            name.removesuffix(".txt") for name in checker_module.EXPECTED_CAPTURE_FILES
        }
        self.assertEqual(declared_captures, expected_captures)
        test_environment = os.environ.copy()
        test_environment["PHASE4_S3_SECRET_KEY"] = "SyntheticProtectedMaterial987"

        def build_archive(parent: pathlib.Path, name: str, payload: str) -> pathlib.Path:
            archive = parent / f"{name}.tgz"
            with tarfile.open(archive, mode="w:gz") as bundle:
                root_member = tarfile.TarInfo(checker_module.ROOT_MEMBER)
                root_member.type = tarfile.DIRTYPE
                root_member.mode = 0o700
                root_member.uid = root_member.gid = 0
                root_member.uname = root_member.gname = "root"
                bundle.addfile(root_member)
                for capture in sorted(checker_module.EXPECTED_CAPTURE_FILES):
                    content = (
                        payload.encode("utf-8")
                        if capture == "service-status.txt"
                        else b"diagnostic context retained\n"
                    )
                    member = tarfile.TarInfo(f"{checker_module.ROOT_MEMBER}/{capture}")
                    member.mode = 0o600
                    member.uid = member.gid = 0
                    member.uname = member.gname = "root"
                    member.size = len(content)
                    bundle.addfile(member, io.BytesIO(content))
            return archive

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            clean = build_archive(
                root,
                "clean",
                "service active endpoint=[REDACTED_ENDPOINT] location=[REDACTED_S3_LOCATION]\n",
            )
            clean_result = subprocess.run(
                [sys.executable, str(checker), "--archive", str(clean)],
                env=test_environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(clean_result.returncode, 0)
            self.assertTrue(clean.exists())

            rejected_payloads = {
                "authority": "retry Objects.Example.Verda.Storage\n",
                "bucket": "retry Verda-Takehome-Mgmt-Etcd-Synthetic123\n",
                "process-value": "SyntheticProtectedMaterial987\n",
            }
            for name, payload in rejected_payloads.items():
                with self.subTest(name=name):
                    rejected = build_archive(root, name, payload)
                    result = subprocess.run(
                        [sys.executable, str(checker), "--archive", str(rejected)],
                        env=test_environment,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(rejected.exists())

    def test_support_bundle_checker_rejects_malformed_topology_and_bounds(self) -> None:
        checker_path = ROOT / "scripts/cluster/check_support_bundle.py"
        checker_spec = importlib.util.spec_from_file_location(
            "phase4_support_checker_safety", checker_path
        )
        self.assertIsNotNone(checker_spec)
        self.assertIsNotNone(checker_spec.loader)
        checker = importlib.util.module_from_spec(checker_spec)
        checker_spec.loader.exec_module(checker)

        def write_archive(
            path: pathlib.Path,
            *,
            missing: str | None = None,
            duplicate: str | None = None,
            extra: str | None = None,
            root_type: bytes = tarfile.DIRTYPE,
            root_uname: str = "",
            replacement_type: tuple[str, bytes] | None = None,
            invalid_utf8: str | None = None,
        ) -> pathlib.Path:
            with tarfile.open(path, mode="w:gz") as bundle:
                root = tarfile.TarInfo(checker.ROOT_MEMBER)
                root.type = root_type
                root.mode = 0o700
                root.uname = root_uname
                bundle.addfile(root, io.BytesIO(b"") if root_type == tarfile.REGTYPE else None)
                for capture in sorted(checker.EXPECTED_CAPTURE_FILES):
                    if capture == missing:
                        continue
                    member_name = f"{checker.ROOT_MEMBER}/{capture}"
                    member = tarfile.TarInfo(member_name)
                    member.mode = 0o600
                    if replacement_type and capture == replacement_type[0]:
                        member.type = replacement_type[1]
                        member.linkname = f"{checker.ROOT_MEMBER}/nodes.txt"
                        bundle.addfile(member)
                        continue
                    payload = b"\xff\xfe" if capture == invalid_utf8 else b"diagnostic context\n"
                    member.size = len(payload)
                    bundle.addfile(member, io.BytesIO(payload))
                    if capture == duplicate:
                        duplicate_member = tarfile.TarInfo(member_name)
                        duplicate_member.mode = 0o600
                        duplicate_member.size = len(payload)
                        bundle.addfile(duplicate_member, io.BytesIO(payload))
                if extra:
                    payload = b"unexpected\n"
                    member = tarfile.TarInfo(extra)
                    member.mode = 0o600
                    member.size = len(payload)
                    bundle.addfile(member, io.BytesIO(payload))
            return path

        def assert_rejected(archive: pathlib.Path) -> None:
            with self.assertRaises(checker.SupportBundleError):
                checker.validate_archive(archive, {})
            self.assertFalse(archive.exists())

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            captures = sorted(checker.EXPECTED_CAPTURE_FILES)
            assert_rejected(write_archive(root / "missing.tgz", missing=captures[0]))
            assert_rejected(
                write_archive(
                    root / "duplicate.tgz", missing=captures[0], duplicate=captures[1]
                )
            )
            assert_rejected(
                write_archive(
                    root / "extra.tgz",
                    missing=captures[0],
                    extra=f"{checker.ROOT_MEMBER}/extra.txt",
                )
            )
            assert_rejected(write_archive(root / "root-file.tgz", root_type=tarfile.REGTYPE))
            assert_rejected(
                write_archive(root / "unexpected-uname.tgz", root_uname="SyntheticMetadataSecret987")
            )
            for name, member_path in (
                ("traversal", f"{checker.ROOT_MEMBER}/../escape.txt"),
                ("absolute", "/escape.txt"),
                (
                    "child-trailing-slash",
                    f"{checker.ROOT_MEMBER}/{captures[0]}/",
                ),
            ):
                assert_rejected(
                    write_archive(
                        root / f"{name}.tgz", missing=captures[0], extra=member_path
                    )
                )
            for name, member_type in (
                ("symlink", tarfile.SYMTYPE),
                ("hardlink", tarfile.LNKTYPE),
                ("fifo", tarfile.FIFOTYPE),
            ):
                assert_rejected(
                    write_archive(
                        root / f"{name}.tgz",
                        replacement_type=(captures[0], member_type),
                    )
                )
            assert_rejected(
                write_archive(root / "invalid-utf8.tgz", invalid_utf8=captures[0])
            )

            malformed = root / "malformed.tgz"
            malformed.write_bytes(b"not-a-gzip-stream")
            assert_rejected(malformed)

            truncated = write_archive(root / "truncated.tgz")
            truncated.write_bytes(truncated.read_bytes()[:32])
            assert_rejected(truncated)

            pax_archive = root / "oversized-pax.tgz"
            with tarfile.open(pax_archive, mode="w:gz", format=tarfile.PAX_FORMAT) as bundle:
                pax_root = tarfile.TarInfo(checker.ROOT_MEMBER)
                pax_root.type = tarfile.DIRTYPE
                pax_root.pax_headers = {"comment": "A" * 8192}
                bundle.addfile(pax_root)
            original_stream_limit = checker.MAX_TAR_STREAM_BYTES
            checker.MAX_TAR_STREAM_BYTES = 2048
            try:
                assert_rejected(pax_archive)
            finally:
                checker.MAX_TAR_STREAM_BYTES = original_stream_limit

            metadata_secret = root / "metadata-secret.tgz"
            with tarfile.open(
                metadata_secret, mode="w:gz", format=tarfile.PAX_FORMAT
            ) as bundle:
                metadata_root = tarfile.TarInfo(checker.ROOT_MEMBER)
                metadata_root.type = tarfile.DIRTYPE
                metadata_root.mode = 0o700
                metadata_root.pax_headers = {"comment": "SyntheticMetadataSecret987"}
                bundle.addfile(metadata_root)
                for capture in sorted(checker.EXPECTED_CAPTURE_FILES):
                    payload = b"diagnostic context\n"
                    member = tarfile.TarInfo(f"{checker.ROOT_MEMBER}/{capture}")
                    member.mode = 0o600
                    member.size = len(payload)
                    bundle.addfile(member, io.BytesIO(payload))
            assert_rejected(metadata_secret)

            for name, extension_type in (
                ("gnu-longname", tarfile.GNUTYPE_LONGNAME),
                ("gnu-longlink", tarfile.GNUTYPE_LONGLINK),
            ):
                extension_archive = root / f"{name}-secret.tgz"
                with tarfile.open(
                    extension_archive, mode="w:gz", format=tarfile.GNU_FORMAT
                ) as bundle:
                    extension_root = tarfile.TarInfo(checker.ROOT_MEMBER)
                    extension_root.type = tarfile.DIRTYPE
                    extension_root.mode = 0o700
                    bundle.addfile(extension_root)
                    for index, capture in enumerate(
                        sorted(checker.EXPECTED_CAPTURE_FILES)
                    ):
                        if index == 0:
                            hidden = b"\0SyntheticMetadataSecret987\0"
                            extension = tarfile.TarInfo("././@LongLink")
                            extension.type = extension_type
                            extension.size = len(hidden)
                            bundle.addfile(extension, io.BytesIO(hidden))
                        payload = b"diagnostic context\n"
                        member = tarfile.TarInfo(
                            f"{checker.ROOT_MEMBER}/{capture}"
                        )
                        member.mode = 0o600
                        member.size = len(payload)
                        bundle.addfile(member, io.BytesIO(payload))
                assert_rejected(extension_archive)

            for name, transform in (
                ("raw-trailing", lambda data: data + b"SyntheticTrailingSecret987"),
                (
                    "gzip-member-trailing",
                    lambda data: data + gzip.compress(b"SyntheticTrailingSecret987"),
                ),
                (
                    "tar-trailing",
                    lambda data: gzip.compress(
                        gzip.decompress(data) + b"SyntheticTrailingSecret987"
                    ),
                ),
            ):
                trailing = write_archive(root / f"{name}.tgz")
                trailing.write_bytes(transform(trailing.read_bytes()))
                assert_rejected(trailing)

            for attribute, reduced_limit in (
                ("MAX_ARCHIVE_BYTES", 1),
                ("MAX_EXPANDED_BYTES", 4),
                ("MAX_TAR_STREAM_BYTES", 512),
                ("MAX_MEMBERS", 2),
            ):
                with self.subTest(bound=attribute):
                    bounded = write_archive(root / f"bound-{attribute}.tgz")
                    original = getattr(checker, attribute)
                    setattr(checker, attribute, reduced_limit)
                    try:
                        assert_rejected(bounded)
                    finally:
                        setattr(checker, attribute, original)

            removable = root / "partial-support.tgz"
            removable.write_bytes(b"partial")
            checker.remove_unvalidated_archive(removable)
            self.assertFalse(removable.exists())

            undeletable = root / "partial-support-directory"
            undeletable.mkdir()
            with self.assertRaises(checker.SupportBundleError):
                checker.remove_unvalidated_archive(undeletable)
            self.assertTrue(undeletable.is_dir())

    def test_network_smoke_server_uses_available_pinned_busybox_applets(self) -> None:
        manifest = (ROOT / "tests/cluster/phase4/network-smoke.yaml").read_text()
        smoke = (ROOT / "scripts/cluster/network-smoke.sh").read_text()
        pinned_image = (
            "quay.io/cilium/alpine-curl:v1.10.0@sha256:"
            "913e8c9f3d960dde03882defa0edd3a919d529c2eb167caa7f54194528bde364"
        )
        self.assertEqual(manifest.count(pinned_image), 3)
        self.assertIn("busybox nc -l -p 8080", manifest)
        self.assertIn("busybox nc -l -p 8081", manifest)
        self.assertIn("containerPort: 8080", manifest)
        self.assertIn("containerPort: 8081", manifest)
        self.assertNotIn("busybox httpd", manifest)
        self.assertIn("http://${server_ip}:8081/mtu.bin", smoke)
        documents = list(yaml.safe_load_all(manifest))
        policy = next(
            document
            for document in documents
            if document.get("kind") == "NetworkPolicy"
            and document["metadata"]["name"] == "echo-allow-approved-client"
        )
        approved_client, traefik = policy["spec"]["ingress"]
        self.assertEqual(
            approved_client["ports"],
            [{"protocol": "TCP", "port": 8080}, {"protocol": "TCP", "port": 8081}],
        )
        self.assertEqual(
            traefik,
            {
                "from": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                        },
                        "podSelector": {
                            "matchLabels": {"app.kubernetes.io/name": "rke2-traefik"}
                        },
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 8080}],
            },
        )

    def test_runtime_helper_stdout_cannot_pollute_the_node_array(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        runtime_function = controller.split("function New-Phase4Runtime", 1)[1].split(
            "function Invoke-Phase2Boundary", 1
        )[0]
        self.assertIn("$runtimeOutput = @(& python @arguments 2>&1)", runtime_function)
        self.assertIn("$runtimeExitCode = $LASTEXITCODE", runtime_function)
        self.assertIn("foreach ($line in $runtimeOutput) { Write-Host $line }", runtime_function)
        self.assertNotIn("\n    & python @arguments\n", runtime_function)

    def test_phase_four_resume_does_not_weaken_the_phase_three_default(self) -> None:
        diagnostics = (ROOT / "infra/ansible/roles/diagnostics/tasks/main.yml").read_text()
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        self.assertIn("phase3_require_rke2_absent | default(true)", diagnostics)
        self.assertIn("function Get-PreparedRke2HostCount", controller)
        self.assertIn("phase3_require_rke2_absent = 'false'", controller)
        self.assertIn("strict-phase3-absence-gate=preserved", controller)

    def test_serial_membership_gate_is_safe_for_fresh_and_resumed_clusters(self) -> None:
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        self.assertIn("function Get-CurrentEtcdMemberCount", controller)
        self.assertIn("$existingMembers = Get-CurrentEtcdMemberCount", controller)
        self.assertIn("[Math]::Max($existingMembers, $index + 1)", controller)
        self.assertIn("-MinimumMembers $minimumMembers", controller)
        self.assertNotIn("-ExpectedMembers ($index + 1)", controller)

    def test_cidr_gate_rejects_an_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    "python",
                    str(ROOT / "scripts/cluster/assert-cidr-plan.py"),
                    "--planned",
                    "management-pods=10.42.0.0/16",
                    "--planned",
                    "management-services=10.43.0.0/16",
                    "--route",
                    "controller=10.42.7.0/24",
                    "--output",
                    str(pathlib.Path(directory) / "report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("overlaps an active controller route", result.stderr)

    def test_cidr_gate_accepts_only_an_explicitly_owned_resume_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    "python",
                    str(ROOT / "scripts/cluster/assert-cidr-plan.py"),
                    "--planned",
                    "management-pods=10.42.0.0/16",
                    "--route",
                    "verda-mgmt-server-01=10.42.0.0/24",
                    "--owned-route",
                    "verda-mgmt-server-01=10.42.0.0/24",
                    "--output",
                    str(pathlib.Path(directory) / "report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        controller = (ROOT / "scripts/cluster/phase4.ps1").read_text()
        self.assertIn("$route.dev -match '^cilium_(host|net|vxlan)$'", controller)
        self.assertIn("$routeArgs.Add('--owned-route')", controller)

    def test_cidr_gate_rejects_owned_route_outside_management_cilium(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    "python",
                    str(ROOT / "scripts/cluster/assert-cidr-plan.py"),
                    "--planned",
                    "management-pods=10.42.0.0/16",
                    "--route",
                    "verda-mgmt-server-01=10.44.0.0/24",
                    "--owned-route",
                    "verda-mgmt-server-01=10.44.0.0/24",
                    "--output",
                    str(pathlib.Path(directory) / "report.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the management Cilium boundary", result.stderr)


if __name__ == "__main__":
    unittest.main()
