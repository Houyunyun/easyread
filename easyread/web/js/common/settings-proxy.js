/* Process-wide proxy settings; CLI terminal sessions use the same saved config. */
(function (PR) {
  "use strict";
  const form = s => s.proxyForm || (s.proxyForm = { ...(s.cfg.system_proxy || { enabled: false, http_proxy: "", https_proxy: "", no_proxy: "" }) });
  PR.settingsTabs.proxy = {
    render(s) {
      const p = form(s);
      const field = (id, title, value, placeholder) => '<label class="field"><span>' + title + '</span><input class="input" id="' + id + '" value="' + PR.esc(value || "") + '" placeholder="' + placeholder + '" autocomplete="off"></label>';
      return '<h4 class="set-h">' + PR.t("全局系统代理") + '</h4><label class="switch-row"><span><b>' + PR.t("启用全局代理") + '</b><small>' + PR.t("同时影响 API、CLI 和网页导入的新网络请求") + '</small></span><input type="checkbox" class="switch" id="proxyEnabled"' + (p.enabled ? " checked" : "") + '></label>' +
        '<div class="settings-sec">' + field("proxyHttp", PR.t("HTTP 代理（http_proxy）"), p.http_proxy, "http://host.docker.internal:7890") +
        field("proxyHttps", PR.t("HTTPS 代理（https_proxy）"), p.https_proxy, "http://host.docker.internal:7890") +
        field("proxyBypass", PR.t("绕过代理（no_proxy）"), p.no_proxy, "localhost,127.0.0.1,host.docker.internal") + '</div>' +
        '<p class="hint">' + PR.t("两个代理字段可使用相同地址。容器内的 127.0.0.1 不是宿主机。") + '</p>' +
        '<p class="hint">' + PR.t("保存后新请求和 CLI 调用生效；已打开的终端请重新连接，或使用 easyread-cli 命令。") + '</p>' +
        '<button class="btn" id="testProxy"' + (s.proxyTesting ? " disabled" : "") + '>' + (s.proxyTesting ? PR.t("正在测试代理…") : PR.t("测试代理连接")) + '</button>' +
        '<p class="hint" role="status">' + PR.esc(s.proxyMessage || "") + '</p>';
    },
    sync(s, root) {
      const p = form(s);
      p.enabled = root.querySelector("#proxyEnabled").checked;
      p.http_proxy = root.querySelector("#proxyHttp").value;
      p.https_proxy = root.querySelector("#proxyHttps").value;
      p.no_proxy = root.querySelector("#proxyBypass").value;
    },
    collect(s) {
      const p = form(s);
      return { enabled: !!p.enabled, http_proxy: p.http_proxy || "", https_proxy: p.https_proxy || "", no_proxy: p.no_proxy || "" };
    },
    async click(e, s, root) {
      if (!e.target.closest("#testProxy")) return false;
      this.sync(s, root);
      s.proxyTesting = true; s.proxyMessage = ""; PR.settingsRender();
      try {
        const r = await PR.api("/api/system-proxy/test", { method: "POST", body: this.collect(s) });
        s.proxyMessage = (r.ok ? PR.t("代理连接成功") : PR.t("代理连接失败")) + ": " + r.results.map(x => x.name + ": " + (x.status ? "HTTP " + x.status : x.message)).join(" · ") + " — " + r.message;
      } catch (err) { s.proxyMessage = err.message; }
      finally { s.proxyTesting = false; }
      return true;
    },
  };
})(window.PR);
