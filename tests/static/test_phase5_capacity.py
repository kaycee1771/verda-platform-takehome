import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase5" / "capacity-report.py"


def load_module():
    spec = importlib.util.spec_from_file_location("phase5_capacity_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Phase5CapacityTests(unittest.TestCase):
    def test_quantities_and_restartable_init_semantics(self):
        module = load_module()
        self.assertEqual(module.parse_quantity("1500m", "cpu"), module.Decimal("1.5"))
        self.assertEqual(
            module.parse_quantity("2Gi", "memory"), module.Decimal(2 * 1024**3)
        )
        pod = {
            "spec": {
                "containers": [
                    {"resources": {"requests": {"cpu": "500m", "memory": "1Gi"}}}
                ],
                "initContainers": [
                    {
                        "restartPolicy": "Always",
                        "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}},
                    },
                    {"resources": {"requests": {"cpu": "1", "memory": "2Gi"}}},
                ],
            }
        }
        self.assertEqual(
            module.effective_pod_resource(pod, "requests", "cpu"), module.Decimal("1.1")
        )
        self.assertEqual(
            module.effective_pod_resource(pod, "requests", "memory"),
            module.Decimal(2 * 1024**3 + 128 * 1024**2),
        )

    def test_identity_free_aggregate_and_three_node_gate(self):
        nodes = {
            "items": [
                {
                    "metadata": {"name": f"sensitive-node-{index}"},
                    "spec": {},
                    "status": {
                        "allocatable": {"cpu": "3", "memory": "12Gi"},
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                }
                for index in range(3)
            ]
        }
        pods = {
            "items": [
                {
                    "metadata": {"name": "sensitive-pod"},
                    "spec": {
                        "nodeName": "sensitive-node-0",
                        "containers": [
                            {
                                "resources": {
                                    "requests": {"cpu": "1", "memory": "1Gi"},
                                    "limits": {"cpu": "2", "memory": "2Gi"},
                                }
                            }
                        ],
                    },
                    "status": {"phase": "Running"},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            node_path = Path(directory) / "nodes.json"
            pod_path = Path(directory) / "pods.json"
            node_path.write_text(json.dumps(nodes), encoding="utf-8")
            pod_path.write_text(json.dumps(pods), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--nodes",
                    str(node_path),
                    "--pods",
                    str(pod_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["nodes_ready_schedulable"], 3)
            self.assertEqual(report["one_node_loss_cpu_headroom_cores"], 5.0)
            self.assertNotIn("sensitive", result.stdout)

            nodes["items"][0]["status"]["conditions"][0]["status"] = "False"
            node_path.write_text(json.dumps(nodes), encoding="utf-8")
            failure = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--nodes",
                    str(node_path),
                    "--pods",
                    str(pod_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failure.returncode, 0)


if __name__ == "__main__":
    unittest.main()
