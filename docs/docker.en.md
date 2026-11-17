# Docker deployment

[简体中文](docker.md)

The Docker image runs the Python backend and existing Web UI. No host Python, Node.js or Electron installation is required. Use Docker Engine 20.10+ and Docker Compose v2.

## Clone and start

```bash
git clone https://github.com/Jasaxion/easyread.git
cd easyread
docker compose up -d --build
```

The first launch builds the image; later launches can use `docker compose up -d`. Open <http://127.0.0.1:8765> on the server. The image runs as a non-root user (UID 1000), and closing the browser does not stop the service.

**There is no built-in login. By default the published port binds only to the server's loopback interface, not its LAN or public interfaces.** Neither `X-Token` nor the Host allowlist is authentication. Anyone with access can read/write the library, change model settings and invoke models.

### Access a remote server from your computer

Leave the defaults unchanged and run an SSH tunnel on your computer:

```bash
ssh -N -L 8765:127.0.0.1:8765 user@your-server
```

Then open <http://127.0.0.1:8765> on your computer. If your local port is occupied, change the leftmost port in `-L` to 18765 and open `http://127.0.0.1:18765` instead.

### Direct access on a trusted LAN (optional)

Only use this on a trusted network or behind appropriate firewall restrictions:

```bash
cp .env.example .env
```

Edit `.env` with your server's IP/domain:

```dotenv
EASYREAD_BIND_IP=0.0.0.0
EASYREAD_PORT=8765
EASYREAD_ALLOWED_HOSTS=192.168.1.20,easyread.lan
```

Run `docker compose up -d` and open `http://192.168.1.20:8765`. The allowlist contains server IPs/domains from the browser URL, not client IPs. Separate entries with commas; `*` is not supported. Check this list if requests return `bad host`. In Compose, `EASYREAD_PORT` changes only the host port; the container always uses 8765.

### HTTPS / public access

Keep the default loopback binding. Configure **HTTPS and authentication** (such as existing SSO or Basic Auth) on your reverse proxy, and add the public domain to `EASYREAD_ALLOWED_HOSTS` in `.env`. HTTPS or a domain name alone is not sufficient protection.

The proxy must:

- Forward to `http://127.0.0.1:8765` and preserve the original `Host`, including non-default ports.
- Forward WebSocket `Upgrade` and `Connection` headers; HTTPS clients use `wss://`.
- Disable response buffering for streaming AI answers and allow long requests.
- Allow the desired PDF upload size (the application's limit is 200 MiB).
- Serve the app at the domain root; subpaths such as `/easyread/` are not supported.

Example Nginx forwarding settings, **with TLS and authentication configured separately in the enclosing server/location**:

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 1800s;
    client_max_body_size 200m;
}
```

A containerized proxy must share a network with EasyRead and forward to `http://easyread:8765`. Its own `127.0.0.1` is not the host or the EasyRead container.

## Models and files

- The default image does not install model CLIs such as Claude/Codex or inherit host logins. Configure a model API in the Web settings. PDF import and original-page viewing need no desktop installation.
- For host Ollama, use `http://host.docker.internal:11434/v1` in Settings. Ollama must listen on an address reachable from the container, with access restricted by a firewall. Container `127.0.0.1` is not the host.
- If model CLIs are required, extend the image with the CLI and supply its credentials. Do not bake API keys or login directories into images or commit them to Git.
- Folder imports, Zotero migration and linked local PDFs use **container paths**. Mount the source, for example `./papers:/papers:ro`, then enter `/papers` in the UI. A client-side folder dialog is not available.
- Dynamic website import needs Chrome/Chromium/Edge, which is not included. BabelDOC PDF translation also requires a separately installed optional component.
- Docker support does not add PWA installation or application-level offline caching.

## Data, updates and troubleshooting

Library data, settings, notes and preferences live in the `easyread-data` named volume, mounted at `/data/EasyRead`. Compose prefixes the volume name with the project name. Recreating a container preserves it; changing the project name can create a different, empty volume.

```bash
# Status and logs
docker compose ps
docker compose logs -f --tail=100 easyread

# Update and rebuild, preserving the volume
git pull
docker compose up -d --build

# Remove containers but keep the volume
docker compose down
```

**`docker compose down -v` deletes the data volume, including papers and notes. Do not use it for routine updates.**

To back up, stop the service, copy the entire data directory and start it again:

```bash
docker compose stop
docker compose cp easyread:/data/EasyRead ./easyread-backup
docker compose start
```

Backups contain model settings and credentials; treat them as sensitive. Alternatively, replace the named volume mapping with `./data:/data/EasyRead`. Create the directory and give UID/GID 1000 write access first (on Linux, `sudo chown -R 1000:1000 ./data`). Do not run multiple EasyRead instances against the same library.

The backend accepts `--host` / `--port` or `EASYREAD_HOST` / `EASYREAD_PORT`; command-line flags take precedence. Source and desktop launches still default to loopback. Explicit ports fail when occupied rather than silently switching to an unmapped random port.
