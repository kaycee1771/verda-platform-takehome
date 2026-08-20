import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SEALED = ROOT / "platform" / "management" / "sealed-secrets"
KYVERNO = ROOT / "platform" / "management" / "kyverno"
POLICIES = ROOT / "policies" / "kyverno"
DIGEST_TAG = re.compile(r"^[^@]+@sha256:[0-9a-f]{64}$")


def load_one(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain one YAML mapping")
    return value


class Phase6SealedSecretsContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = load_one(SEALED / "values.yaml")

    def test_chart_provenance_and_controller_image_are_pinned(self):
        lock = load_one(ROOT / "versions.lock.yaml")["helm_charts"]["sealed_secrets"]
        self.assertEqual(lock["version"], "2.19.0")
        self.assertEqual(lock["app_version"], "0.38.1")
        self.assertRegex(lock["archive_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(lock["source"], "https://bitnami.github.io/sealed-secrets/index.yaml")

        image = self.values["image"]
        self.assertEqual(image["registry"], "ghcr.io")
        self.assertEqual(image["repository"], "bitnami/sealed-secrets-controller")
        self.assertRegex(image["tag"], DIGEST_TAG)
        self.assertTrue(image["tag"].startswith("0.38.1@sha256:"))
        central = lock["images"]["controller"]
        self.assertEqual(
            f"{image['registry']}/{image['repository']}:{image['tag'].split('@', 1)[0]}",
            central["reference"],
        )
        self.assertEqual(image["tag"].split("@", 1)[1], central["digest"])

    def test_controller_is_capacity_explicit_and_one_node_tolerant(self):
        self.assertEqual(self.values["replicaCount"], 2)
        self.assertEqual(self.values["resources"]["requests"], {"cpu": "50m", "memory": "64Mi"})
        self.assertEqual(self.values["resources"]["limits"], {"memory": "256Mi"})
        self.assertEqual(self.values["pdb"], {"create": True, "minAvailable": 1})
        self.assertEqual(
            self.values["topologySpreadConstraints"][0]["whenUnsatisfiable"],
            "DoNotSchedule",
        )
        required = self.values["affinity"]["podAntiAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]
        self.assertEqual(required[0]["topologyKey"], "kubernetes.io/hostname")

    def test_controller_rbac_and_exposure_are_bounded(self):
        self.assertFalse(self.values["rbac"]["serviceProxier"]["create"])
        self.assertFalse(self.values["rbac"]["serviceProxier"]["bind"])
        self.assertFalse(self.values["ingress"]["enabled"])
        self.assertFalse(self.values["watchForSecrets"])
        security = self.values["containerSecurityContext"]
        self.assertTrue(security["runAsNonRoot"])
        self.assertTrue(security["readOnlyRootFilesystem"])
        self.assertFalse(security["allowPrivilegeEscalation"])
        self.assertEqual(security["capabilities"]["drop"], ["ALL"])

    def test_monitoring_is_owned_after_prometheus_crds(self):
        self.assertFalse(self.values["metrics"]["serviceMonitor"]["enabled"])
        monitor = load_one(SEALED / "monitoring" / "servicemonitor.yaml")
        self.assertEqual(monitor["kind"], "ServiceMonitor")
        self.assertEqual(monitor["spec"]["endpoints"][0]["port"], "metrics")
        self.assertEqual(
            monitor["spec"]["selector"]["matchLabels"]["app.kubernetes.io/component"],
            "metrics",
        )

    def test_strict_scope_and_recovery_contract_are_explicit(self):
        desired_files = list(SEALED.rglob("*.yaml"))
        self.assertFalse(
            any(
                doc.get("kind") == "SealedSecret"
                for path in desired_files
                for doc in yaml.safe_load_all(path.read_text(encoding="utf-8"))
                if isinstance(doc, dict)
            ),
            "offline desired state must not fabricate ciphertext before the live certificate exists",
        )
        runbook = (ROOT / "docs" / "runbooks" / "sealed-secrets-recovery.md").read_text(
            encoding="utf-8"
        )
        for token in ("--scope strict", "--namespace <exact-namespace>", "--name <exact-secret-name>"):
            self.assertIn(token, runbook)
        self.assertIn("encrypted external recovery backup", runbook)


class Phase6KyvernoContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = load_one(KYVERNO / "values.yaml")

    def test_chart_provenance_and_all_runtime_images_are_pinned(self):
        lock = load_one(ROOT / "versions.lock.yaml")["helm_charts"]["kyverno"]
        self.assertEqual(lock["version"], "3.8.2")
        self.assertEqual(lock["app_version"], "v1.18.2")
        self.assertRegex(lock["archive_sha256"], r"^[0-9a-f]{64}$")

        images = [
            self.values["admissionController"]["initContainer"]["image"],
            self.values["admissionController"]["container"]["image"],
            self.values["backgroundController"]["image"],
            self.values["cleanupController"]["image"],
            self.values["reportsController"]["image"],
            self.values["webhooksCleanup"]["image"],
            self.values["test"]["image"],
        ]
        for image in images:
            with self.subTest(image=image["repository"]):
                self.assertRegex(image["tag"], DIGEST_TAG)
                self.assertTrue(image["tag"].startswith("v1.18.2@sha256:"))
                self.assertEqual(image["pullPolicy"], "IfNotPresent")

        enabled = {
            "admission_init": images[0],
            "admission": images[1],
            "background": images[2],
            "reports": images[4],
            "readiness_checker": images[5],
        }
        central = lock["images"]
        self.assertEqual(set(central), set(enabled))
        for role, image in enabled.items():
            tag, digest = image["tag"].split("@", 1)
            self.assertEqual(
                central[role],
                {
                    "reference": f"{image['registry']}/{image['repository']}:{tag}",
                    "digest": digest,
                },
            )

    def test_audit_first_features_fail_open_and_scan_in_background(self):
        features = self.values["features"]
        self.assertTrue(features["forceFailurePolicyIgnore"]["enabled"])
        self.assertTrue(features["backgroundScan"]["enabled"])
        self.assertEqual(features["backgroundScan"]["backgroundScanInterval"], "1h")
        self.assertTrue(features["policyReports"]["enabled"])
        self.assertTrue(features["policyExceptions"]["enabled"])
        self.assertEqual(features["policyExceptions"]["namespace"], "kyverno")
        self.assertFalse(features["generateValidatingAdmissionPolicy"]["enabled"])

    def test_controller_capacity_is_deliberate(self):
        admission = self.values["admissionController"]
        self.assertEqual(admission["replicas"], 2)
        self.assertEqual(admission["container"]["resources"]["requests"]["cpu"], "100m")
        self.assertTrue(admission["podDisruptionBudget"]["enabled"])
        self.assertEqual(admission["podDisruptionBudget"]["minAvailable"], 1)
        self.assertEqual(
            admission["topologySpreadConstraints"][0]["whenUnsatisfiable"],
            "DoNotSchedule",
        )
        self.assertEqual(self.values["backgroundController"]["replicas"], 1)
        self.assertEqual(self.values["reportsController"]["replicas"], 1)
        self.assertFalse(self.values["cleanupController"]["enabled"])
        self.assertFalse(self.values["crds"]["migration"]["enabled"])

    def test_metrics_services_and_late_servicemonitor_are_explicit(self):
        for name in ("admissionController", "backgroundController", "reportsController"):
            with self.subTest(controller=name):
                controller = self.values[name]
                self.assertTrue(controller["metricsService"]["create"])
                self.assertFalse(controller["serviceMonitor"]["enabled"])
        monitor = load_one(KYVERNO / "monitoring" / "servicemonitor.yaml")
        components = monitor["spec"]["selector"]["matchExpressions"][0]["values"]
        self.assertEqual(
            set(components),
            {"admission-controller", "background-controller", "reports-controller"},
        )

    def test_every_phase6_policy_is_audit_only_and_demo_scoped(self):
        policies = []
        for path in (POLICIES / "base").glob("*.yaml"):
            document = load_one(path)
            if document.get("kind") == "ClusterPolicy":
                policies.append(document)
        self.assertGreaterEqual(len(policies), 2)
        for policy in policies:
            with self.subTest(policy=policy["metadata"]["name"]):
                spec = policy["spec"]
                self.assertEqual(spec["validationFailureAction"], "Audit")
                self.assertTrue(spec["background"])
                self.assertEqual(spec["failurePolicy"], "Ignore")
                self.assertNotIn("exclude", str(spec))

        workload = next(p for p in policies if p["metadata"]["name"] == "phase6-workload-baseline")
        namespaces = {
            namespace
            for rule in workload["spec"]["rules"]
            for match in rule["match"]["any"]
            for namespace in match["resources"]["namespaces"]
        }
        self.assertEqual(namespaces, {"demo-dev", "demo-staging", "demo-prod"})

    def test_sealed_secret_scope_policy_rejects_broad_annotations(self):
        policy = load_one(POLICIES / "base" / "require-strict-sealing-scope.yaml")
        rendered = yaml.safe_dump(policy, sort_keys=True)
        self.assertIn("sealedsecrets.bitnami.com/cluster-wide", rendered)
        self.assertIn("sealedsecrets.bitnami.com/namespace-wide", rendered)
        self.assertEqual(policy["spec"]["validationFailureAction"], "Audit")

    def test_exception_template_is_narrow_and_never_active_by_default(self):
        self.assertFalse(list((POLICIES / "exceptions").glob("*.yaml")))
        template = (POLICIES / "exceptions" / "policy-exception.yaml.tmpl").read_text(
            encoding="utf-8"
        )
        for token in (
            "__POLICY_NAME__",
            "__RULE_NAME__",
            "__RESOURCE_NAMESPACE__",
            "__RESOURCE_NAME__",
            "__SERVICE_ACCOUNT__",
            "__IMAGE_REFERENCE_AT_SHA256_DIGEST__",
            "__OWNER__",
            "__REASON__",
            "__REVIEW_BY_YYYY_MM_DD__",
        ):
            self.assertIn(token, template)
        self.assertNotIn("namespaces:\n            - '*'", template)
        self.assertNotIn("ruleNames:\n        - '*'", template)


class Phase6SecretMaterialTests(unittest.TestCase):
    def test_owned_manifests_contain_no_plaintext_secret_or_private_key(self):
        paths = [
            *SEALED.rglob("*.yaml"),
            *KYVERNO.rglob("*.yaml"),
            *(POLICIES / "base").rglob("*.yaml"),
        ]
        forbidden = (
            "kind: Secret\n",
            "stringData:",
            "BEGIN PRIVATE KEY",
            "AGE-SECRET-KEY-",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                with self.subTest(path=path, pattern=pattern):
                    self.assertNotIn(pattern, text)


if __name__ == "__main__":
    unittest.main()
