ARG GO_BUILDER_IMAGE=docker.io/library/golang:1.26.0-bookworm@sha256:2a0ba12e116687098780d3ce700f9ce3cb340783779646aafbabed748fa6677c
FROM ${GO_BUILDER_IMAGE} AS build

ARG GO_BUILDER_IMAGE
ARG TARGETARCH=amd64
ARG VERSION=unreleased
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN digest="${GO_BUILDER_IMAGE##*@sha256:}" \
    && test "${GO_BUILDER_IMAGE}" != "${digest}" \
    && test "${#digest}" -eq 64 \
    && case "${digest}" in *[!0-9a-f]*) echo 'builder digest must be 64 lowercase hexadecimal characters' >&2; exit 64;; esac \
    && test "${digest}" != "0000000000000000000000000000000000000000000000000000000000000000" \
    && CGO_ENABLED=0 GOOS=linux GOARCH="${TARGETARCH}" go build \
      -mod=readonly -trimpath -buildvcs=false \
      -ldflags="-s -w -buildid= -X main.version=${VERSION}" \
      -o /out/platform-demo ./main.go \
    && test "$(stat -c %s /out/platform-demo)" -gt 0

# scratch is Docker's reserved empty, immutable base and has no registry digest.
FROM scratch
LABEL org.opencontainers.image.title="Verda Platform Demo" \
      org.opencontainers.image.base.name="scratch"
COPY --from=build --chown=65532:65532 /out/platform-demo /platform-demo
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/platform-demo"]
