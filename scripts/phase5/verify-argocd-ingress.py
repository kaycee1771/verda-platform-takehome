#!/usr/bin/env python3
"""Validate the allowed Argo CD ingress lifecycle states without exposing host data."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(message)


def scalar(values_path: Path, key: str) -> str:
    matches = re.findall(rf"(?m)^{re.escape(key)}:\s*([^\s#]+)\s*$", values_path.read_text(encoding="utf-8"))
    if len(matches) != 1:
        fail("the approved ingress values are incomplete")
    return matches[0].strip('"\'')


def validate(payload: dict[str, object], values_path: Path) -> str:
    items = payload.get("items")
    if not isinstance(items, list):
        fail("the live ingress response is malformed")
    if not items:
        return "ClusterIP-only"
    if len(items) != 1 or not isinstance(items[0], dict):
        fail("the argocd namespace contains an unapproved ingress set")

    hostname = scalar(values_path, "hostname")
    tls_secret = scalar(values_path, "tlsSecretName")
    policy_owner = scalar(values_path, "networkPolicyOwner")
    item = items[0]
    metadata = item.get("metadata", {})
    spec = item.get("spec", {})
    if not isinstance(metadata, dict) or not isinstance(spec, dict):
        fail("the approved ingress shape is malformed")
    if metadata.get("name") != "argocd-server" or metadata.get("namespace") != "argocd":
        fail("the argocd namespace contains an unapproved ingress")

    annotations = metadata.get("annotations", {})
    required_annotations = {
        "argocd.argoproj.io/ignore-healthcheck": "true",
        "argocd.argoproj.io/tracking-id": (
            "argocd-public-ingress:networking.k8s.io/Ingress:argocd/argocd-server"
        ),
        "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
        "traefik.ingress.kubernetes.io/router.tls": "true",
        "verda.platform/authentication-boundary": "argocd-rbac",
        "verda.platform/cli-mode": "grpc-web",
        "verda.platform/network-policy-owner": policy_owner,
        "verda.platform/exposure-gates": "verified",
    }
    if not isinstance(annotations, dict) or any(
        annotations.get(key) != value for key, value in required_annotations.items()
    ):
        fail("the approved ingress ownership or security annotations changed")

    expected_tls = [{"hosts": [hostname], "secretName": tls_secret}]
    expected_rules = [
        {
            "host": hostname,
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
    ]
    if spec.get("ingressClassName") != "traefik":
        fail("the approved ingress class changed")
    if spec.get("tls") != expected_tls or spec.get("rules") != expected_rules:
        fail("the approved ingress TLS or backend contract changed")
    return "git-owned-tls-ingress"


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--values", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        fail("the live ingress response is malformed")
    if not isinstance(payload, dict):
        fail("the live ingress response is malformed")
    print(validate(payload, args.values))


if __name__ == "__main__":
    main()
