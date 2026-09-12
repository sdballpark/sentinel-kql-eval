#!/usr/bin/env bash
# Start/stop the local Kusto emulator.
#
# Binds to 127.0.0.1 deliberately. The emulator supports neither HTTPS nor
# Entra authentication, so publishing it on 0.0.0.0 would expose an
# unauthenticated query engine to anything that can reach this host.
set -euo pipefail

NAME=kustainer
IMAGE=mcr.microsoft.com/azuredataexplorer/kustainer-linux:latest
PORT="${KQL_EVAL_KUSTO_PORT:-8080}"

case "${1:-start}" in
  start)
    if [ -n "$(docker ps -q -f name="^${NAME}$")" ]; then
      echo "${NAME} already running on 127.0.0.1:${PORT}"
      exit 0
    fi
    docker rm -f "${NAME}" >/dev/null 2>&1 || true
    docker run -e ACCEPT_EULA=Y -m 4G -d \
      -p "127.0.0.1:${PORT}:8080" --name "${NAME}" "${IMAGE}" >/dev/null
    until curl -s -m 5 -X POST "http://127.0.0.1:${PORT}/v1/rest/query" \
      -H 'Content-Type: application/json' \
      -d '{"db":"NetDefaultDB","csl":"print ready=1"}' 2>/dev/null | grep -q '"Rows"'; do
      sleep 1
    done
    echo "${NAME} ready on 127.0.0.1:${PORT}"
    ;;
  stop)
    docker rm -f "${NAME}" >/dev/null 2>&1 && echo "${NAME} stopped" || echo "${NAME} not running"
    ;;
  *)
    echo "usage: $0 {start|stop}" >&2
    exit 2
    ;;
esac
