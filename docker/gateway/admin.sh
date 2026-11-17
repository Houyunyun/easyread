#!/bin/sh
set -eu
if [ "${1:-}" != credentials ]; then
    echo 'Usage: easyread-admin credentials' >&2
    exit 1
fi
printf 'Username: '; head -n 1 /auth/username
printf 'Password: '; head -n 1 /auth/password
