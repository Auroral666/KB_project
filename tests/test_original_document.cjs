"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {JSDOM} = require("../temp/dev-tools/node_modules/jsdom");
const dom = new JSDOM(`<!doctype html><div id="source-document-info"></div>
  <div id="original-toolbar"><button id="original-prev"></button><input id="original-page">
  <span id="original-total"></span><button id="original-next"></button><select id="original-zoom"><option value="fit">适宽</option></select>
  <button id="original-jump"></button></div><div id="source-fragments"></div>`,{runScripts:"outside-only"});
const w=dom.window, d=w.document;
w.ResizeObserver=class{observe(){}};
w.requestAnimationFrame=fn=>fn();
w.HTMLElement.prototype.scrollTo=function(options){this.scrollTop=options.top;};
for(const file of ["text-locator.js","document-viewer.js"]) w.eval(fs.readFileSync(path.join(__dirname,"../app/web/static/js",file),"utf8"));

(async()=>{
  const root=d.createElement("div");
  root.innerHTML="<p>开头的完整上下文。</p><p>基本<span>助学金为每生每月</span>１７５０ 元。</p><p>结尾的完整上下文。</p>";
  const original=root.textContent;
  const found=w.OriginalTextLocator.highlight(root,"基本助学金为每生每月1750元。");
  assert.ok(found.exact);
  assert.ok(found.marks.length>=2);
  assert.equal(root.textContent,original,"highlighting must not reconstruct or truncate original content");
  w.OriginalTextLocator.highlight(root,"完全不存在的引用文字");
  assert.equal(root.querySelectorAll("mark").length,0,"unmatched text must not be inserted as a fragment");
  assert.equal(root.textContent,original);
  console.log("PASS: real DOM offsets, Unicode normalization, full surrounding content and honest no-match handling");

  const complete="全文开始：这部分没有被检索。\n\n引用内容是1750元。\n\n全文结束：这部分也没有被检索。";
  w.fetch=async()=>({ok:true,headers:{get:()=>"application/json"},json:async()=>({pages:[{number:1,text:complete}]})});
  w.OriginalDocumentReader.initialize();
  await w.OriginalDocumentReader.open({docId:"a".repeat(32),name:"全文.txt"},{page:0,content:"引用内容是1750元。"});
  assert.equal(d.querySelector(".original-full-text").textContent,complete);
  assert.equal(d.querySelector(".original-highlight").textContent,"引用内容是1750元。");
  assert.equal(d.querySelectorAll(".reference-fragment").length,0);
  assert.equal(d.querySelector("#original-total").textContent,"/ 1");
  console.log("PASS: reader loads complete original text rather than retrieved excerpts");

  w.fetch=async()=>({ok:false,json:async()=>({detail:"原始文件已删除"})});
  await w.OriginalDocumentReader.open({docId:"b".repeat(32),name:"missing.txt"},{page:1,content:"引用副本不能冒充原文"});
  assert.ok(d.querySelector(".original-error").textContent.includes("已删除"));
  assert.ok(!d.querySelector("#source-fragments").textContent.includes("引用副本不能冒充原文"));
  console.log("PASS: missing originals show an error without falling back to excerpt lists");
  dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
