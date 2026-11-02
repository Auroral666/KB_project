"use strict";

// The complete reply is parsed as Markdown, then sanitized before entering the DOM.
window.KnowledgeMarkdown = Object.freeze({
  render(text) {
    if (!window.marked || !window.DOMPurify) throw new Error("回复渲染组件未加载，请刷新页面重试。");
    const html = window.marked.parse(String(text ?? ""), {gfm:true, breaks:false, async:false});
    return window.DOMPurify.sanitize(html, {
      ALLOWED_TAGS:["p","br","h1","h2","h3","h4","h5","h6","strong","em","del","s",
        "ul","ol","li","blockquote","pre","code","table","thead","tbody","tfoot","tr","th","td",
        "a","hr","span","sup","sub","details","summary"],
      ALLOWED_ATTR:["href","title","class","align","start","colspan","rowspan"],
      ALLOW_DATA_ATTR:false,
      ALLOW_ARIA_ATTR:false
    });
  }
});
