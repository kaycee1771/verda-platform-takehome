#!/usr/bin/env python3
"""Behavioral and evidence-safety contract for Stage A runtime acceptance."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "phase6" / "verify-stage-a.sh"
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
    "platform-namespaces",
    "sealed-secrets-controller",
    "kyverno-controller",
    "rancher",
    "harbor-secrets",
    "harbor-postgresql",
    "harbor",
    "monitoring",
    "monitoring-resources",
    "loki",
    "alloy",
    "velero-controller",
    "velero-resources",
    "kyverno-policies",
    "sealed-secrets-monitoring",
    "kyverno-monitoring",
    "argocd-monitoring",
    "harbor-monitoring",
    "longhorn-monitoring",
    "rancher-monitoring",
    "traefik-monitoring",
    "demo-dev-foundation",
    "demo-staging-foundation",
    "demo-prod-foundation",
    "stage-a-smoke-dev",
    "stage-a-smoke-staging",
    "stage-a-smoke-prod",
)
DIGEST = "sha256:" + "a" * 64


def write_file(path: pathlib.Path, content: str, mode: int = 0o600) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def write_executable(path: pathlib.Path, content: str) -> None:
    write_file(path, textwrap.dedent(content).lstrip(), 0o700)


class Phase6StageARuntimeVerifierTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if os.name != "posix" or shutil.which("bash") is None:
            self.skipTest("behavioral verifier tests run in the pinned Linux quality image")

        runtime_root = ROOT / ".local" / "test-runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="phase6-stage-a-", dir=runtime_root
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.kubeconfig = self.root / "management.kubeconfig"
        write_file(self.kubeconfig, "apiVersion: v1\nkind: Config\n")

        self.rancher_endpoint = self.root / "rancher.endpoint"
        self.harbor_endpoint = self.root / "harbor.endpoint"
        self.grafana_endpoint = self.root / "grafana.endpoint"
        write_file(self.rancher_endpoint, "https://rancher.192-0-2-10.sslip.io\n")
        write_file(self.harbor_endpoint, "https://harbor.192-0-2-10.sslip.io\n")
        write_file(self.grafana_endpoint, "https://grafana.192-0-2-10.sslip.io\n")

        self.rancher_token = self.root / "rancher.header"
        self.harbor_token = self.root / "harbor.header"
        self.grafana_token = self.root / "grafana.header"
        write_file(
            self.rancher_token,
            "Authorization: Bearer token-reviewer-placeholder-value\n",
        )
        write_file(
            self.harbor_token,
            "Authorization: Basic YWRtaW46cGxhY2Vob2xkZXI=\n",
        )
        write_file(
            self.grafana_token,
            "Authorization: Bearer grafana-reviewer-placeholder-value\n",
        )

        self.application_endpoints = self.root / "applications.json"
        write_file(
            self.application_endpoints,
            json.dumps(
                {
                    environment: f"https://demo-{environment}.192-0-2-10.sslip.io"
                    for environment in ("dev", "staging", "prod")
                }
            ),
        )
        self.capacity = self.root / "capacity.json"
        write_file(self.capacity, json.dumps(self._capacity_report()))
        self.client_log = self.root / "clients.log"
        self._write_fake_clients()

        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PHASE6_KUBECONFIG": str(self.kubeconfig),
                "PHASE6_KUBE_CONTEXT": "verda-management",
                "PHASE6_RANCHER_ENDPOINT_FILE": str(self.rancher_endpoint),
                "PHASE6_RANCHER_REVIEWER_TOKEN_FILE": str(self.rancher_token),
                "PHASE6_HARBOR_ENDPOINT_FILE": str(self.harbor_endpoint),
                "PHASE6_HARBOR_REVIEWER_TOKEN_FILE": str(self.harbor_token),
                "PHASE6_GRAFANA_ENDPOINT_FILE": str(self.grafana_endpoint),
                "PHASE6_GRAFANA_REVIEWER_TOKEN_FILE": str(self.grafana_token),
                "PHASE6_APPLICATION_ENDPOINTS_FILE": str(self.application_endpoints),
                "PHASE6_CAPACITY_EVIDENCE_FILE": str(self.capacity),
                "PHASE6_KUBECTL_BIN": str(self.bin / "kubectl"),
                "PHASE6_CURL_BIN": str(self.bin / "curl"),
                "MOCK_CLIENT_LOG": str(self.client_log),
                "MOCK_EXPECTED_APPS": json.dumps(EXPECTED_APPS),
                "MOCK_IMAGE_DIGEST": DIGEST,
            }
        )

    @staticmethod
    def _capacity_report() -> dict[str, int | str]:
        return {
            "schema_version": 1,
            "status": "PASS",
            "component_count": 10,
            "rendered_document_count": 120,
            "workload_definition_count": 30,
            "pvc_definition_count": 8,
            "new_steady_cpu_millicores": 5000,
            "new_rollout_peak_cpu_millicores": 6500,
            "one_node_loss_rollout_cpu_headroom_millicores": 1200,
            "new_steady_memory_bytes": 8_000_000_000,
            "new_rollout_peak_memory_bytes": 10_000_000_000,
            "one_node_loss_rollout_memory_headroom_bytes": 2_000_000_000,
            "new_logical_pvc_bytes": 50_000_000_000,
            "new_raw_pvc_bytes": 150_000_000_000,
            "one_node_loss_pvc_bytes": 100_000_000_000,
            "storage_headroom_bytes": 120_000_000_000,
            "one_node_loss_storage_headroom_bytes": 60_000_000_000,
        }

    def _write_fake_clients(self) -> None:
        write_executable(
            self.bin / "kubectl",
            r'''
            #!/usr/bin/env python3
            import json, os, sys, urllib.parse

            original = sys.argv[1:]
            with open(os.environ["MOCK_CLIENT_LOG"], "a", encoding="utf-8") as log:
                log.write("kubectl " + " ".join(original) + "\n")
            args = original[:]
            namespace = None
            cleaned = []
            index = 0
            while index < len(args):
                item = args[index]
                if item in {"--kubeconfig", "--context", "--request-timeout", "-n", "--namespace"}:
                    if item in {"-n", "--namespace"}:
                        namespace = args[index + 1]
                    index += 2
                elif item.startswith("--request-timeout="):
                    index += 1
                else:
                    cleaned.append(item)
                    index += 1
            args = cleaned

            def emit(value):
                if isinstance(value, str):
                    print(value)
                else:
                    print(json.dumps(value, separators=(",", ":")))

            def ready_status(replicas):
                return {
                    "observedGeneration": 4,
                    "updatedReplicas": replicas,
                    "readyReplicas": replicas,
                    "availableReplicas": replicas,
                    "unavailableReplicas": 0,
                }

            def environment_name(ns):
                return {"demo-dev":"dev", "demo-staging":"staging", "demo-prod":"prod"}[ns]

            if args[:2] == ["config", "current-context"]:
                emit(os.environ.get("MOCK_CONTEXT", "verda-management")); raise SystemExit
            if args[:2] == ["config", "get-contexts"]:
                emit("verda-management"); raise SystemExit
            if args[:2] == ["config", "view"]:
                emit({"clusters":[{"name":"management","cluster":{"server":"https://192.0.2.20:6443"}}]}); raise SystemExit
            if args[:3] == ["get", "--raw", args[2] if len(args) > 2 else ""]:
                path = args[2]
                if path.endswith("/api/v1/targets?state=active"):
                    services = [
                        ("argocd", "argocd-application-controller-metrics"),
                        ("argocd", "argocd-applicationset-controller-metrics"),
                        ("argocd", "argocd-repo-server-metrics"),
                        ("argocd", "argocd-server-metrics"),
                        ("cattle-system", "rancher"),
                        ("harbor", "harbor-core"),
                        ("harbor", "harbor-exporter"),
                        ("harbor", "harbor-jobservice"),
                        ("harbor", "harbor-registry"),
                        ("longhorn-system", "longhorn-backend"),
                        ("kube-system", "rke2-traefik-metrics"),
                    ]
                    if os.environ.get("MOCK_DROP_PROMETHEUS_TARGET") == "1": services.pop(0)
                    namespaces = ["kyverno","monitoring","sealed-secrets","velero","logging","loki","demo-dev","demo-staging","demo-prod"]
                    targets = [{"health":"up","labels":{"namespace":namespace,"service":service}} for namespace, service in services]
                    targets.extend({"health":"up","labels":{"namespace":value,"service":"fixture"}} for value in namespaces)
                    emit({"status":"success","data":{"activeTargets":targets}}); raise SystemExit
                if "/api/v1/query?query=" in path:
                    emit({"status":"success","data":{"result":[
                        {"metric":{"environment":"dev"},"value":[1,"1"]},
                        {"metric":{"environment":"staging"},"value":[1,"1"]},
                        {"metric":{"environment":"prod"},"value":[1,"2"]},
                    ]}}); raise SystemExit
            if args[:2] == ["get", "nodes"]:
                emit({"items":[{"status":{"conditions":[{"type":"Ready","status":"True"}]}} for _ in range(3)]}); raise SystemExit
            if args[:2] == ["get", "applications.argoproj.io"]:
                apps = list(json.loads(os.environ["MOCK_EXPECTED_APPS"]))
                if os.environ.get("MOCK_DROP_APP") == "1": apps.pop()
                if os.environ.get("MOCK_EXTRA_APP") == "1": apps.append("stage-b-workload")
                destination = "https://workload.invalid" if os.environ.get("MOCK_STAGEB_DEST") == "1" else "https://kubernetes.default.svc"
                items = []
                for app_index, name in enumerate(apps):
                    server = destination if app_index == 0 else "https://kubernetes.default.svc"
                    items.append({"metadata":{"name":name},"spec":{"destination":{"server":server}},"status":{"health":{"status":"Healthy"},"sync":{"status":"Synced"}}})
                emit({"items":items}); raise SystemExit
            if args[:2] == ["get", "namespaces"]:
                items = []
                for ns in ("demo-dev", "demo-staging", "demo-prod"):
                    environment = environment_name(ns)
                    items.append({"metadata":{"name":ns,"labels":{
                        "app.kubernetes.io/part-of":"platform-demo",
                        "kubernetes.io/metadata.name":ns,
                        "platform.verda-demo.io/environment":environment,
                        "platform.verda-demo.io/owner":"platform-team",
                        "platform.verda-demo.io/topology":"stage-a-management-cluster",
                        "pod-security.kubernetes.io/enforce":"restricted",
                        "pod-security.kubernetes.io/enforce-version":"v1.35",
                        "pod-security.kubernetes.io/audit":"restricted",
                        "pod-security.kubernetes.io/audit-version":"v1.35",
                        "pod-security.kubernetes.io/warn":"restricted",
                        "pod-security.kubernetes.io/warn-version":"v1.35",
                    }}})
                emit({"items":items}); raise SystemExit
            if args[:2] == ["get", "resourcequota"]:
                environment = environment_name(namespace)
                hard = {"requests.cpu":"500m","requests.memory":"1Gi","limits.cpu":"2","limits.memory":"2Gi","pods":"10","persistentvolumeclaims":"2"}
                if environment == "prod": hard = {"requests.cpu":"1","requests.memory":"2Gi","limits.cpu":"4","limits.memory":"4Gi","pods":"16","persistentvolumeclaims":"2"}
                emit({"metadata":{"name":"stage-a-budget"},"spec":{"hard":hard}}); raise SystemExit
            if args[:2] == ["get", "limitrange"]:
                emit({"metadata":{"name":"workload-defaults"},"spec":{"limits":[{"type":"Container","default":{"cpu":"250m","memory":"256Mi"},"defaultRequest":{"cpu":"50m","memory":"64Mi"},"max":{"cpu":"1","memory":"1Gi"}}]}}); raise SystemExit
            if args[:2] == ["get", "networkpolicy"]:
                emit({"items":[
                    {"metadata":{"name":"default-deny"},"spec":{"podSelector":{},"policyTypes":["Ingress","Egress"]}},
                    {"metadata":{"name":"allow-cluster-dns"},"spec":{"podSelector":{},"policyTypes":["Egress"],"egress":[{"to":[{"namespaceSelector":{"matchLabels":{"kubernetes.io/metadata.name":"kube-system"}},"podSelector":{"matchLabels":{"k8s-app":"kube-dns"}}}],"ports":[{"protocol":"UDP","port":53},{"protocol":"TCP","port":53}]}]}},
                ]}); raise SystemExit
            if args[:2] == ["get", "serviceaccount"]:
                emit({"metadata":{"name":"platform-demo"},"automountServiceAccountToken":False,"imagePullSecrets":[{"name":"platform-demo-registry"}]}); raise SystemExit
            if args[:2] == ["get", "rolebinding"]:
                emit({"metadata":{"name":"verda-reviewers-view"},"subjects":[{"kind":"Group","apiGroup":"rbac.authorization.k8s.io","name":"verda-reviewers"}],"roleRef":{"kind":"ClusterRole","apiGroup":"rbac.authorization.k8s.io","name":"view"}}); raise SystemExit
            if args[:2] == ["get", "secret"]:
                name = args[2]
                emit("secret/" + name); raise SystemExit
            if args[:2] == ["get", "sealedsecret"]:
                emit("Synced=True"); raise SystemExit
            if args[:2] == ["get", "clusterpolicy"]:
                items = []
                for name in ("phase6-workload-baseline", "sealed-secret-strict-scope"):
                    items.append({"metadata":{"name":name},"spec":{"validationFailureAction":"Audit","background":True,"failurePolicy":"Ignore"},"status":{"ready":True}})
                emit({"items":items}); raise SystemExit
            if args[:2] == ["get", "policyreports.wgpolicyk8s.io"]:
                emit({"items":[{"metadata":{"namespace":ns},"summary":{"pass":1,"fail":0,"warn":0,"error":0,"skip":0},"results":[{"policy":"phase6-workload-baseline","result":"pass"}]} for ns in ("demo-dev","demo-staging","demo-prod")]}); raise SystemExit
            if args[:2] == ["get", "clusterpolicyreports.wgpolicyk8s.io"]:
                emit({"items":[]}); raise SystemExit
            if args[:2] == ["get", "backupstoragelocations.velero.io"]:
                emit({"metadata":{"name":"management-s3"},"status":{"phase":"Available","lastValidationTime":"2026-08-20T00:00:00Z"}}); raise SystemExit
            if args[:2] == ["get", "deployment"]:
                environment = environment_name(namespace)
                replicas = {"dev":1,"staging":1,"prod":2}[environment]
                image = "harbor.192-0-2-10.sslip.io/platform-demo/stage-a-smoke@" + os.environ["MOCK_IMAGE_DIGEST"]
                emit({"metadata":{"name":"stage-a-smoke","generation":4},"spec":{"replicas":replicas,"template":{"spec":{"serviceAccountName":"platform-demo","containers":[{"name":"stage-a-smoke","image":image}]}}},"status":ready_status(replicas)}); raise SystemExit
            if args[:2] == ["get", "ingress"]:
                environment = environment_name(namespace)
                host = f"demo-{environment}.192-0-2-10.sslip.io"
                emit({"items":[{"metadata":{"name":"stage-a-smoke","labels":{"app.kubernetes.io/name":"stage-a-smoke"}},"spec":{"ingressClassName":"traefik","rules":[{"host":host}],"tls":[{"hosts":[host],"secretName":"stage-a-smoke-tls"}]}}]}); raise SystemExit
            if args[:2] == ["get", "certificate"]:
                environment = environment_name(namespace)
                host = f"demo-{environment}.192-0-2-10.sslip.io"
                emit({"items":[{"metadata":{"name":"stage-a-smoke-production"},"spec":{"secretName":"stage-a-smoke-tls","dnsNames":[host]},"status":{"conditions":[{"type":"Ready","status":"True"}]}}]}); raise SystemExit
            if args[:2] == ["get", "service"] and namespace == "monitoring":
                emit({"items":[{"metadata":{"name":"monitoring-prometheus","labels":{"app.kubernetes.io/name":"prometheus"}},"spec":{"ports":[{"name":"http-web","port":9090}]}}]}); raise SystemExit
            raise SystemExit("unexpected fake kubectl invocation: " + " ".join(original))
            ''',
        )
        write_executable(
            self.bin / "curl",
            r'''
            #!/usr/bin/env python3
            import json, os, pathlib, sys, urllib.parse

            args = sys.argv[1:]
            url = next((value for value in reversed(args) if value.startswith("https://")), "")
            output = args[args.index("--output") + 1]
            status_mode = "--write-out" in args
            parsed = urllib.parse.urlparse(url)
            path = parsed.path + (("?" + parsed.query) if parsed.query else "")
            with open(os.environ["MOCK_CLIENT_LOG"], "a", encoding="utf-8") as log:
                log.write("curl GET " + parsed.hostname + path + "\n")

            def write(value):
                pathlib.Path(output).write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")

            digest = os.environ["MOCK_IMAGE_DIGEST"]
            host = parsed.hostname or ""
            if status_mode and path.startswith("/v3/globalrolebindings"):
                if os.environ.get("MOCK_REVIEWER_ADMIN") == "1":
                    write({"data":[{"globalRoleId":"admin"}]}); print("200", end="")
                else:
                    write({"message":"forbidden"}); print("403", end="")
                raise SystemExit
            if host.startswith("demo-"):
                environment = host.removeprefix("demo-").split(".", 1)[0]
                write({"service":"stage-a-smoke","environment":environment,"version":"fixture"}); raise SystemExit
            if host.startswith("rancher."):
                if path.startswith("/v3/clusters"):
                    write({"data":[{"id":"local","name":"local","state":"active"}]}); raise SystemExit
                if path.startswith("/v3/users"):
                    write({"data":[{"id":"u-reviewer","username":"verda-reviewer","me":True,"enabled":True}]}); raise SystemExit
                if path.startswith("/k8s/clusters/local/apis/apps/v1/namespaces/"):
                    namespace = path.split("/namespaces/", 1)[1].split("/", 1)[0]
                    replicas = {"demo-dev":1,"demo-staging":1,"demo-prod":2}[namespace]
                    write({"metadata":{"name":"stage-a-smoke"},"spec":{"replicas":replicas},"status":{"readyReplicas":replicas}}); raise SystemExit
            if host.startswith("harbor."):
                if path == "/api/v2.0/projects/platform-demo":
                    write({"name":"platform-demo","metadata":{"public":"false","auto_scan":"true"}}); raise SystemExit
                if "/artifacts?" in path:
                    write([{"digest":digest,"scan_overview":{"report":{"scan_status":"Success","summary":{"summary":{"Critical":0,"High":1}}}}}]); raise SystemExit
                if path.endswith("/additions/vulnerabilities"):
                    write({"scanner":{"name":"Trivy","vendor":"Aqua Security"},"vulnerabilities":[{"severity":"High"}]}); raise SystemExit
            if host.startswith("grafana."):
                if path == "/api/datasources/uid/prometheus":
                    write({"uid":"prometheus","type":"prometheus","access":"proxy","url":"http://monitoring-kube-prometheus-prometheus.monitoring:9090/"}); raise SystemExit
                if path == "/api/datasources/uid/loki":
                    write({"uid":"loki","type":"loki","access":"proxy","url":"http://loki-gateway.loki.svc.cluster.local"}); raise SystemExit
                if "/proxy/uid/prometheus/" in path:
                    write({"status":"success","data":{"result":[
                        {"metric":{"environment":"dev"},"value":[1,"1"]},
                        {"metric":{"environment":"staging"},"value":[1,"1"]},
                        {"metric":{"environment":"prod"},"value":[1,"2"]},
                    ]}}); raise SystemExit
                if "/proxy/uid/loki/" in path:
                    write({"status":"success","data":{"result":[{"metric":{},"value":[1,"4"]}]}}); raise SystemExit
            raise SystemExit("unexpected fake curl invocation")
            ''',
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
            timeout=45,
        )

    def assert_sanitized(self, output: str) -> None:
        forbidden = (
            "192-0-2-10",
            "192.0.2.20",
            "sslip.io",
            "token-reviewer",
            "YWRtaW46",
            "grafana-reviewer",
            DIGEST,
            "u-reviewer",
            '"marker":"stage_a_smoke"',
            "https://",
        )
        for value in forbidden:
            self.assertNotIn(value, output)

    def test_success_is_fixed_sanitized_and_read_only(self) -> None:
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_lines = (
            "[PASS] protected-inputs=10 endpoints=validated authorization=files-only",
            "[PASS] kube-context=exact management-nodes=3 direct-api=ready",
            "[PASS] argocd-applications=36 healthy=36 synced=36 destinations=local-only",
            "[PASS] environment-foundations=3 labels=exact quota=true limitrange=true network-default-deny=true dns=true rbac=true pull-secret=present",
            "[PASS] sealed-secret-reconciled=1 secret-data-read=false",
            "[PASS] kyverno-policies=2 mode=audit background=true environment-reports=3",
            "[PASS] velero-bsl=available locations=1",
            "[PASS] applications=3 replicas=1-1-2 immutable-image=one-digest tls-endpoints=3",
            "[PASS] rancher-cluster=active workload-visibility=3 reviewer-non-admin=true direct-kubeconfig-independent=true",
            "[PASS] harbor-project=private artifact=digest-matched trivy-scan=complete critical-findings=0",
            "[PASS] prometheus-targets=all-up platform-target-classes=13 required-service-targets=11 application-series=3",
            "[PASS] grafana-datasources=2 datasource-queries=2 demo-dev-log-marker=present raw-logs-read=false",
            "[PASS] one-node-loss-capacity=admitted stage-b-dependency=false",
            "[PASS] Phase 6 Stage A runtime acceptance completed.",
        )
        self.assertEqual(result.stdout.splitlines(), list(expected_lines))
        self.assertEqual(result.stderr, "")
        self.assert_sanitized(result.stdout + result.stderr)

        calls = self.client_log.read_text(encoding="utf-8")
        for mutation in (
            " apply ", " create ", " delete ", " patch ", " replace ",
            " edit ", " scale ", " rollout ", " exec ", " port-forward ",
            " sync ", " action ", "POST", "PUT", "PATCH", "DELETE",
        ):
            self.assertNotIn(mutation, calls)
        secret_reads = [line for line in calls.splitlines() if " get secret " in line]
        self.assertTrue(secret_reads)
        self.assertTrue(all(" -o name" in line for line in secret_reads))
        self.assertFalse(any(" get secret " in line and "-o json" in line for line in secret_reads))

    def test_world_readable_runtime_input_fails_before_clients(self) -> None:
        self.rancher_token.chmod(0o644)
        result = self.run_verifier()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=protected-file\n")
        self.assertFalse(self.client_log.exists())
        self.assert_sanitized(result.stdout + result.stderr)

    def test_incomplete_or_extra_argocd_inventory_fails_closed(self) -> None:
        for override in ("MOCK_DROP_APP", "MOCK_EXTRA_APP"):
            with self.subTest(override=override):
                if self.client_log.exists():
                    self.client_log.unlink()
                result = self.run_verifier(**{override: "1"})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "[FAIL] gate=argocd-applications\n")
                self.assert_sanitized(result.stdout + result.stderr)

    def test_nonlocal_argocd_destination_proves_no_stage_b_dependency(self) -> None:
        result = self.run_verifier(MOCK_STAGEB_DEST="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=argocd-applications\n")
        self.assert_sanitized(result.stdout + result.stderr)

    def test_missing_required_service_target_fails_closed(self) -> None:
        result = self.run_verifier(MOCK_DROP_PROMETHEUS_TARGET="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=prometheus-targets\n")
        self.assert_sanitized(result.stdout + result.stderr)

    def test_reviewer_admin_role_is_rejected_without_mutation(self) -> None:
        result = self.run_verifier(MOCK_REVIEWER_ADMIN="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=rancher-reviewer\n")
        self.assertNotIn("POST", self.client_log.read_text(encoding="utf-8"))
        self.assert_sanitized(result.stdout + result.stderr)

    def test_capacity_report_must_be_complete_positive_pass_evidence(self) -> None:
        report = self._capacity_report()
        report["one_node_loss_rollout_cpu_headroom_millicores"] = 0
        write_file(self.capacity, json.dumps(report))
        result = self.run_verifier()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "[FAIL] gate=one-node-loss-capacity\n")
        self.assert_sanitized(result.stdout + result.stderr)

    def test_source_has_no_secret_data_read_or_mutation_escape_hatch(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('--kubeconfig "$PHASE6_KUBECONFIG"', source)
        self.assertIn('--context "$PHASE6_KUBE_CONTEXT"', source)
        self.assertIn("[[ \"$mode\" == '600'", source)
        for application in EXPECTED_APPS:
            self.assertIn(f"'{application}'", source)
        self.assertIn("stage-b-dependency=false", source)
        self.assertIn("secret-data-read=false", source)
        self.assertIn("raw-logs-read=false", source)
        self.assertIn("count_over_time", source)
        self.assertNotIn("--insecure", source)
        self.assertNotIn("-k ", source)
        self.assertNotIn("set -x", source)
        self.assertNotIn("kubectl apply", source)
        self.assertNotIn("kubectl delete", source)
        self.assertNotIn("argocd app sync", source)
        self.assertNotIn("rancher kubectl", source)
        self.assertNotIn(" get secret platform-demo-registry -o json", source)
        self.assertNotIn(" get secret phase6-reconciliation-test -o json", source)
        self.assertNotIn("kubectl logs", source)
        self.assertNotIn("loki/api/v1/query_range", source)


if __name__ == "__main__":
    unittest.main()
