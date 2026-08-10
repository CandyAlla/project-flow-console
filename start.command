#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROFILE="${PROJECT_FLOW_PROFILE:-}"
if [[ -n "$PROFILE" ]]; then
  PROFILE_PORT="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("port", 4318))' "$PROFILE")"
  PORT="${PROJECT_FLOW_PORT:-$PROFILE_PORT}"
  HEALTH_PATH="api/health"
else
  PORT="${PROJECT_FLOW_HUB_PORT:-4318}"
  HEALTH_PATH="api/hub/projects"
fi
URL="http://127.0.0.1:${PORT}/"

cd "$SCRIPT_DIR"

if /usr/bin/curl --silent --fail "${URL}${HEALTH_PATH}" >/dev/null 2>&1; then
  /usr/bin/open "$URL"
  exit 0
fi

# Keep an already-running legacy single-project service untouched. Its active jobs
# must finish in the process that owns them; the Hub can take over after restart.
if [[ -z "$PROFILE" ]] && /usr/bin/curl --silent --fail "${URL}api/health" >/dev/null 2>&1; then
  /usr/bin/open "$URL"
  exit 0
fi

(
  /bin/sleep 0.8
  /usr/bin/open "$URL"
) &

if [[ -n "$PROFILE" ]]; then
  exec /usr/bin/python3 "$SCRIPT_DIR/server.py" --profile "$PROFILE" --port "$PORT"
fi

exec /usr/bin/python3 "$SCRIPT_DIR/hub.py" --port "$PORT"
