const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = ["notespanel", "notes-markdown"].map(name => fs.readFileSync(path.join(__dirname, "../../easyread/web/js/reader/" + name + ".js"), "utf8")).join("\n");
const exportSource = fs.readFileSync(path.join(__dirname, "../../easyread/web/js/reader/research-export.js"), "utf8");
const pickerSource = fs.readFileSync(path.join(__dirname, "../../easyread/web/js/common/pick-folder.js"), "utf8");

function loadReader({ notes, blocks, entries = [] }) {
  const noopNode = { addEventListener() {}, classList: { add() {}, remove() {} }, contains() { return false; } };
  const PR = {
    state: { paper: { meta: {}, blocks }, reader: { notes }, discussion: { entries } },
    ls: { get: (_key, fallback) => fallback, set() {} },
    $: () => noopNode,
    $$: () => [],
    on() {},
    t: (text, values) => values ? text.replace(/\{(\w+)\}/g, (_match, key) => values[key]) : text,
    myNotes: () => Object.values(notes).filter((note) => !note.deleted),
    anchorOfEntry: (entry) => entry.anchor || "head",
    order: {},
    blockById: Object.fromEntries(blocks.map((block) => [block.id, block])),
    editOf: () => null,
    plain: (text) => text || "",
    textFor: (id) => PR.blockById[id]?.zh || "",
    esc: (text) => String(text || ""),
    mdBlocks: (text) => text,
    HL_COLORS: [["yellow", "黃"], ["green", "綠"], ["blue", "藍"], ["pink", "紅"]],
    debounce: (fn) => { fn.flush = fn; fn.cancel = () => {}; return fn; },
  };
  vm.runInNewContext(source, { window: { PR, addEventListener() {} }, document: { addEventListener() {}, querySelector() { return noopNode; }, querySelectorAll() { return []; } }, location: { search: "" }, URLSearchParams });
  return PR;
}

test("export includes Chinese quote for accepted smart highlights and legacy English highlights", () => {
  const blocks = [{
    id: "p1", type: "para", en: "We propose a method. It is fast.", zh: "我們提出一個方法。它很快。",
    sents: [[20, 9], [34, 15]],
  }];
  const PR = loadReader({ blocks, notes: {
    smart: { id: "smart", anchor: "p1", key: "p1", quote: "我們提出一個方法。", side: "zh", kind: "highlight", body: "提出可介接不同前端的解碼器。", ai_generated: true },
    legacy: { id: "legacy", anchor: "p1", key: "p1", quote: "It is fast.", kind: "highlight" },
  } });
  const markdown = PR.notesMarkdown({ paper: false, note: false, highlight: true, question: false, ai: false, chat: false, quote: true }, [], { order: ["highlight"], chat: [] });
  assert.match(markdown, /「我們提出一個方法。」/);
  assert.match(markdown, /「它很快。」/);
  assert.match(markdown, /引用（中文译文）/);
  assert.match(markdown, /我的注记：\*\* 提出可介接不同前端的解碼器/);
});

test("page-side AI explanations do not gain a quote from the export checkbox", () => {
  const PR = loadReader({ blocks: [{ id: "p1", type: "para", en: "Original", zh: "譯文" }], notes: {}, entries: [
    { id: "answer", anchor: "p1", quote: "原文", body: "說明", kind: "reply" },
  ] });
  const markdown = PR.notesMarkdown({ paper: false, note: false, highlight: false, question: false, ai: true, chat: false, quote: true }, [], { order: ["ai"], chat: [] });
  assert.ok(!markdown.includes("「原文」"));
  assert.match(markdown, /說明/);
});

function loadExporter({ configured = false, selectedPath = "C:\\Vault", desktop = true, ink = {} } = {}) {
  const requests = [];
  const fields = [{ dataset: { exp: "paper" }, checked: true }];
  const dialogContent = {};
  const dialog = {
    closed: false,
    classList: { add() {}, remove() { dialog.closed = true; } },
    addEventListener(_event, handler) { dialog.click = handler; },
    querySelector() { return dialogContent; },
  };
  const button = {
    disabled: false,
    innerHTML: "匯出至 Obsidian Vault",
    hasAttribute(name) { return name === "data-exp-vault"; },
  };
  const PR = {
    state: { paper: { meta: { title_en: "Paper" }, blocks: [] }, reader: { paper_note: { body: "note" }, notes: {}, ink }, discussion: { entries: [] } },
    ls: { get: (_key, fallback) => fallback, set() {} },
    $: () => dialog,
    $$: () => fields,
    t: (text, values) => values ? text.replace(/\{(\w+)\}/g, (_match, key) => values[key]) : text,
    api: async (path, options = {}) => {
      requests.push({ path, options });
      if (path === "/api/research/v1/status") return { configured };
      if (path === "/api/library/pick-folder") return { supported: true, path: selectedPath };
      return {};
    },
    notesMarkdown: () => "# Notes",
    pid: "paper-id", store: {mode:"server"},
    toast() {},
  };
  const window = { PR, ...(desktop ? { easyreadDesktop: { pickFolder: async () => selectedPath } } : {}) };
  vm.runInNewContext(pickerSource + "\n" + exportSource, { window });
  return {
    requests,
    button,
    dialog,
    click: () => dialog.click({ target: { closest: (selector) => selector === "[data-exp-vault]" ? button : null } }),
  };
}

test("Obsidian note export prompts for a vault, saves it, then exports", async () => {
  const app = loadExporter();
  await app.click();
  assert.deepEqual(app.requests.map((request) => request.path), [
    "/api/research/v1/status", "/api/research/v1/setup", "/api/research/v2/export/obsidian",
  ]);
  assert.equal(app.requests[1].options.body.vault, "C:\\Vault");
  assert.equal(app.dialog.closed, true);
});

test("canceling vault selection keeps the export dialog usable", async () => {
  const app = loadExporter({ selectedPath: null });
  await app.click();
  assert.deepEqual(app.requests.map((request) => request.path), ["/api/research/v1/status"]);
  assert.equal(app.button.disabled, false);
  assert.equal(app.button.innerHTML, "匯出至 Obsidian Vault");
  assert.equal(app.dialog.closed, false);
});

test("browser note export uses the server folder picker", async () => {
  const app = loadExporter({ desktop: false });
  await app.click();
  assert.deepEqual(app.requests.map((request) => request.path), [
    "/api/research/v1/status", "/api/library/pick-folder", "/api/research/v1/setup", "/api/research/v2/export/obsidian",
  ]);
});

test("configured vault exports without prompting for another folder", async () => {
  const app = loadExporter({ configured: true });
  await app.click();
  assert.deepEqual(app.requests.map((request) => request.path), [
    "/api/research/v1/status", "/api/research/v2/export/obsidian",
  ]);
});

test("Obsidian export warns about handwritten strokes but excludes deleted strokes from the count", async () => {
  const app = loadExporter({ configured: true, ink: {
    one: { id: "one" }, two: { id: "two" }, gone: { id: "gone", deleted: true },
  } });
  await app.click();
  const docs = app.requests.find(request => request.path === "/api/research/v2/export/obsidian").options.body.documents;
  assert.ok(docs.every(doc => doc.body.includes("本次汇出未包含 2 笔手写注记。")));
});


test('export headings and metadata labels follow UI language, never paper titles or authored notes', () => {
  const readDictionary = lang => lang === 'zh' ? {} : JSON.parse(fs.readFileSync(path.join(__dirname, '../../easyread/web/i18n/' + lang + '.json'), 'utf8'));
  for (const lang of ['zh','en','zh-Hant']) {
    const dict = readDictionary(lang);
    const t = (text, values) => (dict[text] || text).replace(/\{(\w+)\}/g, (match, key) => values?.[key] ?? match);
    const PR = loadReader({blocks:[{id:'p1', type:'para', en:'An original sentence.', zh:'不可轉換的論文。'}], notes:{
      note:{id:'note', anchor:'p1', key:'p1', quote:'不可轉換的論文。', side:'zh', kind:'note', body:'我寫的繁體筆記。'},
    }});
    PR.t = t;
    PR.state.paper.meta = {title_zh:'原始論文標題', title_en:'Original title', authors:'作者姓名', date:'2026'};
    PR.state.reader.paper_note = {body:'我寫的繁體筆記。'};
    const markdown = PR.notesMarkdown({paper:true, note:true, quote:true}, [], {order:['paper','note'], chat:[]});
    assert.ok(markdown.includes(t('论文笔记')));
    assert.ok(markdown.includes(t('我的笔记')));
    assert.ok(markdown.includes('我寫的繁體筆記。'));
    assert.ok(markdown.includes('不可轉換的論文。'));
    vm.runInNewContext(exportSource, {window:{PR}});
    const [doc] = PR.researchExport.documents({pick:{paper:true}, order:['paper'], chat:[], mindmap:''});
    assert.ok(doc.body.includes('## ' + t('书目资料')));
    assert.ok(doc.body.includes(t('英文标题：{title}', {title:'Original title'})));
    assert.ok(doc.body.includes(t('作者：{authors}', {authors:'作者姓名'})));
    assert.ok(doc.body.includes('我寫的繁體筆記。'));
    assert.ok(doc.title.startsWith('原始論文標題'));
  }
});
