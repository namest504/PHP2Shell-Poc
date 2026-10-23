#!/bin/bash
set -e
export USE_ZEND_ALLOC=${USE_ZEND_ALLOC:-1}
php-fpm --nodaemonize &
FPM_PID=$!
sleep 1
if ! kill -0 "$FPM_PID" 2>/dev/null; then
    echo "ERROR: PHP-FPM failed to start (PID $FPM_PID exited)" >&2
    exit 1
fi
nginx -g 'daemon off;' &
NGINX_PID=$!
wait -n "$FPM_PID" "$NGINX_PID" 2>/dev/null || true
echo "ERROR: a child process exited; shutting down" >&2
kill "$FPM_PID" "$NGINX_PID" 2>/dev/null || true
exit 1
