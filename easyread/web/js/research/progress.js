/* Milestones and followed research live in the planning store, not browser-only prefs. */
(function (PR) {
  "use strict";
  const API = "/api/research/v2";
  const state = { milestones: [], follows: [], items: [], loaded: false, editing: null };
  const esc = PR.esc;
  const today = () => { const d = new Date(); return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"), String(d.getDate()).padStart(2, "0")].join("-"); };
  const day = value => Date.parse(value + "T00:00:00Z") / 86400000;
  const iso = value => new Date(value * 86400000).toISOString().slice(0, 10);
  const ref = item => "paper:" + (item.saved_key || item.paper_ref || item.id);
  const title = item => item.display_title || item.title || item.title_zh || item.title_en || item.id;
  function completion(milestone, items = state.items) {
    const linked = milestone.linked || [];
    const done = linked.filter(key => items.some(item => ref(item) === key && item.status === "done")).length;
    const progress = linked.reduce((sum, key) => {
      const item = items.find(item => ref(item) === key);
      return sum + (item?.status === "done" ? 1 : Math.max(0, Math.min(1, Number(item?.progress) || 0)));
    }, 0);
    return { total: linked.length, done, percent: linked.length ? Math.round(progress / linked.length * 100) : 0 };
  }
  function reminders(milestones, items, date = today()) {
    return milestones.flatMap(m => {
      const stats = completion(m, items);
      if (stats.total && stats.done === stats.total) return [];
      const start = day(m.start_date), end = day(m.end_date || m.start_date), now = day(date);
      if (![start, end, now].every(Number.isFinite) || start > now) return [];
      const shift = m.recurrence === "weekly" ? Math.floor((now - start) / 7) * 7 : 0;
      const occurrence = iso(start + shift);
      if (m.exceptions?.cancelled?.includes(occurrence)) return [];
      const override = m.exceptions?.overrides?.[occurrence];
      const due = override?.end_date || iso(end + shift);
      if (due > date) return [];
      return [{ key: "milestone:" + m.id + ":" + occurrence, milestone_id: m.id, title: override?.title || m.title, date: due }];
    });
  }
  const host = () => PR.$("[data-view='progress']");
  const field = (name, label, input) => '<label class="rw-field"><span>' + esc(label) + '</span>' + input + '</label>';
  const input = (name, type, extra = "") => '<input name="' + name + '" type="' + type + '" ' + extra + '>';
  function mount() {
    const root = host();
    if (root.querySelector("[data-progress-form]")) return;
    root.innerHTML = '<div class="rw-progress-tools"><h2>' + PR.t("研究进度") + '</h2><button class="btn line" data-progress="refresh">' + PR.t("刷新") + '</button><button class="btn line" data-progress="reminders">' + PR.t("检查到期提醒") + '</button></div><p role="status" data-progress-status></p>' +
      '<section class="rw-panel"><h3>' + PR.t("目标与里程碑") + '</h3><p class="rw-source">' + PR.t("为阅读目标设置日期并关联论文，进度与阅读看板同步。") + '</p><form data-progress-form="milestone"><input type="hidden" name="id"><div class="rw-form-grid">' +
      field("title", PR.t("目标名称"), input("title", "text", 'required maxlength="160"')) +
      field("start_date", PR.t("开始日期"), input("start_date", "date", 'required')) + field("end_date", PR.t("结束日期"), input("end_date", "date", 'required')) +
      field("recurrence", PR.t("重复"), '<select name="recurrence"><option value="once">' + PR.t("单次") + '</option><option value="weekly">' + PR.t("每周") + '</option></select>') +
      field("color", PR.t("颜色"), input("color", "color", 'value="#6b9eb1"')) + '</div><fieldset class="rw-progress-papers"><legend>' + PR.t("关联论文") + '</legend><div data-progress-papers></div></fieldset>' +
      '<div class="actions"><button class="btn accent" type="submit">' + PR.t("保存里程碑") + '</button><button class="btn line" type="button" data-progress="reset">' + PR.t("清空") + '</button></div></form><div class="rw-list" data-progress-milestones></div></section>' +
      '<section class="rw-panel"><h3>' + PR.t("追踪研究") + '</h3><form data-progress-form="follow"><div class="rw-form-grid">' +
      field("kind", PR.t("追踪类型"), '<select name="kind"><option value="topic">' + PR.t("研究主题") + '</option><option value="author">' + PR.t("OpenAlex 作者 ID") + '</option></select>') +
      field("value", PR.t("主题或作者 ID"), input("value", "text", 'required maxlength="500"')) + field("label", PR.t("显示名称（选填）"), input("label", "text", 'maxlength="160"')) +
      '</div><p class="rw-source">' + PR.t("作者请填写 OpenAlex 的 A 开头数字 ID，而不是姓名，以免混淆同名作者。") + '</p><button class="btn accent" type="submit">' + PR.t("添加追踪") + '</button></form><div class="rw-list" data-progress-follows></div></section>';
    root.addEventListener("submit", submit);
    root.addEventListener("click", click);
    reset();
  }
  function status(text, error = false) {
    const node = host().querySelector("[data-progress-status]");
    node.textContent = text; node.className = error ? "rw-error" : "rw-source";
  }
  function paperChoices(linked = []) {
    const available = state.items.slice(0, 200).map(item => ({ key: ref(item), label: title(item) }));
    linked.forEach(key => { if (!available.some(item => item.key === key)) available.push({ key, label: key }); });
    host().querySelector("[data-progress-papers]").innerHTML = available.map(item => '<label><input type="checkbox" name="linked" value="' + esc(item.key) + '"' + (linked.includes(item.key) ? ' checked' : '') + '> ' + esc(item.label) + '</label>').join("") || '<p class="rw-source">' + PR.t("先从研究探索或文献库加入论文。") + '</p>';
  }
  function reset() {
    state.editing = null;
    const form = host().querySelector('[data-progress-form="milestone"]');
    form.reset();
    form.elements.id.value = "";
    form.elements.start_date.value = form.elements.end_date.value = today();
    paperChoices();
  }
  async function load() {
    mount(); status(PR.t("正在载入…"));
    try {
      const [milestones, follows] = await Promise.all([PR.api(API + "/milestones"), PR.api(API + "/follows")]);
      state.milestones = milestones.milestones || []; state.follows = follows.follows || []; state.loaded = true;
      renderLists(); status("");
    } catch (error) { status(PR.t(error.message), true); }
  }
  function renderLists() {
    host().querySelector("[data-progress-milestones]").innerHTML = state.milestones.map(m => {
      const stats = completion(m);
      return '<article class="rw-card"><h4>' + esc(m.title) + '</h4><p>' + esc(m.start_date) + ' – ' + esc(m.end_date) + ' · ' + (m.recurrence === "weekly" ? PR.t("每周") : PR.t("单次")) + '</p><p>' + PR.t("已完成 {done}/{total} 篇 · 阅读进度 {percent}%", stats) + '</p><progress max="100" value="' + stats.percent + '" aria-label="' + PR.t("阅读进度") + '"></progress><div class="actions"><button class="btn sm line" data-progress="edit" data-id="' + esc(m.id) + '">' + PR.t("编辑") + '</button><button class="btn sm line danger" data-progress="delete-milestone" data-id="' + esc(m.id) + '">' + PR.t("删除") + '</button></div></article>';
    }).join("") || '<p class="rw-empty">' + PR.t("还没有里程碑。") + '</p>';
    host().querySelector("[data-progress-follows]").innerHTML = state.follows.map(f => {
      const url = f.kind === "author" ? 'https://openalex.org/' + encodeURIComponent(f.value) : '/research?q=' + encodeURIComponent(f.value);
      return '<article class="rw-card"><h4>' + esc(f.label || f.value) + '</h4><p>' + esc(f.value) + '</p><div class="actions"><a class="btn sm line" href="' + esc(url) + '"' + (f.kind === "author" ? ' target="_blank" rel="noopener"' : '') + '>' + (f.kind === "author" ? PR.t("查看作者") : PR.t("探索主题")) + '</a><button class="btn sm line danger" data-progress="delete-follow" data-id="' + esc(f.id) + '">' + PR.t("取消追踪") + '</button></div></article>';
    }).join("") || '<p class="rw-empty">' + PR.t("还没有追踪的研究。") + '</p>';
  }
  async function submit(event) {
    const form = event.target.closest("[data-progress-form]");
    if (!form) return;
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form)), button = form.querySelector('[type="submit"]');
    button.disabled = true;
    try {
      if (form.dataset.progressForm === "milestone") {
        data.linked = [...form.querySelectorAll('[name="linked"]:checked')].map(node => node.value);
        if (data.end_date < data.start_date) throw new Error(PR.t("结束日期不能早于开始日期"));
        await PR.api(API + "/milestones", { method: "POST", body: { ...state.editing, ...data } });
        reset();
      } else {
        data.value = data.value.trim();
        if (data.kind === "author" && !/^A\d+$/.test(data.value)) throw new Error(PR.t("请填写有效的 OpenAlex 作者 ID（A 开头的数字）"));
        await PR.api(API + "/follows", { method: "POST", body: data });
        form.reset();
      }
      await load(); status(PR.t("已保存"));
    } catch (error) { status(PR.t(error.message), true); }
    finally { button.disabled = false; }
  }
  async function click(event) {
    const button = event.target.closest("[data-progress]");
    if (!button) return;
    const action = button.dataset.progress;
    if (action === "reset") return reset();
    if (action === "refresh") return load();
    if (action === "edit") {
      const record = state.milestones.find(m => m.id === button.dataset.id);
      if (!record) return;
      state.editing = record;
      const form = host().querySelector('[data-progress-form="milestone"]');
      for (const name of ["id", "title", "start_date", "end_date", "recurrence", "color"]) form.elements[name].value = record[name] || "";
      paperChoices(record.linked || []); form.elements.title.focus(); return;
    }
    button.disabled = true;
    try {
      if (action === "reminders") {
        const result = await PR.api(API + "/reminders/claim", { method: "POST", body: { candidates: reminders(state.milestones, state.items) } });
        status(result.claimed?.length ? PR.t("到期提醒：{titles}", { titles: result.claimed.map(item => item.title).join(" · ") }) : PR.t("没有新的到期提醒。已提示的场次不会重复提醒。"));
      } else if (action === "delete-milestone" || action === "delete-follow") {
        if (!await PR.confirm({ title: PR.t("确定删除？"), ok: PR.t("删除"), danger: true })) return;
        await PR.api(API + (action === "delete-milestone" ? "/milestones/delete" : "/follows/delete"), { method: "POST", body: { id: button.dataset.id } });
        if (state.editing?.id === button.dataset.id) reset();
        await load();
      }
    } catch (error) { status(PR.t(error.message), true); }
    finally { button.disabled = false; }
  }
  PR.researchProgress = {
    render(items) { state.items = items; mount(); if (!state.loaded) void load(); else renderLists(); },
    completion, reminders
  };
})(window.PR);
