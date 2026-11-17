/* Durable edits to generated paper mindmaps. Unsaved drafts survive a reload. */
(function (PR) {
  "use strict";
  const key = () => "easyread-mindmap-draft-" + PR.paperKey + (PR.store.mode === "static" ? "-static" : "");
  function toMermaid(data) {
    const lines = ["mindmap"];
    let count = 0;
    function walk(node, depth) {
      if (!node || depth > 32 || ++count > 2000) throw new Error(PR.t("思維導圖過大，請縮減節點"));
      // Quoted shape labels preserve parentheses, quotes and LaTeX on round-trip.
      const topic = String(node.topic || "").replace(/[\r\n]+/g, " ").trim();
      if (!topic) throw new Error(PR.t("節點文字不能為空"));
      lines.push("  ".repeat(depth + 1) + "node" + count + "[" + JSON.stringify(topic) + "]");
      for (const child of node.children || []) walk(child, depth + 1);
    }
    walk(data.nodeData, 0);
    return lines.join("\n");
  }
  function current(generated) {
    const draft = PR.ls.get(key(), null);
    return draft?.mermaid ? { ...generated, ...draft } : generated;
  }
  function attach(toolbar, instance, generated, onSaved) {
    const box = document.createElement("div"); box.className = "mm-edit-tools";
    box.innerHTML = '<button class="btn sm" data-map-edit="toggle" aria-pressed="false">' + PR.t("編輯") + '</button>' +
      '<span data-map-edit-actions hidden><button class="btn sm" data-map-edit="rename">' + PR.t("修改節點") + '</button><button class="btn sm" data-map-edit="child">' + PR.t("新增子節點") + '</button><button class="btn sm" data-map-edit="remove">' + PR.t("刪除節點") + '</button></span>' +
      '<button class="btn sm" data-map-edit="save">' + PR.t("儲存") + '</button><span role="status" class="mm-edit-status"></span>';
    toolbar.appendChild(box);
    const status = box.querySelector("[role=status]");
    let editing = false, timer = null, saving = null, dirty = false, revision = Number.isInteger(generated?.revision) ? generated.revision : 0, version = 0;
    const draft = PR.ls.get(key(), null);
    if (draft?.mermaid) { dirty = true; status.textContent = PR.t("尚有未同步的修改"); }
    async function save() {
      clearTimeout(timer);
      if (saving) { await saving; if (dirty) return save(); return; }
      if (!dirty) return;
      const mermaid = toMermaid(instance.getData()), savingVersion = version;
      if (PR.store.mode === "static") {
        if (!PR.ls.set(key(), { mermaid, revision })) throw new Error(PR.t("浏览器存储已满，修改只在内存里，请尽快导出"));
        status.textContent = PR.t("已儲存於本瀏覽器"); dirty = false; return;
      }
      status.textContent = PR.t("儲存中…");
      saving = PR.api("/api/research/v2/paper/" + encodeURIComponent(PR.pid) + "/mindmap/save", {
        method: "POST", body: { mermaid, ...(revision != null ? { revision } : {}) },
      });
      try {
        const result = await saving;
        revision = result.revision; generated = result;
        if (version === savingVersion) {
          dirty = false;
          if (PR.ls.get(key(), null)?.mermaid === mermaid) PR.ls.set(key(), null);
          status.textContent = PR.t("已保存");
        } else {
          PR.ls.set(key(), { mermaid: toMermaid(instance.getData()), revision });
        }
        if (!PR.ls.get(key(), null)?.mermaid) PR.state.mindmap = result;
        onSaved?.(result);
      } catch (error) {
        status.textContent = PR.t("同步失敗，修改保留在本機；請重試");
        PR.toast(PR.esc(PR.errorText ? PR.errorText(error) : error.message));
      } finally { saving = null; }
    }
    function changed(event) {
      if (["beginEdit"].includes(event?.name)) return;
      try {
        const mermaid = toMermaid(instance.getData());
        dirty = true; version++;
        const persisted = PR.ls.set(key(), { mermaid, ...(revision != null ? { revision } : {}) });
        PR.state.mindmap = { ...generated, mermaid, revision };
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
        if (!node) { status.textContent = PR.t("請先選擇節點"); return; }
        if (action === "rename") instance.beginEdit(node);
        else if (action === "child") instance.addChild(node);
        else if (action === "remove" && node.nodeObj?.id !== "me-root") instance.removeNodes([node]);
      }
    });
    return { save, destroy() { clearTimeout(timer); if (dirty) save().catch(showError); instance.bus.removeListener?.("operation", changed); } };
  }
  PR.mindmapEdits = { toMermaid, current, attach };
})(window.PR);
