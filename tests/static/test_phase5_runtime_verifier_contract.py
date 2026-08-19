#!/usr/bin/env python3
"""Behavioral contract for the credential-safe Phase 5 runtime verifier."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "phase5" / "verify-runtime.sh"


def write_file(path: pathlib.Path, content: str, mode: int = 0o600) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def write_executable(path: pathlib.Path, content: str) -> None:
    write_file(path, textwrap.dedent(content).lstrip(), 0o700)


class Phase5RuntimeVerifierContractTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if os.name != "posix" or shutil.which("bash") is None:
            self.skipTest("behavioral verifier tests run in the pinned Linux quality image")

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.host = "argocd.192-0-2-10.sslip.io"

        self.kubeconfig = self.root / "kubeconfig"
        self.admin_token = self.root / "admin.token"
        self.reviewer_token = self.root / "reviewer.token"
        self.endpoints = self.root / "endpoints"
        write_file(self.kubeconfig, "apiVersion: v1\nkind: Config\n")
        write_file(self.admin_token, "admin-token-value-with-safe-length\n")
        write_file(self.reviewer_token, "reviewer-token-value-with-safe-length\n")
        write_file(
            self.endpoints,
            "192.0.2.10\n192.0.2.11\n192.0.2.12\n",
        )

        self.applications = self.root / "applications.json"
        self.deployments = self.root / "deployments.json"
        self.certificates = self.root / "certificates.json"
        self.issuers = self.root / "issuers.json"
        self.ingresses = self.root / "ingresses.json"
        self.argocd_log = self.root / "argocd-arguments.log"
        self._write_fixtures()
        self._write_mocks()

        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PHASE5_KUBECONFIG": str(self.kubeconfig),
                "PHASE5_KUBE_CONTEXT": "verda-management",
                "PHASE5_PUBLIC_HOST": self.host,
                "PHASE5_ARGO_ROOT_APP": "platform-root",
                "PHASE5_ARGO_EXPECTED_CHILDREN": "platform-cert-manager,platform-ingress",
                "PHASE5_ARGOCD_ADMIN_TOKEN_FILE": str(self.admin_token),
                "PHASE5_ARGOCD_REVIEWER_TOKEN_FILE": str(self.reviewer_token),
                "PHASE5_ARGOCD_ADMIN_SUBJECT": "admin-user",
                "PHASE5_ARGOCD_REVIEWER_SUBJECT": "reviewer-user",
                "PHASE5_EXTERNAL_ENDPOINTS_FILE": str(self.endpoints),
                "PHASE5_HTTP_MODE": "acme-only",
                "PHASE5_KUBECTL_BIN": str(self.bin / "kubectl"),
                "PHASE5_ARGOCD_BIN": str(self.bin / "argocd"),
                "PHASE5_CURL_BIN": str(self.bin / "curl"),
                "PHASE5_OPENSSL_BIN": str(self.bin / "openssl"),
                "PHASE5_NC_BIN": str(self.bin / "nc"),
                "PHASE5_TIMEOUT_BIN": str(self.bin / "timeout"),
                "MOCK_APPLICATIONS": str(self.applications),
                "MOCK_DEPLOYMENTS": str(self.deployments),
                "MOCK_CERTIFICATES": str(self.certificates),
                "MOCK_ISSUERS": str(self.issuers),
                "MOCK_INGRESSES": str(self.ingresses),
                "MOCK_ARGOCD_LOG": str(self.argocd_log),
            }
        )

    def _write_fixtures(self) -> None:
        healthy = {
            "health": {"status": "Healthy"},
            "sync": {"status": "Synced"},
        }
        write_file(
            self.applications,
            json.dumps(
                {
                    "items": [
                        {"metadata": {"name": name}, "status": healthy}
                        for name in (
                            "platform-root",
                            "platform-cert-manager",
                            "platform-ingress",
                        )
                    ]
                }
            ),
        )

        deployment_items = []
        for name in (
            "cert-manager",
            "cert-manager-webhook",
            "cert-manager-cainjector",
        ):
            deployment_items.append(
                {
                    "metadata": {"name": name, "generation": 4},
                    "spec": {"replicas": 2},
                    "status": {
                        "observedGeneration": 4,
                        "replicas": 2,
                        "updatedReplicas": 2,
                        "readyReplicas": 2,
                        "availableReplicas": 2,
                        "unavailableReplicas": 0,
                    },
                }
            )
        write_file(self.deployments, json.dumps({"items": deployment_items}))

        ready = [{"type": "Ready", "status": "True"}]
        write_file(
            self.certificates,
            json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"name": "argocd-staging"},
                            "spec": {
                                "secretName": "argocd-staging-tls",
                                "dnsNames": [self.host],
                                "issuerRef": {
                                    "group": "cert-manager.io",
                                    "kind": "Issuer",
                                    "name": "letsencrypt-staging",
                                },
                            },
                            "status": {"conditions": ready},
                        },
                        {
                            "metadata": {"name": "argocd-production"},
                            "spec": {
                                "secretName": "argocd-ingress-tls",
                                "dnsNames": [self.host],
                                "issuerRef": {
                                    "group": "cert-manager.io",
                                    "kind": "Issuer",
                                    "name": "letsencrypt-production",
                                },
                            },
                            "status": {"conditions": ready},
                        },
                    ]
                }
            ),
        )
        write_file(
            self.issuers,
            json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"name": "letsencrypt-staging"},
                            "spec": {
                                "acme": {
                                    "server": "https://acme-staging-v02.api.letsencrypt.org/directory"
                                }
                            },
                            "status": {"conditions": ready},
                        },
                        {
                            "metadata": {"name": "letsencrypt-production"},
                            "spec": {
                                "acme": {
                                    "server": "https://acme-v02.api.letsencrypt.org/directory"
                                }
                            },
                            "status": {"conditions": ready},
                        },
                    ]
                }
            ),
        )
        write_file(
            self.ingresses,
            json.dumps(
                {
                    "items": [
                        {
                            "metadata": {
                                "name": "argocd-server",
                                "namespace": "argocd",
                                "annotations": {
                                    "traefik.ingress.kubernetes.io/router.entrypoints": "websecure"
                                },
                            },
                            "spec": {
                                "ingressClassName": "traefik",
                                "tls": [
                                    {
                                        "hosts": [self.host],
                                        "secretName": "argocd-ingress-tls",
                                    }
                                ],
                                "rules": [{"host": self.host}],
                            },
                        }
                    ]
                }
            ),
        )

    def _write_mocks(self) -> None:
        write_executable(
            self.bin / "kubectl",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            arguments=" $* "
            case "${arguments}" in
              *" config current-context "*) printf '%s\n' "${PHASE5_KUBE_CONTEXT}" ;;
              *" config get-contexts "*) printf '%s\n' "${PHASE5_KUBE_CONTEXT}" ;;
              *" get applications.argoproj.io "*) cat "${MOCK_APPLICATIONS}" ;;
              *" get deployment "*) cat "${MOCK_DEPLOYMENTS}" ;;
              *" get certificate "*) cat "${MOCK_CERTIFICATES}" ;;
              *" get issuer "*) cat "${MOCK_ISSUERS}" ;;
              *" get ingress "*) cat "${MOCK_INGRESSES}" ;;
              *) exit 91 ;;
            esac
            """,
        )
        write_executable(
            self.bin / "argocd",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >>"${MOCK_ARGOCD_LOG}"
            arguments=" $* "
            if [[ "${arguments}" == *" account get-user-info "* ]]; then
              if [[ "${ARGOCD_AUTH_TOKEN}" == admin-* ]]; then
                printf '{"loggedIn":true,"username":"admin-user"}\n'
              elif [[ "${ARGOCD_AUTH_TOKEN}" == reviewer-* ]]; then
                printf '{"loggedIn":true,"username":"reviewer-user"}\n'
              else
                exit 92
              fi
              exit 0
            fi
            if [[ "${arguments}" == *" app list "* ]]; then
              [[ "${ARGOCD_AUTH_TOKEN}" == reviewer-* ]] || exit 93
              printf '[{"metadata":{"name":"platform-root"}}]\n'
              exit 0
            fi
            if [[ "${arguments}" == *" account can-i "* ]]; then
              if [[ "${ARGOCD_AUTH_TOKEN}" == admin-* ]]; then
                printf 'yes\n'
              elif [[ "${arguments}" == *" can-i get applications "* ]]; then
                printf 'yes\n'
              elif [[ "${arguments}" == *" can-i sync applications "* &&
                      "${MOCK_REVIEWER_SYNC:-no}" == yes ]]; then
                printf 'yes\n'
              else
                printf 'no\n'
              fi
              exit 0
            fi
            exit 94
            """,
        )
        write_executable(
            self.bin / "curl",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            url=''
            for argument in "$@"; do
              case "${argument}" in http://*|https://*) url="${argument}" ;; esac
            done
            case "${url}" in
              https://*/api/v1/applications) printf '401' ;;
              https://*/) printf '200' ;;
              http://*/) printf '%s' "${MOCK_HTTP_CODE:-404}" ;;
              *) exit 95 ;;
            esac
            """,
        )
        write_executable(
            self.bin / "openssl",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            command_name=${1:-}
            shift || true
            arguments=" $* "
            if [[ "${command_name}" == s_client ]]; then
              printf '%s\n' 'mock-public-certificate'
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -outform PEM "* ]]; then
              cat
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -checkhost "* ]]; then
              printf '%s\n' 'Hostname does match certificate'
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -issuer "* ]]; then
              printf "%s\n" "issuer=O = Let's Encrypt, CN = E8"
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -checkend "* ]]; then
              exit 0
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -enddate "* ]]; then
              printf '%s\n' 'notAfter=Dec 31 23:59:59 2099 GMT'
            else
              exit 96
            fi
            """,
        )
        write_executable(
            self.bin / "timeout",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            shift
            exec "$@"
            """,
        )
        write_executable(
            self.bin / "nc",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            port=${!#}
            case "${port}" in
              22|80|443|6443) exit 0 ;;
              2379) [[ "${MOCK_OPEN_EXTRA_PORT:-no}" == yes ]] && exit 0 || exit 1 ;;
              *) exit 1 ;;
            esac
            """,
        )

    def run_verifier(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        environment = self.environment.copy()
        environment.update(overrides)
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def assert_sanitized(self, output: str) -> None:
        for forbidden in (
            self.host,
            "192.0.2.10",
            "192.0.2.11",
            "192.0.2.12",
            "admin-token-value",
            "reviewer-token-value",
            "admin-user",
            "reviewer-user",
            "platform-root",
            "mock-public-certificate",
        ):
            self.assertNotIn(forbidden, output)

    def test_success_emits_only_sanitized_aggregate_markers(self) -> None:
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[PASS] kube-context=explicit kubeconfig-mode=0600", result.stdout)
        self.assertIn(
            "[PASS] argocd-applications=3 children=2 healthy=3 synced=3",
            result.stdout,
        )
        self.assertIn("[PASS] cert-manager-components=3 ready-replicas=6", result.stdout)
        self.assertIn("[PASS] certificates=2 issuers=2 ready=true", result.stdout)
        self.assertIn("[PASS] argocd-anonymous=denied", result.stdout)
        self.assertIn("reviewer-sync=false reviewer-action=false", result.stdout)
        self.assertIn("public-https=200 http-mode=acme-only http-status=404", result.stdout)
        self.assertIn("external-nodes=3 allowed-tcp-classes=4", result.stdout)
        self.assertTrue(
            result.stdout.rstrip().endswith("[PASS] Phase 5 runtime verification completed.")
        )
        self.assertEqual(result.stderr, "")
        self.assert_sanitized(result.stdout + result.stderr)

        arguments = self.argocd_log.read_text(encoding="utf-8")
        self.assertNotIn("--auth-token", arguments)
        self.assertNotIn("--insecure", arguments)
        self.assertNotIn("--plaintext", arguments)
        self.assertNotIn("token-value", arguments)

    def test_world_readable_auth_file_is_rejected_before_use(self) -> None:
        self.reviewer_token.chmod(0o644)
        result = self.run_verifier()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=protected-file\n")
        self.assertFalse(self.argocd_log.exists())
        self.assert_sanitized(result.stdout + result.stderr)

    def test_reviewer_sync_permission_fails_closed_without_syncing(self) -> None:
        result = self.run_verifier(MOCK_REVIEWER_SYNC="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=argocd-rbac\n")
        arguments = self.argocd_log.read_text(encoding="utf-8")
        self.assertIn("account can-i sync applications", arguments)
        self.assertNotIn("app sync", arguments)
        self.assertNotIn("actions run", arguments)
        self.assert_sanitized(result.stdout + result.stderr)

    def test_unexpected_external_port_fails_the_exact_boundary(self) -> None:
        result = self.run_verifier(MOCK_OPEN_EXTRA_PORT="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=external-port-boundary\n")
        self.assert_sanitized(result.stdout + result.stderr)

    def test_plain_http_application_content_is_rejected(self) -> None:
        result = self.run_verifier(MOCK_HTTP_CODE="200")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=public-http\n")
        self.assert_sanitized(result.stdout + result.stderr)

    def test_source_contract_has_no_secret_cli_or_tls_bypass(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('--kubeconfig "${PHASE5_KUBECONFIG}"', source)
        self.assertIn('--context "${PHASE5_KUBE_CONTEXT}"', source)
        self.assertIn('ARGOCD_AUTH_TOKEN="${token}"', source)
        self.assertIn("[[ \"${mode}\" == '600'", source)
        self.assertNotIn("--auth-token", source)
        self.assertNotIn("--insecure", source)
        self.assertNotIn("--plaintext", source)
        self.assertNotIn("set -x", source)
        self.assertNotIn("app sync", source)
        self.assertNotIn("actions run", source)


if __name__ == "__main__":
    unittest.main()
