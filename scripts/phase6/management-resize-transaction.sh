#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

if [[ "$(uname -s)" != Linux ]]; then
  printf '%s\n' '[FAIL] Phase 6 transaction requires Linux.' >&2
  exit 64
fi

action="${1:-}"
node="${2:-}"
case "$action" in
  verify-state) ;;
  plan-node)
    [[ "$node" =~ ^0[1-3]$ ]] || { printf '%s\n' '[FAIL] plan-node requires node 01, 02, or 03.' >&2; exit 64; }
    ;;
  *) printf '%s\n' '[FAIL] supported actions are verify-state and plan-node; apply remains disabled.' >&2; exit 64 ;;
esac

config_root="${XDG_CONFIG_HOME:-$HOME/.config}/verda-takehome"
state_root="${XDG_STATE_HOME:-$HOME/.local/state}/verda-takehome"
gpg_home="$config_root/gnupg"
encrypted_state="$state_root/terraform/management.tfstate.gpg"
lock_file="$state_root/phase6-resize.lock"
terraform_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../infra/terraform/environments/management" && pwd -P)"
repository="$(cd -- "$terraform_root/../../../.." && pwd -P)"
terraform_bin=/snap/bin/terraform
[[ -x "$terraform_bin" ]] || terraform_bin=/usr/bin/terraform
[[ -x "$terraform_bin" ]] || { printf '%s\n' '[FAIL] pinned Linux Terraform binary is absent.' >&2; exit 64; }

for directory in "$config_root" "$state_root" "$gpg_home"; do
  [[ -d "$directory" && ! -L "$directory" ]] || { printf '%s\n' '[FAIL] protected Linux directory is absent.' >&2; exit 64; }
  [[ "$(stat -c '%u:%a' "$directory")" == "$(id -u):700" ]] || {
    printf '%s\n' '[FAIL] protected Linux directory ownership/mode differs.' >&2
    exit 64
  }
done
[[ -f "$encrypted_state" && ! -L "$encrypted_state" && "$(stat -c '%u:%a:%h' "$encrypted_state")" == "$(id -u):600:1" ]] || {
  printf '%s\n' '[FAIL] encrypted Linux Terraform state boundary differs.' >&2
  exit 64
}

exec 9>"$lock_file"
chmod 0600 "$lock_file"
flock -n 9 || { printf '%s\n' '[FAIL] another Phase 6 transaction holds the state lease.' >&2; exit 75; }

runtime="$(mktemp -d "${TMPDIR:-/tmp}/verda-phase6-resize.XXXXXX")"
cleanup() {
  unset VERDA_CLIENT_ID VERDA_CLIENT_SECRET || true
  if [[ -n "${runtime:-}" && "$runtime" == "${TMPDIR:-/tmp}"/verda-phase6-resize.* ]]; then
    rm -rf -- "$runtime"
  fi
}
trap cleanup EXIT HUP INT TERM
state_path="$runtime/management.tfstate"
gpg --homedir "$gpg_home" --batch --quiet --decrypt "$encrypted_state" >"$state_path"
chmod 0600 "$state_path"

state_receipt="$runtime/state-receipt.json"
python3 - "$state_path" "$state_receipt" <<'PY'
import hashlib, json, pathlib, sys
source = pathlib.Path(sys.argv[1])
value = json.loads(source.read_text(encoding="utf-8"))
lineage = value.get("lineage")
serial = value.get("serial")
if not isinstance(lineage, str) or len(lineage) != 36 or type(serial) is not int or serial < 0:
    raise SystemExit(64)
receipt = {
    "schema_version": 1,
    "status": "LINUX_STATE_VERIFIED",
    "state_lineage_sha256": hashlib.sha256(lineage.encode()).hexdigest(),
    "state_serial": serial,
    "state_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "raw_values_recorded": False,
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
PY

export TF_IN_AUTOMATION=1
export TF_INPUT=0
export TF_DATA_DIR="$runtime/terraform-data"
export PATH="/snap/bin:/usr/bin:/bin"
"$terraform_bin" -chdir="$terraform_root" init -reconfigure -input=false -lockfile=readonly \
  -backend-config="path=$state_path" >/dev/null
"$terraform_bin" -chdir="$terraform_root" state pull >/dev/null
if [[ "$action" == verify-state ]]; then
  cat "$state_receipt"
  exit 0
fi

[[ -z "$(git -C "$repository" status --porcelain --untracked-files=all)" ]] || {
  printf '%s\n' '[FAIL] plan-node requires an exactly clean reviewed commit.' >&2
  exit 64
}
commit="$(git -C "$repository" rev-parse HEAD)"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { printf '%s\n' '[FAIL] reviewed commit is invalid.' >&2; exit 64; }

credential_file="$config_root/verda-shared-credentials"
[[ -f "$credential_file" && ! -L "$credential_file" && "$(stat -c '%u:%a:%h' "$credential_file")" == "$(id -u):600:1" ]] || {
  printf '%s\n' '[FAIL] protected Verda credential file differs.' >&2
  exit 64
}
while IFS='=' read -r key value; do
  key="${key//[[:space:]]/}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  case "$key" in
    verda_client_id) export VERDA_CLIENT_ID="$value" ;;
    verda_client_secret) export VERDA_CLIENT_SECRET="$value" ;;
  esac
done <"$credential_file"
[[ -n "${VERDA_CLIENT_ID:-}" && -n "${VERDA_CLIENT_SECRET:-}" ]] || {
  printf '%s\n' '[FAIL] process-only Verda credentials are absent.' >&2
  exit 64
}

active_contract="$runtime/phase6-management-resize.active.json"
python3 - "$repository/config/phase6-management-resize.json" "$active_contract" "$commit" <<'PY'
import json, pathlib, sys
source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
commit = sys.argv[3]
value = json.loads(source.read_text(encoding="utf-8"))
value["activation"] = {
    "enabled": True,
    "writes_allowed": True,
    "integrated_commit": commit,
    "reason": "User-approved Phase 6 serial resize through the locked Linux transaction.",
}
value["terraform"]["target_resource_expiry_utc"] = "2026-08-27T21:00:00Z"
target.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY

python3 - "$terraform_root/main.tf" "$node" <<'PY'
import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
node = sys.argv[2]
match = re.search(rf'"{node}"\s*=\s*\{{(?P<body>.*?)\n\s*\}}', text, re.S)
if not match:
    raise SystemExit(64)
body = match.group("body")
if 'instance_type       = "CPU.8V.32G"' not in body:
    raise SystemExit(64)
if 'resource_expiry_utc = "2026-08-27T21:00:00Z"' not in body:
    raise SystemExit(64)
PY

plan_directory="$state_root/phase6/plans"
backup_directory="$state_root/phase6/backups"
install -d -m 0700 "$plan_directory" "$backup_directory"
plan_file="$plan_directory/node-$node-$commit.tfplan"
backup_file="$backup_directory/pre-plan-$node-$commit.tfstate.gpg"
cp --reflink=never -- "$encrypted_state" "$backup_file.tmp"
chmod 0600 "$backup_file.tmp"
mv -f -- "$backup_file.tmp" "$backup_file"
rm -f -- "$plan_file"
set +e
"$terraform_bin" -chdir="$terraform_root" plan -input=false -lock-timeout=60s \
  -detailed-exitcode -out="$plan_file" >/dev/null
plan_exit=$?
set -e
[[ "$plan_exit" == 2 ]] || { printf '%s\n' '[FAIL] Phase 6 plan is empty or Terraform refused it.' >&2; exit 64; }
chmod 0600 "$plan_file"
python3 "$repository/scripts/phase6/management-node-resize.py" \
  --repository "$repository" --contract "$active_contract" assert-saved-plan \
  --saved-plan "$plan_file" --node "$node" --direction resize
