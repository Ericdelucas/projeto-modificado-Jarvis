#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export OPENJARVIS_CONFIG="${OPENJARVIS_CONFIG:-$PWD/configs/local-dev.toml}"
export JARVIS_VOICE_REFERENCE="$PWD/.runtime/voices/lucas.wav"
export JARVIS_XTTS_MODEL="$PWD/.runtime/xtts"
export OLLAMA_MODELS="$PWD/.runtime/models"
export NUMBA_CACHE_DIR="$PWD/.runtime/numba"
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
mkdir -p .runtime/logs
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    nohup .runtime/bin/ollama serve > .runtime/logs/ollama.log 2>&1 &
    for attempt in {1..30}; do
        if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then break; fi
        sleep 1
    done
fi
if ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    nohup .venv/bin/jarvis serve > .runtime/logs/jarvis.log 2>&1 &
    for attempt in {1..60}; do
        if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then break; fi
        sleep 1
    done
fi
curl -fsS http://127.0.0.1:8000/health >/dev/null
printf 'Jarvis disponível em http://127.0.0.1:8000\n'
if [[ "${1:-}" != "--no-browser" ]]; then
    xdg-open http://127.0.0.1:8000 >/dev/null 2>&1 || true
fi

# Keep the launch session alive while its servers are running.
wait
