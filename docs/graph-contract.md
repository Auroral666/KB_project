# 局部图谱组件

组件只展示本次回答的证据关系，不主动请求数据库、不保存会话。先加载本地 Vis Network standalone（`window.vis.Network`），再加载 `/static/js/knowledge-graph.js`；样式为 `/static/css/knowledge-graph.css`。

```javascript
KnowledgeGraph.loading(container);
KnowledgeGraph.render(container, {
  nodes: [
    {id: "alpha", label: "Alpha 项目"},
    {id: "team", label: "研发部"},
    {id: "person", label: "张明"}
  ],
  edges: [
    {id: "r1", from: "alpha", to: "team", label: "负责部门", sources: [sourceA]},
    {id: "r2", from: "team", to: "person", label: "主管", sources: [sourceB]}
  ]
}, source => openOriginal(source));
// 移除消息或切换会话之前释放 canvas 与事件监听。
KnowledgeGraph.destroy(container);
```

`id/from/to/label` 为字符串，实体和关系 ID 各自唯一。`sources` 使用现有引用格式 `{doc_id,name,page,chunk,content}`：`page` 为 1 起始页码或 0（未知），`chunk` 为 1 起始片段号，`content` 是原文依据。节点可选提供 `sources`；点击节点也会收集其所有关联边的来源。边的两个端点必须存在。

原文回调必须连接现有原文阅读器并保留正确的消息引用映射。组件返回原始来源对象，不自行拼接文件路径或 URL。图谱不能替代问答引用核对。

无节点时显示空状态；`{error:"原因"}` 显示错误状态。缺少 Vis 或 canvas 构造失败时明确提示，仍提供可用的关系列表和原文按钮。所有服务端文字通过 `textContent` 或纯文本 canvas label 展示；不传 Vis 的 HTML tooltip。

## 验证

```powershell
node tests/test_knowledge_graph.cjs
```

沿用 `temp/dev-tools/node_modules/jsdom`，覆盖状态转换、关系和节点来源选择、多文档与来源去重、XSS 字面文字、网络销毁、独立消息、空数据和依赖失败。该测试 stub Vis canvas API，不确认真实 canvas 绘制。

浏览器验收样例使用上面两个跨文档关系：A 文档包含“Alpha 项目由研发部负责”，B 文档包含“研发部主管为张明”；以实际上传返回的 `doc_id` 构造两个 `source`。应显示三节点两条有向边；点击“研发部”可查看两文档来源；点击任一来源应打开对应完整原文并定位；关系列表可使用 Tab/Enter 操作。在宽屏和 390px 宽窗口分别检查拖动、滚轮缩放、来源面板和长文件名；切换会话再返回应无重复 canvas。
