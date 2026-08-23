#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077

readonly MODE="${1:-preflight}"
readonly HARBOR_URL_VALUE="${HARBOR_URL:-}"
readonly HARBOR_PROJECT="${HARBOR_PROJECT:-platform-demo}"
readonly HARBOR_REVIEWER_USER_VALUE="${HARBOR_REVIEWER_USER:-verda-reviewer}"
readonly HARBOR_REVIEWER_EMAIL_VALUE="${HARBOR_REVIEWER_EMAIL:-verda-reviewer@example.invalid}"
readonly HARBOR_ADMIN_USER_VALUE="${HARBOR_ADMIN_USER:-admin}"

admin_password="${HARBOR_ADMIN_PASSWORD:-}"
reviewer_password="${HARBOR_REVIEWER_PASSWORD:-}"
unset HARBOR_ADMIN_PASSWORD HARBOR_REVIEWER_PASSWORD

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit "${2:-1}"
}

case "$MODE" in
  preflight | reconcile | verify) ;;
  *) die "usage: $0 [preflight|reconcile|verify]" 64 ;;
esac

[[ "$HARBOR_URL_VALUE" =~ ^https://harbor\.([0-9]{1,3}-){3}[0-9]{1,3}\.nip\.io$ ]] ||
  die "HARBOR_URL must be the accepted HTTPS harbor.<IPv4-with-dashes>.nip.io endpoint" 64
[[ "$HARBOR_PROJECT" == "platform-demo" ]] || die "HARBOR_PROJECT must remain platform-demo" 64
[[ "$HARBOR_REVIEWER_USER_VALUE" == "verda-reviewer" ]] || die "reviewer username must remain verda-reviewer" 64
[[ "$HARBOR_ADMIN_USER_VALUE" == "admin" ]] || die "admin username must remain admin" 64
command -v curl >/dev/null || die "curl is required" 69
command -v python3 >/dev/null || die "python3 is required" 69

work_dir="$(mktemp -d)"
cleanup() {
  rm -f -- "$work_dir"/* 2>/dev/null || true
  rmdir -- "$work_dir" 2>/dev/null || true
}
trap cleanup EXIT
response_file="$work_dir/response.json"
request_file="$work_dir/request.json"

anonymous_request() {
  local method="$1" path="$2"
  curl --silent --show-error --location --max-time 20 --proto '=https' --tlsv1.2 \
    --request "$method" --output "$response_file" --write-out '%{http_code}' \
    "${HARBOR_URL_VALUE}${path}"
}

authenticated_request() {
  local username="$1" password="$2" method="$3" path="$4" body_file="${5:-}"
  local -a args=(
    --silent --show-error --location --max-time 30 --proto '=https' --tlsv1.2
    --config - --request "$method" --output "$response_file" --write-out '%{http_code}'
    --header 'Accept: application/json'
  )
  if [[ -n "$body_file" ]]; then
    args+=(--header 'Content-Type: application/json' --data-binary "@$body_file")
  fi
  args+=("${HARBOR_URL_VALUE}${path}")
  printf 'user = "%s:%s"\n' "$username" "$password" | curl "${args[@]}"
}

require_credentials() {
  [[ ${#admin_password} -ge 16 ]] || die "HARBOR_ADMIN_PASSWORD must be supplied out of band and contain at least 16 characters" 64
  [[ "$admin_password" != *$'\n'* ]] || die "HARBOR_ADMIN_PASSWORD must be a single curl-config-safe line" 64
  [[ "$admin_password" != *$'\r'* ]] || die "HARBOR_ADMIN_PASSWORD must be a single curl-config-safe line" 64
  [[ "$admin_password" != *\"* ]] || die "HARBOR_ADMIN_PASSWORD must not contain a double quote" 64
  [[ "$admin_password" != *\\* ]] || die "HARBOR_ADMIN_PASSWORD must not contain a backslash" 64
}

require_reviewer_credentials() {
  require_credentials
  [[ ${#reviewer_password} -ge 16 ]] || die "HARBOR_REVIEWER_PASSWORD must be supplied out of band and contain at least 16 characters" 64
  [[ "$reviewer_password" != *$'\n'* ]] || die "HARBOR_REVIEWER_PASSWORD must be a single curl-config-safe line" 64
  [[ "$reviewer_password" != *$'\r'* ]] || die "HARBOR_REVIEWER_PASSWORD must be a single curl-config-safe line" 64
  [[ "$reviewer_password" != *\"* ]] || die "HARBOR_REVIEWER_PASSWORD must not contain a double quote" 64
  [[ "$reviewer_password" != *\\* ]] || die "HARBOR_REVIEWER_PASSWORD must not contain a backslash" 64
  [[ "$reviewer_password" != "$admin_password" ]] || die "admin and reviewer passwords must differ" 64
}

health_status="$(anonymous_request GET /api/v2.0/health)"
[[ "$health_status" == "200" ]] || die "Harbor health endpoint is not reachable over verified TLS"
python3 - "$response_file" <<'PY'
import json, pathlib, sys
body = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if body.get("status") != "healthy":
    raise SystemExit("Harbor reports an unhealthy component")
PY

anonymous_project_status="$(anonymous_request GET "/api/v2.0/projects/${HARBOR_PROJECT}")"
case "$anonymous_project_status" in
  401 | 403 | 404) ;;
  *) die "anonymous project detail access is not denied" ;;
esac
anonymous_push_status="$(anonymous_request POST "/v2/${HARBOR_PROJECT}/blobs/uploads/")"
case "$anonymous_push_status" in
  401 | 403 | 404) ;;
  *) die "anonymous registry push initiation is not denied" ;;
esac

if [[ "$MODE" == "preflight" ]]; then
  printf 'PASS preflight: Harbor TLS/health is valid and anonymous project/push access is denied\n'
  exit 0
fi

require_credentials

project_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" GET "/api/v2.0/projects/${HARBOR_PROJECT}")"
if [[ "$MODE" == "reconcile" && "$project_status" == "404" ]]; then
  [[ "${HARBOR_MUTATION_APPROVED:-}" == "yes" ]] || die "set HARBOR_MUTATION_APPROVED=yes for the bounded reconcile" 64
  [[ "${HARBOR_MUTATION_SCOPE:-}" == "platform-demo,verda-reviewer" ]] || die "mutation scope must be exactly platform-demo,verda-reviewer" 64
  printf '%s\n' "$HARBOR_PROJECT" | python3 -c 'import json,sys; print(json.dumps({"project_name":sys.stdin.readline().strip(),"metadata":{"public":"false","auto_scan":"true","auto_sbom_generation":"true","prevent_vul":"false","reuse_sys_cve_allowlist":"true"},"storage_limit":53687091200},separators=(",",":")))' >"$request_file"
  project_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" POST /api/v2.0/projects "$request_file")"
  [[ "$project_status" == "201" ]] || die "failed to create the bounded private Harbor project"
  project_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" GET "/api/v2.0/projects/${HARBOR_PROJECT}")"
fi
[[ "$project_status" == "200" ]] || die "the private Harbor project does not exist"
project_state="$(python3 - "$response_file" "$HARBOR_PROJECT" <<'PY'
import json, pathlib, sys
body = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
metadata = body.get("metadata") or {}
expected = {"public":"false", "auto_scan":"true", "auto_sbom_generation":"true"}
print("ready" if body.get("name") == sys.argv[2] and all(metadata.get(k) == v for k, v in expected.items()) else "drift")
PY
)"
if [[ "$project_state" == "drift" && "$MODE" == "reconcile" ]]; then
  [[ "${HARBOR_MUTATION_APPROVED:-}" == "yes" ]] || die "set HARBOR_MUTATION_APPROVED=yes for the bounded reconcile" 64
  [[ "${HARBOR_MUTATION_SCOPE:-}" == "platform-demo,verda-reviewer" ]] || die "mutation scope must be exactly platform-demo,verda-reviewer" 64
  printf '%s\n' "$HARBOR_PROJECT" | python3 -c 'import json,sys; print(json.dumps({"project_name":sys.stdin.readline().strip(),"metadata":{"public":"false","auto_scan":"true","auto_sbom_generation":"true","prevent_vul":"false","reuse_sys_cve_allowlist":"true"},"storage_limit":53687091200},separators=(",",":")))' >"$request_file"
  project_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" PUT "/api/v2.0/projects/${HARBOR_PROJECT}" "$request_file")"
  [[ "$project_status" == "200" ]] || die "failed to restore the private scan-on-push project contract"
  project_state="ready"
fi
[[ "$project_state" == "ready" ]] || die "Harbor project is not private with automatic scan and SBOM enabled"

if [[ "$MODE" == "reconcile" ]]; then
  require_reviewer_credentials
  [[ "${HARBOR_MUTATION_APPROVED:-}" == "yes" ]] || die "set HARBOR_MUTATION_APPROVED=yes for the bounded reconcile" 64
  [[ "${HARBOR_MUTATION_SCOPE:-}" == "platform-demo,verda-reviewer" ]] || die "mutation scope must be exactly platform-demo,verda-reviewer" 64
  user_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" GET "/api/v2.0/users/search?username=${HARBOR_REVIEWER_USER_VALUE}")"
  [[ "$user_status" == "200" ]] || die "failed to query the evaluator account"
  user_state="$(python3 - "$response_file" "$HARBOR_REVIEWER_USER_VALUE" <<'PY'
import json, pathlib, sys
users = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
exact = [u for u in users if u.get("username") == sys.argv[2]]
if len(exact) > 1:
    raise SystemExit("duplicate evaluator users")
print("present" if exact else "missing")
PY
)"
  if [[ "$user_state" == "missing" ]]; then
    printf '%s\n%s\n%s\n' "$HARBOR_REVIEWER_EMAIL_VALUE" "$reviewer_password" "$HARBOR_REVIEWER_USER_VALUE" |
      python3 -c 'import json,sys; email=sys.stdin.readline().strip(); password=sys.stdin.readline().strip(); username=sys.stdin.readline().strip(); print(json.dumps({"email":email,"realname":"Verda Reviewer","comment":"Phase 6 evaluator guest account","password":password,"username":username},separators=(",",":")))' >"$request_file"
    user_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" POST /api/v2.0/users "$request_file")"
    [[ "$user_status" == "201" ]] || die "failed to create the evaluator account"
  fi

  member_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" GET "/api/v2.0/projects/${HARBOR_PROJECT}/members?entityname=${HARBOR_REVIEWER_USER_VALUE}")"
  [[ "$member_status" == "200" ]] || die "failed to query evaluator project membership"
  member_state="$(python3 - "$response_file" "$HARBOR_REVIEWER_USER_VALUE" <<'PY'
import json, pathlib, sys
members = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
exact = [m for m in members if m.get("entity_name") == sys.argv[2]]
if len(exact) > 1:
    raise SystemExit("duplicate evaluator memberships")
if not exact:
    print("missing")
elif exact[0].get("role_id") == 3:
    print("guest")
else:
    print(f"drift:{exact[0].get('id')}")
PY
)"
  case "$member_state" in
    guest) ;;
    missing)
      printf '%s\n' "$HARBOR_REVIEWER_USER_VALUE" | python3 -c 'import json,sys; print(json.dumps({"role_id":3,"member_user":{"username":sys.stdin.readline().strip()}},separators=(",",":")))' >"$request_file"
      member_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" POST "/api/v2.0/projects/${HARBOR_PROJECT}/members" "$request_file")"
      [[ "$member_status" == "201" ]] || die "failed to grant the evaluator guest role"
      ;;
    drift:*)
      member_id="${member_state#drift:}"
      [[ "$member_id" =~ ^[0-9]+$ ]] || die "invalid evaluator membership identity"
      printf '%s' '{"role_id":3}' >"$request_file"
      member_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" PUT "/api/v2.0/projects/${HARBOR_PROJECT}/members/${member_id}" "$request_file")"
      [[ "$member_status" == "200" ]] || die "failed to reduce evaluator membership to guest"
      ;;
    *) die "unexpected evaluator membership state" ;;
  esac
fi

member_status="$(authenticated_request "$HARBOR_ADMIN_USER_VALUE" "$admin_password" GET "/api/v2.0/projects/${HARBOR_PROJECT}/members?entityname=${HARBOR_REVIEWER_USER_VALUE}")"
[[ "$member_status" == "200" ]] || die "failed final evaluator membership query"
python3 - "$response_file" "$HARBOR_REVIEWER_USER_VALUE" <<'PY'
import json, pathlib, sys
members = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
exact = [m for m in members if m.get("entity_name") == sys.argv[2] and m.get("role_id") == 3]
if len(exact) != 1:
    raise SystemExit("evaluator is not exactly one guest member")
PY

final_anonymous_push_status="$(anonymous_request POST "/v2/${HARBOR_PROJECT}/blobs/uploads/")"
case "$final_anonymous_push_status" in
  401 | 403) ;;
  *) die "final anonymous push denial did not return an authentication/authorization failure" ;;
esac

printf 'PASS %s: private project, automatic scanning/SBOM, anonymous denial, and evaluator guest role verified\n' "$MODE"
