#!/bin/sh
set -eu
umask 077
mkdir -p /auth
if [ ! -s /auth/htpasswd ]; then
    username=${EASYREAD_ADMIN_USER:-admin}
    case "$username" in ''|*[!a-zA-Z0-9_-]*) echo 'Invalid administrator username' >&2; exit 1;; esac
    password=${EASYREAD_ADMIN_PASSWORD:-}
    if [ -z "$password" ]; then
        password=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
    fi
    if [ ${#password} -lt 16 ]; then
        echo 'Administrator password must have at least 16 characters' >&2
        exit 1
    fi
    printf '%s\n' "$username" > /auth/username
    printf '%s\n' "$password" > /auth/password
    htpasswd -Bbc /auth/htpasswd.tmp "$username" "$password" >/dev/null 2>&1
    mv /auth/htpasswd.tmp /auth/htpasswd
    echo 'Administrator credentials created. Retrieve with: docker compose exec gateway easyread-admin credentials'
fi
if [ ! -s /auth/tls.crt ] || [ ! -s /auth/tls.key ]; then
    san='DNS:localhost,IP:127.0.0.1,IP:::1'
    old_ifs=$IFS
    IFS=,
    for name in ${EASYREAD_ALLOWED_HOSTS:-}; do
        case "$name" in ''|*[!a-zA-Z0-9_.:-]*) echo 'Certificate names must be plain IPs/domains' >&2; exit 1;; esac
        case "$name" in
            *:*) san="$san,IP:$name";;
            *[!0-9.]*) san="$san,DNS:$name";;
            *) san="$san,IP:$name";;
        esac
    done
    IFS=$old_ifs
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
        -subj '/CN=EasyRead local deployment' -addext "subjectAltName=$san" \
        -keyout /auth/tls.key.tmp -out /auth/tls.crt.tmp >/dev/null 2>&1
    mv /auth/tls.key.tmp /auth/tls.key
    mv /auth/tls.crt.tmp /auth/tls.crt
    echo 'Local HTTPS certificate created. Trust only your own certificate; use a trusted certificate/proxy for public deployment.'
fi
exec nginx -g 'daemon off;'
