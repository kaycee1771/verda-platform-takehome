#!/usr/bin/env bash
set -Eeuo pipefail

from="${1:-}"
to="${2:-}"
digest="${3:-}"
[[ "$from" =~ ^(dev|staging)$ && "$to" =~ ^(staging|prod)$ ]] ||
  { echo 'usage: promote.sh dev staging sha256:<64hex> | staging prod sha256:<64hex>' >&2; exit 2; }
[[ "$from:$to" == dev:staging || "$from:$to" == staging:prod ]] ||
  { echo 'promotion must be dev -> staging -> prod' >&2; exit 2; }
[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] ||
  { echo 'digest must be sha256:<64 lowercase hex>' >&2; exit 2; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source_file="${repo_root}/applications/platform-demo/values-${from}.yaml"
target_file="${repo_root}/applications/platform-demo/values-${to}.yaml"
grep -q "digest: ${digest}" "$source_file" ||
  { echo 'source environment does not contain the requested digest' >&2; exit 1; }

python3 - "$target_file" "$digest" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
digest = sys.argv[2]
text = path.read_text(encoding="utf-8")
updated, count = re.subn(r"(?m)^  digest: sha256:[0-9a-f]{64}$", f"  digest: {digest}", text)
if count != 1:
    raise SystemExit("target digest field was not unique")
path.write_text(updated, encoding="utf-8", newline="\n")
PY

printf 'updated=%s digest=%s\n' "$target_file" "$digest"
printf 'review the diff, commit it, open a PR, and let Argo CD reconcile\n'
