"use strict";
// This DOM unit test never opens or controls a browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("../temp/dev-tools/node_modules/jsdom");
const root = path.resolve(__dirname,"..");
const dom = new JSDOM("<!doctype html><div id='reply'></div>",{runScripts:"outside-only"});
for (const file of ["app/web/static/vendor/marked/marked.umd.js","app/web/static/vendor/dompurify/purify.min.js","app/web/static/js/markdown.js"]) {
  dom.window.eval(fs.readFileSync(path.join(root,file),"utf8"));
}
const sample = ["# 渲染验收", "", "**结论**：资料中的数字应保持准确。", "", "## 清单", "",
  "1. 第一项", "2. 第二项", "", "- 项目甲", "- 项目乙", "", "> 引用文字", "",
  "| 项目 | 金额 |", "| --- | --- |", "| 基本助学金 | 1750 元 |", "",
  "```python", "print('<safe>')", "```", "", "行内 `code` 和 [资料](https://example.com)"] .join("\n");
const target = dom.window.document.querySelector("#reply");
target.innerHTML = dom.window.KnowledgeMarkdown.render(sample);
for (const selector of ["h1","h2","strong","ol li","ul li","blockquote","table th","table td","pre code.language-python","p code","a"]) {
  assert.ok(target.querySelector(selector),`${selector} should be rendered`);
}
assert.equal(target.querySelector("pre code").textContent.trim(),"print('<safe>')");
assert.ok(!target.textContent.includes("| --- |"));
assert.ok(!target.textContent.includes("**结论**"));
console.log("PASS: headings, bold, lists, blockquotes, tables, fenced code, inline code, links");
target.innerHTML = dom.window.KnowledgeMarkdown.render('<script>alert(1)</script><img src="https://example.com/a" onerror="alert(1)"><svg onload="alert(1)"></svg><a href="javascript:alert(1)">bad</a>');
assert.equal(target.querySelectorAll("script,img,svg,iframe,object").length,0);
assert.equal(target.querySelectorAll("[onerror],[onload],[style]").length,0);
assert.ok(!target.innerHTML.includes("javascript:"));
console.log("PASS: scripts, external images, event handlers and unsafe URLs removed");
for (const partial of ["**正在", "```python\nprint(", "| a | b |\n| --- | --- |\n| 1", "<img src=x onerror="]) {
  assert.equal(typeof dom.window.KnowledgeMarkdown.render(partial),"string");
}
console.log("PASS: incomplete streamed Markdown can be rendered safely");
dom.window.close();
