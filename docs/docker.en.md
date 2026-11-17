# Docker: one service, one reading space

[简体中文](docker.md)

The full image includes **Claude Code, Codex CLI, Chromium and BabelDOC**. A single container and port serve the reader, access-code settings, CLI management and embedded Web Terminal. There are no gateway/terminal sidecars, secondary ports or browser HTTP Basic prompts.

## Start

Use Docker Engine 24+, Compose v2, at least 4 GB RAM and 8 GB free disk.

```bash
git clone https://github.com/Jasaxion/easyread.git
cd easyread
cp .env.example .env
docker compose up -d --build
```

Open **http://localhost:8765**. Defaults publish only on loopback and require no username. The first build downloads CLIs, browser/PDF components and the layout model. Later starts can use `docker compose up -d`.

## Access code

Use **Settings → Access protection** to enable, disable or change the code:

- When enabled, visitors see a dedicated EasyRead access page. Enter one code; there is no username or HTTP Basic dialog.
- Codes require 6–256 characters; a long random string is recommended. Only a salted hash is stored, not retrievable plaintext.
- Changing or disabling protection requires the current code. Other browser sessions are revoked and all terminals close; the current browser stays authorized.
- `EASYREAD_ACCESS_CODE` optionally seeds the code on first startup. Later settings take precedence; changing the environment does not overwrite the saved code.
- Sessions use HttpOnly/SameSite cookies and expire on server restart.

Access protection defaults to off for local personal use. **Configure a code before exposing the service to a network. With protection disabled, anyone who can reach the app can read/write papers, invoke models and use the container terminal.**

```dotenv
EASYREAD_BIND_IP=0.0.0.0
EASYREAD_PORT=8765
EASYREAD_ALLOWED_HOSTS=192.168.1.20,easyread.lan
EASYREAD_ACCESS_CODE=replace-with-your-own-long-random-code
```

The allowlist contains server IPs/domains, not client IPs, and is not authentication. A server administrator who forgets the code can stop the container, remove only `/data/EasyRead/.access.json`, set a new `EASYREAD_ACCESS_CODE`, and restart. Do not remove the library.

### Remote access

For SSH access without public exposure:

```bash
ssh -N -L 8765:127.0.0.1:8765 user@your-server
```

Then open localhost. Use an external HTTPS reverse proxy for public/untrusted networks. Preserve Host, Origin, Cookie and WebSocket Upgrade/Connection, disable streaming-response buffering and allow required uploads (up to 200 MiB). Deploy at the domain root and forward `/terminal/` to the same backend. Automatic self-signed certificates are no longer used; local HTTP avoids certificate warnings but does not encrypt transport.

## CLI and terminal inside Settings

Open **Settings → CLI & terminal**:

- Claude Code / Codex cards show installed versions.
- **Sign in**, **Login status** and **Update** run directly in the embedded terminal.
- **Open terminal** starts an interactive shell; no second website or password.
- Open CLI login links in your own browser and paste verification codes when requested. Codex uses device authentication rather than a publicly exposed OAuth callback.
- **Disconnect**, switching tabs or closing Settings ends the terminal and unfinished commands. Complete login/update operations first.

Available terminal commands:

```bash
easyread-cli status
easyread-cli login claude
easyread-cli login codex
easyread-cli auth-status claude
easyread-cli auth-status codex
easyread-cli update all
```

Installation does not prove login, account entitlement, regional availability or quotas. Host logins are not copied and paid model calls are not made automatically. Update CLIs while model/PDF jobs are idle.

ttyd is reused internally, launched on demand on container loopback only and reached through the main site's access/origin checks. This is a personal administrator shell, not a multi-user sandbox. Do not share library write access with untrusted people.

## Optional global proxy

**Settings → Network & proxy** controls `http_proxy`, `https_proxy` and `no_proxy`:

```text
http_proxy  = http://172.16.1.116:7890
https_proxy = http://172.16.1.116:7890
```

The IP above is only a local test example. HTTPS targets use HTTP CONNECT, so both fields can use `http://`. TLS-to-proxy `https://` URLs and SOCKS are not currently supported.

Settings persist in the app-data volume and affect new API/CLI/import requests. Reopen existing terminals after changing them. Disabling proxies clears the app's proxy variables; unset settings inherit the process environment. Internal connections bypass external proxies. Host settings and other containers are unchanged.

**Test proxy connection** tests network reachability to the Claude download service and OpenAI, not model accounts or quotas. Proxy credentials are redacted; Chromium dynamic imports do not support proxy URLs containing credentials.

Before building/starting, `.env` can supply defaults:

```dotenv
EASYREAD_BUILD_PROXY=http://172.16.1.116:7890
EASYREAD_HTTP_PROXY=http://172.16.1.116:7890
EASYREAD_HTTPS_PROXY=http://172.16.1.116:7890
```

Build proxies do not configure the Docker daemon's base-image pulls. Use `host.docker.internal` for a host proxy/Ollama; container loopback is not the host.

## Data and updates

| Named volume (prefixed by Compose project) | Content |
| --- | --- |
| `easyread-data` | Papers, notes, progress, API/proxy settings and access-code hash |
| `easyread-cli-home` | CLI installations/updates, logins, configuration and PDF caches |

Mounts are `/data/EasyRead` and `/home/easyread`, owned by non-root UID/GID 1000. Recreation preserves existing CLI HOME. User-updated CLI versions are not overwritten by app-image upgrades.

```bash
git pull
docker compose up -d --build --remove-orphans
docker compose ps
docker compose logs -f --tail=100
```

When upgrading the older three-service deployment, `--remove-orphans` removes gateway/terminal containers. The old `easyread-auth` volume and username/password are no longer used. Existing paper and CLI HOME volumes remain shared with the new container.

Use `docker compose down` to stop/remove containers. **Do not use `down -v` for routine updates:** it deletes data. Keep the project name stable; never run simultaneous writers against the same library. Stop services when backing up both data directories and treat CLI credentials as sensitive.

## Boundaries

- Chromium keeps its sandbox using Moby's default seccomp policy plus clone/setns/unshare for user namespaces. No privileged mode, SYS_ADMIN, Docker socket or host HOME. The host must permit user namespaces.
- Isolated BabelDOC includes the layout model; public font assets may download on first PDF generation. A working translation model is still required.
- Folder/Zotero imports and linked PDFs use container paths, e.g. mount `./papers:/papers:ro` and enter `/papers`.
- Image generation depends on Codex/image API capabilities; separately billed image APIs are not invoked automatically.
- Electron OS integration, client-native folder dialogs and PWA offline installation are not included.
- Optional lite API image: `docker compose -f docker-compose.lite.yml up -d --build`, without an embedded terminal. Do not run both against the same port/data volume.
