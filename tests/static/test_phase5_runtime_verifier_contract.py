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
EXPECTED_APPS = (
    "platform-root",
    "platform-project",
    "cert-manager-controller",
    "argocd-certificate-staging",
    "longhorn-prerequisites",
    "longhorn-controller",
    "longhorn-resources",
    "argocd-certificate-production",
    "argocd-public-ingress",
)


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

        test_runtime = ROOT / ".local" / "test-runtime"
        test_runtime.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="phase5-verifier-", dir=test_runtime
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.host = "argocd.192-0-2-10.nip.io"

        self.kubeconfig = self.root / "kubeconfig"
        self.admin_token = self.root / "admin.token"
        self.reviewer_token = self.root / "reviewer.token"
        self.endpoints = self.root / "endpoints"
        write_file(self.kubeconfig, "apiVersion: v1\nkind: Config\n")
        write_file(
            self.admin_token,
            "adminheader.adminpayloadwithsafelength.adminsignaturevalue\n",
        )
        write_file(
            self.reviewer_token,
            "reviewerheader.reviewerpayloadwithsafelength.reviewersignaturevalue\n",
        )
        write_file(
            self.endpoints,
            "192.0.2.10\n192.0.2.11\n192.0.2.12\n",
        )

        self.applications = self.root / "applications.json"
        self.deployments = self.root / "deployments.json"
        self.certificates = self.root / "certificates.json"
        self.issuers = self.root / "issuers.json"
        self.ingresses = self.root / "ingresses.json"
        self.curl_log = self.root / "curl-arguments.log"
        self.openssl_log = self.root / "openssl-arguments.log"
        self._write_fixtures()
        self._write_mocks()

        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PHASE5_KUBECONFIG": str(self.kubeconfig),
                "PHASE5_KUBE_CONTEXT": "verda-management",
                "PHASE5_PUBLIC_HOST": self.host,
                "PHASE5_ARGOCD_ADMIN_TOKEN_FILE": str(self.admin_token),
                "PHASE5_ARGOCD_REVIEWER_TOKEN_FILE": str(self.reviewer_token),
                "PHASE5_EXTERNAL_ENDPOINTS_FILE": str(self.endpoints),
                "PHASE5_KUBECTL_BIN": str(self.bin / "kubectl"),
                "PHASE5_CURL_BIN": str(self.bin / "curl"),
                "PHASE5_OPENSSL_BIN": str(self.bin / "openssl"),
                "PHASE5_NC_BIN": str(self.bin / "nc"),
                "PHASE5_TIMEOUT_BIN": str(self.bin / "timeout"),
                "MOCK_APPLICATIONS": str(self.applications),
                "MOCK_DEPLOYMENTS": str(self.deployments),
                "MOCK_CERTIFICATES": str(self.certificates),
                "MOCK_ISSUERS": str(self.issuers),
                "MOCK_INGRESSES": str(self.ingresses),
                "MOCK_CURL_LOG": str(self.curl_log),
                "MOCK_OPENSSL_LOG": str(self.openssl_log),
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
                        for name in EXPECTED_APPS
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
            self.bin / "curl",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            url=''
            header=''
            config=''
            previous=''
            for argument in "$@"; do
              case "${previous}" in
                --header) header="${argument}" ;;
                --config) config="${argument}" ;;
              esac
              case "${argument}" in http://*|https://*) url="${argument}" ;; esac
              previous="${argument}"
            done
            printf '%s\t%s\n' "$(basename -- "${config:-none}")" "${url}" >>"${MOCK_CURL_LOG}"
            identity='anonymous'
            if [[ "${header}" == @* ]]; then
              authorization=$(<"${header#@}")
              case "${authorization}" in
                *adminheader.*) identity='admin' ;;
                *reviewerheader.*) identity='reviewer' ;;
                *) exit 92 ;;
              esac
            fi
            case "${url}" in
              https://*/api/v1/session/userinfo)
                [[ "${identity}" != anonymous ]] || exit 93
                printf '{"loggedIn":true,"username":"%s"}\n' "${identity}"
                ;;
              https://*/api/v1/account/can-i/applications/*)
                [[ "${identity}" != anonymous ]] || exit 94
                action=${url#*/api/v1/account/can-i/applications/}
                action=${action%%/*}
                if [[ "${identity}" == admin ]]; then
                  value=yes
                elif [[ "${action}" == get ]]; then
                  value=yes
                elif [[ "${action}" == sync && "${MOCK_REVIEWER_SYNC:-no}" == yes ]]; then
                  value=yes
                else
                  value=no
                fi
                printf '{"value":"%s"}\n' "${value}"
                ;;
              https://*/api/v1/applications)
                if [[ "${identity}" == anonymous ]]; then
                  printf '401'
                elif [[ "${identity}" == reviewer ]]; then
                  cat "${MOCK_APPLICATIONS}"
                else
                  exit 95
                fi
                ;;
              https://*/) printf '200' ;;
              http://*/) printf '%s' "${MOCK_HTTP_CODE:-404}" ;;
              *) exit 96 ;;
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
              printf '%s\n' "${arguments}" >>"${MOCK_OPENSSL_LOG}"
              printf '%s\n' 'mock-public-certificate'
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -outform PEM "* ]]; then
              cat
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -checkhost "* ]]; then
              printf '%s\n' 'Hostname does match certificate'
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -issuer "* ]]; then
              printf "%s\n" "issuer=O = Let's Encrypt, CN = E8"
            elif [[ "${command_name}" == x509 && "${arguments}" == *" -fingerprint "* ]]; then
              fingerprint='AA'
              for _ in {2..32}; do fingerprint="${fingerprint}:AA"; done
              printf 'sha256 Fingerprint=%s\n' "${fingerprint}"
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
            "adminpayloadwithsafelength",
            "reviewerpayloadwithsafelength",
            "platform-root",
            "mock-public-certificate",
        ):
            self.assertNotIn(forbidden, output)

    def test_success_emits_only_sanitized_aggregate_markers(self) -> None:
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[PASS] kube-context=explicit kubeconfig-mode=0600", result.stdout)
        self.assertIn(
            "[PASS] argocd-applications=9 children=8 healthy=9 synced=9",
            result.stdout,
        )
        self.assertIn("[PASS] cert-manager-components=3 ready-replicas=6", result.stdout)
        self.assertIn("[PASS] certificates=2 issuers=2 ready=true", result.stdout)
        self.assertIn("[PASS] tls-endpoints=3", result.stdout)
        self.assertIn("certificate-consistent=true", result.stdout)
        self.assertIn("[PASS] argocd-anonymous=denied endpoints=3", result.stdout)
        self.assertIn("reviewer-sync=false reviewer-action=false", result.stdout)
        self.assertIn(
            "public-endpoints=3 https=200 http-mode=acme-only http-status=404",
            result.stdout,
        )
        self.assertIn("external-nodes=3 allowed-tcp-classes=4", result.stdout)
        self.assertTrue(
            result.stdout.rstrip().endswith("[PASS] Phase 5 runtime verification completed.")
        )
        self.assertEqual(result.stderr, "")
        self.assert_sanitized(result.stdout + result.stderr)

        curl_calls = self.curl_log.read_text(encoding="utf-8")
        for index in range(3):
            self.assertIn(f"endpoint-{index}.curl", curl_calls)
        tls_calls = self.openssl_log.read_text(encoding="utf-8")
        for address in ("192.0.2.10", "192.0.2.11", "192.0.2.12"):
            self.assertIn(f"-connect {address}:443", tls_calls)
        self.assertNotIn("adminpayload", curl_calls)
        self.assertNotIn("reviewerpayload", curl_calls)

    def test_world_readable_auth_file_is_rejected_before_use(self) -> None:
        self.reviewer_token.chmod(0o644)
        result = self.run_verifier()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=protected-file\n")
        self.assertFalse(self.curl_log.exists())
        self.assert_sanitized(result.stdout + result.stderr)

    def test_reviewer_sync_permission_fails_closed_without_syncing(self) -> None:
        result = self.run_verifier(MOCK_REVIEWER_SYNC="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=argocd-rbac\n")
        arguments = self.curl_log.read_text(encoding="utf-8")
        self.assertIn("/account/can-i/applications/sync/", arguments)
        self.assertNotIn("/api/v1/applications/platform-root/sync", arguments)
        self.assertNotIn("/resource/actions", arguments)
        self.assert_sanitized(result.stdout + result.stderr)

    def test_exact_application_set_rejects_extras_and_subsets(self) -> None:
        original = json.loads(self.applications.read_text(encoding="utf-8"))
        variants = (
            {"items": [*original["items"], {"metadata": {"name": "extra-app"}}]},
            {"items": original["items"][:-1]},
        )
        for payload in variants:
            with self.subTest(count=len(payload["items"])):
                write_file(self.applications, json.dumps(payload))
                result = self.run_verifier()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "[FAIL] gate=argocd-applications\n")
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
        for application in EXPECTED_APPS:
            self.assertIn(f"'{application}'", source)
        self.assertIn("readonly argocd_admin_subject='admin'", source)
        self.assertIn("readonly argocd_reviewer_subject='reviewer'", source)
        self.assertIn('--header "@${authorization_file}"', source)
        self.assertIn(
            '/api/v1/account/can-i/applications/${action}/${object}', source
        )
        self.assertIn("'%2A%2F%2A'", source)
        self.assertIn("'platform%2F%2A'", source)
        self.assertIn("'platform-bootstrap%2F%2A'", source)
        self.assertIn('-connect "${external_endpoints[index]}:443"', source)
        self.assertIn('curl_resolve_files+=("${resolve_file}")', source)
        self.assertIn("[[ \"${mode}\" == '600'", source)
        self.assertNotIn("PHASE5_ARGO_ROOT_APP", source)
        self.assertNotIn("PHASE5_ARGO_EXPECTED_CHILDREN", source)
        self.assertNotIn("PHASE5_ARGOCD_ADMIN_SUBJECT", source)
        self.assertNotIn("PHASE5_ARGOCD_REVIEWER_SUBJECT", source)
        self.assertNotIn("ARGOCD_AUTH_TOKEN", source)
        self.assertNotIn("argocd_bin", source)
        self.assertNotIn("--auth-token", source)
        self.assertNotIn("--insecure", source)
        self.assertNotIn("--plaintext", source)
        self.assertNotIn("set -x", source)
        self.assertNotIn("app sync", source)
        self.assertNotIn("actions run", source)


if __name__ == "__main__":
    unittest.main()
