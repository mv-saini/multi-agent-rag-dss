#!/bin/sh
set -eu

uvicorn api:app --host 0.0.0.0 --port 8000 &
backend_pid=$!

cleanup() {
    kill "$backend_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

nginx -g 'daemon off;'