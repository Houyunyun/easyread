const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '../../easyread/web');
const source = fs.readFileSync(path.join(web, 'js/common/access.js'), 'utf8');
const dictionaries = Object.fromEntries(['en', 'zh-Hant'].map(lang => [lang, JSON.parse(fs.readFileSync(path.join(web, 'i18n', lang + '.json'), 'utf8'))]));

function page(lang) {
  const nodes = new Map(), requests = [];
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {value:'', textContent:'', type:'password', setAttribute(k,v){this[k]=v;}, focus(){}});
    return nodes.get(selector);
  };
  const labels = ['欢迎回来','私人阅读空间','输入访问授权码，继续你的阅读。','进入 EasyRead'].map(key => ({dataset:{zh:key},textContent:key}));
  const document = {documentElement:{lang:lang === 'zh' ? 'zh-CN' : lang}, querySelector:node, querySelectorAll:()=>labels,
    getElementById:()=>({textContent:JSON.stringify(dictionaries[lang] || {})})};
  const context = {window:{}, document, navigator:{language:lang === 'en' ? 'zh-CN' : 'en-US'}, URL, URLSearchParams,
    location:{search:'',origin:'http://localhost',replace(value){this.redirect=value;}},
    fetch:async(url, options) => {requests.push(url); if (url.startsWith('/web/i18n/')) return {ok:true,json:async()=>dictionaries[url.split('/').at(-1).replace('.json','')]}; return {ok:false,status:401};}};
  vm.runInNewContext(source,context);
  return {document,node,labels,requests};
}

test('access page initially follows server/app locale, not a conflicting browser locale', () => {
  for (const lang of ['zh','en','zh-Hant']) {
    const p=page(lang), dict=dictionaries[lang] || {};
    assert.equal(p.node('#accessLang').value,lang);
    assert.equal(p.node('#accessCode').placeholder,dict['输入访问授权码'] || '输入访问授权码');
    assert.equal(p.labels[0].textContent,dict['欢迎回来'] || '欢迎回来');
    assert.equal(p.document.title,dict['EasyRead · 访问授权'] || 'EasyRead · 访问授权');
    assert.equal(p.requests.length,0);
  }
});

test('visitor can choose each locale and errors follow it without mutating global preferences', async () => {
  const p=page('zh');
  for (const lang of ['zh-Hant','en','zh']) {
    const picker=p.node('#accessLang');picker.value=lang;await picker.onchange();
    const dict=dictionaries[lang] || {};
    assert.equal(p.labels[0].textContent,dict['欢迎回来'] || '欢迎回来');
    p.node('#accessCode').value='incorrect-code';
    await p.node('#accessForm').onsubmit({preventDefault(){}});
    assert.equal(p.node('#accessError').textContent,dict['访问授权码不正确'] || '访问授权码不正确');
    assert.equal(p.node('#accessSubmit').disabled,false);
  }
  assert.ok(p.requests.every(url => url.startsWith('/web/i18n/') || url === '/api/access/login'));
});
