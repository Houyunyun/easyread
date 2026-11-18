# 本机接口约定（给外部工具）

Zotero 插件、脚本等外部工具接入 EasyRead 时，只依赖本页列出的接口。这些接口保持兼容；不兼容的改动会把 API 版本加 1，并提前写进 CHANGELOG。本页没列的 `/api/*` 都是界面内部用的，随时可能改。

当前 API 版本：**1**（EasyRead 1.3.1 起）。

新增可选的版本化 `/api/v1` 与 `/mcp` 接入见[开放 API 与 MCP](open-api.md)。它们复用访问授权码（Bearer），默认关闭；下述旧接口及 Cookie / X-Token 约定保持兼容。

## 找到服务

EasyRead 运行时把地址写在数据目录的 `.server.json`（默认 `~/EasyRead/.server.json`，设置了 `EASYREAD_HOME` 时在那个目录下）：

```json
{ "url": "http://127.0.0.1:52341", "pid": 12345, "started": "2026-10-03T12:00:00Z" }
```

默认服务只监听 `127.0.0.1`，本机默认端口被占用时可能改用随机端口，不要写死。读到地址后先请求 `/api/version` 确认服务还活着、版本是否支持。

Docker / 远程部署可通过 `--host` / `--port` 或 `EASYREAD_HOST` / `EASYREAD_PORT` 显式配置监听地址和端口，命令行参数优先；显式端口被占用时启动失败，不会随机换端口。`EASYREAD_ALLOWED_HOSTS` 添加以逗号分隔的服务器 IP/域名白名单，本机名称默认允许。通配监听时 `.server.json` 仍记录容器/本机内部访问地址，外部客户端使用实际映射端口或代理地址。

`X-Token` 用来阻止跨站写入，不是登录凭证。主站可在“设置 → 访问保护”开启访问授权码；开启后包括 API 在内的请求都需要授权 Cookie。`POST /api/access/login` 提交 JSON `{"code":"…"}`，需匹配服务地址的 Origin 头，成功后保存响应的 HttpOnly Cookie；错误请求限流。终端与阅读器共用 8765 端口，不再使用 Basic 认证。健康检查 `/healthz` 不要求授权，其他数据接口无匿名豁免。授权设置和终端管理接口属内部接口，详见 [Docker 部署](docker.md)。

网页“设置 → 网络与代理”可配置持久化全局 HTTP/HTTPS 代理。保存经 `/api/system-proxy`，连通性测试经 `/api/system-proxy/test`；这些属于内部接口。配置影响新请求和新 CLI 调用，不会中断已运行任务。

## 问答 CLI 设置（内部接口）

`GET /api/chat/cli/{claude|codex}` 返回问答能力配置、Skill 元数据和原生配置路径；`POST` 保存该 CLI 的独立问答配置。`POST /api/chat/cli/{engine}/skills/import` 接受 `filename` 与 `content_b64`，仅导入问答专用目录。写操作需要正常访问授权、`X-Token` 和同源 `Origin`。不会返回 CLI 原生配置内容或凭证。详见 [问答 CLI 设置](qa-cli.md)。

## 论文怎么标识

- **论文 id** = 原 PDF 完整 SHA-256 的前 12 位（小写十六进制）。同一个 PDF 重复导入得到同一个 id，不会建第二篇。
- **段落 id** 是 `paper.json` 里块的 `id`（如 `p3-2`、`eq4`、`fig2`），定下后不变，见 [data-format.md](data-format.md)。

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/version` | `{"api": 1, "version": "1.3.1"}`；`api` 是本页约定的版本，`version` 是应用版本 |
| GET | `/api/library` | 文献库列表 `items`（每篇的 `id`、标题、作者、DOI、进度、笔记数等）和写操作要用的 `token` |
| POST | `/api/import?name=<文件名>&translate=0\|1` | 请求体是 PDF 原始字节，请求头带 `X-Token`。返回 `{"id", "new", "queued"}`；已有同一 PDF 时 `new` 为 false |
| GET | `/api/p/{id}/part/paper` | `{"data": paper.json, "version": …}`：标题、段落原文和译文 |
| GET | `/api/p/{id}/part/reader` | `{"data": reader.json, "version": …}`：划线、批注、整篇心得 |
| GET | `/api/p/{id}/part/discussion` | `{"data": discussion.json, "version": …}`：保存到页边的 AI 回答 |
| GET | `/read/{id}` | 阅读页，可加 `#段落id` 定位 |
| GET | `/open?sha256=<完整 SHA-256>&block=<段落 id>` | 按指纹打开论文；也可用 `id=<论文 id>`。找到就跳到阅读页，找不到回文献库 |

`/api/p/{id}/state` 是阅读页自己用的：会把论文标记成"打开过"、触发补图，外部工具读数据请用上面的 `part/*`。

写操作（POST）都要带 `X-Token` 请求头，值从 `/api/library` 取；token 每次启动都会变。

### 浏览器静态资源缓存

`/web/*` 的静态文件返回弱 `ETag` 和 `Cache-Control: private, no-cache`：浏览器可以保存文件，但再次使用前须用 `If-None-Match` 核对，未变时返回无正文的 `304`。未带内容指纹的 vendor 文件同样需要核对，避免升级后混用新旧脚本。`HEAD` 返回对应响应头而不读取或发送文件正文。此策略不改变 API、论文文件、动态注入语言的页面（如 `/`、`/read/*`、`/web/tabs.html`）或流式响应；这些入口沿用原缓存策略。静态响应暂不压缩。

## 桌面版打开链接

桌面版（1.3.1 起）注册了 `easyread://` 协议：

```
easyread://open?sha256=<完整 SHA-256>&block=<段落 id>
easyread://open?id=<论文 id>
```

点击后打开（或唤起）EasyRead 窗口并定位到该段落，参数含义同 `/open`。参数只接受字母、数字、`-`、`_`，其余内容会被忽略。没装桌面版时，用浏览器打开 `<url>/open?...` 效果相同。

## 数据格式

`part/*` 返回的 JSON 结构见 [data-format.md](data-format.md)。其中字段只会增加，不会改名或改含义；改了算不兼容，按上面的规则升 API 版本。

## 研究工作区内部接口

以下是随 PaperRead 功能迁入的界面内部接口，不改变上述公开 API v1 约定。所有 POST 仍要求 Host 白名单与 `X-Token`，沿用文献库切换保护。

| 前缀 / 路径 | 用途 |
| --- | --- |
| `/research`、`/web/tabs.html` | 研究工作区与多标签分屏页面 |
| `/api/research/v1` | Vault 设置、跨论文比较、提案审核、后台任务查询/取消/确认 |
| `/api/research/v2` | 论文发现、候选/阅读计划、路径、关键词与跨论文检索 |
| `/api/research/v2/paper/{id}/mindmap` | GET 读取已保存导图；POST 重新生成 |
| `/api/research/v2/paper/{id}/mindmap/save` | POST `{mermaid, revision, target, source_sha256}`，其中语言和来源身份取自 GET 导图结果；陈旧身份或版本不得覆盖较新编辑 |
| `/api/research/v2/paper/{id}/deep-analysis` | GET 读取深度报告；对应 `/tasks` 发起后台分析 |
| `/api/research/v2/milestones`、`/follows` | 研究里程碑和关注主题/作者；对应 `/delete` 删除 |
| `/api/research/v2/reminders/claim` | POST `{candidates:[{key,...}]}`，返回 `{claimed:[]}`，避免重复提醒 |
| `/api/research/v2/export/obsidian`、`/export/zip` | 结构化知识库导出；ZIP 不要求配置 Vault |
| `/api/research/v2/summary/save` | POST `{paper_key, summary_markdown, expected_updated?, expected_markdown?}` 编辑已保存摘要，返回 `{summary}` |
| `/api/research/v1/comparisons/{id}/export` | 显式将已接受的本地比较报告导出到 Vault |
| `/api/zotero/sync-config`、`/sync-preview`、`/sync` | 读取同步设置、预览和单向导入；启动时携带预览的 `library_token` 与显式重导入的 `selected` 指纹 |

研究任务的完成、取消、失败状态以 API 返回值为准；返回任务 ID 不表示结果已经生成。模型凭证复用现有模型配置，接口不会在导出里包含凭证。
