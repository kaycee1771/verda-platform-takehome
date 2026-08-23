from __future__ import annotations

import copy
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "check-root-admission.py"
SPEC = importlib.util.spec_from_file_location("phase6_root_admission", SCRIPT)
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)

FIXTURE_FILES = (
    "config/phase6-root-admission.yaml",
    "config/phase6-capacity-admission.yaml",
    "gitops/root/kustomization.yaml",
    "gitops/root/phase6/kustomization.yaml",
    "platform/management/rancher/values.yaml",
    "platform/management/harbor/secrets/values.yaml",
    "platform/management/harbor/postgresql/values.yaml",
    "platform/management/harbor/service/values.yaml",
    "platform/management/loki/activation-contract.yaml",
    "observability/alloy/image-lock.yaml",
    "platform/management/velero/activation-contract.yaml",
    "platform/management/monitoring/image-lock.yaml",
    "platform/management/sealed-secrets/values.yaml",
    "platform/management/kyverno/values.yaml",
    "environments/dev/namespace/registry-credentials.yaml",
    "environments/staging/namespace/registry-credentials.yaml",
    "environments/prod/namespace/registry-credentials.yaml",
    "applications/stage-a-smoke/values-dev.yaml",
    "applications/stage-a-smoke/values-staging.yaml",
    "applications/stage-a-smoke/values-prod.yaml",
)


def read_yaml(root: Path, relative: str) -> dict:
    return yaml.safe_load((root / relative).read_text(encoding="utf-8"))


def write_yaml(root: Path, relative: str, document: dict) -> None:
    (root / relative).write_text(
        "---\n" + yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )


def copy_fixture(destination: Path) -> None:
    for relative in FIXTURE_FILES:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    candidate = destination / "gitops" / "root" / "phase6"
    candidate.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "gitops" / "root" / "phase6").glob("*.yaml"):
        shutil.copy2(source, candidate / source.name)


def include_candidate(root: Path) -> None:
    document = read_yaml(root, "gitops/root/kustomization.yaml")
    document["resources"].append("phase6")
    write_yaml(root, "gitops/root/kustomization.yaml", document)


def fully_admit(root: Path) -> None:
    include_candidate(root)

    ledger = read_yaml(root, "config/phase6-root-admission.yaml")
    ledger["admission_status"] = "admitted"
    for group in ledger["gates"].values():
        for gate in group:
            group[gate] = True
    write_yaml(root, "config/phase6-root-admission.yaml", ledger)

    capacity = read_yaml(root, "config/phase6-capacity-admission.yaml")
    capacity["admission_status"] = "ready"
    for key, value in capacity["baseline"].items():
        if value is None:
            capacity["baseline"][key] = 1
    for index, component in enumerate(capacity["components"].values(), start=1):
        component["render_sha256"] = format(index, "064x")
        component["expected_document_count"] = 1
        component["expected_workload_count"] = 1
        component["expected_pvc_definition_count"] = 0
    write_yaml(root, "config/phase6-capacity-admission.yaml", capacity)

    rancher = read_yaml(root, "platform/management/rancher/values.yaml")
    rancher["gates"] = {key: True for key in rancher["gates"]}
    rancher["rancher"]["enabled"] = True
    write_yaml(root, "platform/management/rancher/values.yaml", rancher)

    harbor_secrets = read_yaml(root, "platform/management/harbor/secrets/values.yaml")
    harbor_secrets["enabled"] = True
    harbor_secrets["gates"] = {key: True for key in harbor_secrets["gates"]}
    harbor_secrets["ciphertexts"] = {
        key: "Ag" + format(index, "090x")
        for index, key in enumerate(harbor_secrets["ciphertexts"], start=1)
    }
    write_yaml(root, "platform/management/harbor/secrets/values.yaml", harbor_secrets)

    postgres = read_yaml(root, "platform/management/harbor/postgresql/values.yaml")
    postgres["enabled"] = True
    postgres["gates"] = {key: True for key in postgres["gates"]}
    write_yaml(root, "platform/management/harbor/postgresql/values.yaml", postgres)

    harbor = read_yaml(root, "platform/management/harbor/service/values.yaml")
    harbor["gates"] = {key: True for key in harbor["gates"]}
    harbor["harbor"]["enabled"] = True
    write_yaml(root, "platform/management/harbor/service/values.yaml", harbor)

    for relative in (
        "platform/management/loki/activation-contract.yaml",
        "observability/alloy/image-lock.yaml",
        "platform/management/velero/activation-contract.yaml",
    ):
        contract = read_yaml(root, relative)
        contract["activation_status"] = "ready"
        contract["blocking_gates"] = {key: True for key in contract["blocking_gates"]}
        if "object_storage" in contract:
            contract["object_storage"]["status"] = "live-proven"
        write_yaml(root, relative, contract)

    for environment in ("dev", "staging", "prod"):
        relative = f"environments/{environment}/namespace/registry-credentials.yaml"
        sealed = read_yaml(root, relative)
        sealed["spec"]["encryptedData"][".dockerconfigjson"] = "Ag" + "B" * 90
        write_yaml(root, relative, sealed)

        relative = f"applications/stage-a-smoke/values-{environment}.yaml"
        smoke = read_yaml(root, relative)
        smoke["activation"] = {key: True for key in smoke["activation"]}
        smoke["certificate"]["bootstrapEnabled"] = True
        smoke["certificate"]["stagingCertificateVerified"] = True
        smoke["image"]["digest"] = "sha256:" + "c" * 64
        write_yaml(root, relative, smoke)


def run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class Phase6RootAdmissionTests(unittest.TestCase):
    def fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        copy_fixture(root)
        return temporary, root

    def test_current_tree_is_blocked_and_candidate_is_inert(self) -> None:
        result = run_checker(ROOT)
        self.assertEqual(result.returncode, 1)
        self.assertIn("root admission_status must equal admitted", result.stderr)
        root = read_yaml(ROOT, "gitops/root/kustomization.yaml")
        self.assertNotIn("phase6", [str(item).rstrip("/") for item in root["resources"]])

    def test_synthetic_fully_admitted_fixture_passes(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        fully_admit(root)
        calls = []
        passed, reason = RUNTIME.evaluate(root, lambda candidate: calls.append(candidate))
        self.assertTrue(passed, reason)
        self.assertEqual(calls, [root])

    def test_root_cannot_pass_without_regeneration_and_non_projection_admission(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("render-capacity-inputs.py", source)
        self.assertIn("--verify-contract", source)
        self.assertIn("capacity-admission.py", source)
        self.assertNotIn("--projection-only", source)

    def test_capacity_preflight_failure_blocks_otherwise_admitted_root(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        fully_admit(root)

        def fail_preflight(_root: Path) -> None:
            raise RUNTIME.AdmissionError("capacity non-projection admission did not pass")

        passed, reason = RUNTIME.evaluate(root, fail_preflight)
        self.assertFalse(passed)
        self.assertEqual(reason, "Phase 6 candidate is included before every admission gate is satisfied")

    def test_premature_root_inclusion_is_rejected_without_gate_details(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        include_candidate(root)
        result = run_checker(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("included before every admission gate", result.stderr)
        self.assertNotIn("ciphertext", result.stderr.lower())

    def test_each_sanitized_ledger_gate_is_fail_closed(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        fully_admit(root)
        root_document = read_yaml(root, "gitops/root/kustomization.yaml")
        root_document["resources"].remove("phase6")
        write_yaml(root, "gitops/root/kustomization.yaml", root_document)
        ledger = read_yaml(root, "config/phase6-root-admission.yaml")
        for group_name, group in ledger["gates"].items():
            for gate_name in group:
                candidate = copy.deepcopy(ledger)
                candidate["gates"][group_name][gate_name] = False
                write_yaml(root, "config/phase6-root-admission.yaml", candidate)
                result = run_checker(root)
                self.assertEqual(result.returncode, 1, f"{group_name}.{gate_name}")
                self.assertIn(f"{group_name}.{gate_name} is not satisfied", result.stderr)

    def test_component_contract_cannot_be_bypassed_by_green_ledger(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        fully_admit(root)
        root_document = read_yaml(root, "gitops/root/kustomization.yaml")
        root_document["resources"].remove("phase6")
        write_yaml(root, "gitops/root/kustomization.yaml", root_document)
        loki = read_yaml(root, "platform/management/loki/activation-contract.yaml")
        loki["blocking_gates"]["lifecycle_policy_proven"] = False
        write_yaml(root, "platform/management/loki/activation-contract.yaml", loki)
        result = run_checker(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Loki blocking gates are not all satisfied", result.stderr)

    def test_harbor_ciphertext_sentinel_is_rejected(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        fully_admit(root)
        root_document = read_yaml(root, "gitops/root/kustomization.yaml")
        root_document["resources"].remove("phase6")
        write_yaml(root, "gitops/root/kustomization.yaml", root_document)
        values = read_yaml(root, "platform/management/harbor/secrets/values.yaml")
        first = next(iter(values["ciphertexts"]))
        values["ciphertexts"][first] = "REQUIRED_SEALED_CIPHERTEXT_TEST"
        write_yaml(root, "platform/management/harbor/secrets/values.yaml", values)
        result = run_checker(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unresolved sentinel", result.stderr)
        self.assertNotIn("REQUIRED_SEALED", result.stderr)

    def test_registry_ciphertext_and_stage_a_digest_sentinels_are_rejected(self) -> None:
        for relative, mutate in (
            (
                "environments/dev/namespace/registry-credentials.yaml",
                lambda doc: doc["spec"]["encryptedData"].update({".dockerconfigjson": "REQUIRED_SEALED_CIPHERTEXT_TEST"}),
            ),
            (
                "applications/stage-a-smoke/values-dev.yaml",
                lambda doc: doc["image"].update({"digest": "sha256:REQUIRED_STAGE_A_SMOKE_IMAGE_DIGEST"}),
            ),
        ):
            with self.subTest(relative=relative):
                temporary, root = self.fixture()
                self.addCleanup(temporary.cleanup)
                fully_admit(root)
                root_document = read_yaml(root, "gitops/root/kustomization.yaml")
                root_document["resources"].remove("phase6")
                write_yaml(root, "gitops/root/kustomization.yaml", root_document)
                document = read_yaml(root, relative)
                mutate(document)
                write_yaml(root, relative, document)
                result = run_checker(root)
                self.assertEqual(result.returncode, 1)
                self.assertIn("unresolved sentinel", result.stderr)

    def test_script_has_no_live_client_surface(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("kubectl", "helm install", "curl ", "requests.", "boto", "ssh "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
