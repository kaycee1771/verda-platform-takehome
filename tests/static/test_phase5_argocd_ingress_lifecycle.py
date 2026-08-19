"""Behavioral contract for bootstrap verification before and after GitOps exposure."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "phase5" / "verify-argocd-ingress.py"
VALUES = ROOT / "platform" / "management" / "ingress" / "argocd" / "values.yaml"
WAIT = ROOT / "scripts" / "wait-for-argocd.sh"


def ingress() -> dict[str, object]:
    return {
        "metadata": {
            "name": "argocd-server",
            "namespace": "argocd",
            "annotations": {
                "argocd.argoproj.io/ignore-healthcheck": "true",
                "argocd.argoproj.io/tracking-id": (
                    "argocd-public-ingress:networking.k8s.io/Ingress:argocd/argocd-server"
                ),
                "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
                "traefik.ingress.kubernetes.io/router.tls": "true",
                "verda.platform/authentication-boundary": "argocd-rbac",
                "verda.platform/cli-mode": "grpc-web",
                "verda.platform/network-policy-owner": "bootstrap-helm",
                "verda.platform/exposure-gates": "verified",
            },
        },
        "spec": {
            "ingressClassName": "traefik",
            "tls": [
                {
                    "hosts": ["argocd.95-133-252-214.sslip.io"],
                    "secretName": "argocd-ingress-tls",
                }
            ],
            "rules": [
                {
                    "host": "argocd.95-133-252-214.sslip.io",
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": "argocd-server",
                                        "port": {"name": "http"},
                                    }
                                },
                            }
                        ]
                    },
                }
            ],
        },
    }


class Phase5ArgocdIngressLifecycleTests(unittest.TestCase):
    def run_helper(self, items: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python", str(HELPER), "--values", str(VALUES)],
            cwd=ROOT,
            input=json.dumps({"items": items}),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_day_zero_and_exact_git_owned_ingress_are_the_only_success_states(self) -> None:
        day_zero = self.run_helper([])
        self.assertEqual(day_zero.returncode, 0, day_zero.stderr)
        self.assertEqual(day_zero.stdout.strip(), "ClusterIP-only")

        converged = self.run_helper([ingress()])
        self.assertEqual(converged.returncode, 0, converged.stderr)
        self.assertEqual(converged.stdout.strip(), "git-owned-tls-ingress")

    def test_unknown_extra_or_mutated_ingress_fails_closed(self) -> None:
        approved = ingress()
        cases: list[list[dict[str, object]]] = [
            [approved, ingress()],
            [{"metadata": {"name": "other", "namespace": "argocd"}, "spec": {}}],
        ]
        for key, value in (
            ("argocd.argoproj.io/tracking-id", "other-owner"),
            ("verda.platform/exposure-gates", "unverified"),
        ):
            mutated = json.loads(json.dumps(approved))
            mutated["metadata"]["annotations"][key] = value
            cases.append([mutated])
        mutated = json.loads(json.dumps(approved))
        mutated["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"] = "other"
        cases.append([mutated])

        for items in cases:
            with self.subTest(items=items):
                result = self.run_helper(items)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_waiter_uses_checked_validator_and_reports_the_validated_state(self) -> None:
        source = WAIT.read_text(encoding="utf-8")
        self.assertIn('ingress_json=$("${kubectl_base[@]}" -n argocd get ingress -o json)', source)
        self.assertIn('exposure=$(python3 "${ingress_validator}" --values "${ingress_values}"', source)
        self.assertIn("exposure=%s", source)
        self.assertNotIn("must not have ingress during day-zero bootstrap", source)


if __name__ == "__main__":
    unittest.main()
