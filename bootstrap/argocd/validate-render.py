#!/usr/bin/env python3
"""Fail-closed security validation and sanitized inventory for the Argo render."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job"}
PUBLIC_ROUTE_KINDS = {"Ingress", "HTTPRoute", "GRPCRoute", "Gateway", "Route"}
EXPECTED_WORKLOADS = {
    "argocd-application-controller",
    "argocd-applicationset-controller",
    "argocd-redis",
    "argocd-repo-server",
    "argocd-server",
}
EXPECTED_CRDS = {
    "applications.argoproj.io",
    "applicationsets.argoproj.io",
    "appprojects.argoproj.io",
}
ALLOWED_SECRET_NAMES = {"argocd-secret", "argocd-redis"}


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def pod_spec(document: dict) -> dict | None:
    kind = document.get("kind")
    spec = document.get("spec", {})
    if kind == "Pod":
        return spec
    if kind in WORKLOAD_KINDS:
        return spec.get("template", {}).get("spec", {})
    return None


def validate_container(container: dict, workload: str, pod_security: dict) -> str:
    image = str(container.get("image", ""))
    if (
        not image
        or image.endswith(":latest")
        or (":" not in image and "@sha256:" not in image)
    ):
        fail(f"{workload} contains an unpinned container image")
    security = container.get("securityContext", {})
    if security.get("allowPrivilegeEscalation") is not False:
        fail(f"{workload} does not disable privilege escalation")
    if security.get("readOnlyRootFilesystem") is not True:
        fail(f"{workload} does not use a read-only root filesystem")
    if security.get("privileged") is True:
        fail(f"{workload} contains a privileged container")
    if security.get("runAsNonRoot", pod_security.get("runAsNonRoot")) is not True:
        fail(f"{workload} does not require a non-root container identity")
    capabilities = security.get("capabilities", {}).get("drop", [])
    if "ALL" not in capabilities:
        fail(f"{workload} does not drop all Linux capabilities")
    resources = container.get("resources", {})
    if not resources.get("requests") or not resources.get("limits"):
        fail(f"{workload} does not define bounded requests and limits")
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()

    documents = [
        document
        for document in yaml.safe_load_all(args.manifest.read_text(encoding="utf-8"))
        if document is not None
    ]
    if not documents:
        fail("the Argo CD chart rendered no Kubernetes objects")

    names: set[str] = set()
    crds: set[str] = set()
    inventory: list[str] = []
    bootstrap_projects = 0

    for document in documents:
        if not isinstance(document, dict):
            fail("the Argo CD render contains a non-object YAML document")
        api_version = str(document.get("apiVersion", ""))
        kind = str(document.get("kind", ""))
        metadata = document.get("metadata", {})
        name = str(metadata.get("name", ""))
        namespace = str(metadata.get("namespace", ""))
        if not api_version or not kind or not name:
            fail("a rendered object lacks apiVersion, kind, or metadata.name")
        if kind in PUBLIC_ROUTE_KINDS:
            fail("the bootstrap render contains a public routing resource")
        if kind == "Service":
            spec = document.get("spec", {})
            if spec.get("type", "ClusterIP") != "ClusterIP":
                fail("the bootstrap render contains a non-ClusterIP Service")
            if spec.get("externalIPs") or spec.get("loadBalancerIP"):
                fail("the bootstrap render contains an externally addressed Service")
        if kind == "Secret":
            if name not in ALLOWED_SECRET_NAMES:
                fail("the bootstrap render contains an unexpected Secret")
            labels = metadata.get("labels", {})
            if labels.get("argocd.argoproj.io/secret-type") in {
                "repository",
                "repo-creds",
                "cluster",
            }:
                fail(
                    "repository or cluster credentials are forbidden in the chart render"
                )
        if kind == "CustomResourceDefinition":
            crds.add(name)
        if kind == "AppProject" and name == "platform-bootstrap":
            bootstrap_projects += 1
            spec = document.get("spec", {})
            if spec.get("sourceRepos") != [
                "https://github.com/kaycee1771/verda-platform-takehome.git"
            ]:
                fail("the bootstrap AppProject repository allowlist is not exact")
            if spec.get("destinations") != [
                {"namespace": "argocd", "server": "https://kubernetes.default.svc"}
            ]:
                fail("the bootstrap AppProject destination allowlist is not exact")
            if spec.get("clusterResourceWhitelist"):
                fail("the bootstrap AppProject must not allow cluster-scoped resources")
            allowed = {
                (item.get("group"), item.get("kind"))
                for item in spec.get("namespaceResourceWhitelist", [])
            }
            if allowed != {
                ("argoproj.io", "Application"),
                ("argoproj.io", "ApplicationSet"),
                ("argoproj.io", "AppProject"),
            }:
                fail("the bootstrap AppProject kind allowlist is not exact")

        images: list[str] = []
        workload_spec = pod_spec(document)
        if workload_spec is not None:
            if (
                workload_spec.get("hostNetwork")
                or workload_spec.get("hostPID")
                or workload_spec.get("hostIPC")
            ):
                fail(f"{name} requests a host namespace")
            for volume in workload_spec.get("volumes", []):
                if "hostPath" in volume:
                    fail(f"{name} requests a hostPath volume")
            pod_security = workload_spec.get("securityContext", {})
            for container in workload_spec.get("containers", []):
                images.append(validate_container(container, name, pod_security))
            for container in workload_spec.get("initContainers", []):
                images.append(validate_container(container, name, pod_security))
            if kind in WORKLOAD_KINDS:
                names.add(name)
        image_field = ",".join(sorted(images)) if images else "-"
        inventory.append(
            f"{api_version}\t{kind}\t{namespace or '-'}\t{name}\t{image_field}"
        )

    if not EXPECTED_WORKLOADS.issubset(names):
        fail("the render is missing a required Argo CD workload")
    if not EXPECTED_CRDS.issubset(crds):
        fail("the render is missing a required Argo CD CRD")
    if bootstrap_projects != 1:
        fail("the render must contain exactly one platform-bootstrap AppProject")

    args.inventory.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.inventory, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("apiVersion\tkind\tnamespace\tname\timages\n")
        stream.write("\n".join(sorted(inventory)))
        stream.write("\n")
    print(
        "[PASS] Argo CD render security and secret boundary validated; "
        f"objects={len(documents)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
