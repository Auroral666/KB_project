"use strict";

// Each container owns its network and source selection; no global chat state is used.
window.KnowledgeGraph = (() => {
  const records = new WeakMap();

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function destroy(container) {
    const state = records.get(container);
    state?.network?.destroy();
    records.delete(container);
    container.replaceChildren();
    container.removeAttribute("aria-busy");
    container.classList.remove("knowledge-graph");
  }

  function prepare(container) {
    destroy(container);
    container.classList.add("knowledge-graph");
  }

  function message(container, text, error = false) {
    const status = element("p", "knowledge-graph-status", text);
    status.setAttribute("role", error ? "alert" : "status");
    container.append(status);
  }

  function loading(container) {
    prepare(container);
    container.setAttribute("aria-busy", "true");
    message(container, "正在加载本次回答的关系图谱…");
  }

  function sources(items) {
    const unique = new Map();
    for (const source of items) {
      if (!source || typeof source.doc_id !== "string" || !source.doc_id) continue;
      const key = JSON.stringify([source.doc_id, source.page, source.chunk, source.content]);
      if (!unique.has(key)) unique.set(key, source);
    }
    return [...unique.values()];
  }

  function render(container, graph, onSourceClick) {
    prepare(container);
    if (graph?.error) {
      message(container, typeof graph.error === "string" ? graph.error : "图谱暂时不可用。", true);
      return;
    }
    const nodes = new Map();
    for (const node of Array.isArray(graph?.nodes) ? graph.nodes : []) {
      if (node && typeof node.id === "string" && typeof node.label === "string") nodes.set(node.id, node);
    }
    const edges = (Array.isArray(graph?.edges) ? graph.edges : []).filter(edge =>
      edge && typeof edge.id === "string" && typeof edge.label === "string" &&
      nodes.has(edge.from) && nodes.has(edge.to));
    if (!nodes.size) {
      message(container, "本次回答没有可展示的关系图谱。");
      return;
    }

    const header = element("div", "knowledge-graph-heading");
    header.append(element("strong", "", "本次回答的关系图谱"),
      element("span", "knowledge-graph-count", `${nodes.size} 个实体 · ${edges.length} 条关系`));
    container.append(header);
    const canvas = element("div", "knowledge-graph-canvas");
    canvas.setAttribute("aria-label", "可拖动缩放的关系图；也可使用下方关系列表查看来源");
    canvas.setAttribute("role", "img");
    const selection = element("div", "knowledge-graph-selection");
    selection.setAttribute("aria-live", "polite");

    function showSources(label, items) {
      selection.replaceChildren(element("strong", "knowledge-graph-selection-title", label));
      const references = sources(items);
      if (!references.length) {
        selection.append(element("p", "knowledge-graph-hint", "此实体或关系没有可打开的原文来源。"));
        return;
      }
      references.forEach(source => {
        const row = element("div", "knowledge-graph-source");
        const button = element("button", "knowledge-graph-source-button",
          `${source.name || "原文"}${source.page > 0 ? ` · 第 ${source.page} 页` : ""} · 片段 ${source.chunk || 0}`);
        button.type = "button";
        button.disabled = typeof onSourceClick !== "function";
        button.addEventListener("click", () => onSourceClick(source));
        row.append(button);
        if (source.content) row.append(element("p", "knowledge-graph-quotation", String(source.content)));
        selection.append(row);
      });
    }

    const details = element("details", "knowledge-graph-relations");
    details.append(element("summary", "", "查看关系与原文来源"));
    const list = element("div", "knowledge-graph-relation-list");
    edges.forEach(edge => {
      const label = `${nodes.get(edge.from).label} → ${edge.label} → ${nodes.get(edge.to).label}`;
      const button = element("button", "knowledge-graph-relation", label);
      button.type = "button";
      button.addEventListener("click", () => showSources(label, Array.isArray(edge.sources) ? edge.sources : []));
      list.append(button);
    });
    if (!edges.length) list.append(element("p", "knowledge-graph-hint", "暂未抽取到实体之间的关系。"));
    details.append(list);
    container.append(canvas, details, selection);

    if (typeof window.vis?.Network !== "function") {
      canvas.hidden = true;
      message(container, "图谱绘制组件未加载，可通过关系列表查看来源。", true);
      details.open = true;
      return;
    }
    let network;
    try {
      network = new window.vis.Network(canvas, {
        nodes: [...nodes.values()].map(node => ({id: node.id, label: node.label})),
        edges: edges.map(edge => ({id: edge.id, from: edge.from, to: edge.to, label: edge.label, arrows: "to"}))
      }, {
        autoResize: true,
        layout: {randomSeed: 17, improvedLayout: true},
        nodes: {shape: "dot", size: 16, color: {background: "#edf3ff", border: "#7d9ed9"},
          font: {face: "Microsoft YaHei, Segoe UI, sans-serif", color: "#415c85", size: 13, multi: false}},
        edges: {color: {color: "#9aaccc", highlight: "#4179e8"}, smooth: {type: "dynamic"},
          font: {face: "Microsoft YaHei, Segoe UI, sans-serif", color: "#687e9d", size: 11, multi: false}},
        physics: {stabilization: {iterations: 120}, barnesHut: {gravitationalConstant: -2800}},
        interaction: {hover: true, keyboard: false, navigationButtons: false}
      });
      records.set(container, {network});
      network.on("click", event => {
        // Vis may include connected edge IDs when a node is selected.
        const node = nodes.get(event.nodes?.[0]);
        if (node) {
          const related = edges.filter(item => item.from === node.id || item.to === node.id);
          showSources(node.label, [...(Array.isArray(node.sources) ? node.sources : []),
            ...related.flatMap(item => Array.isArray(item.sources) ? item.sources : [])]);
          return;
        }
        const edge = edges.find(item => item.id === event.edges?.[0]);
        if (edge) {
          showSources(`${nodes.get(edge.from).label} → ${edge.label} → ${nodes.get(edge.to).label}`,
            Array.isArray(edge.sources) ? edge.sources : []);
        }
      });
      network.on("resize", () => window.requestAnimationFrame(() => {
        if (records.get(container)?.network === network) network.fit({animation: false});
      }));
      network.once("stabilizationIterationsDone", () => {
        network.setOptions({physics: false});
        network.fit({animation: false});
      });
    } catch (error) {
      network?.destroy();
      records.delete(container);
      canvas.hidden = true;
      details.open = true;
      message(container, "图谱绘制失败，可通过关系列表查看来源。", true);
    }
    selection.append(element("p", "knowledge-graph-hint", "点击实体或关系查看依据；拖动节点调整位置，滚轮缩放。"));
  }

  return Object.freeze({render, destroy, loading});
})();
