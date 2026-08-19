#!/usr/bin/env bash
set -Eeuo pipefail

# This harness may delete only its uniquely labelled test namespace. At final
# cleanup it may patch only that test's exactly proven PV from Retain to Delete,
# allowing the CSI controller to remove the test volume. It never uninstalls
# Longhorn, deletes a StorageClass, or deletes Longhorn CRs directly.

umask 077

usage() {
  printf '%s\n' \
    'Usage: CONFIRM_DESTRUCTIVE_ACTION=yes scripts/phase5/longhorn-storage-test.sh --confirm' \
    'Requires: KUBECONFIG, PHASE5_KUBE_CONTEXT, PHASE5_CONFIRM_CLUSTER=verda-mgmt,' \
    '          PHASE5_CONFIRM_STORAGE_TEST=longhorn-critical-reschedule-and-cleanup'
}

case "${1:-}" in
  --help)
    (($# == 1)) || {
      usage >&2
      exit 64
    }
    usage
    exit 0
    ;;
  --confirm)
    (($# == 1)) || {
      usage >&2
      exit 64
    }
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "${script_dir}/../.." && pwd -P)
# shellcheck source=bootstrap/argocd/runtime-lib.sh
# Resolved from the validated repository root.
# shellcheck disable=SC1091
source "${repo_root}/bootstrap/argocd/runtime-lib.sh"

readonly storage_class='longhorn-critical'
readonly expected_checksum='bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8'
readonly fixture_image='quay.io/cilium/alpine-curl:v1.10.0@sha256:913e8c9f3d960dde03882defa0edd3a919d529c2eb167caa7f54194528bde364'
readonly contract_helper="${script_dir}/longhorn-storage-contract.py"
readonly capacity_helper="${script_dir}/capacity-report.py"
readonly longhorn_capacity_helper="${script_dir}/longhorn-capacity.py"

runtime_dir=''
namespace_created='false'
identity_file=''
absence_file=''
run_id=''
test_namespace=''

kubectl_base=()

assert_destructive_kubeconfig() {
  local mode owner

  [[ -n ${KUBECONFIG:-} && "${KUBECONFIG}" == /* ]] ||
    phase5_fail 'KUBECONFIG must be an absolute protected path.'
  [[ -f "${KUBECONFIG}" && ! -L "${KUBECONFIG}" ]] ||
    phase5_fail 'KUBECONFIG must be a regular, non-symlink file.'
  mode=$(stat -c '%a' -- "${KUBECONFIG}") ||
    phase5_fail 'Unable to verify KUBECONFIG permissions.'
  owner=$(stat -c '%u' -- "${KUBECONFIG}") ||
    phase5_fail 'Unable to verify KUBECONFIG ownership.'
  [[ "${mode}" == '600' && "${owner}" == "$(id -u)" ]] ||
    phase5_fail 'KUBECONFIG must be owned by the current user with mode 0600.'
}

capture_cluster_lists() {
  local prefix=$1
  "${kubectl_base[@]}" get namespaces -o json >"${runtime_dir}/${prefix}-namespaces.json"
  "${kubectl_base[@]}" get persistentvolumes -o json >"${runtime_dir}/${prefix}-pvs.json"
  "${kubectl_base[@]}" -n longhorn-system get volumes.longhorn.io -o json >"${runtime_dir}/${prefix}-volumes.json"
}

cleanup_test_objects() {
  local namespace_json pvc_json pv_name deadline

  namespace_json=$("${kubectl_base[@]}" get namespace "${test_namespace}" \
    --ignore-not-found -o json) || return 1
  if [[ -n "${namespace_json}" ]]; then
    printf '%s' "${namespace_json}" >"${runtime_dir}/cleanup-namespace.json"
    python3 "${contract_helper}" namespace \
      --input "${runtime_dir}/cleanup-namespace.json" \
      --run-id "${run_id}" \
      --namespace "${test_namespace}" >/dev/null || return 1

    pvc_json=$("${kubectl_base[@]}" -n "${test_namespace}" get pvc checksum-data \
      --ignore-not-found -o json) || return 1
    if [[ -n "${pvc_json}" ]]; then
      # A PVC is never removed without the immutable identity captured after
      # provisioning. On an early failure, retaining the labelled namespace is
      # safer than orphaning a Retain-policy volume.
      [[ -f "${identity_file}" ]] || return 1
      printf '%s' "${pvc_json}" >"${runtime_dir}/cleanup-pvc.json"
      "${kubectl_base[@]}" get persistentvolumes -o json \
        >"${runtime_dir}/cleanup-target-pvs.json" || return 1
      "${kubectl_base[@]}" -n longhorn-system get volumes.longhorn.io -o json \
        >"${runtime_dir}/cleanup-target-volumes.json" || return 1

      if python3 "${contract_helper}" cleanup-target \
        --identity "${identity_file}" \
        --namespace-file "${runtime_dir}/cleanup-namespace.json" \
        --pvc "${runtime_dir}/cleanup-pvc.json" \
        --pvs "${runtime_dir}/cleanup-target-pvs.json" \
        --volumes "${runtime_dir}/cleanup-target-volumes.json" \
        --run-id "${run_id}" \
        --namespace "${test_namespace}" \
        --expected-reclaim-policy Retain >/dev/null 2>&1; then
        pv_name=$(python3 -c \
          'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["pv_name"])' \
          "${identity_file}") || return 1
        [[ ${#pv_name} -le 253 && "${pv_name}" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ ]] || return 1

        # The reschedule and checksum proofs are already complete. This exact,
        # identity-guarded lifecycle transition is the only storage mutation in
        # cleanup and lets normal CSI deletion remove only the bounded test data.
        "${kubectl_base[@]}" patch persistentvolume "${pv_name}" \
          --type=merge \
          --patch '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}' \
          >/dev/null || return 1
        "${kubectl_base[@]}" get persistentvolumes -o json \
          >"${runtime_dir}/cleanup-target-pvs.json" || return 1
      fi

      # This also makes cleanup retry-safe if a prior attempt completed the
      # exact Retain-to-Delete transition but failed before namespace deletion.
      python3 "${contract_helper}" cleanup-target \
        --identity "${identity_file}" \
        --namespace-file "${runtime_dir}/cleanup-namespace.json" \
        --pvc "${runtime_dir}/cleanup-pvc.json" \
        --pvs "${runtime_dir}/cleanup-target-pvs.json" \
        --volumes "${runtime_dir}/cleanup-target-volumes.json" \
        --run-id "${run_id}" \
        --namespace "${test_namespace}" \
        --expected-reclaim-policy Delete >/dev/null || return 1
      unset pv_name
    fi

    "${kubectl_base[@]}" delete namespace "${test_namespace}" \
      --wait=false --cascade=foreground >/dev/null || return 1
  fi

  deadline=$((SECONDS + timeout_seconds))
  while true; do
    namespace_json=$("${kubectl_base[@]}" get namespace "${test_namespace}" \
      --ignore-not-found -o json) || return 1
    [[ -z "${namespace_json}" ]] && break
    (( SECONDS < deadline )) || return 1
    sleep 5
  done

  deadline=$((SECONDS + timeout_seconds))
  while true; do
    capture_cluster_lists cleanup || return 1
    if python3 "${contract_helper}" run-absence \
      --run-id "${run_id}" \
      --namespace "${test_namespace}" \
      --namespaces "${runtime_dir}/cleanup-namespaces.json" \
      --pvs "${runtime_dir}/cleanup-pvs.json" \
      --volumes "${runtime_dir}/cleanup-volumes.json" >/dev/null 2>&1; then
      break
    fi
    (( SECONDS < deadline )) || return 1
    sleep 5
  done

  if [[ -f "${identity_file}" ]]; then
    python3 "${contract_helper}" absence \
      --identity "${identity_file}" \
      --namespace "${test_namespace}" \
      --namespaces "${runtime_dir}/cleanup-namespaces.json" \
      --pvs "${runtime_dir}/cleanup-pvs.json" \
      --volumes "${runtime_dir}/cleanup-volumes.json" >"${absence_file}" || return 1
  fi
  namespace_created='false'
}

on_exit() {
  local status=$?
  trap - EXIT INT TERM
  if [[ "${namespace_created}" == 'true' ]]; then
    if ! cleanup_test_objects; then
      printf '[FAIL] Bounded Longhorn test cleanup could not prove ownership and complete absence.\n' >&2
      status=1
    fi
  fi
  if [[ -n "${runtime_dir}" && -d "${runtime_dir}" ]]; then
    case "${runtime_dir}" in
      "${TMPDIR:-/tmp}"/verda-phase5-longhorn-test.*) rm -rf -- "${runtime_dir}" ;;
      *)
        printf '[FAIL] Refusing to clean an unexpected Longhorn-test temporary path.\n' >&2
        status=1
        ;;
    esac
  fi
  exit "${status}"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ ${CONFIRM_DESTRUCTIVE_ACTION:-} == 'yes' ]] ||
  phase5_fail 'CONFIRM_DESTRUCTIVE_ACTION must equal yes.'
[[ ${PHASE5_CONFIRM_STORAGE_TEST:-} == 'longhorn-critical-reschedule-and-cleanup' ]] ||
  phase5_fail 'PHASE5_CONFIRM_STORAGE_TEST must equal longhorn-critical-reschedule-and-cleanup.'

for command in kubectl python3 realpath openssl date mktemp stat id; do
  phase5_require_command "${command}"
done
for helper in "${contract_helper}" "${capacity_helper}" "${longhorn_capacity_helper}"; do
  phase5_require_regular_file "${helper}" 'Phase 5 storage helper'
done
assert_destructive_kubeconfig
phase5_assert_cluster_runtime "${repo_root}"

timeout=${PHASE5_STORAGE_TEST_TIMEOUT:-10m}
phase5_assert_timeout "${timeout}"
case "${timeout}" in
  *s) timeout_seconds=${timeout%s} ;;
  *m) timeout_seconds=$((10#${timeout%m} * 60)) ;;
esac

run_id=${PHASE5_STORAGE_TEST_RUN_ID:-}
if [[ -z "${run_id}" ]]; then
  run_id="p5st-$(date -u +%Y%m%dt%H%M%sz)-$(openssl rand -hex 4)"
fi
[[ "${run_id}" =~ ^p5st-[0-9]{8}t[0-9]{6}z-[a-f0-9]{8}$ ]] ||
  phase5_fail 'PHASE5_STORAGE_TEST_RUN_ID does not satisfy the bounded run identity format.'
test_namespace="longhorn-test-${run_id}"

mount_report=${PHASE5_LONGHORN_MOUNT_REPORT:-${repo_root}/.local/reports/phase3/mount-uuid-report.json}
phase5_require_regular_file "${mount_report}" 'PHASE5_LONGHORN_MOUNT_REPORT'

runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/verda-phase5-longhorn-test.XXXXXXXX")
identity_file="${runtime_dir}/identity.json"
absence_file="${runtime_dir}/absence.json"

kubectl_base=(
  kubectl
  --kubeconfig "${KUBECONFIG}"
  --context "${PHASE5_KUBE_CONTEXT}"
  --request-timeout=30s
)

capture_capacity() {
  local phase=$1
  "${kubectl_base[@]}" get nodes -o json >"${runtime_dir}/${phase}-nodes.json"
  "${kubectl_base[@]}" get pods --all-namespaces -o json >"${runtime_dir}/${phase}-pods.json"
  python3 "${capacity_helper}" \
    --nodes "${runtime_dir}/${phase}-nodes.json" \
    --pods "${runtime_dir}/${phase}-pods.json" >"${runtime_dir}/capacity-${phase}.json"
  "${kubectl_base[@]}" -n longhorn-system get nodes.longhorn.io -o json \
    >"${runtime_dir}/${phase}-longhorn-nodes.json"
  python3 "${longhorn_capacity_helper}" \
    --mount-report "${mount_report}" \
    --longhorn-nodes "${runtime_dir}/${phase}-longhorn-nodes.json" \
    >"${runtime_dir}/longhorn-capacity-${phase}.json"
}

capture_workload_state() {
  local prefix=$1
  local pod_name=$2
  "${kubectl_base[@]}" -n "${test_namespace}" get pvc checksum-data -o json \
    >"${runtime_dir}/${prefix}-pvc.json"
  "${kubectl_base[@]}" get persistentvolumes -o json >"${runtime_dir}/${prefix}-pvs.json"
  "${kubectl_base[@]}" -n longhorn-system get volumes.longhorn.io -o json \
    >"${runtime_dir}/${prefix}-volumes.json"
  "${kubectl_base[@]}" -n "${test_namespace}" get pod "${pod_name}" -o json \
    >"${runtime_dir}/${prefix}-pod.json"
}

capture_longhorn_health() {
  local prefix=$1
  "${kubectl_base[@]}" -n longhorn-system get volumes.longhorn.io -o json \
    >"${runtime_dir}/${prefix}-volumes.json"
  "${kubectl_base[@]}" -n longhorn-system get replicas.longhorn.io -o json \
    >"${runtime_dir}/${prefix}-replicas.json"
}

wait_for_longhorn_health() {
  local prefix=$1
  local output=$2
  local deadline=$((SECONDS + timeout_seconds))
  while true; do
    capture_longhorn_health "${prefix}"
    if python3 "${contract_helper}" health \
      --identity "${identity_file}" \
      --volumes "${runtime_dir}/${prefix}-volumes.json" \
      --replicas "${runtime_dir}/${prefix}-replicas.json" >"${output}" 2>/dev/null; then
      return 0
    fi
    (( SECONDS < deadline )) || break
    sleep 5
  done
  python3 "${contract_helper}" health \
    --identity "${identity_file}" \
    --volumes "${runtime_dir}/${prefix}-volumes.json" \
    --replicas "${runtime_dir}/${prefix}-replicas.json" >"${output}"
}

capture_capacity pre

"${kubectl_base[@]}" get storageclass "${storage_class}" -o json \
  >"${runtime_dir}/storage-class.json"
python3 "${contract_helper}" storage-class --input "${runtime_dir}/storage-class.json" \
  >"${runtime_dir}/storage-class-evidence.json"

existing_namespace=$("${kubectl_base[@]}" get namespace "${test_namespace}" \
  --ignore-not-found -o name)
[[ -z "${existing_namespace}" ]] || phase5_fail 'The unique Longhorn test namespace already exists.'

cat <<EOF | "${kubectl_base[@]}" apply --server-side \
  --field-manager=verda-phase5-storage-test --filename - >/dev/null
apiVersion: v1
kind: Namespace
metadata:
  name: ${test_namespace}
  labels:
    platform.verda-demo.io/test: longhorn-reschedule
    platform.verda-demo.io/run-id: ${run_id}
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: v1.35
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
EOF
namespace_created='true'

cat <<EOF | "${kubectl_base[@]}" apply --server-side \
  --field-manager=verda-phase5-storage-test --filename - >/dev/null
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: checksum-data
  namespace: ${test_namespace}
  labels:
    platform.verda-demo.io/test: longhorn-reschedule
    platform.verda-demo.io/run-id: ${run_id}
spec:
  accessModes: [ReadWriteOnce]
  volumeMode: Filesystem
  storageClassName: ${storage_class}
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: writer
  namespace: ${test_namespace}
  labels:
    platform.verda-demo.io/test: longhorn-reschedule
    platform.verda-demo.io/run-id: ${run_id}
spec:
  restartPolicy: Always
  terminationGracePeriodSeconds: 5
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    fsGroup: 65532
    fsGroupChangePolicy: OnRootMismatch
    seccompProfile: {type: RuntimeDefault}
  containers:
    - name: fixture
      image: ${fixture_image}
      imagePullPolicy: IfNotPresent
      command: [/bin/sh, -ec]
      args:
        - >-
          test ! -e /data/payload.bin;
          dd if=/dev/zero of=/data/payload.bin bs=1048576 count=4 2>/dev/null;
          test "\$(sha256sum /data/payload.bin | awk '{print \$1}')" = "${expected_checksum}";
          printf '%s\n' "${expected_checksum}" > /data/payload.sha256;
          sync;
          sleep infinity
      readinessProbe:
        exec:
          command:
            - /bin/sh
            - -ec
            - >-
              test "\$(sha256sum /data/payload.bin | awk '{print \$1}')" = "${expected_checksum}"
        initialDelaySeconds: 1
        periodSeconds: 5
      resources:
        requests: {cpu: 10m, memory: 16Mi}
        limits: {cpu: 100m, memory: 64Mi}
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: {drop: [ALL]}
        readOnlyRootFilesystem: true
        runAsNonRoot: true
        runAsUser: 65532
        seccompProfile: {type: RuntimeDefault}
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: checksum-data
EOF

"${kubectl_base[@]}" -n "${test_namespace}" wait pod/writer \
  --for=condition=Ready --timeout="${timeout}" >/dev/null
writer_checksum=$("${kubectl_base[@]}" -n "${test_namespace}" exec writer -- \
  sha256sum /data/payload.bin | awk '{print $1}')
[[ "${writer_checksum}" == "${expected_checksum}" ]] || phase5_fail 'Writer checksum verification failed.'
unset writer_checksum

capture_workload_state before writer
python3 "${contract_helper}" capture-identity \
  --pvc "${runtime_dir}/before-pvc.json" \
  --pvs "${runtime_dir}/before-pvs.json" \
  --volumes "${runtime_dir}/before-volumes.json" \
  --pod "${runtime_dir}/before-pod.json" \
  --run-id "${run_id}" \
  --namespace "${test_namespace}" \
  --output "${identity_file}"
wait_for_longhorn_health before "${runtime_dir}/health-before.json"

source_node=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_node"])' "${identity_file}")
[[ "${source_node}" =~ ^verda-mgmt-server-0[1-3]$ ]] || phase5_fail 'Captured source node is outside the management cluster.'

"${kubectl_base[@]}" -n "${test_namespace}" delete pod writer --wait=true \
  --timeout="${timeout}" >/dev/null

cat <<EOF | "${kubectl_base[@]}" apply --server-side \
  --field-manager=verda-phase5-storage-test --filename - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: reader
  namespace: ${test_namespace}
  labels:
    platform.verda-demo.io/test: longhorn-reschedule
    platform.verda-demo.io/run-id: ${run_id}
spec:
  restartPolicy: Always
  terminationGracePeriodSeconds: 5
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - key: kubernetes.io/hostname
                operator: NotIn
                values: [${source_node}]
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    fsGroup: 65532
    fsGroupChangePolicy: OnRootMismatch
    seccompProfile: {type: RuntimeDefault}
  containers:
    - name: fixture
      image: ${fixture_image}
      imagePullPolicy: IfNotPresent
      command: [/bin/sh, -ec]
      args:
        - >-
          test -f /data/payload.bin;
          test "\$(sha256sum /data/payload.bin | awk '{print \$1}')" = "${expected_checksum}";
          test "\$(cat /data/payload.sha256)" = "${expected_checksum}";
          sleep infinity
      readinessProbe:
        exec:
          command:
            - /bin/sh
            - -ec
            - >-
              test "\$(sha256sum /data/payload.bin | awk '{print \$1}')" = "${expected_checksum}"
        initialDelaySeconds: 1
        periodSeconds: 5
      resources:
        requests: {cpu: 10m, memory: 16Mi}
        limits: {cpu: 100m, memory: 64Mi}
      securityContext:
        allowPrivilegeEscalation: false
        capabilities: {drop: [ALL]}
        readOnlyRootFilesystem: true
        runAsNonRoot: true
        runAsUser: 65532
        seccompProfile: {type: RuntimeDefault}
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: checksum-data
EOF
unset source_node

"${kubectl_base[@]}" -n "${test_namespace}" wait pod/reader \
  --for=condition=Ready --timeout="${timeout}" >/dev/null
reader_checksum=$("${kubectl_base[@]}" -n "${test_namespace}" exec reader -- \
  sha256sum /data/payload.bin | awk '{print $1}')
[[ "${reader_checksum}" == "${expected_checksum}" ]] || phase5_fail 'Reader checksum verification failed.'
unset reader_checksum

capture_workload_state after reader
python3 "${contract_helper}" reschedule \
  --identity "${identity_file}" \
  --pvc "${runtime_dir}/after-pvc.json" \
  --pvs "${runtime_dir}/after-pvs.json" \
  --volumes "${runtime_dir}/after-volumes.json" \
  --pod "${runtime_dir}/after-pod.json" >"${runtime_dir}/reschedule.json"
wait_for_longhorn_health after "${runtime_dir}/health-after.json"

cleanup_test_objects || phase5_fail 'Bounded Longhorn cleanup or absence proof failed.'
capture_capacity post

python3 "${contract_helper}" report \
  --capacity-pre "${runtime_dir}/capacity-pre.json" \
  --capacity-post "${runtime_dir}/capacity-post.json" \
  --longhorn-capacity-pre "${runtime_dir}/longhorn-capacity-pre.json" \
  --longhorn-capacity-post "${runtime_dir}/longhorn-capacity-post.json" \
  --health-before "${runtime_dir}/health-before.json" \
  --health-after "${runtime_dir}/health-after.json" \
  --reschedule "${runtime_dir}/reschedule.json" \
  --absence "${absence_file}" \
  --run-id "${run_id}"
