# syntax=docker/dockerfile:1.7
FROM python:3.13.11-slim-bookworm@sha256:20080e807bfc404f8450b185cf0fc95d553462673598549613735f70a5b4d5d0

ARG AQUA_VERSION=2.62.3
ARG AQUA_SHA256=89cb081adb19e425b1dca6b16d912c349a43535ce88d8713050738c9263618d0

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Package revisions follow the security-patched snapshot behind the immutable
# base digest. The completed image is itself identified by a content digest.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        jq \
        make \
        openssh-client \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --silent --show-error --location \
      "https://github.com/aquaproj/aqua/releases/download/v${AQUA_VERSION}/aqua_linux_amd64.tar.gz" \
      --output /tmp/aqua.tar.gz \
    && echo "${AQUA_SHA256}  /tmp/aqua.tar.gz" | sha256sum --check --strict \
    && tar --extract --gzip --file /tmp/aqua.tar.gz --directory /usr/local/bin aqua \
    && rm /tmp/aqua.tar.gz

ENV AQUA_ROOT_DIR=/opt/aqua
ENV PATH=/opt/aqua/bin:${PATH}
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV DEBIAN_FRONTEND=noninteractive

COPY aqua.yaml /tmp/aqua.yaml
RUN aqua install --all --config /tmp/aqua.yaml

COPY requirements-quality.txt /tmp/requirements-quality.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/requirements-quality.txt

LABEL org.opencontainers.image.title="Verda Platform Phase 1 quality toolchain" \
      org.opencontainers.image.description="Pinned, credential-free repository validation environment" \
      org.opencontainers.image.version="2026-08-16" \
      org.opencontainers.image.source="repository-local"

RUN groupadd --gid 65532 quality \
    && useradd --uid 65532 --gid 65532 --no-create-home \
      --home-dir /nonexistent --shell /usr/sbin/nologin quality \
    && git config --system --add safe.directory /workspace

WORKDIR /workspace
USER 65532:65532
