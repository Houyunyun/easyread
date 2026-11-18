/* A saved, editable view of keyword-to-paper evidence. No model is invoked here. */
(function (PR) {
  "use strict";
  const API = "/api/research/v2/keyword-maps";
  function graph(data) {
    const columns = { root: 0, keyword: 1, paper: 2, excerpt: 3 }, rows = [0, 0, 0, 0], positions = new Map();
    for (const node of data.nodes || []) {
      const column = columns[node.kind] ?? 3;
      positions.set(node.id, { x: 16 + column * 245, y: 16 + rows[column]++ * 86 });
    }
    const height = Math.max(240, Math.max(...rows) * 86 + 32);
    const edges = (data.edges || []).map(edge => {
      const a = positions.get(edge.from), b = positions.get(edge.to);
      return a && b ? '<path d="M' + (a.x + 210) + ' ' + (a.y + 30) + ' C' + (a.x + 240) + ' ' + (a.y + 30) + ' ' + (b.x - 30) + ' ' + (b.y + 30) + ' ' + b.x + ' ' + (b.y + 30) + '"></path>' : "";
    }).join("");
    const nodes = (data.nodes || []).map(node => {
      const p = positions.get(node.id);
      return '<button type="button" class="kwm-node" data-kwm-node="' + PR.esc(node.id) + '" style="left:' + p.x + 'px;top:' + p.y + 'px" title="' + PR.esc(node.label) + '">' + PR.esc(node.label) + '</button>';
    }).join("");
    return '<div class="kwm-scroll"><div class="kwm-canvas" style="height:' + height + 'px"><svg width="990" height="' + height + '" aria-hidden="true">' + edges + '</svg>' + nodes + '</div></div>';
  }
  PR.openKeywordMaps = async function (keywordIds, paperIds) {
    const box = PR.el("dialog", { class: "confirm rw-keyword-map-dialog", "aria-label": PR.t("关键词图谱") },
      '<h2>' + PR.t("关键词图谱") + '</h2><p class="rw-source">' + PR.t("根据已扫描的关键词和论文原文建立关联图，不会调用 AI。选择节点可修改文字或回到原文。") + '</p>' +
      '<div class="rw-toolbar"><select data-kwm-list aria-label="' + PR.esc(PR.t("已保存图谱")) + '"></select>' +
      '<input data-kwm-name maxlength="200" aria-label="' + PR.esc(PR.t("图谱名称")) + '">' +
      '<button class="btn accent" data-kwm-create>' + PR.t("从所选关键词建立") + '</button>' +
      '<button class="btn line" data-kwm-save>' + PR.t("保存图谱") + '</button>' +
      '<button class="btn line" data-kwm-delete>' + PR.t("删除图谱") + '</button></div>' +
      '<div data-kwm-view></div><div class="rw-toolbar" data-kwm-editor hidden><label>' + PR.t("节点文字") + '<input data-kwm-label maxlength="500"></label><a class="btn line" data-kwm-source target="_blank" rel="noopener">' + PR.t("查看原文") + '</a></div>' +
      '<p role="status" data-kwm-status></p><div class="cf-acts"><button class="btn" data-kwm-close>' + PR.t("关闭") + '</button></div>');
    document.body.appendChild(box); box.showModal();
    const get = selector => box.querySelector(selector), list = get("[data-kwm-list]"), name = get("[data-kwm-name]");
    let maps = [], current = null, selected = null, busy = false, dirty = false;
    name.value = PR.t("关键词图谱");
    const status = text => { get("[data-kwm-status]").textContent = text || ""; };
    const paint = () => {
      get("[data-kwm-view]").innerHTML = current ? graph(current.data) : '<p class="rw-source">' + PR.t("选择关键词并扫描原文后，可以创建图谱。") + '</p>';
      get("[data-kwm-editor]").hidden = true; selected = null;
      get("[data-kwm-save]").disabled = !current || busy;
      get("[data-kwm-delete]").disabled = !current || busy;
    };
    const refresh = async id => {
      maps = (await PR.api(API)).maps || [];
      list.innerHTML = '<option value="">' + PR.t("选择已保存图谱") + '</option>' + maps.map(m => '<option value="' + PR.esc(m.id) + '">' + PR.esc(m.name) + '</option>').join("");
      const selectedMap = maps.find(m => m.id === id);
      current = selectedMap ? JSON.parse(JSON.stringify(selectedMap)) : null;
      list.value = current?.id || ""; if (current) name.value = current.name;
      dirty = false; paint();
    };
    const run = async action => {
      if (busy) return;
      busy = true; status(PR.t("处理中…"));
      box.querySelectorAll("input,select,button").forEach(control => { control.disabled = true; });
      try { await action(); }
      catch (error) { status(PR.errorText ? PR.errorText(error) : String(error.message || error)); }
      finally {
        busy = false;
        if (box.isConnected) {
          box.querySelectorAll("input,select,button").forEach(control => { control.disabled = false; });
          get("[data-kwm-save]").disabled = !current; get("[data-kwm-delete]").disabled = !current;
        }
      }
    };
    list.onchange = async () => {
      if (dirty && !await PR.confirm({ title: PR.t("放弃未保存的修改？") })) { list.value = current?.id || ""; return; }
      const selectedMap = maps.find(m => m.id === list.value);
      current = selectedMap ? JSON.parse(JSON.stringify(selectedMap)) : null; dirty = false;
      if (current) name.value = current.name; paint(); status("");
    };
    name.oninput = () => { dirty = true; };
    get("[data-kwm-create]").onclick = () => run(async () => {
      if (!keywordIds.length) throw new Error(PR.t("请先在关键词清单中勾选关键词。"));
      if (!name.value.trim()) throw new Error(PR.t("请输入图谱名称。"));
      const result = await PR.api(API, { method: "POST", body: { name: name.value.trim(), keyword_ids: keywordIds, paper_ids: paperIds } });
      await refresh(result.map.id); status(PR.t("图谱已创建"));
    });
    get("[data-kwm-save]").onclick = () => run(async () => {
      if (!current) return;
      const result = await PR.api(API, { method: "POST", body: { id: current.id, revision: current.revision, name: name.value.trim(), data: current.data } });
      await refresh(result.map.id); status(PR.t("图谱已保存"));
    });
    get("[data-kwm-delete]").onclick = () => run(async () => {
      if (!current || !await PR.confirm({ title: PR.t("删除图谱？"), danger: true })) return;
      await PR.api(API + "/delete", { method: "POST", body: { id: current.id } });
      await refresh(); status(PR.t("图谱已删除"));
    });
    box.addEventListener("click", event => {
      const button = event.target.closest("[data-kwm-node]"); if (!button || !current) return;
      selected = current.data.nodes.find(n => n.id === button.dataset.kwmNode); if (!selected) return;
      get("[data-kwm-editor]").hidden = false; get("[data-kwm-label]").value = selected.label || "";
      const source = selected.source || {}, link = get("[data-kwm-source]");
      link.hidden = !source.paper_id;
      if (source.paper_id) link.href = "/read/" + encodeURIComponent(source.paper_id) + (source.anchor ? "#b-" + encodeURIComponent(source.anchor) : "");
    });
    get("[data-kwm-label]").oninput = event => {
      if (!selected) return;
      selected.label = event.target.value; dirty = true;
      const node = Array.from(box.querySelectorAll("[data-kwm-node]")).find(n => n.dataset.kwmNode === selected.id);
      if (node) { node.textContent = selected.label; node.title = selected.label; }
    };
    const close = async () => {
      if (busy || (dirty && !await PR.confirm({ title: PR.t("放弃未保存的修改？") }))) return;
      box.close(); box.remove();
    };
    get("[data-kwm-close]").onclick = close;
    box.addEventListener("cancel", event => { event.preventDefault(); close(); });
    box.addEventListener("keydown", event => event.stopPropagation());
    await run(async () => { await refresh(); status(""); });
    return box;
  };
  PR.keywordMapGraph = graph;
})(window.PR);
