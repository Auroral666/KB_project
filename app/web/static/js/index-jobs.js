"use strict";

window.KnowledgeJobs = (() => {
  const stages = ["waiting","semantic_chunking","extracting_relations","writing_vectors","writing_graph","complete"];
  const labels = ["等待处理","语义分块","抽取关系","写入向量","写入图谱","完成"];
  const states = {queued:"排队中",running:"处理中",succeeded:"已完成",failed:"处理失败"};
  function node(tag, cls, text) {
    const el = document.createElement(tag);
    el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }
  function render(container, jobs) {
    container.className = "panel index-jobs-panel";
    container.setAttribute("aria-label","后台建库任务");
    const heading = node("div","panel-heading");
    const title = node("div","");
    title.append(node("h2","","后台建库任务"),node("p","","查看文档处理阶段与结果；无关系的文档仍可用于知识问答。"));
    const active = jobs.filter(j => ["queued","running"].includes(j.status)).length;
    heading.append(title,node("span","jobs-summary",active ? `${active} 个任务处理中` : "全部任务已结束"));
    const list = node("div","index-jobs-list");
    list.setAttribute("role","list");
    if (!jobs.length) list.append(node("p","jobs-empty","暂无建库任务，上传文档后会在这里显示处理进度。"));
    for (const job of jobs.slice(0,10)) {
      const state = Object.hasOwn(states,job.status) ? job.status : "queued";
      const row = node("article",`index-job job-${state}`);
      row.setAttribute("role","listitem");
      const top = node("div","index-job-top");
      const name = node("strong","index-job-name",job.name);
      name.title = job.name;
      top.append(name,node("span",`job-status job-status-${state}`,states[state]));
      const stage = stages.indexOf(job.stage);
      row.append(top,node("p","index-job-meta",`任务 ${job.id.slice(0,8)} · ${job.updated_at ? new Date(job.updated_at).toLocaleString("zh-CN",{timeZone:"Asia/Shanghai",hour12:false}) : "等待更新"}`));
      if (state === "running" || state === "queued") {
        const steps = node("ol","job-steps");
        steps.setAttribute("aria-label",`当前阶段：${labels[stage] || "等待处理"}`);
        labels.forEach((label,i) => {
          const step = node("li",i < stage ? "done" : i === stage ? "current" : "",label);
          if (i === stage) step.setAttribute("aria-current","step");
          steps.append(step);
        });
        row.append(steps);
      } else {
        row.append(node("p",`index-job-result ${state === "failed" ? "job-error" : ""}`,
          state === "failed" ? job.error || "处理失败，请检查服务后重新上传。" : "文档已收录，可用于知识问答。"));
      }
      list.append(row);
    }
    container.replaceChildren(heading,list);
  }
  return Object.freeze({render});
})();
