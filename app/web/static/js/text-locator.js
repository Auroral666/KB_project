"use strict";

window.OriginalTextLocator = (() => {
  const normalize = value => String(value ?? "").normalize("NFKC").replace(/[\s\u00ad\u200b\ufeff]/g,"");

  function find(text, quotation) {
    const query = normalize(quotation);
    if (!query) return {ranges:[],exact:false};
    const position = text.indexOf(query);
    if (position >= 0) return {ranges:[[position,position+query.length]],exact:true};
    // Different PDF extractors can order table cells differently. Match real spans,
    // never insert the quotation into the document when it cannot be found.
    if (query.length < 16) return {ranges:[],exact:false};
    const matches = [];
    for (let i=0; i<query.length; i+=24) {
      let size = Math.min(72,query.length-i);
      while (size >= 16) {
        const at = text.indexOf(query.slice(i,i+size));
        if (at >= 0) { matches.push([at,at+size]); break; }
        size = Math.floor(size/2);
      }
    }
    matches.sort((a,b) => a[0]-b[0]);
    const ranges = [];
    for (const match of matches) {
      const last = ranges[ranges.length-1];
      if (last && match[0] <= last[1]) last[1] = Math.max(last[1],match[1]);
      else ranges.push([...match]);
    }
    return {ranges,exact:false};
  }

  function highlight(container, quotation) {
    container.querySelectorAll("mark.original-highlight").forEach(mark => mark.replaceWith(...mark.childNodes));
    container.normalize();
    const walker = document.createTreeWalker(container,NodeFilter.SHOW_TEXT);
    const positions = [];
    let text = "";
    while (walker.nextNode()) {
      const node = walker.currentNode;
      let offset = 0;
      for (const character of node.textContent) {
        const normalized = normalize(character);
        for (let i=0; i<normalized.length; i++) positions.push({node,start:offset,end:offset+character.length});
        text += normalized;
        offset += character.length;
      }
    }
    const match = find(text,quotation);
    const byNode = new Map();
    for (const [start,end] of match.ranges) {
      for (let i=start; i<end; i++) {
        const point = positions[i];
        if (!byNode.has(point.node)) byNode.set(point.node,[]);
        const list = byNode.get(point.node), last = list[list.length-1];
        if (last && point.start <= last[1]) last[1] = Math.max(last[1],point.end);
        else list.push([point.start,point.end]);
      }
    }
    for (const [node,ranges] of byNode) {
      const fragment = document.createDocumentFragment();
      let start = 0;
      for (const [from,to] of ranges) {
        fragment.append(document.createTextNode(node.textContent.slice(start,from)));
        const mark = document.createElement("mark");
        mark.className = "original-highlight";
        mark.textContent = node.textContent.slice(from,to);
        fragment.append(mark);
        start = to;
      }
      fragment.append(document.createTextNode(node.textContent.slice(start)));
      node.replaceWith(fragment);
    }
    return {...match,marks:container.querySelectorAll("mark.original-highlight")};
  }
  return Object.freeze({normalize,find,highlight});
})();
