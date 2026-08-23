#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

if [[ "$(uname -s)" != Linux ]]; then
  printf '%s\n' '[FAIL] Phase 6 transaction requires Linux.' >&2
  exit 64
fi

action="${1:-}"
case "$action" in
  verify-state) ;;
  *) printf '%s\n' '[FAIL] supported action is verify-state while mutation remains disabled.' >&2; exit 64 ;;
esac

config_root="${XDG_CONFIG_HOME:-$HOME/.config}/verda-takehome"
state_root="${XDG_STATE_HOME:-$HOME/.local/state}/verda-takehome"
gpg_home="$config_root/gnupg"
encrypted_state="$state_root/terraform/management.tfstate.gpg"
lock_file="$state_root/phase6-resize.lock"
terraform_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../infra/terraform/environments/management" && pwd -P)"
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
"$terraform_bin" -chdir="$terraform_root" init -reconfigure -input=false -lockfile=readonly \
  -backend-config="path=$state_path" >/dev/null
"$terraform_bin" -chdir="$terraform_root" state pull >/dev/null
cat "$state_receipt"
