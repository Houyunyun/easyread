/* Durable edits to generated paper mindmaps. Unsaved drafts survive a reload. */
(function (PR) {
  "use strict";
  const revisionOf = map => Number.isInteger(map?.revision) && map.revision >= 0 ? map.revision : 0;
  function identityOf(map) {
    if (!PR.paperKey || !PR.pid || map?.paper_id !== PR.pid ||
        typeof map.target !== "string" || !map.target || typeof map.source_sha256 !== "string" || !map.source_sha256) return null;
    return { paper_key: PR.paperKey, paper_id: PR.pid, target: map.target, source_sha256: map.source_sha256,
      mode: PR.store.mode === "static" ? "static" : "server" };
  }
  const key = identity => "easyread-mindmap-draft-v2-" + encodeURIComponent(JSON.stringify([
    identity.paper_key, identity.target, identity.source_sha256, identity.mode,
  ]));
  const sameMap = (map, identity) => map?.paper_id === identity.paper_id &&
    map?.target === identity.target && map?.source_sha256 === identity.source_sha256;
  function draftFor(identity, revision) {
    if (!identity) return null;
    const draft = PR.ls.get(key(identity), null);
    return sameMap(draft, identity) && draft.paper_key === identity.paper_key && draft.mode === identity.mode &&
      draft.revision === revision && typeof draft.mermaid === "string" && draft.mermaid ? draft : null;
  }
  function toMermaid(data) {
    const lines = ["mindmap"];
    let count = 0;
    function walk(node, depth) {
      if (!node || depth > 32 || ++count > 2000) throw new Error(PR.t("思维导图过大，请缩减节点"));
      // Quoted shape labels preserve parentheses, quotes and LaTeX on round-trip.
      const topic = String(node.topic || "").replace(/[\r\n]+/g, " ").trim();
      if (!topic) throw new Error(PR.t("节点文字不能为空"));
      lines.push("  ".repeat(depth + 1) + "node" + count + "[" + JSON.stringify(topic) + "]");
      for (const child of node.children || []) walk(child, depth + 1);
    }
    walk(data.nodeData, 0);
    return lines.join("\n");
  }
  function current(generated) {
    const draft = draftFor(identityOf(generated), revisionOf(generated));
    return draft ? { ...generated, mermaid: draft.mermaid } : generated;
  }
  function attach(toolbar, instance, generated, onSaved) {
    // An open editor must keep the identity it loaded, even after preferences or the current paper change.
    const identity = identityOf(generated), draftKey = identity ? key(identity) : null;
    const box = document.createElement("div"); box.className = "mm-edit-tools";
    box.innerHTML = '<button class="btn sm" data-map-edit="toggle" aria-pressed="false">' + PR.t("编辑") + '</button>' +
      '<span data-map-edit-actions hidden><button class="btn sm" data-map-edit="rename">' + PR.t("修改节点") + '</button><button class="btn sm" data-map-edit="child">' + PR.t("新增子节点") + '</button><button class="btn sm" data-map-edit="remove">' + PR.t("删除节点") + '</button></span>' +
      '<button class="btn sm" data-map-edit="save">' + PR.t("储存") + '</button><span role="status" class="mm-edit-status"></span>';
    toolbar.appendChild(box);
    const status = box.querySelector("[role=status]");
    let editing = false, timer = null, saving = null, dirty = false, revision = revisionOf(generated), version = 0;
    const draft = draftFor(identity, revision);
    if (draft) { dirty = true; status.textContent = PR.t("尚有未同步的修改"); }
    const requireIdentity = () => {
      if (!identity) throw new Error(PR.t("心智图缺少语言或来源标识，请重新载入后编辑。"));
    };
    function publish(map, previousRevision) {
      const currentIdentity = identityOf(PR.state.mindmap);
      if (PR.paperKey !== identity.paper_key || PR.pid !== identity.paper_id ||
          (PR.store.mode === "static" ? "static" : "server") !== identity.mode ||
          (PR.state.mindmap && (!currentIdentity || !sameMap(PR.state.mindmap, identity) || revisionOf(PR.state.mindmap) !== previousRevision))) return false;
      PR.state.mindmap = map;
      return true;
    }
    async function save() {
      clearTimeout(timer);
      if (saving) { await saving; if (dirty) return save(); return; }
      if (!dirty) return;
      requireIdentity();
      const mermaid = toMermaid(instance.getData()), savingVersion = version, savingRevision = revision;
      if (identity.mode === "static") {
        if (!PR.ls.set(draftKey, { ...identity, mermaid, revision })) throw new Error(PR.t("浏览器存储已满，修改只在内存里，请尽快导出"));
        status.textContent = PR.t("已储存于本浏览器"); dirty = false; return;
      }
      status.textContent = PR.t("储存中…");
      saving = PR.api("/api/research/v2/paper/" + encodeURIComponent(identity.paper_id) + "/mindmap/save", {
        method: "POST", body: { mermaid, revision, target: identity.target, source_sha256: identity.source_sha256 },
      });
      try {
        const result = await saving;
        if (!sameMap(result, identity)) throw new Error(PR.t("心智图语言或来源标识不匹配，修改保留在本机。"));
        revision = result.revision; generated = result;
        if (version === savingVersion) {
          dirty = false;
          if (draftFor(identity, savingRevision)?.mermaid === mermaid) PR.ls.set(draftKey, null);
          status.textContent = PR.t("已保存");
          if (publish(result, savingRevision)) onSaved?.(result);
        } else {
          const pending = { ...identity, mermaid: toMermaid(instance.getData()), revision };
          PR.ls.set(draftKey, pending);
          if (publish(result, savingRevision)) onSaved?.(result);
        }
      } catch (error) {
        status.textContent = PR.t("同步失败，修改保留在本机；请重试");
        PR.toast(PR.esc(PR.errorText ? PR.errorText(error) : error.message));
      } finally { saving = null; }
    }
    function changed(event) {
      if (["beginEdit"].includes(event?.name)) return;
      try {
        const mermaid = toMermaid(instance.getData());
        dirty = true; version++;
        requireIdentity();
        const persisted = PR.ls.set(draftKey, { ...identity, mermaid, revision });
        publish({ ...generated, mermaid, revision }, revision);
        status.textContent = persisted ? PR.t("尚未同步") : PR.t("浏览器存储已满，修改只在内存里，请尽快导出");
        clearTimeout(timer); timer = setTimeout(() => save().catch(showError), 600);
      } catch (error) { showError(error); }
    }
    const showError = error => { status.textContent = error.message; PR.toast(PR.esc(error.message)); };
    instance.bus.addListener("operation", changed);
    box.addEventListener("click", async event => {
      const action = event.target.closest("[data-map-edit]")?.dataset.mapEdit;
      if (!action) return;
      event.stopPropagation();
      if (action === "toggle") {
        editing = !editing;
        if (editing) instance.enableEdit(); else { instance.disableEdit(); save().catch(showError); }
        event.target.closest("button").setAttribute("aria-pressed", String(editing));
        box.querySelector("[data-map-edit-actions]").hidden = !editing;
      } else if (action === "save") { await save().catch(showError); }
      else if (editing) {
        const node = instance.currentNode;
        if (!node) { status.textContent = PR.t("请先选择节点"); return; }
        if (action === "rename") instance.beginEdit(node);
        else if (action === "child") instance.addChild(node);
        else if (action === "remove" && node.nodeObj?.id !== "me-root") instance.removeNodes([node]);
      }
    });
    return { save, destroy() { clearTimeout(timer); if (dirty) save().catch(showError); instance.bus.removeListener?.("operation", changed); } };
  }
  PR.mindmapEdits = { toMermaid, current, attach };
})(window.PR);
