"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {JSDOM} = require("../temp/dev-tools/node_modules/jsdom");
const dom = new JSDOM('<section id="jobs"></section><input id="document-search"><select id="type-filter"><option value="all">All</option></select><div id="document-list"></div><button id="clear-library"></button><span id="selection-count"></span><button id="delete-selected"></button>',{runScripts:"outside-only"});
const {window:w} = dom;
w.eval(fs.readFileSync("app/web/static/js/index-jobs.js","utf8"));
const panel = w.document.querySelector("#jobs");
w.KnowledgeJobs.render(panel,[
  {id:"a".repeat(32),name:"<img src=x onerror=alert(1)>.txt",status:"failed",stage:"failed",error:"<script>alert(1)</script>"},
  {id:"b".repeat(32),name:"running.txt",status:"running",stage:"writing_vectors"},
  {id:"c".repeat(32),name:"done.txt",status:"succeeded",stage:"complete"}
]);
assert.equal(panel.querySelectorAll(".index-job").length,3);
assert.equal(panel.querySelectorAll("script,img").length,0);
assert.equal(panel.querySelector(".job-error").textContent,"<script>alert(1)</script>");
assert.equal(panel.querySelector('[aria-current="step"]').textContent,"写入向量");
assert.match(panel.querySelector(".jobs-summary").textContent,/1 个/);
w.KnowledgeJobs.render(panel,[]);
assert.equal(panel.querySelectorAll(".index-job").length,0);
assert.match(panel.textContent,/暂无建库任务/);
console.log("PASS: job cards, states, active stage, safe errors, empty state and repeated refresh");
w.eval(fs.readFileSync("app/web/static/js/workspace.js","utf8").replace('initialize().catch(error => toast(error.message,true));', '') + `
workspace={documents:[{id:'${"a".repeat(32)}',name:'a.txt',extension:'.txt',size:4,chunks:1}]};
window.testSelection={filterDocuments,selectedDocuments};`);
w.testSelection.filterDocuments();
const checkbox = w.document.querySelector("[data-select-document]");
checkbox.checked = true;
checkbox.dispatchEvent(new w.Event("change"));
assert.equal(w.testSelection.selectedDocuments.size,1);
assert.equal(w.document.querySelector("#delete-selected").disabled,false);
assert.match(w.document.querySelector("[data-delete]").textContent,/删除/);
w.testSelection.filterDocuments();
assert.equal(w.document.querySelector("[data-select-document]").checked,true);
console.log("PASS: file selection, visible delete button and selection preserved on refresh");
dom.window.close();
