#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROFILE="${PROJECT_FLOW_PROFILE:-}"
if [[ -z "$PROFILE" ]]; then
  LOCAL_PROFILES=("$SCRIPT_DIR"/profiles/*.json(N))
  LOCAL_PROFILES=("${(@)LOCAL_PROFILES:#$SCRIPT_DIR/profiles/example.json}")
  if (( ${#LOCAL_PROFILES} != 1 )); then
    print -u2 "Please set PROJECT_FLOW_PROFILE to a configured Project Profile JSON."
    print -u2 "Example: PROJECT_FLOW_PROFILE=\"$SCRIPT_DIR/profiles/my-project.json\" ./start.command"
    exit 1
  fi
  PROFILE="$LOCAL_PROFILES[1]"
fi
PROFILE_PORT="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("port", 4318))' "$PROFILE")"
PORT="${PROJECT_FLOW_PORT:-$PROFILE_PORT}"
URL="http://127.0.0.1:${PORT}/"

cd "$SCRIPT_DIR"

if /usr/bin/curl --silent --fail "${URL}api/health" >/dev/null 2>&1; then
  /usr/bin/open "$URL"
  exit 0
fi

(
  /bin/sleep 0.8
  /usr/bin/open "$URL"
) &

exec /usr/bin/python3 "$SCRIPT_DIR/server.py" --profile "$PROFILE" --port "$PORT"
