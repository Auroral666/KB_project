"use strict";
// Repeatable DOM checks; the vis canvas API is stubbed, real drawing needs a browser.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {JSDOM} = require("../temp/dev-tools/node_modules/jsdom");
const dom = new JSDOM("<!doctype html><section id='graph'></section><section id='second'></section>", {runScripts:"outside-only"});
const {window} = dom, {document} = window;
window.requestAnimationFrame = callback => callback();
const instances = [];
class Network {
  constructor(container, data, options) {
    Object.assign(this, {container, data, options, handlers:{}, destroyed:false});
    instances.push(this);
  }
  on(name, callback) { this.handlers[name] = callback; }
  once(name, callback) { this.handlers[name] = callback; }
  setOptions(options) { this.lastOptions = options; }
  fit(options) { this.fitOptions = options; }
  destroy() { this.destroyed = true; }
}
window.vis = {Network};
window.eval(fs.readFileSync(path.join(__dirname, "../app/web/static/js/knowledge-graph.js"), "utf8"));
const graph = window.KnowledgeGraph;
const container = document.querySelector("#graph"), second = document.querySelector("#second");
const firstSource = {doc_id:"a".repeat(32), name:"研发说明<img src=x>.md", page:2, chunk:1,
  content:"Alpha 项目由研发部负责。<script>window.infected=true</script>"};
const secondSource = {doc_id:"b".repeat(32), name:"人员说明.md", page:1, chunk:2, content:"研发部主管为张明。"};
const fixture = {
  nodes:[{id:"alpha", label:"Alpha <script>"}, {id:"team", label:"研发部"}, {id:"person", label:"张明"}],
  edges:[{id:"e1", from:"alpha", to:"team", label:"负责部门", sources:[firstSource, {...firstSource}]},
    {id:"e2", from:"team", to:"person", label:"主管", sources:[secondSource]}]
};
const opened = [];
graph.loading(container);
assert.equal(container.getAttribute("aria-busy"), "true");
assert.match(container.textContent, /正在加载/);
graph.render(container, fixture, source => opened.push(source));
assert.equal(container.hasAttribute("aria-busy"), false);
assert.match(container.textContent, /3 个实体 · 2 条关系/);
assert.equal(instances[0].data.nodes.length, 3);
assert.equal(instances[0].data.edges[0].arrows, "to");
assert.equal(instances[0].options.nodes.font.multi, false);
assert.equal(document.querySelectorAll("script,img").length, 0);
console.log("PASS: loading state, directed graph data, entity counts and literal safe labels");

instances[0].handlers.click({edges:["e1"], nodes:[]});
assert.equal(container.querySelectorAll(".knowledge-graph-source-button").length, 1, "duplicate evidence is grouped");
container.querySelector(".knowledge-graph-source-button").click();
assert.equal(opened.at(-1), firstSource);
assert.match(container.querySelector(".knowledge-graph-quotation").textContent, /<script>/);
assert.equal(document.querySelectorAll("script,img").length, 0);
instances[0].handlers.click({edges:["e1", "e2"], nodes:["team"]});
assert.equal(container.querySelectorAll(".knowledge-graph-source-button").length, 2);
container.querySelectorAll(".knowledge-graph-source-button")[1].click();
assert.equal(opened.at(-1), secondSource);
container.querySelectorAll(".knowledge-graph-relation")[1].click();
assert.equal(container.querySelector(".knowledge-graph-source-button").textContent, "人员说明.md · 第 1 页 · 片段 2");
instances[0].handlers.stabilizationIterationsDone();
assert.equal(instances[0].lastOptions.physics, false);
instances[0].handlers.resize();
assert.equal(instances[0].fitOptions.animation, false, "fit nodes to the changed container width");
console.log("PASS: edge and shared-node evidence, document mapping, keyboard-accessible relation buttons and stabilization");

graph.render(second, fixture, source => opened.push(source));
graph.loading(container);
assert.equal(instances[0].destroyed, true);
assert.equal(instances[1].destroyed, false, "other reply graphs keep their own network");
graph.destroy(second);
assert.equal(instances[1].destroyed, true);
assert.equal(second.children.length, 0);
graph.destroy(second);
graph.render(container, {nodes:[], edges:[]}, () => {});
assert.match(container.textContent, /没有可展示/);
graph.render(container, {error:"Neo4j 暂时不可用 <img>"});
assert.equal(container.querySelector("[role=alert]").textContent, "Neo4j 暂时不可用 <img>");
assert.equal(container.querySelectorAll("img").length, 0);
console.log("PASS: independent reply lifecycles, repeated cleanup, empty data and safe error states");

delete window.vis;
graph.render(container, fixture, source => opened.push(source));
assert.match(container.textContent, /组件未加载/);
assert.equal(container.querySelector("details").open, true);
container.querySelector(".knowledge-graph-relation").click();
container.querySelector(".knowledge-graph-source-button").click();
assert.equal(opened.at(-1), firstSource, "source viewing survives failed canvas dependency");
window.vis = {Network: class {constructor() {throw new Error("canvas unavailable");}}};
graph.render(container, fixture);
assert.match(container.textContent, /绘制失败/);
container.querySelector(".knowledge-graph-relation").click();
assert.equal(container.querySelector(".knowledge-graph-source-button").disabled, true);
graph.render(container, {nodes:[null, {id:"x", label:"孤立实体"}], edges:[null, {id:"bad", from:"x", to:"missing", label:"坏关系"}]});
assert.match(container.textContent, /1 个实体 · 0 条关系/);
assert.match(container.textContent, /暂未抽取到/);
console.log("PASS: missing/failed vendor still exposes evidence; missing callbacks and malformed edges are safe");

// Exercise the current workspace adapter with the real citation component.
const shell = document.createElement("div");
shell.innerHTML = `<div class="chat-layout"><div id="chat-messages"><article id="integration-message" class="assistant-message"><div class="message-content">回答[1][2]</div></article></div><div id="chat-context-default"></div>
  <section id="source-reader" hidden><span id="source-document-count"></span><div id="source-document-tabs"></div><div id="source-document"><h3 id="source-document-name"></h3><a id="source-download"></a></div></section>
  <button id="close-source-reader"></button><button id="close-chat-context"></button><button id="show-chat-context"></button><button id="source-backdrop" hidden></button></div>`;
document.body.append(shell);
window.matchMedia = () => ({matches:false});
let selectedOriginal;
window.OriginalDocumentReader = {initialize(){},close(){},open(group, source){selectedOriginal={group,source};}};
window.vis = {Network};
window.eval(fs.readFileSync(path.join(__dirname,"../app/web/static/js/citations.js"),"utf8"));
const workspaceCode = fs.readFileSync(path.join(__dirname,"../app/web/static/js/workspace.js"),"utf8");
window.eval(workspaceCode.slice(workspaceCode.indexOf("function graphFromSources("),workspaceCode.indexOf("async function consumeAnswerStream(")));
window.KnowledgeSources.initialize();
const message = document.querySelector("#integration-message");
const adapterSources = [
  {...firstSource, relations:[{id:"adapter-1",from:"project",to:"team",subject:"Alpha 项目",object:"研发部",label:"负责部门"}]},
  {...secondSource, relations:[{id:"adapter-2",from:"team",to:"person",subject:"研发部",object:"张明",label:"主管"}]}
];
window.KnowledgeSources.register(message,adapterSources);
window.renderAnswerGraph(message,window.graphFromSources(adapterSources),adapterSources);
message.querySelectorAll(".knowledge-graph-relation")[1].click();
message.querySelector(".knowledge-graph-source-button").click();
assert.equal(document.querySelector("#source-reader").hidden,false);
assert.equal(document.querySelector("#source-document-name").textContent,secondSource.name);
assert.equal(selectedOriginal.source,adapterSources[1]);
assert.equal(selectedOriginal.group.docId,secondSource.doc_id);
assert.equal(document.querySelectorAll(".document-tab").length,2);
const adapterNetwork = instances.at(-1);
window.renderAnswerGraph(message,window.graphFromSources(adapterSources),adapterSources);
assert.equal(adapterNetwork.destroyed,true,"SSE graph replaced by final answer releases the old instance");
assert.equal(message.querySelectorAll(".answer-graph").length,1);
graph.destroy(message.querySelector(".answer-graph"));
console.log("PASS: current workspace adapter opens the correct original document; final graph replaces streamed graph without duplicate canvas");
dom.window.close();
