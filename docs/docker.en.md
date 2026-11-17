# Full Docker deployment

[简体中文](docker.md)

The default Compose deployment includes the Python backend, existing Web UI, **Claude Code, Codex CLI, Chromium and BabelDOC**, plus an authenticated browser terminal. Host Python, Node.js and Electron are not required. For the full deployment, use Docker Engine 24+, Compose v2 and a host permitting unprivileged user namespaces; allow at least 4 GB RAM and 8 GB free disk. Large papers/concurrent jobs need more RAM.

## 1. Clone and start

```bash
git clone https://github.com/Jasaxion/easyread.git
cd easyread
cp .env.example .env
docker compose up -d --build
```

The first build downloads model CLIs, a browser and PDF components. Later starts can use `docker compose up -d`. Optional build proxy and CLI versions are configured in `.env`; proxy build arguments use both lowercase and uppercase forms for apt/curl/npm/pip compatibility.

Default URLs:

- Reader: **https://localhost:8765**
- CLI terminal: **https://localhost:8766**

Both ports require administrator authentication at the HTTPS gateway. Backend/ttyd ports are not published. The terminal has a separate origin, rejects foreign-origin WebSockets and cannot be embedded in the reader. HTTP requests redirect to HTTPS.

### First-run credentials and certificate

First startup generates a random persistent password and a local self-signed certificate in a separate authentication volume. The password is never printed in startup logs. Retrieve it explicitly:

```bash
docker compose exec gateway easyread-admin credentials
```

The default username is `admin`. Alternatively, set `EASYREAD_ADMIN_USER` and `EASYREAD_ADMIN_PASSWORD` (at least 16 characters) **before the first startup**. Changing `.env` does not silently reset an existing authentication volume.

Your browser will initially warn that the certificate is not trusted by a public CA. Proceed only after confirming this is your deployment. You can check its fingerprint:

```bash
docker compose exec gateway openssl x509 -in /auth/tls.crt -noout -fingerprint -sha256
```

Trust only your own certificate, not arbitrary certificate warnings. Public deployments should use a trusted certificate/HTTPS proxy.

## 2. CLI login and updates in the browser

Choose **CLI login & terminal** at the bottom of Settings, or open the terminal URL. ttyd provides terminal input, clipboard support and resizing.

```bash
easyread-cli status

easyread-cli login claude
easyread-cli login codex

easyread-cli auth-status claude
easyread-cli auth-status codex

# Update only while translation/AI/PDF jobs are idle
easyread-cli update all
# Or update individually
easyread-cli update claude
easyread-cli update codex
```

Open Claude's login URL in your own browser and paste a verification code back if prompted. Codex uses `login --device-auth`, avoiding a publicly exposed OAuth callback port. Some accounts/workspaces require enabling device login. If unavailable, follow the [official Codex authentication documentation](https://developers.openai.com/codex/auth) and tunnel its local callback over SSH; do not publicly publish OAuth callback ports.

Users complete their own login. No host credentials are copied or baked into images. Installation does not prove login, subscription entitlement, regional availability or model access.

Disconnecting the terminal ends its shell and unfinished login/update commands, so finish them before closing the page. The reader stays running. Return to model Settings, choose **Detect again**, and select the desired translation/Ask AI model.

### Persistence and update precedence

App and terminal share UID/GID 1000, HOME and PATH:

- App data: `/data/EasyRead`
- CLI HOME: `/home/easyread`
- Claude native binaries/updates: `~/.local/`; settings/login: `~/.claude/`, `~/.claude.json`
- Codex npm binaries/updates: `~/.npm-global/`; settings/login: `~/.codex/`

Startup fills only missing first-initialization files and never overwrites existing user files. CLI updates and logins survive container recreation. Consequently, rebuilding the app image does **not** replace persisted CLI versions: use the update commands to upgrade them. Keep HOME writable by UID/GID 1000.

## 3. Optional global system proxies

Use **Settings → Network & proxy** to enable and configure each field:

```text
http_proxy  = http://172.16.1.116:7890
https_proxy = http://172.16.1.116:7890
no_proxy    = localhost,127.0.0.1,host.docker.internal
```

That IP is a local testing example, not a universally available proxy. HTTPS requests using HTTP CONNECT can still use an `http://` proxy URL.

**Test proxy connection** checks network reachability to the Claude download service and OpenAI. HTTP 401/403/404 can demonstrate transport reachability but do **not** verify accounts, keys, model access or quotas. Saved settings affect new app/API/import requests, new CLI calls and newly connected terminals. Existing processes are not interrupted. Reconnect an existing shell or use `easyread-cli`, which reloads saved proxy settings for each action.

Settings persist in the app-data volume and populate lowercase/uppercase HTTP/HTTPS proxy variables. Internal app/container services always bypass external proxies. The two fields are independent; Proxy server URLs must use `http://`. Both HTTP and HTTPS targets are supported (HTTPS uses CONNECT with destination TLS verification); TLS-to-proxy `https://` URLs and SOCKS are not supported. Credential-bearing proxy URLs are redacted in configuration responses. Chromium receives explicit proxy flags, but authenticated proxy URLs are not currently supported for dynamic-page rendering; use a proxy without embedded credentials there.

Environment defaults can also be set before startup:

```dotenv
EASYREAD_BUILD_PROXY=http://172.16.1.116:7890
EASYREAD_HTTP_PROXY=http://172.16.1.116:7890
EASYREAD_HTTPS_PROXY=http://172.16.1.116:7890
```

Build proxies affect dependency downloads, not the Docker daemon's base-image pull configuration. Saved Web settings take precedence over runtime environment defaults. Disabling proxies clears the proxy variables for new app calls. This does not modify the host OS or other containers.

For a host proxy or Ollama, use `host.docker.internal` and ensure the service listens on a container-reachable address. Container `127.0.0.1` is not the host.

## 4. Remote, LAN and public access

Default published ports are loopback-only. On your own computer:

```bash
ssh -N -L 8765:127.0.0.1:8765 -L 8766:127.0.0.1:8766 user@your-server
```

Open the two localhost HTTPS URLs. For a trusted LAN, change `.env`:

```dotenv
EASYREAD_BIND_IP=0.0.0.0
EASYREAD_ALLOWED_HOSTS=192.168.1.20,easyread.lan
```

Set the server IPs/domains **before first startup**; these also enter the generated certificate. Adding names later requires reissuing the certificate or using external certificates. Host allowlisting is not authentication; gateway credentials provide authentication. Never publish backend/ttyd ports to bypass the gateway.

For public deployment, prefer separate trusted HTTPS domains:

```dotenv
EASYREAD_ALLOWED_HOSTS=read.example.com,terminal.example.com
EASYREAD_TERMINAL_URL=https://terminal.example.com
```

Forward each domain to its gateway port, preserving Host, Authorization and WebSocket Upgrade/Connection. Disable streaming-response buffering, extend timeouts, and permit uploads up to 200 MiB. Trust and verify the gateway's upstream TLS certificate. Export its public certificate for your proxy:

```bash
docker compose cp gateway:/auth/tls.crt ./easyread-gateway.crt
```

A containerized proxy should share a network and use `https://gateway:8080` / `https://gateway:8081`, not its own loopback. Upstream verification can use the certificate's `localhost` name. The reader expects a domain-root deployment; keep terminal content on a separate origin.

The terminal is an administrator shell with access to papers, model credentials and writable CLI binaries. It is not a multi-user isolation boundary. No Docker socket, host HOME, privileged mode or sudo is supplied, but that does not make sharing administrator credentials safe.

## 5. Included features and boundaries

- Native Claude Code and npm Codex are installed. Administrators may install other supported CLIs into HOME and configure their command paths.
- Chromium and Chinese fonts are included. Dynamic imports use a separate temporary browser profile, not a daily browser login. Compose uses a Moby-default-based seccomp policy, additionally allowing only clone/setns/unshare for Chromium user namespaces; the browser sandbox stays enabled, without privileged mode or SYS_ADMIN. Hosts that prohibit user namespaces require an administrator policy adjustment, not a `--no-sandbox` workaround. Attribution and Apache license are in `docker/seccomp.LICENSE`. Login/captcha-protected pages remain unsupported.
- Isolated BabelDOC 0.6.4, ONNX Runtime 1.23.2 and a preloaded layout model are included. Fonts/additional assets may download on first use and cache under HOME. PDF generation still needs a working translation model.
- Paid image APIs are never invoked automatically. Codex image generation depends on CLI/account/provider support; compatible image APIs can be configured separately.
- Folder imports, Zotero migration and linked PDFs use **container paths**. For example, mount `./papers:/papers:ro` and enter `/papers`; client-side native folder dialogs are unavailable.
- Included dependencies do not grant provider permissions, Electron OS integration or PWA features. Application-level PWA offline caching/installation is not implemented.

For a deliberately minimal Web/API-only environment:

```bash
docker compose -f docker-compose.lite.yml up -d --build
```

Lite uses HTTP and a loopback-only port, with no administration terminal. Do not run it concurrently on the same port/data volume as the full deployment.

## 6. Data, updates and backups

Compose prefixes these named volumes with the project name:

| Volume | Content |
| --- | --- |
| `easyread-data` | Papers, notes, progress, API and system-proxy configuration |
| `easyread-cli-home` | CLI binaries, login/settings and BabelDOC caches |
| `easyread-auth` | Administrator authentication and TLS certificate |

```bash
docker compose ps
docker compose logs -f --tail=100

git pull
docker compose up -d --build

docker compose down
```

**Do not use `docker compose down -v` for routine updates: it deletes papers, notes and logins.** Keep the Compose project name stable and do not run multiple instances against the same library.

For a consistent backup, stop services and copy all three directories into a new restricted directory:

```bash
mkdir -m 700 easyread-backup
docker compose stop
docker compose cp easyread:/data/EasyRead easyread-backup/data
docker compose cp easyread:/home/easyread easyread-backup/cli-home
docker compose cp gateway:/auth easyread-backup/auth
docker compose start
```

Backups contain real model credentials and administrator passwords. Treat them as sensitive and never commit them to Git. Bind-mounted app/HOME directories must be writable by UID/GID 1000.
