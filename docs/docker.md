# 完整 Docker 部署

[English](docker.en.md)

默认 Compose 提供 Python 后端、已有 Web 界面、**Claude Code、Codex CLI、Chromium、BabelDOC**，以及经过认证的浏览器终端。无需在宿主机安装 Python、Node.js 或 Electron。完整版建议 Docker Engine 24+、Compose v2，并允许非特权用户 namespace；建议至少 4 GB 内存、8 GB 可用磁盘，较大论文和并发任务需要更多内存。

## 1. 克隆并启动

```bash
git clone https://github.com/Jasaxion/easyread.git
cd easyread
cp .env.example .env
docker compose up -d --build
```

首次构建下载 CLI、浏览器和 PDF 组件，耗时及镜像大小比轻量版多。后续运行用 `docker compose up -d`。构建代理、CLI 版本可以在 `.env` 指定；代理变量同时传入大小写形式，兼容 apt、curl、npm 和 pip。

默认访问：

- 阅读器：**https://localhost:8765**
- CLI 终端：**https://localhost:8766**

两个端口都由 HTTPS 网关要求管理认证，后端和 ttyd 不直接发布端口。终端使用独立 Origin，禁止嵌入阅读页面，也不接受其他 Origin 的 WebSocket。HTTP 请求会跳转到 HTTPS。

### 首次管理密码与证书

第一次启动自动生成随机密码和本地自签名证书，持久化到独立认证卷；不会把密码写入启动日志。获取管理凭证：

```bash
docker compose exec gateway easyread-admin credentials
```

用户名默认 `admin`。也可在**首次启动前**设置 `.env` 中的 `EASYREAD_ADMIN_USER` 和 `EASYREAD_ADMIN_PASSWORD`（至少 16 字符）。已有认证卷时不会因修改 `.env` 而静默重置密码。

浏览器第一次打开会提示证书未受公共 CA 信任。确认这是你部署的服务后再允许继续；可核对证书指纹：

```bash
docker compose exec gateway openssl x509 -in /auth/tls.crt -noout -fingerprint -sha256
```

只信任自己的证书，不要忽略任意网站的证书告警。公网部署应使用受信任证书/HTTPS 代理，不能把自签名证书等同于公共 CA 认证。

## 2. 通过 Web 终端登录、更新 CLI

在“设置”底部点击 **CLI 登录与终端**，或直接打开终端地址。终端采用 ttyd，自带输入、复制粘贴和窗口尺寸适配，不需要自行安装终端前端。

```bash
# 查看实际可执行路径和版本
easyread-cli status

# Claude 登录
easyread-cli login claude

# Codex 设备码登录，无需公开 localhost OAuth 回调端口
easyread-cli login codex

# 检查登录状态（安装成功不代表已经登录）
easyread-cli auth-status claude
easyread-cli auth-status codex

# 在没有翻译、问答或生成 PDF 任务运行时更新
easyread-cli update all
# 也可以仅更新一个
easyread-cli update claude
easyread-cli update codex
```

Claude 会输出登录链接；在自己的浏览器打开，按提示将验证码粘贴回终端。Codex 使用 `login --device-auth`，在自己的浏览器完成设备授权。账号/组织可能需要开启设备登录权限；如果不支持，请按照 [Codex 官方认证说明](https://developers.openai.com/codex/auth) 使用 SSH 隧道转发其本机回调，不要向公网发布 OAuth 回调端口。

不会自动登录、复制宿主机账户或把订阅凭证打入镜像。登录必须由你完成。CLI 的账号、地区、订阅额度和模型支持仍受服务商限制。

退出/断开终端会结束当前 shell，包括未完成的登录/更新命令；完成后再关闭页面。后台阅读服务不受影响。回到模型设置点“重新检测”，再选择 CLI 为翻译或问答默认模型。

### 持久化与更新优先级

应用和终端使用相同的 UID/GID 1000、HOME 和 PATH：

- 应用数据：`/data/EasyRead`
- CLI HOME：`/home/easyread`
- Claude 原生安装及更新：`~/.local/`，配置/登录：`~/.claude/`、`~/.claude.json`
- Codex npm 安装及更新：`~/.npm-global/`，配置/登录：`~/.codex/`

启动时仅补入首次初始化缺失的 CLI 文件，不覆盖已有用户文件。浏览器更新的 CLI 和登录态在重建容器后保留。因此更新应用镜像**不会自动覆盖**已持久化的 CLI 版本；使用上述更新命令升级它们。不要把 CLI HOME 挂载为只读，也不要让其他 UID 修改这些目录。

## 3. 配置可选全局系统代理

网页 **设置 → 网络与代理** 支持开关和分别填写：

```text
http_proxy  = http://172.16.1.116:7890
https_proxy = http://172.16.1.116:7890
no_proxy    = localhost,127.0.0.1,host.docker.internal
```

上面的 IP 仅是当前本地测试示例，请换成你的可达代理。HTTPS 目标使用 HTTP CONNECT 代理时，`https_proxy` 的值也可以是 `http://...`。

点击“测试代理连接”验证到 Claude 下载服务和 OpenAI 的网络连通性；HTTP 401/403/404 可能表示网络已通，但**不证明账号、API Key、模型权限或额度有效**。保存后影响应用的新 API/导入请求、CLI 新调用及重新连接的终端；已经运行的进程不会被强制中断。已打开的 shell 请重新连接，或使用 `easyread-cli` 帮助命令，它每次都会读取保存的代理配置。

代理配置写入应用数据卷，并设置进程的 `http_proxy`、`https_proxy` 及对应大写变量。本机/容器内部服务始终绕过代理，避免把阅读器流量发给外部代理。可以分别只配置 HTTP 或 HTTPS；当前代理服务器地址只支持 `http://` URL，可代理 HTTP 和 HTTPS 目标（HTTPS 使用 CONNECT，目标 TLS 仍会校验）；不支持 TLS 到代理服务器本身的 `https://` URL 或 SOCKS。含认证信息的代理 URL 会在接口中隐藏凭证。Chromium 会收到明确的代理参数；动态网页浏览器暂不支持带账号密码的代理 URL，这种情况请使用无认证代理。

也可在首次启动前通过 `.env` 设置环境默认值：

```dotenv
EASYREAD_BUILD_PROXY=http://172.16.1.116:7890
EASYREAD_HTTP_PROXY=http://172.16.1.116:7890
EASYREAD_HTTPS_PROXY=http://172.16.1.116:7890
```

构建代理只影响下载镜像内依赖，不会替代 Docker daemon 拉取基础镜像的代理设置。网页保存的代理配置优先于运行环境；关闭代理会清除该应用新调用使用的代理变量。不改变宿主机系统设置，也不影响其他容器。

访问宿主机代理或 Ollama，可使用 `host.docker.internal`；服务须监听容器可达的地址。容器的 `127.0.0.1` 不是宿主机。

## 4. 服务器、局域网和公网

默认只发布服务器本机端口。在自己的电脑运行 SSH 隧道：

```bash
ssh -N -L 8765:127.0.0.1:8765 -L 8766:127.0.0.1:8766 user@your-server
```

再访问两个 localhost HTTPS 地址。也可在受信局域网修改 `.env`：

```dotenv
EASYREAD_BIND_IP=0.0.0.0
EASYREAD_ALLOWED_HOSTS=192.168.1.20,easyread.lan
```

**首次启动前**填写访问时使用的服务器 IP/域名，这些名称也会进入本地证书。后续新增名称需要重新签发证书/使用外部证书。Host 白名单不是认证；完整部署的真正认证由网关提供。不要绕过网关额外发布后端或 ttyd 的端口。

公网建议分别使用 `https://read.example.com` 和 `https://terminal.example.com` 的受信任 HTTPS 代理，并配置：

```dotenv
EASYREAD_ALLOWED_HOSTS=read.example.com,terminal.example.com
EASYREAD_TERMINAL_URL=https://terminal.example.com
```

代理分别转发到两个网关端口，保留原始 Host、Authorization 和 WebSocket Upgrade/Connection；关闭 AI 流式回答缓冲，适当增大超时和上传限制（200 MiB）。内部使用 HTTPS，应信任网关证书并验证上游证书；可以将网关公开证书导出给代理：

```bash
docker compose cp gateway:/auth/tls.crt ./easyread-gateway.crt
```

反向代理在另一容器时，用共享网络上的 `https://gateway:8080` / `https://gateway:8081`，不要使用代理容器的 `127.0.0.1`。上游证书可按证书内 `localhost` 名称验证。阅读器部署在域名根路径；终端可以使用独立域名，避免与导入内容共享 Origin。

Web 终端是管理员 shell，可以读取论文、模型凭证及更新 CLI，不是多用户隔离沙箱。只给可信管理员使用。容器不挂 Docker socket、宿主机 HOME，也不运行 privileged/sudo；这不意味着应该随意分享管理密码。

## 5. 功能与运行边界

- 默认包含 Claude 原生安装、Codex npm CLI；其他受支持 CLI 也可以由管理员在终端安装到 HOME 中并在设置中指定命令路径。
- 包含 Chromium 和中文字体，动态网页导入使用隔离的临时浏览器配置，不继承日常浏览器登录。Compose 使用基于 Moby 默认策略的 seccomp 配置，只额外允许 Chromium 用户 namespace 所需的 clone/setns/unshare；不禁用浏览器沙箱、不运行 privileged 或增加 SYS_ADMIN。若宿主安全策略禁止用户 namespace，需管理员调整策略；不要直接用 `--no-sandbox` 绕过。配置来源及 Apache 许可在 `docker/seccomp.LICENSE`。需要登录/验证码的网页仍不支持。
- 包含独立 BabelDOC 0.6.4 环境和 ONNX Runtime 1.23.2，并预下载布局模型。字体/额外模型资源可能首次使用下载并缓存到 HOME；生成 PDF 仍需可用的翻译模型。
- 不自动执行单独计费的图片 API。Codex 生图/译图是否可用取决于 CLI 版本、账号和服务商能力；可另外配置兼容图片 API。
- 文件夹导入、Zotero 迁移和链接 PDF 使用**容器内路径**。例如增加 `./papers:/papers:ro` 挂载后，在页面填 `/papers`，无法弹出客户端电脑的系统文件夹窗口。
- 容器依赖齐全不等于拥有所有服务商权限，也不等于 Electron 桌面系统集成或 PWA。当前没有应用级 PWA 离线缓存/安装流程。

只需要基础 Web/API、且不需要 CLI/终端/浏览器/PDF 生成组件时，可以显式使用轻量部署：

```bash
docker compose -f docker-compose.lite.yml up -d --build
```

轻量版是 HTTP、本机端口，没有管理终端。不要与完整版同时运行到相同端口或数据卷。

## 6. 数据、更新、备份

Compose 命名卷（实际名称带项目名前缀）：

| 卷 | 内容 |
| --- | --- |
| `easyread-data` | 论文、笔记、阅读进度、API 和全局代理配置 |
| `easyread-cli-home` | CLI 可执行文件、登录、配置、BabelDOC 缓存 |
| `easyread-auth` | 管理认证和 HTTPS 证书 |

```bash
docker compose ps
docker compose logs -f --tail=100

# 更新应用，保留数据及 CLI 登录
git pull
docker compose up -d --build

# 停止并删除容器，但保留卷
docker compose down
```

**普通更新不要运行 `docker compose down -v`，它会删除论文、笔记和登录。** 不要随意改变 Compose 项目名，也不要让多个 EasyRead 实例同时写同一份库。

备份时先停止服务，将三份数据保存到一个新的、权限受限的目录：

```bash
mkdir -m 700 easyread-backup
docker compose stop
docker compose cp easyread:/data/EasyRead easyread-backup/data
docker compose cp easyread:/home/easyread easyread-backup/cli-home
docker compose cp gateway:/auth easyread-backup/auth
docker compose start
```

备份包含真实模型凭证和管理员密码，应按敏感数据保存，不要提交 Git。CLI HOME 或应用卷若改成宿主机目录，必须给予 UID/GID 1000 读写权限。
