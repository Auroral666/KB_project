"use strict";

// Each reply owns its source numbers; [1] in another reply may refer to a different document.
window.KnowledgeSources = (() => {
  const records = new WeakMap();
  const $ = selector => document.querySelector(selector);
  let currentMessage = null;
  let activeIndex = -1;
  let returnFocus = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function label(source) {
    return `${source.page > 0 ? `第 ${source.page} 页 · ` : ""}片段 ${source.chunk}`;
  }

  function sourceButton(source, index, compact = false) {
    const button = element("button", compact ? "citation-link" : "source-reference");
    button.type = "button";
    button.dataset.sourceIndex = index;
    button.title = `${source.name} · ${label(source)}`;
    button.setAttribute("aria-label", `查看引用 [${index+1}]：${source.name}，${label(source)}`);
    button.append(element("span", "citation-number", `[${index+1}]`));
    if (!compact) {
      button.append(element("span", "reference-file-name", source.name));
      button.append(element("span", "reference-fragment-label", label(source)));
    }
    return button;
  }

  function indexes(value, length) {
    const values = [];
    for (const part of value.split(/[,，、]/)) {
      const bounds = part.trim().split(/[-–—]/).map(Number);
      const [start, end = start] = bounds;
      if (start < 1 || end < start || end > length || !Number.isInteger(start) || !Number.isInteger(end)) return [];
      for (let i = start; i <= end; i++) values.push(i-1);
    }
    return [...new Set(values)];
  }

  function enhance(message) {
    const sources = records.get(message) || [];
    const content = message.querySelector(".message-content");
    if (!content || !sources.length) return;
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) {
      if (!walker.currentNode.parentElement.closest("a,button,pre,code")) textNodes.push(walker.currentNode);
    }
    for (const node of textNodes) {
      const pattern = /\[\s*(\d+(?:\s*[,，、\-–—]\s*\d+)*)\s*\]/g;
      const fragment = document.createDocumentFragment();
      let start = 0, changed = false;
      for (const match of node.textContent.matchAll(pattern)) {
        const matches = indexes(match[1], sources.length);
        if (!matches.length) continue;
        fragment.append(document.createTextNode(node.textContent.slice(start,match.index)));
        for (const index of matches) fragment.append(sourceButton(sources[index],index,true));
        start = match.index + match[0].length;
        changed = true;
      }
      if (changed) {
        fragment.append(document.createTextNode(node.textContent.slice(start)));
        node.replaceWith(fragment);
      }
    }
    highlightLinks();
  }

  function register(message, sources) {
    records.set(message, Array.isArray(sources) ? sources : []);
    enhance(message);
  }

  function references(sources) {
    const list = element("div", "message-source-list");
    sources.forEach((source,index) => list.append(sourceButton(source,index)));
    return list;
  }

  function groups(sources) {
    const map = new Map();
    sources.forEach((source,index) => {
      const key = source.doc_id || `name:${source.name}`;
      if (!map.has(key)) map.set(key,{key,name:source.name,docId:source.doc_id,items:[]});
      map.get(key).items.push({source,index});
    });
    return [...map.values()];
  }

  function highlightLinks() {
    document.querySelectorAll("#chat-messages [data-source-index].active").forEach(node => node.classList.remove("active"));
    currentMessage?.querySelectorAll(`[data-source-index="${activeIndex}"]`).forEach(node => node.classList.add("active"));
  }

  function showDocument(group) {
    $("#source-document-name").textContent = group.name;
    $("#source-document-name").title = group.name;
    const download = $("#source-download");
    download.hidden = !/^[a-f0-9]{32}$/.test(group.docId || "");
    if (!download.hidden) download.href = `/api/documents/${group.docId}/download`;
    else download.removeAttribute("href");
    const source = group.items.find(item => item.index === activeIndex).source;
    window.OriginalDocumentReader.open(group,source);
  }

  function open(message, index, trigger = null) {
    const sources = records.get(message) || [];
    if (!Number.isInteger(index) || index < 0 || index >= sources.length) return;
    currentMessage = message;
    activeIndex = index;
    if (trigger) returnFocus = trigger;
    const documents = groups(sources);
    const selectedGroup = documents.find(group => group.items.some(item => item.index === index));
    $("#source-document-count").textContent = `${documents.length} 份文档`;
    const tabs = $("#source-document-tabs");
    tabs.replaceChildren();
    for (const group of documents) {
      const button = element("button",`document-tab${group === selectedGroup ? " selected" : ""}`);
      button.type = "button";
      button.title = group.name;
      button.setAttribute("role","tab");
      button.setAttribute("aria-selected",String(group === selectedGroup));
      button.setAttribute("aria-controls","source-document");
      button.tabIndex = group === selectedGroup ? 0 : -1;
      button.append(element("span","document-tab-icon",(group.name.split(".").pop() || "DOC").slice(0,4).toUpperCase()),element("span","document-tab-name",group.name));
      button.addEventListener("click", () => open(message,group.items[0].index));
      button.addEventListener("keydown",event => {
        if (!["ArrowRight","ArrowLeft","Home","End"].includes(event.key)) return;
        event.preventDefault();
        const pos = documents.indexOf(group);
        const next = event.key === "Home" ? 0 : event.key === "End" ? documents.length-1 : (pos+(event.key === "ArrowRight" ? 1 : -1)+documents.length)%documents.length;
        open(message,documents[next].items[0].index);
        tabs.children[next].focus();
      });
      tabs.append(button);
    }
    $(".chat-layout").classList.remove("history-open");
    $(".chat-layout").classList.add("source-open");
    $("#chat-context-default").hidden = true;
    $("#source-reader").hidden = false;
    $("#source-backdrop").hidden = false;
    showDocument(selectedGroup);
    highlightLinks();
    if (trigger && window.matchMedia("(max-width: 1000px)").matches) $("#close-source-reader").focus({preventScroll:true});
  }

  function close() {
    window.OriginalDocumentReader.close();
    $(".chat-layout").classList.remove("source-open","history-open");
    $("#chat-context-default").hidden = false;
    $("#source-reader").hidden = true;
    $("#source-backdrop").hidden = true;
    currentMessage = null;
    activeIndex = -1;
    highlightLinks();
    if (returnFocus?.isConnected) returnFocus.focus({preventScroll:true});
    returnFocus = null;
  }

  function initialize() {
    window.OriginalDocumentReader.initialize();
    $("#chat-messages").addEventListener("click",event => {
      const target = event.target.closest("[data-source-index]");
      if (!target) return;
      const message = target.closest(".assistant-message");
      if (message) open(message,Number(target.dataset.sourceIndex),target);
    });
    $("#close-source-reader").addEventListener("click",close);
    $("#close-chat-context").addEventListener("click",close);
    $("#source-backdrop").addEventListener("click",close);
    $("#show-chat-context").addEventListener("click",event => {
      close();
      returnFocus = event.currentTarget;
      $(".chat-layout").classList.add("history-open");
      $("#source-backdrop").hidden = false;
      $("#close-chat-context").focus({preventScroll:true});
    });
    document.addEventListener("keydown",event => {
      if (event.key === "Escape" && $(".chat-layout").matches(".source-open,.history-open") && !document.querySelector("dialog[open]")) close();
    });
  }

  return Object.freeze({initialize,register,enhance,references,close});
})();
