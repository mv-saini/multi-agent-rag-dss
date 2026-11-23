#!/bin/sh
set -eu

backend_pid=
nginx_pid=

cleanup() {
    trap '' INT TERM
    if [ -n "$backend_pid" ]; then
        kill -TERM "$backend_pid" 2>/dev/null || true
    fi
    if [ -n "$nginx_pid" ]; then
        kill -QUIT "$nginx_pid" 2>/dev/null || true
    fi
    if [ -n "$backend_pid" ]; then
        wait "$backend_pid" 2>/dev/null || true
    fi
    if [ -n "$nginx_pid" ]; then
        wait "$nginx_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

uvicorn api:app --host 0.0.0.0 --port 8000 &
backend_pid=$!

nginx -g 'daemon off;' &
nginx_pid=$!

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$nginx_pid" 2>/dev/null; do
    sleep 1
done

echo "Uvicorn or Nginx stopped; shutting down the container." >&2
exit 1
