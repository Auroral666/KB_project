"use strict";

// This viewer always loads the complete original file. Source quotations only locate text.
window.OriginalDocumentReader = (() => {
  const $ = selector => document.querySelector(selector);
  const cache = new Map();
  let pdfLibrary = null, state = null, version = 0, renderTask = null, resizeTimer = null;

  function node(tag,cls,text) {
    const item = document.createElement(tag);
    if (cls) item.className = cls;
    if (text != null) item.textContent = text;
    return item;
  }

  async function library() {
    if (!pdfLibrary) pdfLibrary = import("/static/vendor/pdfjs/build/pdf.mjs?v=6.4.299").then(pdf => {
      pdf.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/build/pdf.worker.mjs?v=6.4.299";
      return pdf;
    }).catch(error => { pdfLibrary=null; throw error; });
    return pdfLibrary;
  }

  function status(message) { $("#source-document-info").textContent = message; }

  function busy(value) {
    $("#original-toolbar").setAttribute("aria-busy",String(value));
    $("#original-prev").disabled = value || !state || state.page <= 1;
    $("#original-next").disabled = value || !state || state.page >= state.total;
    $("#original-page").disabled = value || !state;
    $("#original-zoom").disabled = value || !state || state.kind !== "pdf";
    $("#original-jump").disabled = value || !state;
  }

  function loading() {
    $("#source-fragments").replaceChildren(node("div","original-loading","正在加载完整原文…"));
    status("正在读取原始文件");
    busy(true);
  }

  async function load(group) {
    const key = group.docId;
    if (!/^[a-f0-9]{32}$/.test(key || "")) throw new Error("此引用缺少原始文件标识，无法打开原文。");
    if (!cache.has(key)) {
      const promise = (async () => {
        const response = await fetch(`/api/documents/${key}/original`);
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(typeof error.detail === "string" ? error.detail : "原始文件无法读取，请下载文件查看。");
        }
        if ((response.headers.get("content-type") || "").includes("application/pdf")) {
          const pdf = await library();
          const data = new Uint8Array(await response.arrayBuffer());
          const document = await pdf.getDocument({data,isEvalSupported:false,
            cMapUrl:"/static/vendor/pdfjs/cmaps/",cMapPacked:true,
            standardFontDataUrl:"/static/vendor/pdfjs/standard_fonts/",
            wasmUrl:"/static/vendor/pdfjs/wasm/"}).promise;
          return {kind:"pdf",document,total:document.numPages};
        }
        const data = await response.json();
        return {kind:"text",pages:data.pages,total:data.pages.length};
      })().catch(error => { cache.delete(key); throw error; });
      cache.set(key,promise);
      // Retain at most three complete documents in the browser.
      if (cache.size > 3) {
        const oldest = cache.keys().next().value;
        const old = cache.get(oldest);
        cache.delete(oldest);
        old.then(value => value.document?.destroy()).catch(() => {});
      }
    }
    return cache.get(key);
  }

  function controls() {
    $("#original-page").value = state.page;
    $("#original-page").max = state.total;
    $("#original-total").textContent = `/ ${state.total}`;
    $("#original-zoom").value = state.zoom;
  }

  function positionAt(mark) {
    const scroll = $("#source-fragments");
    if (!mark) { scroll.scrollTop=0; scroll.scrollLeft=0; return; }
    const rect = mark.getBoundingClientRect(), box = scroll.getBoundingClientRect();
    scroll.scrollTo({top:Math.max(0,scroll.scrollTop+rect.top-box.top-48),
      left:Math.max(0,scroll.scrollLeft+rect.left-box.left-25),behavior:"auto"});
  }

  async function draw(pageNumber,locate=false,token=version) {
    if (!state || token !== version) return;
    const current = state;
    const container = $("#source-fragments");
    current.page = Math.max(1,Math.min(current.total,Math.trunc(Number(pageNumber))||1));
    controls();
    busy(true);
    renderTask?.cancel();
    renderTask = null;
    container.replaceChildren();
    let textRoot;
    if (current.kind === "pdf") {
      const pdf = await library();
      const page = await current.document.getPage(current.page);
      if (token !== version) return;
      const original = page.getViewport({scale:1});
      const scale = current.zoom === "fit" ? Math.max(.2,(container.clientWidth-24)/original.width) : Number(current.zoom);
      const viewport = page.getViewport({scale});
      const paper = node("div","original-pdf-page");
      paper.dataset.pageNumber = current.page;
      paper.style.width = `${viewport.width}px`;
      paper.style.height = `${viewport.height}px`;
      paper.style.setProperty("--total-scale-factor",String(viewport.scale));
      paper.style.setProperty("--scale-factor",String(viewport.scale));
      paper.style.setProperty("--scale-round-x","1px");
      paper.style.setProperty("--scale-round-y","1px");
      const canvas = node("canvas","");
      canvas.setAttribute("aria-label",`原始 PDF 第 ${current.page} 页`);
      const ratio = Math.min(2,window.devicePixelRatio||1);
      canvas.width = Math.ceil(viewport.width*ratio);
      canvas.height = Math.ceil(viewport.height*ratio);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      textRoot = node("div","textLayer original-pdf-text");
      paper.append(canvas,textRoot);
      container.append(paper);
      renderTask = page.render({canvasContext:canvas.getContext("2d"),viewport,
        transform:ratio === 1 ? null : [ratio,0,0,ratio,0,0]});
      await renderTask.promise;
      if (token !== version) return;
      const text = await page.getTextContent();
      if (token !== version) return;
      await new pdf.TextLayer({textContentSource:text,container:textRoot,viewport}).render();
    } else {
      textRoot = node("article","original-full-text",current.pages[current.page-1].text);
      textRoot.dataset.pageNumber = current.page;
      container.append(textRoot);
    }
    if (token !== version) return;
    let match = null;
    if (locate && current.source?.content) match = window.OriginalTextLocator.highlight(textRoot,current.source.content);
    const description = current.kind === "pdf" ? `原始 PDF · 共 ${current.total} 页` : "完整原文 · 文本模式";
    status(`${description} · 第 ${current.page} 页${locate ? match?.marks.length ? match.exact ? " · 已定位引用" : " · 已定位匹配文字" : " · 未匹配到引用文字" : ""}`);
    container.dataset.pageNumber = current.page;
    container.dataset.documentId = current.docId;
    container.dataset.located = String(Boolean(match?.marks.length));
    busy(false);
    requestAnimationFrame(() => { if (token === version) positionAt(match?.marks[0]); });
  }

  async function safelyDraw(page,locate) {
    const token = ++version;
    try { await draw(page,locate,token); }
    catch (error) { if (token === version && error.name !== "RenderingCancelledException") failure(error); }
  }

  function failure(error) {
    busy(false);
    status("原文预览失败");
    $("#source-fragments").replaceChildren(node("p","original-error",error.message || "原文无法打开，请下载文件查看。"));
  }

  async function open(group,source) {
    const token = ++version;
    renderTask?.cancel();
    state = null;
    $("#original-toolbar").hidden = false;
    loading();
    try {
      const loaded = await load(group);
      if (token !== version) return;
      state = {...loaded,docId:group.docId,source,zoom:"fit",page:1};
      state.targetPage = Math.max(1,Math.min(state.total,Number(source.page)||1));
      await draw(state.targetPage,true,token);
    } catch (error) { if (token === version && error.name !== "RenderingCancelledException") failure(error); }
  }

  function close() { version++; renderTask?.cancel(); renderTask=null; state=null; }

  function initialize() {
    $("#original-prev").addEventListener("click", () => safelyDraw(state.page-1,false));
    $("#original-next").addEventListener("click", () => safelyDraw(state.page+1,false));
    $("#original-page").addEventListener("change",event => safelyDraw(event.target.value,false));
    $("#original-page").addEventListener("keydown",event => { if (event.key === "Enter") { event.preventDefault(); safelyDraw(event.target.value,false); } });
    $("#original-zoom").addEventListener("change",event => { if (state) {state.zoom=event.target.value; safelyDraw(state.page,state.page===state.targetPage);} });
    $("#original-jump").addEventListener("click", () => safelyDraw(state.targetPage,true));
    let width = 0;
    new ResizeObserver(entries => {
      const current = entries[0].contentRect.width;
      if (Math.abs(current-width)>1 && current>0 && state?.kind === "pdf" && state.zoom === "fit") {
        clearTimeout(resizeTimer);
        resizeTimer=setTimeout(() => { if (state) safelyDraw(state.page,state.page===state.targetPage); },120);
      }
      width=current;
    }).observe($("#source-fragments"));
  }
  return Object.freeze({initialize,open,close});
})();
