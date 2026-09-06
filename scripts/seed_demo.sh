#!/usr/bin/env sh
# Seed a ready-to-poke demo check: log in, create a project, pin two companies.
# Prints the S2 URL to open. Re-runnable — every call makes a fresh project.
set -eu

BASE="${SEED_BASE_URL:-http://localhost:5173}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

req() {
  # req METHOD PATH [JSON_BODY]
  method="$1"; path="$2"; body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -b "$JAR" -c "$JAR" -X "$method" "$BASE$path" \
      -H 'Content-Type: application/json' -d "$body"
  else
    curl -sS -b "$JAR" -c "$JAR" -X "$method" "$BASE$path"
  fi
}

echo "→ demo login"
req POST /api/v1/auth/session '{"login":"demo-analyst"}' >/dev/null

RID="$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || uuidgen | tr 'A-Z' 'a-z')"
echo "→ create project"
PROJECT="$(req POST /api/v1/projects "{\"client_request_id\":\"$RID\",\"title\":\"Демо: ООО СПОРТ и ООО АГАТ\"}")"
PID="$(printf '%s' "$PROJECT" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')"
TID="$(printf '%s' "$PROJECT" | python3 -c 'import sys,json; print(json.load(sys.stdin)["default_thread_id"])')"

echo "→ pin companies 9705152496, 0278949271"
req POST "/api/v1/projects/$PID/companies" \
  '{"items":[{"inn":"9705152496"},{"inn":"0278949271"}],"expected_context_version":0}' >/dev/null

echo
echo "Open:  $BASE/checks/$PID/chats/$TID"
echo "(demo login is per-browser — press «Войти в демо» once if the app asks)"
