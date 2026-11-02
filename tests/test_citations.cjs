"use strict";
// DOM behavior checks: no browser, model service or live knowledge data is modified.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {JSDOM} = require("../temp/dev-tools/node_modules/jsdom");
const dom = new JSDOM(`<!doctype html><div class="chat-layout">
  <div id="chat-messages"></div><div id="chat-context-default"></div>
  <section id="source-reader" hidden><span id="source-document-count"></span>
    <div id="source-document-tabs"></div><section id="source-document">
      <h3 id="source-document-name"></h3><span id="source-document-info"></span>
      <a id="source-download"></a><div id="source-fragments"></div></section></section>
  <button id="close-source-reader"></button><button id="close-chat-context"></button>
  <button id="show-chat-context"></button><button id="source-backdrop" hidden></button></div>`,{runScripts:"outside-only"});
const {window} = dom;
const {document} = window;
window.matchMedia = () => ({matches:false});
window.requestAnimationFrame = callback => callback();
window.HTMLElement.prototype.scrollTo = function(options) { this.scrollTop = options.top; };
const originalRequests = [];
window.OriginalDocumentReader = {
  initialize() {},close() {},
  open(group,source) { originalRequests.push({group,source}); }
};
window.eval(fs.readFileSync(path.join(__dirname,"../app/web/static/js/citations.js"),"utf8"));
const controller = window.KnowledgeSources;
controller.initialize();
const sources = [
  {name:"这是一份很长的文件名<img src=x>.pdf",doc_id:"a".repeat(32),chunk:3,page:2,content:"第一份文档的原文，含 <script> 字面文字。"},
  {name:"第二份文档.md",doc_id:"b".repeat(32),chunk:7,page:0,content:"第二份文档的原文内容。"},
  {name:"这是一份很长的文件名<img src=x>.pdf",doc_id:"a".repeat(32),chunk:5,page:3,content:"第一份文档的另一个引用片段。"}
];
function reply(html, records=sources) {
  const message = document.createElement("article");
  message.className="assistant-message";
  message.innerHTML=`<div class="message-content">${html}</div>`;
  message.append(controller.references(records));
  document.querySelector("#chat-messages").append(message);
  controller.register(message,records);
  return message;
}
const first = reply("<p>根据资料[1][2]和[1, 3]，也可以写为[1-3]。[99]不属于引用。</p><pre><code>array[1]</code></pre><p><a href='#'>已有链接[1]</a></p>");
assert.equal(first.querySelectorAll(".message-content .citation-link").length,7);
assert.equal(first.querySelectorAll("pre .citation-link,a .citation-link").length,0);
assert.ok(first.textContent.includes("[99]"));
controller.enhance(first);
assert.equal(first.querySelectorAll(".message-content .citation-link").length,7,"enhancement is idempotent");
console.log("PASS: individual/group/range references link correctly; code, links and invalid numbers stay intact");
first.querySelector('.citation-link[data-source-index="1"]').click();
assert.equal(document.querySelector("#source-reader").hidden,false);
assert.equal(document.querySelectorAll(".document-tab").length,2);
assert.equal(document.querySelector("#source-document-name").textContent,"第二份文档.md");
assert.equal(originalRequests.at(-1).source,sources[1]);
assert.equal(document.querySelector("#source-download").getAttribute("href"),`/api/documents/${sources[1].doc_id}/download`);
first.querySelector('.source-reference[data-source-index="2"]').click();
assert.equal(document.querySelectorAll(".reference-fragment").length,0,"retrieved fragments must not replace the original file");
assert.equal(originalRequests.at(-1).source,sources[2]);
assert.equal(originalRequests.at(-1).group.docId,sources[2].doc_id);
assert.equal(document.querySelectorAll("#source-reader img,#source-reader script").length,0);
assert.equal(first.querySelector(".reference-file-name").textContent,sources[0].name);
console.log("PASS: multiple documents, shared tabs, exact selected highlights and safe full filenames");
document.querySelectorAll(".document-tab")[1].click();
assert.equal(document.querySelector("#source-document-name").textContent,sources[1].name);
const second = reply("<p>另一条回答[1]。</p>",[{name:"另一条回答的文档.txt",doc_id:"c".repeat(32),chunk:20,page:0,content:"另一条回答专属内容"}]);
second.querySelector(".citation-link").click();
assert.equal(originalRequests.at(-1).source.content,"另一条回答专属内容");
assert.equal(document.querySelectorAll(".document-tab").length,1);
document.dispatchEvent(new window.KeyboardEvent("keydown",{key:"Escape"}));
assert.equal(document.querySelector("#source-reader").hidden,true);
assert.equal(document.querySelector("#chat-context-default").hidden,false);
document.querySelector("#show-chat-context").click();
assert.ok(document.querySelector(".chat-layout").classList.contains("history-open"));
document.querySelector("#source-backdrop").click();
assert.ok(!document.querySelector(".chat-layout").classList.contains("history-open"));
console.log("PASS: document switching, reply-specific source mapping, close and recent-history drawer");
dom.window.close();
