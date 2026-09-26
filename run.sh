#!/usr/bin/env bash
# Keeps the journal alive. If the process dies for any reason it comes straight back,
# so a crash can never leave you staring at a page that stopped replying.
cd "$(dirname "$0")" || exit 1
PORT="${PORT:-8848}"
export PORT

: "${IASPIRE_LLM_PROVIDER:=ollama}"
: "${IASPIRE_LLM_MODEL:=qwen3.6:35b-a3b-coding-mxfp8}"
: "${IASPIRE_LLM:=1}"
export IASPIRE_LLM IASPIRE_LLM_PROVIDER IASPIRE_LLM_MODEL

if ! curl -s --max-time 2 "http://localhost:11434/api/tags" >/dev/null 2>&1; then
  echo "Ollama not reachable on :11434 - starting in deterministic-only mode."
  echo "The journal still works fully; it just won't consult the local model."
  unset IASPIRE_LLM
  export IASPIRE_LLM=0
fi

echo "iASPIRE Journal -> http://127.0.0.1:${PORT}   (Ctrl-C to stop)"
# Wait for the port to be released before restarting, otherwise the new process races the
# old one and dies on "Address already in use".
wait_for_port_free() {
  for _ in $(seq 1 40); do
    if ! curl -s --max-time 1 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then return 0; fi
    sleep 0.25
  done
  return 1
}

while true; do
  python3 app.py
  code=$?
  echo "--- journal exited (code $code); restarting ---"
  wait_for_port_free || lsof -ti "tcp:${PORT}" | xargs kill -9 2>/dev/null
  sleep 0.5
done
