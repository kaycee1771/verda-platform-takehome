from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "capacity-admission.py"
RENDER_SCRIPT = ROOT / "scripts" / "phase6" / "render-capacity-inputs.py"
CONTRACT = ROOT / "config" / "phase6-capacity-admission.yaml"
SPEC = importlib.util.spec_from_file_location("phase6_capacity_admission", SCRIPT)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNTIME
SPEC.loader.exec_module(RUNTIME)
GIB = 1024**3
MIB = 1024**2


def resources(cpu: str, memory: str, limit_cpu: str, limit_memory: str) -> dict:
    return {
        "requests": {"cpu": cpu, "memory": memory},
        "limits": {"cpu": limit_cpu, "memory": limit_memory},
    }


def pod_spec(cpu: str, memory: str, limit_cpu: str, limit_memory: str) -> dict:
    return {
        "containers": [
            {
                "name": "main",
                "image": "registry.invalid/example@sha256:" + "1" * 64,
                "resources": resources(cpu, memory, limit_cpu, limit_memory),
            }
        ]
    }


def configmap(name: str) -> dict:
    return {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name}}


def deployment(name: str, replicas: int, cpu: str = "100m", memory: str = "128Mi") -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": "phase6-test"},
        "spec": {
            "replicas": replicas,
            "strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxSurge": "25%"}},
            "template": {
                "spec": pod_spec(cpu, memory, "500m", "512Mi"),
            },
        },
    }


def statefulset(name: str) -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": name, "namespace": "phase6-test"},
        "spec": {
            "replicas": 1,
            "template": {"spec": pod_spec("200m", "256Mi", "1", "1Gi")},
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "data"},
                    "spec": {
                        "storageClassName": "longhorn-critical",
                        "resources": {"requests": {"storage": "1Gi"}},
                    },
                }
            ],
        },
    }


def daemonset(name: str) -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "DaemonSet",
        "metadata": {"name": name, "namespace": "phase6-test"},
        "spec": {
            "updateStrategy": {"type": "RollingUpdate", "rollingUpdate": {"maxSurge": 1}},
            "template": {"spec": pod_spec("50m", "64Mi", "200m", "256Mi")},
        },
    }


def base_documents() -> dict[str, list[dict]]:
    result = {
        component: [configmap(component.replace("_", "-"))]
        for component in RUNTIME.REQUIRED_COMPONENTS
    }
    result["rancher"] = [deployment("rancher", 2)]
    result["harbor"] = [statefulset("harbor")]
    result["alloy"] = [daemonset("alloy")]
    result["platform_demo"] = [deployment("platform-demo", 3)]
    return result


def write_contract(root: Path, documents: dict[str, list[dict]]) -> tuple[Path, dict]:
    fixture_source = Path(__file__)
    fixture_source_hash = hashlib.sha256(fixture_source.read_bytes()).hexdigest()
    chart_locks = yaml.safe_load((ROOT / "versions.lock.yaml").read_text(encoding="utf-8"))[
        "helm_charts"
    ]
    components = {}
    for component in sorted(RUNTIME.REQUIRED_COMPONENTS):
        path = root / f"{component}.yaml"
        payload = yaml.safe_dump_all(documents[component], sort_keys=False).encode()
        path.write_bytes(payload)
        workloads = sum(
            document.get("kind") in RUNTIME.STANDARD_WORKLOAD_KINDS
            for document in documents[component]
        )
        pvcs = sum(document.get("kind") == "PersistentVolumeClaim" for document in documents[component])
        pvcs += sum(
            len(document.get("spec", {}).get("volumeClaimTemplates", []))
            for document in documents[component]
            if document.get("kind") == "StatefulSet"
        )
        components[component] = {
            "render_path": path.name,
            "render_sha256": hashlib.sha256(payload).hexdigest(),
            "expected_document_count": len(documents[component]),
            "expected_workload_count": workloads,
            "expected_pvc_definition_count": pvcs,
            "source_inputs": [
                {
                    "path": fixture_source.relative_to(ROOT).as_posix(),
                    "recursive": False,
                    "sha256": fixture_source_hash,
                }
            ],
        }
        if component not in {"environment_foundations", "platform_demo"}:
            components[component]["chart_archive_sha256"] = chart_locks[component][
                "archive_sha256"
            ]
    contract = {
        "schema_version": 1,
        "admission_status": "ready",
        "baseline": {
            "node_count": 3,
            "allocatable_cpu_millicores": 12000,
            "allocatable_memory_bytes": 48 * GIB,
            "one_node_loss_allocatable_cpu_millicores": 8000,
            "one_node_loss_allocatable_memory_bytes": 32 * GIB,
            "existing_requested_cpu_millicores": 2000,
            "existing_requested_memory_bytes": 4 * GIB,
            "required_cpu_reserve_millicores": 100,
            "required_memory_reserve_bytes": 1 * GIB,
            "storage_available_bytes": 100 * GIB,
            "worst_two_node_storage_available_bytes": 70 * GIB,
            "required_storage_reserve_bytes": 10 * GIB,
        },
        "storage_classes": {
            "longhorn-critical": {"replicas": 3, "replicas_after_one_node_loss": 2}
        },
        "components": components,
    }
    contract_path = root / "contract.yaml"
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    return contract_path, contract


class Phase6CapacityAdmissionTests(unittest.TestCase):
    def test_tracked_contract_binds_every_projection_and_stays_blocked(self) -> None:
        contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["admission_status"], "blocked-incomplete-inputs")
        self.assertEqual(
            contract["blockers"],
            [
                "current-three-node-cpu-envelope-insufficient",
                "candidate-shape-kubernetes-allocatable-unverified",
            ],
        )
        self.assertEqual(contract["baseline"]["allocatable_memory_bytes"], 42291773440)
        self.assertEqual(contract["baseline"]["existing_requested_memory_bytes"], 10122952704)
        self.assertEqual(
            contract["baseline_provenance"]["raw_requested_memory_bytes"]
            + contract["baseline_provenance"]["phase5_render_requested_memory_bytes"],
            contract["baseline"]["existing_requested_memory_bytes"],
        )
        self.assertEqual(contract["baseline"]["required_cpu_reserve_millicores"], 1000)
        self.assertEqual(contract["baseline"]["required_memory_reserve_bytes"], 4 * GIB)
        self.assertEqual(contract["baseline"]["required_storage_reserve_bytes"], 50 * GIB)
        self.assertEqual(contract["projection_result"]["new_steady_cpu_millicores"], 4460)
        self.assertEqual(contract["projection_result"]["new_rollout_peak_cpu_millicores"], 6650)
        self.assertEqual(
            contract["projection_result"]["one_node_loss_cpu_reserve_shortfall_millicores"],
            7585,
        )
        self.assertEqual(
            contract["projection_result"]["one_node_loss_memory_reserve_headroom_bytes"],
            874913792,
        )
        self.assertEqual(contract["projection_result"]["unrequested_container_count"], 0)
        self.assertEqual(
            contract["projection_result"]["required_candidate_per_node_cpu_millicores"],
            6793,
        )
        self.assertEqual(set(contract["components"]), RUNTIME.REQUIRED_COMPONENTS)
        for component in contract["components"].values():
            self.assertRegex(component["render_sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(component["expected_document_count"], 0)
            self.assertGreater(len(component["source_inputs"]), 0)

    def test_render_helper_covers_exact_component_set_without_live_clients(self) -> None:
        source = RENDER_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("SYNTHETIC_DIGEST", source)
        self.assertIn("operator-workloads.capacity-input", source)
        self.assertIn("velero_generated_projections", source)
        self.assertIn("inject_rancher_hook_limit", source)
        self.assertIn("cattle-system-limit-range.yaml", source)
        self.assertNotIn("kubectl get", source)
        self.assertNotIn("helm install", source)

    def test_tracked_contract_is_deliberately_fail_closed(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--contract", str(CONTRACT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr,
            "[FAIL] Phase 6 capacity admission: admission_status must equal ready "
            "after every render and baseline input is verified\n",
        )

    def test_aggregate_uses_steady_rollout_pvc_and_one_node_loss_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract_path, _ = write_contract(Path(directory), base_documents())
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["component_count"], 10)
        self.assertEqual(report["workload_definition_count"], 4)
        self.assertEqual(report["pvc_definition_count"], 1)
        self.assertEqual(report["new_steady_cpu_millicores"], 850)
        self.assertEqual(report["new_rollout_peak_cpu_millicores"], 1100)
        self.assertEqual(report["one_node_loss_rollout_cpu_headroom_millicores"], 4900)
        self.assertEqual(report["new_steady_memory_bytes"], 1088 * MIB)
        self.assertEqual(report["new_rollout_peak_memory_bytes"], 1408 * MIB)
        self.assertEqual(report["new_logical_pvc_bytes"], GIB)
        self.assertEqual(report["new_raw_pvc_bytes"], 3 * GIB)
        self.assertEqual(report["one_node_loss_pvc_bytes"], 2 * GIB)

    def test_rollout_peak_cannot_hide_behind_steady_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract_path, contract = write_contract(Path(directory), base_documents())
            contract["baseline"]["one_node_loss_allocatable_cpu_millicores"] = 3000
            contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("rollout peak violates one-node-loss CPU reserve", result.stderr)

    def test_storage_replication_and_loss_reserve_are_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract_path, contract = write_contract(Path(directory), base_documents())
            contract["baseline"]["storage_available_bytes"] = 3 * GIB
            contract["baseline"]["required_storage_reserve_bytes"] = GIB
            contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("PVC replicas violate total storage reserve", result.stderr)

    def test_operator_generated_workload_is_rejected_until_modeled(self) -> None:
        documents = base_documents()
        documents["kube_prometheus_stack"] = [
            {
                "apiVersion": "monitoring.coreos.com/v1",
                "kind": "Prometheus",
                "metadata": {"name": "platform", "namespace": "monitoring"},
                "spec": {"replicas": 2},
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            contract_path, _ = write_contract(Path(directory), documents)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("unsupported capacity-bearing kind Prometheus", result.stderr)

    def test_missing_container_limits_are_allowed_when_requests_remain_exact(self) -> None:
        documents = base_documents()
        del documents["rancher"][0]["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
        with tempfile.TemporaryDirectory() as directory:
            contract_path, _ = write_contract(Path(directory), documents)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_container_requests_fail_closed(self) -> None:
        documents = base_documents()
        del documents["rancher"][0]["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]
        with tempfile.TemporaryDirectory() as directory:
            contract_path, _ = write_contract(Path(directory), documents)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("must set CPU and memory requests", result.stderr)

    def test_peak_only_projection_does_not_inflate_steady_state(self) -> None:
        document = deployment("generated", 3, "250m", "256Mi")
        document["spec"]["strategy"] = {"type": "Recreate"}
        document["metadata"]["annotations"] = {
            "capacity.platform.verda.io/mode": "peak-only"
        }
        result = RUNTIME.component_capacity(
            [document],
            {
                "expected_document_count": 1,
                "expected_workload_count": 1,
                "expected_pvc_definition_count": 0,
            },
            3,
            {"longhorn-critical": {"replicas": 3, "replicas_after_one_node_loss": 2}},
            "generated",
            set(),
        )
        self.assertEqual(result.steady.request_cpu_millicores, 0)
        self.assertEqual(result.peak.request_cpu_millicores, 750)

    def test_restartable_init_resources_follow_scheduler_peak_semantics(self) -> None:
        spec = pod_spec("100m", "100Mi", "200m", "200Mi")
        spec["initContainers"] = [
            {
                "name": "sidecar",
                "restartPolicy": "Always",
                "resources": resources("50m", "20Mi", "100m", "40Mi"),
            },
            {
                "name": "init",
                "resources": resources("400m", "200Mi", "500m", "300Mi"),
            },
        ]
        result = RUNTIME.effective_pod_resources(spec, "test pod")
        self.assertEqual(result.request_cpu_millicores, 450)
        self.assertEqual(result.request_memory_bytes, 220 * MIB)
        self.assertEqual(result.limit_cpu_millicores, 600)
        self.assertEqual(result.limit_memory_bytes, 340 * MIB)

    def test_render_checksum_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract_path, contract = write_contract(Path(directory), base_documents())
            contract["components"]["rancher"]["render_sha256"] = "0" * 64
            contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("checksum does not match", result.stderr)

    def test_source_checksum_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            contract_path, contract = write_contract(Path(directory), base_documents())
            contract["components"]["rancher"]["source_inputs"][0]["sha256"] = "0" * 64
            contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--contract", str(contract_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("source checksum changed", result.stderr)


if __name__ == "__main__":
    unittest.main()
