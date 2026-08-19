#!/usr/bin/env python3
"""Focused credential-free contracts for the Phase 5 Argo bootstrap boundary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).parents[2]
BOOTSTRAP = ROOT / "bootstrap" / "argocd"


class Phase5ArgoBootstrapTests(unittest.TestCase):
    def test_chart_identity_and_official_archive_are_checksum_pinned(self) -> None:
        lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text(encoding="utf-8"))
        chart = lock["helm_charts"]["argocd"]
        self.assertEqual(chart["version"], "10.3.3")
        self.assertEqual(chart["app_version"], "v3.5.1")

        checksum = (BOOTSTRAP / "argo-cd-10.3.3.tgz.sha256").read_text(encoding="utf-8")
        self.assertEqual(
            checksum,
            "ce254920357b323aad981e79ab8b1879c33835ef8efd4a1c91743f75e61d8007"
            "  argo-cd-10.3.3.tgz\n",
        )
        install = (BOOTSTRAP / "install.sh").read_text(encoding="utf-8")
        crd_state = (BOOTSTRAP / "crd-state.py").read_text(encoding="utf-8")
        self.assertIn(
            "https://github.com/argoproj/argo-helm/releases/download/"
            "argo-cd-${chart_version}/${chart_archive_name}",
            install,
        )
        self.assertIn("ARGOCD_CHART_ARCHIVE", install)
        self.assertLess(
            install.index("sha256sum --check"), install.index("upgrade --install")
        )
        self.assertLess(
            install.index('template "${release_name}"'),
            install.index("upgrade --install"),
        )
        self.assertIn("kubeconform", install)
        self.assertIn("--atomic", install)
        self.assertIn("--rollback", install)
        self.assertIn("--crds-output", install)
        self.assertIn("--field-manager=verda-phase5-crd-bootstrap", install)
        self.assertIn('missing_crds+=("${crd}")', install)
        self.assertIn("an existing Argo CD CRD has drifted", crd_state)
        self.assertIn("existing Argo CD release is missing a required CRD", install)
        self.assertIn('"${kubectl_base[@]}" create', install)
        self.assertNotIn("apply --server-side", install)
        self.assertLess(
            install.index('"${kubectl_base[@]}" create'),
            install.index("upgrade --install"),
        )
        self.assertLess(
            install.index('wait --for=condition=Established'),
            install.index("upgrade --install"),
        )
        self.assertLess(
            install.index("kubeconform"),
            install.index('"${kubectl_base[@]}" create'),
        )

    def test_values_enforce_private_backend_and_explicit_rbac(self) -> None:
        values = yaml.safe_load((BOOTSTRAP / "values.yaml").read_text(encoding="utf-8"))
        self.assertTrue(values["crds"]["install"])
        self.assertTrue(values["crds"]["keep"])
        self.assertFalse(values["configs"]["cm"]["users.anonymous.enabled"])
        self.assertTrue(values["configs"]["params"]["server.insecure"])
        self.assertFalse(values["global"]["networkPolicy"]["create"])
        lock = yaml.safe_load((ROOT / "versions.lock.yaml").read_text(encoding="utf-8"))
        images = lock["helm_charts"]["argocd"]["images"]
        self.assertEqual(
            values["global"]["image"]["tag"],
            f"v3.5.1@{images['argocd']['digest']}",
        )
        self.assertEqual(
            values["redis"]["image"]["tag"],
            f"8.6.4-alpine@{images['redis']['digest']}",
        )
        self.assertEqual(
            values["configs"]["rbac"]["policy.default"], "role:authenticated"
        )
        health_lua = values["configs"]["cm"][
            "resource.customizations.health.argoproj.io_Application"
        ]
        self.assertIn("obj.status.health.status", health_lua)
        self.assertIn("obj.status.health.message", health_lua)
        self.assertIn("return health", health_lua)
        self.assertFalse(values["server"]["ingress"]["enabled"])
        self.assertFalse(values["server"]["ingressGrpc"]["enabled"])
        self.assertEqual(values["server"]["service"]["type"], "ClusterIP")
        self.assertFalse(values["dex"]["enabled"])
        policy = values["configs"]["rbac"]["policy.csv"]
        self.assertIn(
            "p, role:reviewer, applications, get, platform/*, allow", policy
        )
        self.assertIn(
            "p, role:reviewer, applications, sync, platform/*, deny", policy
        )
        for component in ("controller", "server", "repoServer", "applicationSet"):
            self.assertTrue(values[component]["metrics"]["enabled"])
            self.assertFalse(values[component]["metrics"]["serviceMonitor"]["enabled"])
            self.assertTrue(values[component]["resources"]["requests"])
            self.assertTrue(values[component]["resources"]["limits"])
        self.assertEqual(values["repoServer"]["resources"]["requests"]["cpu"], "50m")

    def test_bootstrap_project_is_the_restricted_fixed_point(self) -> None:
        values = yaml.safe_load((BOOTSTRAP / "values.yaml").read_text(encoding="utf-8"))
        projects = [
            item for item in values["extraObjects"] if item["kind"] == "AppProject"
        ]
        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertEqual(project["metadata"]["name"], "platform-bootstrap")
        spec = project["spec"]
        self.assertEqual(
            spec["sourceRepos"],
            ["https://github.com/kaycee1771/verda-platform-takehome.git"],
        )

        policies = [
            item for item in values["extraObjects"] if item["kind"] == "NetworkPolicy"
        ]
        self.assertEqual(len(policies), 1)
        ingress = policies[0]["spec"]["ingress"]
        self.assertEqual(len(ingress), 1)
        self.assertEqual(ingress[0]["ports"], [{"protocol": "TCP", "port": 8080}])
        source = ingress[0]["from"]
        self.assertEqual(len(source), 1)
        self.assertEqual(
            source[0]["namespaceSelector"]["matchLabels"],
            {"kubernetes.io/metadata.name": "kube-system"},
        )
        self.assertEqual(
            source[0]["podSelector"]["matchLabels"],
            {"app.kubernetes.io/name": "rke2-traefik"},
        )
        self.assertEqual(
            spec["destinations"],
            [{"namespace": "argocd", "server": "https://kubernetes.default.svc"}],
        )
        self.assertEqual(spec["clusterResourceWhitelist"], [])
        self.assertEqual(
            {
                (item["group"], item["kind"])
                for item in spec["namespaceResourceWhitelist"]
            },
            {
                ("argoproj.io", "Application"),
                ("argoproj.io", "ApplicationSet"),
                ("argoproj.io", "AppProject"),
            },
        )

    def test_exactly_one_root_application_has_bounded_ownership(self) -> None:
        documents = [
            item
            for item in yaml.safe_load_all(
                (BOOTSTRAP / "root-application.yaml").read_text(encoding="utf-8")
            )
            if item
        ]
        self.assertEqual(len(documents), 1)
        app = documents[0]
        self.assertEqual(app["kind"], "Application")
        self.assertEqual(app["metadata"]["name"], "platform-root")
        self.assertNotIn("finalizers", app["metadata"])
        spec = app["spec"]
        self.assertEqual(spec["project"], "platform-bootstrap")
        self.assertEqual(
            spec["source"],
            {
                "repoURL": "https://github.com/kaycee1771/verda-platform-takehome.git",
                "targetRevision": "main",
                "path": "gitops/root",
            },
        )
        self.assertEqual(
            spec["destination"],
            {"server": "https://kubernetes.default.svc", "namespace": "argocd"},
        )
        self.assertTrue(spec["syncPolicy"]["automated"]["selfHeal"])
        self.assertFalse(spec["syncPolicy"]["automated"]["prune"])

    def test_runtime_refuses_ambient_kubeconfig_before_cluster_access(self) -> None:
        script = (
            "source 'bootstrap/argocd/runtime-lib.sh'; "
            "phase5_assert_cluster_runtime '.'"
        )
        environment = os.environ.copy()
        environment.pop("KUBECONFIG", None)
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("KUBECONFIG is required", result.stderr)

    def test_scripts_rotate_password_without_secret_arguments(self) -> None:
        script = (ROOT / "scripts" / "bootstrap-gitops.sh").read_text(encoding="utf-8")
        self.assertIn("argocd-initial-admin-secret", script)
        self.assertIn("/api/v1/account/password", script)
        self.assertIn("--data-binary @-", script)
        self.assertIn("ARGOCD_ADMIN_PASSWORD_FILE", script)
        self.assertIn("ARGOCD_REVIEWER_PASSWORD_FILE", script)
        self.assertIn("phase5_assert_outside_repo", script)
        self.assertIn('create_session reviewer "${reviewer_password}"', script)
        self.assertIn('service/argocd-server "${local_port}:80"', script)
        self.assertIn('http://127.0.0.1:${local_port}/healthz', script)
        self.assertNotIn("https://127.0.0.1:${local_port}", script)
        self.assertEqual(script.count("openssl rand -base64 24"), 2)
        self.assertEqual(script.count("[A-Za-z0-9+/=_-]{32}"), 2)
        self.assertNotIn("openssl rand -base64 36", script)
        self.assertNotIn("{32,128}", script)
        for forbidden in (
            "--password",
            "--current-password",
            "--new-password",
            "--auth-token",
        ):
            self.assertNotIn(forbidden, script)

    def test_bootstrap_handoff_writes_fresh_verified_tokens_atomically(self) -> None:
        script = (ROOT / "scripts" / "bootstrap-gitops.sh").read_text(encoding="utf-8")
        self.assertIn("PHASE5_ARGOCD_ADMIN_TOKEN_FILE", script)
        self.assertIn("PHASE5_ARGOCD_REVIEWER_TOKEN_FILE", script)
        self.assertIn("assert_token_output_target", script)
        self.assertIn(
            '[[ "${path}" == /* ]] || phase5_fail', script
        )
        self.assertIn("phase5_assert_outside_repo", script)
        self.assertIn("-L \"${path}\"", script)
        self.assertIn(
            'phase5_require_regular_file "${path}" "${label}"', script
        )
        self.assertIn("\"${target_mode}\" == '600'", script)
        self.assertIn("\"${target_owner}\" == \"$(id -u)\"", script)
        self.assertIn("tempfile.mkstemp", script)
        self.assertIn("os.fchmod(descriptor, 0o600)", script)
        self.assertIn("os.replace(temporary, target)", script)
        self.assertIn('verify_session admin "${admin_session_token}"', script)
        self.assertIn('verify_session reviewer "${reviewer_session_token}"', script)
        self.assertIn(
            'atomic_write_token "${admin_token_path}" "${admin_session_token}"',
            script,
        )
        self.assertIn(
            'atomic_write_token "${reviewer_token_path}" "${reviewer_session_token}"',
            script,
        )
        self.assertLess(
            script.index(
                "assert_token_output_target \"${admin_token_path}\""
            ),
            script.index('"${repo_root}/bootstrap/argocd/install.sh"'),
        )
        self.assertLess(
            script.index('verify_session reviewer "${reviewer_session_token}"'),
            script.index(
                'atomic_write_token "${admin_token_path}" "${admin_session_token}"'
            ),
        )
        self.assertNotIn('>"${admin_token_path}"', script)
        self.assertNotIn('>"${reviewer_token_path}"', script)
        self.assertNotIn('printf \'%s\\n\' "${admin_session_token}"', script)
        self.assertNotIn('printf \'%s\\n\' "${reviewer_session_token}"', script)

    def test_render_validator_rejects_public_routes_and_repository_secrets(
        self,
    ) -> None:
        validator = BOOTSTRAP / "validate-render.py"
        fixtures = (
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "Ingress",
                "metadata": {"name": "forbidden", "namespace": "argocd"},
                "spec": {},
            },
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "repository-credential",
                    "namespace": "argocd",
                    "labels": {"argocd.argoproj.io/secret-type": "repository"},
                },
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, fixture in enumerate(fixtures):
                manifest = root / f"invalid-{index}.yaml"
                inventory = root / f"inventory-{index}.txt"
                crds = root / f"crds-{index}.yaml"
                manifest.write_text(yaml.safe_dump(fixture), encoding="utf-8")
                result = subprocess.run(
                    [
                        "python",
                        str(validator),
                        "--manifest",
                        str(manifest),
                        "--inventory",
                        str(inventory),
                        "--crds-output",
                        str(crds),
                    ],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(inventory.exists())
                self.assertFalse(crds.exists())

    def test_crd_state_helper_is_create_only_and_rejects_retained_drift(self) -> None:
        helper = BOOTSTRAP / "crd-state.py"
        names = (
            "applications.argoproj.io",
            "applicationsets.argoproj.io",
            "appprojects.argoproj.io",
        )
        documents = []
        for name in names:
            documents.append(
                {
                    "apiVersion": "apiextensions.k8s.io/v1",
                    "kind": "CustomResourceDefinition",
                    "metadata": {
                        "name": name,
                        "labels": {"app.kubernetes.io/managed-by": "Helm"},
                        "annotations": {
                            "helm.sh/resource-policy": "keep",
                            "meta.helm.sh/release-name": "argocd",
                            "meta.helm.sh/release-namespace": "argocd",
                        },
                    },
                    "spec": {
                        "group": "argoproj.io",
                        "scope": "Namespaced",
                        "names": {"plural": name.split(".", 1)[0], "kind": "Fixture"},
                        "versions": [{"name": "v1alpha1", "served": True, "storage": True}],
                    },
                }
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle.yaml"
            bundle.write_text(yaml.safe_dump_all(documents), encoding="utf-8")
            existing = root / "existing.json"
            retained = dict(documents[0])
            retained["spec"] = dict(documents[0]["spec"])
            retained["spec"]["conversion"] = {"strategy": "None"}
            existing.write_text(json.dumps(retained), encoding="utf-8")
            subprocess.run(
                [
                    "python",
                    str(helper),
                    "--bundle",
                    str(bundle),
                    "verify",
                    "--name",
                    names[0],
                    "--existing",
                    str(existing),
                ],
                cwd=ROOT,
                check=True,
            )

            missing = root / "missing.yaml"
            subprocess.run(
                [
                    "python",
                    str(helper),
                    "--bundle",
                    str(bundle),
                    "select",
                    "--output",
                    str(missing),
                    names[1],
                ],
                cwd=ROOT,
                check=True,
            )
            selected = [item for item in yaml.safe_load_all(missing.read_text()) if item]
            self.assertEqual([item["metadata"]["name"] for item in selected], [names[1]])

            foreign = json.loads(existing.read_text(encoding="utf-8"))
            foreign["metadata"]["labels"]["app.kubernetes.io/managed-by"] = "foreign"
            existing.write_text(json.dumps(foreign), encoding="utf-8")
            rejected = subprocess.run(
                [
                    "python",
                    str(helper),
                    "--bundle",
                    str(bundle),
                    "verify",
                    "--name",
                    names[0],
                    "--existing",
                    str(existing),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)

            drifted = json.loads(json.dumps(retained))
            drifted["spec"]["scope"] = "Cluster"
            existing.write_text(json.dumps(drifted), encoding="utf-8")
            rejected = subprocess.run(
                [
                    "python",
                    str(helper),
                    "--bundle",
                    str(bundle),
                    "verify",
                    "--name",
                    names[0],
                    "--existing",
                    str(existing),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)

    def test_shell_entrypoints_are_syntax_valid(self) -> None:
        for path in (
            BOOTSTRAP / "install.sh",
            BOOTSTRAP / "runtime-lib.sh",
            ROOT / "scripts" / "bootstrap-gitops.sh",
            ROOT / "scripts" / "wait-for-argocd.sh",
        ):
            with self.subTest(path=path.name):
                relative = path.relative_to(ROOT).as_posix()
                subprocess.run(["bash", "-n", relative], cwd=ROOT, check=True)

    def test_checksum_file_has_no_accidental_encoding_change(self) -> None:
        payload = (BOOTSTRAP / "argo-cd-10.3.3.tgz.sha256").read_bytes()
        self.assertEqual(len(payload.splitlines()), 1)
        self.assertNotEqual(hashlib.sha256(payload).hexdigest(), "0" * 64)


if __name__ == "__main__":
    unittest.main()
