(() => {
  "use strict";
  let english = (navigator.language || "").startsWith("en");
  const input = document.querySelector("#accessCode"), error = document.querySelector("#accessError"), submit = document.querySelector("#accessSubmit");
  function language() {
    document.documentElement.lang = english ? "en" : "zh-CN";
    document.querySelectorAll("[data-zh]").forEach(el => { el.textContent = el.dataset[english ? "en" : "zh"]; });
    document.querySelector("#accessLang").textContent = english ? "简体中文" : "English"; // i18n-ok
    input.placeholder = english ? "Enter your access code" : "输入访问授权码"; // i18n-ok standalone login page
    document.querySelector("#toggleCode").ariaLabel = english ? "Show or hide code" : "显示或隐藏授权码"; // i18n-ok
    document.title = english ? "EasyRead · Access" : "EasyRead · 访问授权"; // i18n-ok
  }
  document.querySelector("#accessLang").onclick = () => { english = !english; language(); };
  document.querySelector("#toggleCode").onclick = () => { input.type = input.type === "password" ? "text" : "password"; };
  document.querySelector("#accessForm").onsubmit = async e => {
    e.preventDefault(); error.textContent = ""; submit.disabled = true;
    try {
      const r = await fetch("/api/access/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: input.value }) });
      if (!r.ok) {
        error.textContent = english ? (r.status === 429 ? "Too many attempts. Try again in a minute." : "That access code is not correct.") : (r.status === 429 ? "尝试过于频繁，请一分钟后重试" : "访问授权码不正确"); // i18n-ok
        input.focus(); return;
      }
      let next = new URLSearchParams(location.search).get("next") || "/";
      const url = new URL(next, location.origin);
      if (url.origin !== location.origin || url.pathname === "/login") next = "/";
      location.replace(next);
    } catch (_) { error.textContent = english ? "Connection failed. Please try again." : "连接失败，请重试。"; } // i18n-ok
    finally { submit.disabled = false; }
  };
  language();
})();
