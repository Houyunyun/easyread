# Docker 部署

[English](docker.en.md)

Docker 版运行 Python 后端和已有 Web 界面，不需要安装 Python、Node.js 或 Electron。需要 Docker Engine 20.10+ 和 Docker Compose v2。

## 克隆后启动

```bash
git clone https://github.com/Jasaxion/easyread.git
cd easyread
docker compose up -d --build
```

首次启动会构建镜像，以后可以直接 `docker compose up -d`。在服务器本机打开 <http://127.0.0.1:8765>。镜像以非 root 用户（UID 1000）运行，关闭浏览器不会停止服务。

**应用没有内置登录。默认只把端口发布到服务器的 `127.0.0.1`，不会直接暴露给局域网或公网。** `X-Token` 和 Host 白名单不是用户认证；能访问应用的人可以读写文献库、修改模型配置和调用模型。

### 从自己的电脑访问服务器

无需改配置，在自己的电脑上运行 SSH 隧道：

```bash
ssh -N -L 8765:127.0.0.1:8765 user@your-server
```

然后在自己的电脑打开 <http://127.0.0.1:8765>。若本机 8765 已被占用，将 `-L` 左侧端口改成 18765，再访问 `http://127.0.0.1:18765`。

### 可信局域网直接访问（可选）

只在受信网络或已有防火墙访问限制时使用：

```bash
cp .env.example .env
```

编辑 `.env`，将 IP 换成你的服务器地址：

```dotenv
EASYREAD_BIND_IP=0.0.0.0
EASYREAD_PORT=8765
EASYREAD_ALLOWED_HOSTS=192.168.1.20,easyread.lan
```

运行 `docker compose up -d`，访问 `http://192.168.1.20:8765`。白名单填写浏览器地址中的服务器 IP/域名，而不是客户端 IP；多个值以逗号分隔，不支持 `*`。返回 `bad host` 时先检查白名单。`EASYREAD_PORT` 在 Compose 中只改变宿主机端口，容器内仍使用 8765。

### HTTPS / 公网访问

保留默认本机端口，在反向代理上配置 **HTTPS 和认证**（如已有的 SSO 或 Basic Auth），并将外部域名加入 `.env` 中的 `EASYREAD_ALLOWED_HOSTS`。不要仅设置域名或 HTTPS 就公开服务。

代理必须：

- 将请求转发到 `http://127.0.0.1:8765`，保留原始 `Host`（包括非默认端口）；
- 转发 WebSocket 的 `Upgrade` 和 `Connection`，客户端会使用 `wss://`；
- 关闭流式 AI 回答的响应缓冲，适当增大超时；
- 允许所需的 PDF 上传大小（应用上限 200 MiB）；
- 部署在域名根路径，当前不支持 `/easyread/` 之类子路径。

Nginx 的转发部分可以使用下面的配置，**TLS 和认证须在对应 server/location 中另行配置**：

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

如果代理也在容器内，应让它与 EasyRead 加入同一网络，转发到 `http://easyread:8765`；代理容器的 `127.0.0.1` 不是宿主机或 EasyRead。

## 模型与文件

- 默认镜像不安装 Claude/Codex 等模型 CLI，也不继承宿主机的登录。推荐在网页设置中配置模型 API；PDF 导入及原页查看不需要额外安装桌面程序。
- 访问宿主机 Ollama 时，在设置中使用 `http://host.docker.internal:11434/v1`。Ollama 需要监听容器可达的地址，并用防火墙限制访问；容器内的 `127.0.0.1` 不是宿主机。
- 若必须使用模型 CLI，需要基于此镜像自行安装 CLI 和配置其凭证。不要把 API Key 或登录目录打进镜像、提交到 Git。
- 文件夹导入、Zotero 迁移和链接本地 PDF 使用的是**容器内路径**。额外挂载对应目录，例如 `./papers:/papers:ro`，再在页面填 `/papers`；不会弹出客户端电脑的系统文件夹窗口。
- 动态网页导入需要 Chrome/Chromium/Edge；基础镜像不包含浏览器。BabelDOC 翻译 PDF 也是需要单独安装的可选组件。
- Docker 支持不会自动使应用成为 PWA，目前没有应用级离线缓存或 PWA 安装流程。

## 数据、更新和排错

文献库、配置、笔记和偏好保存在命名卷 `easyread-data` 中，容器路径为 `/data/EasyRead`。Compose 会自动给卷名加项目名前缀，重启或重建容器不会删除数据。不要随意改变 Compose 项目名，否则可能创建另一份空卷。

```bash
# 查看运行状态和日志
docker compose ps
docker compose logs -f --tail=100 easyread

# 更新源码并重建（保留数据卷）
git pull
docker compose up -d --build

# 停止并删除容器，保留数据卷
docker compose down
```

**`docker compose down -v` 会删除数据卷，包括论文和笔记，请勿用于普通更新。**

备份时先暂停服务，复制整个数据目录，再启动：

```bash
docker compose stop
docker compose cp easyread:/data/EasyRead ./easyread-backup
docker compose start
```

备份包含模型配置和凭证，应按敏感数据保存。也可以把 Compose 的命名卷替换为 `./data:/data/EasyRead`；先创建目录并给予 UID/GID 1000 读写权限（Linux 上可执行 `sudo chown -R 1000:1000 ./data`）。不要将多个运行中的 EasyRead 实例指向同一个库。

后端也支持直接通过 `--host` / `--port` 或 `EASYREAD_HOST` / `EASYREAD_PORT` 指定监听地址和端口，命令行参数优先。没有显式配置时仍只监听本机；显式端口被占用会报错，不会静默切换到 Docker 未映射的随机端口。
