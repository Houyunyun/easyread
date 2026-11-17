"""Optional HTTP CONNECT proxies for HTTP/HTTPS traffic and CLI invocations."""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from .i18n import tr

BYPASS = "localhost,127.0.0.1,::1,easyread,terminal,gateway,host.docker.internal"
_INITIAL = {key: os.environ.get(key.lower()) or os.environ.get(key) or "" for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")}


def effective(settings=None):
    if settings is None:
        native = urllib.request.getproxies() if not (_INITIAL["HTTP_PROXY"] or _INITIAL["HTTPS_PROXY"]) else {}
        http_proxy = _INITIAL["HTTP_PROXY"] or native.get("http", "")
        https_proxy = _INITIAL["HTTPS_PROXY"] or native.get("https", "")
        return {"enabled": bool(http_proxy or https_proxy), "http_proxy": http_proxy, "https_proxy": https_proxy,
                "no_proxy": _INITIAL["NO_PROXY"] or native.get("no", ""),
                "source": "system" if native.get("http") or native.get("https") else "environment"}
    return {"enabled": bool(settings.get("enabled")), "http_proxy": settings.get("http_proxy", ""),
            "https_proxy": settings.get("https_proxy", ""), "no_proxy": settings.get("no_proxy", ""), "source": "settings"}


def redact(value):
    try:
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            authority = parsed.netloc.rsplit("@", 1)[-1]
            return urlunsplit(parsed._replace(netloc="••••@" + authority))
    except ValueError:
        pass
    return value


def public(settings=None):
    out = effective(settings)
    for key in ("http_proxy", "https_proxy"):
        out[key] = redact(out[key])
    return out


def validate(body, current=None):
    if not isinstance(body, dict) or type(body.get("enabled")) is not bool:
        raise ValueError(tr("代理开关必须是布尔值"))
    previous = effective(current)
    out = {"enabled": body["enabled"]}
    for key in ("http_proxy", "https_proxy"):
        value = body.get(key, "")
        if not isinstance(value, str):
            raise ValueError(tr("代理地址必须是 http:// URL；HTTPS 请求也使用 HTTP CONNECT 代理"))
        value = value.strip()
        if "••••@" in value and value == redact(previous[key]):
            value = previous[key]
        if value:
            try:
                parsed = urlsplit(value)
                port = parsed.port
                valid = (value.isascii() and not any(c.isspace() for c in value)
                         and parsed.scheme == "http" and bool(parsed.hostname)
                         and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                         and (port is None or 1 <= port <= 65535))
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(tr("代理地址必须是 http:// URL；HTTPS 请求也使用 HTTP CONNECT 代理"))
        out[key] = value
    bypass = body.get("no_proxy", "")
    if not isinstance(bypass, str) or not bypass.isascii() or "\n" in bypass or "\r" in bypass:
        raise ValueError(tr("绕过代理的地址必须是逗号分隔的主机名或 IP"))
    out["no_proxy"] = bypass.strip()
    if out["enabled"] and not (out["http_proxy"] or out["https_proxy"]):
        raise ValueError(tr("启用代理时至少填写一个代理地址"))
    return out


def apply(settings=None):
    if settings is None:
        # Unset means inherit: do not poison native OS proxy discovery with NO_PROXY.
        from ..server.http import SafeProxyHandler, SafeRedirectHandler
        urllib.request.install_opener(urllib.request.build_opener(SafeProxyHandler(), SafeRedirectHandler()))
        return
    options = effective(settings)
    if options["enabled"]:
        validate(options, settings)
    for key in ("HTTP_PROXY", "HTTPS_PROXY"):
        value = options[key.lower()] if options["enabled"] else ""
        for name in (key, key.lower()):
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
    if settings is not None:
        os.environ["EASYREAD_SYSTEM_PROXY_CONFIGURED"] = "1"
        # Do not leave a pre-existing SOCKS/ALL_PROXY active after disabling UI proxies.
        os.environ.pop("ALL_PROXY", None)
        os.environ.pop("all_proxy", None)
    else:
        os.environ.pop("EASYREAD_SYSTEM_PROXY_CONFIGURED", None)
    bypass = ",".join(dict.fromkeys(x.strip() for x in (BYPASS + "," + options["no_proxy"]).split(",") if x.strip()))
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = bypass
    # Refresh urllib callers that do not pass an explicit TLS context.
    from ..server.http import SafeProxyHandler, SafeRedirectHandler
    urllib.request.install_opener(urllib.request.build_opener(SafeProxyHandler(), SafeRedirectHandler()))


def apply_saved():
    from . import config
    apply(config.load().get("system_proxy"))


def chromium_args():
    servers = []
    for scheme in ("http", "https"):
        value = os.environ.get(scheme + "_proxy") or os.environ.get(scheme.upper() + "_PROXY")
        if value:
            parsed = urlsplit(value)
            if parsed.username is not None or parsed.password is not None:
                raise ValueError(tr("动态网页浏览器暂不支持带账号密码的代理，请使用无认证代理"))
            servers.append(scheme + "=" + value)
    if not servers:
        return ["--no-proxy-server"] if os.environ.get("EASYREAD_SYSTEM_PROXY_CONFIGURED") else []
    bypass = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or BYPASS
    return ["--proxy-server=" + ";".join(servers), "--proxy-bypass-list=" + ";".join(x.strip() for x in bypass.split(",") if x.strip())]


def test(settings):
    from ..server import http
    options = effective(settings)
    proxies = {key: options[key + "_proxy"] for key in ("http", "https") if options["enabled"] and options[key + "_proxy"]}
    opener = urllib.request.build_opener(http.SafeRedirectHandler(), http.SafeProxyHandler(proxies),
        urllib.request.HTTPSHandler(context=http._context(os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_CERT_DIR"))))
    results = []
    for name, url in (("Claude", "https://downloads.claude.ai/claude-code-releases/latest"), ("OpenAI", "https://auth.openai.com/.well-known/openid-configuration")):
        try:
            with opener.open(urllib.request.Request(url, headers={"User-Agent": "EasyRead proxy test"}), timeout=10) as response:
                response.read(256)
                code = response.status
            results.append({"name": name, "ok": True, "status": code})
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            # 401/403/404 can prove TLS/HTTP reachability, not account authorization.
            results.append({"name": name, "ok": code not in (407, 421) and code < 500, "status": code})
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            results.append({"name": name, "ok": False, "message": tr("代理或目标服务连接失败")})
    return {"ok": all(item["ok"] for item in results), "results": results,
            "message": tr("仅测试网络连通性，不验证模型账号或额度")}
