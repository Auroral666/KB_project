"use strict";

const $ = (selector) => document.querySelector(selector);
const page = document.body.dataset.page;
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon = (name, cls = "") => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const number = value => Number(value || 0).toLocaleString("zh-CN");
const size = bytes => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
const duration = ms => ms == null ? "—" : (ms / 1000).toFixed(1);
const formatDate = value => value ? new Intl.DateTimeFormat("zh-CN", {month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hour12:false, timeZone:"Asia/Shanghai"}).format(new Date(value)) : "";
let workspace = null;
let selectedDays = 7;
let sessionId = new URLSearchParams(location.search).get("session") || null;
let sending = false;
let uploading = false;

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { throw new Error("服务响应异常，请刷新页面重试。"); }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请求未完成，请检查输入后重试。");
  return data;
}

function toast(message, error = false) {
  const item = document.createElement("div");
  item.className = `toast${error ? " error" : ""}`;
  item.innerHTML = icon(error ? "close" : "check") + `<span>${escapeHTML(message)}</span>`;
  $("#toast-region").append(item);
  setTimeout(() => item.remove(), error ? 9000 : 5500);
}

function empty(message, action = "") {
  return `<div class="empty-state">${icon("book")}<div>${escapeHTML(message)}</div>${action}</div>`;
}

function stat(label, value, unit, note, symbol) {
  return `<article class="stat-card"><div class="stat-top"><span>${label}</span><span class="stat-icon">${icon(symbol)}</span></div><div class="stat-value">${value}<span class="stat-unit">${unit}</span></div><div class="stat-note">${note}</div></article>`;
}

function fileBadge(doc) {
  const ext = doc.extension.replace(".", "");
  return `<span class="file-badge ${escapeHTML(ext)}">${escapeHTML(ext.toUpperCase())}</span>`;
}

function documentRow(doc, simple = false) {
  return `<div class="doc-row">${fileBadge(doc)}<div class="doc-info"><a class="doc-name" href="/api/documents/${doc.id}/download" title="${escapeHTML(doc.name)}">${escapeHTML(doc.name)}</a><small>${size(doc.size)} · ${number(doc.chunks)} 个片段</small></div>${simple ? "" : `<span class="doc-meta">${formatDate(doc.created_at)}</span><span class="indexed">已收录</span>`}</div>`;
}

function renderChart(target, trend) {
  if (!target) return;
  const width = 600, height = 180, left = 26, right = 16, top = 15, bottom = 26;
  const max = Math.max(2, ...trend.map(d => d.questions));
  const x = i => left + i * (width - left - right) / Math.max(1, trend.length - 1);
  const y = v => height - bottom - v * (height - top - bottom) / max;
  const points = trend.map((d, i) => [x(i), y(d.questions)]);
  const line = points.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" ");
  const hasData = trend.some(d => d.questions > 0);
  const labelStep = Math.max(1, Math.ceil(trend.length / 7));
  const grid = [0, max / 2, max].map(value => `<line x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}" stroke="#edf1f6" stroke-dasharray="3 4"/><text x="0" y="${y(value)+3}" class="chart-label">${Number.isInteger(value) ? value : value.toFixed(1)}</text>`).join("");
  const labels = trend.map((d, i) => i % labelStep === 0 || i === trend.length-1 ? `<text x="${x(i)}" y="${height-5}" text-anchor="middle" class="chart-label">${d.day.slice(5).replace("-","/")}</text>` : "").join("");
  const dots = trend.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.questions)}" r="${trend.length > 7 ? 2.5 : 3.5}" fill="#7199e5" stroke="white" stroke-width="2"><title>${d.day}：${d.questions} 次提问，${d.answered} 次有资料回答</title></circle>`).join("");
  target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="近 ${trend.length} 天共 ${trend.reduce((sum,d) => sum+d.questions,0)} 次提问"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#83a7ee" stop-opacity=".18"/><stop offset="1" stop-color="#83a7ee" stop-opacity=".01"/></linearGradient></defs>${grid}<path d="${line} L${x(trend.length-1)},${y(0)} L${x(0)},${y(0)} Z" fill="url(#chart-fill)"/><path d="${line}" fill="none" stroke="#7199e5" stroke-width="2" vector-effect="non-scaling-stroke"/>${dots}${labels}</svg>${hasData ? "" : '<span class="chart-empty">还没有问答记录，开始对话后会在这里留下轨迹</span>'}`;
}

function renderOverview() {
  const {summary:s, documents:docs, trend} = workspace;
  $("#overview-stats").innerHTML = stat("已收录文档",number(s.documents),"份","你的个人知识积累","file") + stat("知识片段",number(s.chunks),"段","可检索的文档内容","layers") + stat("近 7 天提问",number(s.questions),"次","每一次好奇都有迹可循","chat") + stat("平均回答耗时",duration(s.avg_duration_ms),"秒","统计有资料回答的完整耗时","clock");
  renderChart($("#activity-chart"), trend);
  const steps = [["file","文档收录","保留原始资料",`${s.documents} 份文档`,s.documents],["layers","知识索引","将内容组织为可检索的片段",`${s.chunks} 个片段`,s.chunks],["search","检索与回答","从相关原文中生成答案",`${s.answered} 次回答`,s.answered]];
  $("#pipeline").innerHTML = steps.map(([symbol,name,note,value,ready]) => `<div class="pipeline-row"><span class="pipeline-step">${icon(symbol)}</span><div class="pipeline-name">${name}<small>${note}</small></div><span class="pipeline-status ${ready ? "ready" : ""}">${value}</span></div>`).join("");
  $("#recent-documents").innerHTML = docs.length ? docs.slice(0,3).map(doc => documentRow(doc)).join("") : empty("知识空间已准备好，从第一份文档开始。",'<a href="/knowledge">添加你的第一份文档 →</a>');
}

function renderLibrary() {
  const s = workspace.summary;
  $("#library-stats").innerHTML = stat("文档总数",number(s.documents),"份","构建属于你的知识空间","file") + stat("知识片段",number(s.chunks),"段","保留上下文的内容切片","layers") + stat("文档占用",size(s.storage_bytes).split(" ")[0],size(s.storage_bytes).split(" ")[1],"原始文件总大小","book");
  $("#document-count").textContent = number(s.documents);
  filterDocuments();
}

function filterDocuments() {
  const search = $("#document-search").value.trim().toLocaleLowerCase();
  const type = $("#type-filter").value;
  const docs = workspace.documents.filter(d => d.name.toLocaleLowerCase().includes(search) && (type === "all" || d.extension === type));
  $("#document-list").innerHTML = docs.length ? `<table class="document-table"><thead><tr><th>文档名称</th><th>知识片段</th><th>收录时间</th><th>状态</th><th>操作</th></tr></thead><tbody>${docs.map(d => `<tr><td><div class="table-doc">${fileBadge(d)}<div class="doc-info"><a class="doc-name" href="/api/documents/${d.id}/download" title="${escapeHTML(d.name)}">${escapeHTML(d.name)}</a><small>${size(d.size)}</small></div></div></td><td>${number(d.chunks)} 段</td><td>${formatDate(d.created_at)}</td><td><span class="indexed">已收录</span></td><td><a href="/api/documents/${d.id}/download" class="icon-button" aria-label="下载 ${escapeHTML(d.name)}">${icon("down")}</a><button class="icon-button danger" data-delete="${d.id}" aria-label="移除 ${escapeHTML(d.name)}">${icon("trash")}</button></td></tr>`).join("")}</tbody></table>` : empty(workspace.documents.length ? "没有找到匹配的文档，试试其他名称或文件类型。" : "这里还没有文档，上传资料后即可开始问答。");
  $("#clear-library").disabled = !workspace.documents.length || uploading;
  document.querySelectorAll("[data-delete]").forEach(button => {
    button.disabled = uploading;
    button.addEventListener("click", () => deleteDocument(button.dataset.delete));
  });
}

function sourceCards(sources) {
  return sources.map((s,i) => `<details class="source-item"><summary>${icon("file")}<span class="source-title">[${i+1}] ${escapeHTML(s.name)}</span><span>${s.page > 0 ? `第 ${s.page} 页 · ` : ""}片段 ${s.chunk}</span></summary><div class="source-body"><p>${escapeHTML(s.content)}</p><div class="source-meta">向量距离 ${s.distance} · 数值越小，语义越接近</div>${/^[a-f0-9]{32}$/.test(s.doc_id) ? `<a class="text-link" href="/api/documents/${s.doc_id}/download">下载原始文档 ↗</a>` : ""}</div></details>`).join("");
}

function renderInsights() {
  const s = workspace.summary;
  const rate = s.questions ? Math.round(s.with_sources / s.questions * 100) : null;
  $("#insight-stats").innerHTML = stat("累计知识片段",number(s.chunks),"段","当前知识库可检索内容","layers") + stat(`近 ${selectedDays} 天提问`,number(s.questions),"次","当前周期内完成的问答请求","chat") + stat("资料命中率",rate == null ? "—" : rate,"%","有检索资料的问答 / 完成的问答","search") + stat("平均回答耗时",duration(s.avg_duration_ms),"秒","含检索与回答生成时间","clock");
  renderChart($("#insight-chart"), workspace.trend);
  const types = [[".pdf","PDF","#779be0"],[".docx","Word","#9bb6de"],[".txt","TXT","#8ab7ae"],[".md","Markdown","#bdcce2"]].map(([ext,label,color]) => ({label,color,count:workspace.documents.filter(d => d.extension === ext).length}));
  let percent = 0;
  const slices = types.filter(t => t.count).map(t => { const start = percent; percent += t.count / s.documents * 100; return `${t.color} ${start}% ${percent}%`; });
  $("#document-composition").innerHTML = `<div class="composition"><div class="donut" style="background:${slices.length ? `conic-gradient(${slices.join(",")})` : "#edf1f6"}" role="img" aria-label="${types.map(t => `${t.label} ${t.count} 份`).join("，")}"><div class="donut-center">${s.documents}<small>文档总数</small></div></div><div class="type-legend">${types.map(t => `<span><i style="background:${t.color}"></i>${t.label} <b>${t.count}</b></span>`).join("")}</div></div>`;
  $("#query-records").innerHTML = workspace.recent.length ? workspace.recent.map(m => `<details class="query-row"><summary><span class="query-title">${escapeHTML(m.question)}</span><span class="indexed">${m.sources.length ? `${m.sources.length} 条资料` : "未命中资料"}</span><small>${duration(m.duration_ms)} 秒</small><small>${formatDate(m.created_at)}</small></summary><div class="query-details"><div class="timings"><span>检索 ${duration(m.retrieval_ms)} 秒</span><span>总耗时 ${duration(m.duration_ms)} 秒</span><span>${m.status === "answered" ? "已根据资料回答" : "资料不足"}</span></div><div class="answer-preview markdown-body">${formatAnswer(m.answer)}</div>${sourceCards(m.sources)}<a class="text-link" style="margin-top:14px" href="/chat?session=${m.session_id}">打开这段对话 →</a></div></details>`).join("") : empty("暂无问答记录。完成一次知识库问答后，可在这里查看检索过程。",'<a href="/chat">开始提问 →</a>');
}

function formatAnswer(text) {
  return window.KnowledgeMarkdown.render(text);
}

function appendMessage(role, text, record = null) {
  $("#chat-welcome")?.remove();
  const message = document.createElement("article");
  message.className = `chat-message ${role}-message`;
  message.innerHTML = `<div class="message-heading"><span class="message-avatar">${role === "user" ? "K" : icon("spark")}</span>${role === "user" ? "你" : "知屿助手"}</div><div class="message-content ${role === "user" ? "" : "markdown-body"}">${role === "user" ? escapeHTML(text) : formatAnswer(text)}</div>`;
  if (record) appendAnswerDetails(message, record);
  $("#chat-messages").append(message);
  scrollChat();
  return message;
}

function appendAnswerDetails(message, record) {
  const details = document.createElement("div");
  details.className = "answer-details";
  details.innerHTML = `<div class="message-timing">${record.sources.length ? `参考 ${record.sources.length} 条原文` : "未检索到相关资料"}${record.first_token_ms != null ? ` · 首字 ${duration(record.first_token_ms)} 秒` : ""} · 总耗时 ${duration(record.duration_ms)} 秒</div>`;
  if (record.sources.length) {
    const sources = document.createElement("div");
    sources.className = "message-sources";
    const caption = document.createElement("small");
    caption.textContent = "引用来源 · 点击在右侧查看";
    sources.append(caption,window.KnowledgeSources.references(record.sources));
    details.append(sources);
  }
  message.append(details);
  window.KnowledgeSources.register(message,record.sources);
}

async function consumeAnswerStream(question, id, onEvent) {
  const response = await fetch("/rag/chat/stream/", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({question,session_id:id})
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : "请求未完成，请稍后重试。");
  }
  if (!response.body) throw new Error("浏览器不支持流式回答，请更新浏览器后重试。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", result = null;
  const processFrame = frame => {
    const raw = frame.split("\n").filter(line => line.startsWith("data: ")).map(line => line.slice(6)).join("\n");
    if (!raw) return;
    const event = JSON.parse(raw);
    if (event.type === "error") throw new Error(event.message);
    if (event.type === "done") result = event;
    onEvent(event);
  };
  try {
    while (true) {
      const {value,done} = await reader.read();
      buffer += decoder.decode(value, {stream:!done}).replace(/\r\n/g,"\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        processFrame(buffer.slice(0,boundary));
        buffer = buffer.slice(boundary+2);
      }
      if (done) break;
    }
    if (buffer.trim()) processFrame(buffer);
    if (!result) throw new Error("连接已中断，回答尚未完成，请重新发送。");
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

function scrollChat() {
  const box = $("#chat-messages");
  box.scrollTop = box.scrollHeight;
}

function renderChatDocuments() {
  $("#chat-documents").innerHTML = workspace.documents.length ? workspace.documents.slice(0,4).map(d => documentRow(d, true)).join("") : empty("先添加文档，让回答有据可依。");
}

async function loadSessions() {
  const data = await api("/api/sessions");
  $("#session-list").innerHTML = data.sessions.length ? data.sessions.map(s => `<button class="session-button ${s.id === sessionId ? "current" : ""}" data-session="${s.id}"><strong>${escapeHTML(s.title)}</strong><small>${s.count} 次提问 · ${formatDate(s.updated_at || s.created_at)}</small></button>`).join("") : '<div class="empty-state" style="font-size:10px;padding:16px">每一次对话都会自动保存在这里。</div>';
  document.querySelectorAll("[data-session]").forEach(button => {
    button.disabled = sending;
    button.addEventListener("click", () => loadConversation(button.dataset.session).catch(e => toast(e.message,true)));
  });
}

async function loadConversation(id) {
  if (sending) return;
  const data = await api(`/api/sessions/${encodeURIComponent(id)}`);
  if (!data.messages.length) { toast("没有找到这段对话。", true); return; }
  sessionId = id;
  history.replaceState(null,"",`/chat?session=${id}`);
  window.KnowledgeSources.close();
  $("#chat-messages").innerHTML = "";
  data.messages.forEach(m => { appendMessage("user",m.question); appendMessage("assistant",m.answer,m); });
  await loadSessions();
}

async function sendQuestion(event) {
  event.preventDefault();
  const question = $("#question").value.trim();
  if (!question || sending) return;
  sending = true;
  $("#send-message").disabled = true;
  $("#new-chat").disabled = true;
  $("#question").disabled = true;
  $("#composer-hint").textContent = "正在检索资料并整理回答…";
  document.querySelectorAll("[data-session]").forEach(button => button.disabled = true);
  appendMessage("user",question);
  $("#question").value = "";
  window.KnowledgeSources.close();
  const pending = appendMessage("assistant","");
  pending.querySelector(".message-content").innerHTML = '<span class="typing" aria-label="正在整理回答"><i></i><i></i><i></i></span>';
  scrollChat();
  let answerText = "";
  let lastRender = 0;
  try {
    const result = await consumeAnswerStream(question,sessionId,event => {
      if (event.type === "status") $("#composer-hint").textContent = event.message;
      if (event.type === "sources") {
        $("#composer-hint").textContent = "正在生成回答…";
        window.KnowledgeSources.register(pending,event.sources);
      }
      if (event.type === "delta") {
        answerText += event.text;
        const now = performance.now();
        if (now-lastRender > 45 || answerText === event.text) {
          pending.querySelector(".message-content").innerHTML = formatAnswer(answerText);
          window.KnowledgeSources.enhance(pending);
          lastRender = now;
          scrollChat();
        }
      }
    });
    pending.querySelector(".message-content").innerHTML = formatAnswer(result.answer);
    appendAnswerDetails(pending,result);
    scrollChat();
    sessionId = result.session_id;
    history.replaceState(null,"",`/chat?session=${sessionId}`);
  } catch (error) {
    pending.querySelector(".message-content").innerHTML = (answerText ? formatAnswer(answerText) : "") + `<div class="${answerText ? "partial-answer-note" : "error-message"}">${escapeHTML(error.message)}<br>${answerText ? "以上为未完成的回答，尚未保存。" : ""}问题已保留在输入框，可以重新发送。</div>`;
    window.KnowledgeSources.enhance(pending);
    $("#question").value = question;
    scrollChat();
  } finally {
    sending = false;
    $("#send-message").disabled = false;
    $("#new-chat").disabled = false;
    $("#question").disabled = false;
    $("#composer-hint").textContent = "Enter 发送 · Shift + Enter 换行";
    $("#question").focus();
    await loadSessions().catch(error => toast(error.message,true));
    checkService();
  }
}

function confirmAction(title, message, label) {
  return new Promise(resolve => {
    const dialog = $("#confirm-dialog");
    $("#confirm-title").textContent = title;
    $("#confirm-message").textContent = message;
    $("#confirm-action").textContent = label;
    dialog.returnValue = "cancel";
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), {once:true});
    dialog.showModal();
  });
}

async function deleteDocument(id) {
  if (uploading) return;
  const doc = workspace.documents.find(d => d.id === id);
  if (!doc) return;
  if (!await confirmAction("移除这份文档？",`将移除「${doc.name}」及其知识片段。已有对话记录会保留；如需恢复，请重新上传文档。`,"确认移除")) return;
  try { const result = await api(`/api/documents/${id}`,{method:"DELETE"}); toast(result.message); await refreshWorkspace(); }
  catch (error) { toast(error.message,true); }
}

async function clearLibrary() {
  if (uploading || !workspace.documents.length) return;
  if (!await confirmAction("清空当前知识库？",`将移除当前工作空间的 ${workspace.documents.length} 份文档及其全部知识片段。对话记录仍会保留。如需恢复，请重新上传原始文档。`,"确认清空")) return;
  try { const result = await api("/rag/clear/",{method:"POST"}); toast(result.message); await refreshWorkspace(); }
  catch (error) { toast(error.message,true); }
}

async function uploadFiles(files) {
  if (uploading || !files.length) return;
  uploading = true;
  $("#upload-progress").hidden = false;
  document.querySelectorAll("[data-upload], [data-delete], #clear-library").forEach(button => button.disabled = true);
  try {
    for (const file of files) {
      if (!/\.(pdf|docx|txt|md)$/i.test(file.name)) { toast(`${file.name}：不支持此文件格式。`,true); continue; }
      if (!file.size || file.size > 20 * 1024 * 1024) { toast(`${file.name}：请选择非空且不超过 20 MB 的文件。`,true); continue; }
      $("#upload-label").textContent = `正在收录：${file.name}`;
      const form = new FormData();
      form.append("file",file);
      try { const result = await api("/rag/create/",{method:"POST",body:form}); toast(result.message); }
      catch (error) { toast(`${file.name}：${error.message}`,true); }
    }
  } finally {
    uploading = false;
    $("#upload-progress").hidden = true;
    $("#file-input").value = "";
    document.querySelectorAll("[data-upload]").forEach(button => button.disabled = false);
    await refreshWorkspace().catch(error => toast(error.message,true));
    checkService();
  }
}

async function refreshWorkspace() {
  const requestedDays = selectedDays;
  const result = await api(`/api/overview?days=${requestedDays}`);
  if (requestedDays !== selectedDays) return;
  workspace = result;
  $("#nav-doc-count").textContent = number(workspace.summary.documents);
  if (page === "/") renderOverview();
  if (page === "/knowledge") renderLibrary();
  if (page === "/insights") renderInsights();
  if (page === "/chat") renderChatDocuments();
}

async function checkService() {
  try {
    const state = await api("/api/status");
    const connected = state.database && state.model_configured;
    $("#service-dot").classList.toggle("offline",!connected);
    $("#service-label").textContent = !state.database ? "向量服务暂未连接" : state.warming ? "正在准备检索模型" : !state.model_configured ? "请配置问答模型" : "知识服务已连接";
    if (state.warming) setTimeout(checkService,2000);
  } catch {
    $("#service-dot").classList.add("offline");
    $("#service-label").textContent = "工作空间暂未连接";
  }
}

async function initialize() {
  $("#header-date").textContent = new Intl.DateTimeFormat("zh-CN",{year:"numeric",month:"2-digit",day:"2-digit",timeZone:"Asia/Shanghai"}).format(new Date()).replaceAll("/",".");
  document.querySelectorAll("[data-upload]").forEach(button => button.addEventListener("click", () => { if (!uploading) $("#file-input").click(); }));
  $("#file-input").addEventListener("change",event => uploadFiles(Array.from(event.target.files)));
  if (page === "/knowledge") {
    $("#document-search").addEventListener("input",filterDocuments);
    $("#type-filter").addEventListener("change",filterDocuments);
    $("#clear-library").addEventListener("click",clearLibrary);
    const zone = $("#drop-zone");
    ["dragenter","dragover"].forEach(name => zone.addEventListener(name,event => { event.preventDefault(); zone.classList.add("dragover"); }));
    ["dragleave","drop"].forEach(name => zone.addEventListener(name,event => { event.preventDefault(); zone.classList.remove("dragover"); }));
    zone.addEventListener("drop",event => uploadFiles(Array.from(event.dataTransfer.files)));
  }
  if (page === "/insights") document.querySelectorAll("[data-days]").forEach(button => button.addEventListener("click",async () => {
    selectedDays = Number(button.dataset.days);
    document.querySelectorAll("[data-days]").forEach(b => b.classList.toggle("selected",b === button));
    await refreshWorkspace().catch(error => toast(error.message,true));
  }));
  if (page === "/chat") {
    window.KnowledgeSources.initialize();
    $("#chat-form").addEventListener("submit",sendQuestion);
    $("#question").addEventListener("keydown",event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("#chat-form").requestSubmit(); } });
    document.querySelectorAll("[data-prompt]").forEach(button => button.addEventListener("click", () => { $("#question").value = button.dataset.prompt; $("#question").focus(); }));
    $("#new-chat").addEventListener("click", () => { if (!sending) location.href = "/chat"; });
  }
  await Promise.all([refreshWorkspace(),checkService()]);
  if (page === "/chat") {
    await loadSessions();
    if (sessionId) await loadConversation(sessionId);
  }
}

initialize().catch(error => toast(error.message,true));
