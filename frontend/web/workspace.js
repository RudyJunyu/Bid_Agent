import { ApiClient } from "./api.js";

const api = new ApiClient();
const $ = (id) => document.getElementById(id);
const state = {
  user: null, auth: false, projects: [], documents: [], jobs: [], projectId: "", selectedJob: "",
  result: null, refreshing: false, requirements: [], requirementsVersionId: "", requirementCategory: "overview",
};
const labels = { queued: "排队中", running: "解析中", retry_wait: "等待重试", succeeded: "已完成", failed: "失败", cancelling: "取消中", cancelled: "已取消" };
const stages = { queued: "等待 Worker 领取", starting: "开始处理", verifying_source: "校验原件", parsing: "解析文档", normalizing: "统一结构", succeeded: "完成", failed: "失败", cancelled: "已取消", cancelling: "等待当前步骤结束", retry_wait: "等待自动重试" };
const categoryLabels = {
  overview: "概览", qualification: "资格", rejection: "废标",
  commercial: "商务", technical: "技术", scoring: "评分",
};
const reviewLabels = { draft: "草稿", confirmed: "已确认", rejected: "已驳回", conflict: "冲突" };
let noticeTimer;

function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}

function notify(message, error = false) {
  clearTimeout(noticeTimer);
  $("notice").textContent = message;
  $("notice").className = `notice${error ? " error" : ""}`;
  $("notice").hidden = false;
  noticeTimer = setTimeout(() => { $("notice").hidden = true; }, error ? 12000 : 6000);
}

function action(text, handler, disabled = false) {
  const button = element("button", text);
  button.type = "button";
  button.disabled = disabled;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await handler(); } catch (error) { handleError(error); }
    finally { button.disabled = disabled; }
  });
  return button;
}

function handleError(error) {
  if (error.status === 401) {
    state.user = null;
    $("workspace").hidden = true;
    $("loginPanel").hidden = false;
  }
  notify(error.message || "请求失败，请检查服务连接", true);
}

function selectedProject() { return state.projects.find((item) => item.id === state.projectId); }
function canEdit() { return state.user?.is_admin || ["owner", "editor"].includes(selectedProject()?.access_role); }
function formatTime(value) { return value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : ""; }
function requestKey() { return globalThis.crypto?.randomUUID?.() || `request-${Date.now()}-${Math.random().toString(36).slice(2)}`; }

async function loadIdentity() {
  state.auth = (await api.request("/auth/status")).enabled;
  const result = await api.request("/auth/me");
  state.user = result.user;
  $("identity").textContent = state.auth ? result.user.username : "本机单用户模式";
  $("logout").hidden = !state.auth;
  $("legacyLink").hidden = !result.user.is_admin;
  $("loginPanel").hidden = true;
  $("workspace").hidden = false;
  await loadProjects();
}

async function loadProjects() {
  state.projects = (await api.request("/v1/projects")).projects;
  $("projectCount").textContent = state.projects.length;
  renderProjects();
  const saved = localStorage.getItem("bid.workspace.project");
  const id = state.projectId || saved;
  if (state.projects.some((item) => item.id === id)) await selectProject(id);
  else if (state.projects.length) await selectProject(state.projects[0].id);
}

function renderProjects() {
  const container = $("projectList");
  container.replaceChildren();
  for (const item of state.projects) {
    const button = action(item.project_name, () => selectProject(item.id));
    button.className = `project-button${item.id === state.projectId ? " active" : ""}`;
    button.append(element("span", `${item.document_count || 0} 份文档 · ${formatTime(item.created_at).split(" ")[0]}`));
    container.append(button);
  }
  if (!state.projects.length) container.append(element("p", "创建项目后即可上传招标原件。", "empty-list"));
}

async function selectProject(id) {
  if (state.projectId !== id) {
    state.selectedJob = "";
    state.result = null;
    state.documents = [];
    state.jobs = [];
    state.requirements = [];
    state.requirementsVersionId = "";
    renderDocuments();
    renderJobs();
    renderRequirements();
    $("resultPanel").hidden = true;
    $("requirementsPanel").hidden = true;
    $("eventsPanel").hidden = true;
  }
  state.projectId = id;
  localStorage.setItem("bid.workspace.project", id);
  $("emptyState").hidden = true;
  $("projectContent").hidden = false;
  $("activeTitle").textContent = selectedProject()?.project_name || "项目";
  $("accessHint").textContent = canEdit() ? "可管理原件、文档版本与解析任务" : "只读成员：可查看文档、原件与解析结果";
  $("membersPanel").hidden = !state.auth || !(state.user?.is_admin || selectedProject()?.access_role === "owner");
  $("uploadButton").disabled = !canEdit();
  renderProjects();
  await refreshProject();
}

async function refreshProject() {
  if (!state.projectId) return;
  const projectId = state.projectId;
  const [documents, jobs] = await Promise.all([
    api.request(`/v1/projects/${projectId}/documents`), api.request(`/v1/projects/${projectId}/jobs`)
  ]);
  if (projectId !== state.projectId) return; // Ignore a response from a previously selected project.
  const documentsChanged = JSON.stringify(state.documents) !== JSON.stringify(documents.documents);
  const jobsChanged = JSON.stringify(state.jobs) !== JSON.stringify(jobs.jobs);
  state.documents = documents.documents;
  state.jobs = jobs.jobs;
  const selected = selectedProject();
  if (selected) selected.document_count = state.documents.length;
  if (documentsChanged) { renderProjects(); renderDocuments(); }
  if (jobsChanged) renderJobs();
  if (state.selectedJob) await viewJob(state.selectedJob, true);
}

function renderDocuments() {
  const container = $("documents");
  container.replaceChildren();
  $("documentCount").textContent = state.documents.length;
  for (const [id, placeholder] of [["targetDocument", "新建文档"], ["parentDocument", "无关联"]]) {
    const select = $(id), previous = select.value;
    select.replaceChildren(new Option(placeholder, ""));
    for (const document of state.documents) select.add(new Option(document.title, document.id));
    select.value = previous;
    if (select.selectedIndex < 0) select.value = "";
  }
  for (const document of state.documents) {
    const card = element("article", "", "document");
    const heading = element("div", "", "document-title");
    heading.append(element("strong", document.title), element("span", { tender: "招标", clarification: "澄清", attachment: "附件" }[document.kind] || document.kind, "badge"));
    card.append(heading);
    if (document.parent_document_id) card.append(element("p", `关联文档：${state.documents.find((item) => item.id === document.parent_document_id)?.title || document.parent_document_id}`, "muted"));
    for (const version of document.versions) {
      const row = element("div", "", "version");
      const info = element("div", `v${version.version} · ${version.file_name}`, "version-info");
      info.append(element("small", `${(version.size_bytes / 1024).toFixed(1)} KB · ${formatTime(version.created_at)} · SHA-256 ${version.sha256.slice(0, 12)}…`));
      const actions = element("div", "", "actions");
      const link = element("a", "下载原件");
      link.href = `${api.base}/v1/document-versions/${version.id}/download`;
      const parsedJob = latestSucceededJobForVersion(version.id);
      actions.append(
        link,
        action("解析此版", () => startParse(version.id), !canEdit()),
        action("要求清单", () => openRequirements(version.id, parsedJob?.id), !parsedJob),
      );
      row.append(info, actions); card.append(row);
    }
    container.append(card);
  }
  if (!state.documents.length) container.append(element("p", "还没有原件。上传后会保留文件与不可覆盖的版本记录。", "empty-list"));
}

function renderJobs() {
  const container = $("jobs");
  container.replaceChildren();
  const active = state.jobs.filter((item) => !["succeeded", "failed", "cancelled"].includes(item.status));
  $("queueState").textContent = active.length ? `${active.length} 项处理中` : "暂无进行中任务";
  for (const job of state.jobs) {
    const row = element("article", "", "job");
    const main = element("div");
    const heading = element("div", "", "job-heading");
    heading.append(element("span", labels[job.status] || job.status, `state state-${job.status}`), element("span", job.id, "job-id"));
    main.append(heading, element("p", `${stages[job.stage] || job.stage} · 已尝试 ${job.attempts} 次 · ${formatTime(job.created_at)}`, "muted"));
    const progress = element("progress"); progress.max = 100; progress.value = job.progress; progress.setAttribute("aria-label", "解析进度"); main.append(progress);
    if (job.error_message) main.append(element("p", job.error_message, "job-error"));
    const actions = element("div", "", "actions");
    actions.append(action(job.status === "succeeded" ? "查看结果" : "查看事件", () => viewJob(job.id)));
    if (["failed", "cancelled"].includes(job.status)) actions.append(action("重试", async () => { await api.request(`/v1/jobs/${job.id}/retry`, { method: "POST" }); await refreshProject(); }, !canEdit()));
    if (["queued", "running", "retry_wait"].includes(job.status)) actions.append(action("取消", async () => { await api.request(`/v1/jobs/${job.id}/cancel`, { method: "POST" }); await refreshProject(); }, !canEdit()));
    row.append(main, actions); container.append(row);
  }
  if (!state.jobs.length) container.append(element("p", "保存原件后点击“解析此版”。任务进度与结果会保存在服务端。", "empty-list"));
}

async function startParse(versionId) {
  const options = { parse_method: $("parseMethod").value, model_version: $("parseMethod").value === "mineru_pipeline" ? "pipeline" : "vlm" };
  const result = await api.request(`/v1/document-versions/${versionId}/parse-jobs`, {
    method: "POST", headers: { "Idempotency-Key": requestKey() }, body: options
  });
  state.selectedJob = result.job.id;
  notify("解析任务已创建。可以离开或刷新页面，任务将在后台继续。");
  await refreshProject();
}

async function viewJob(id, quiet = false) {
  const projectId = state.projectId;
  state.selectedJob = id;
  const [job, history] = await Promise.all([api.request(`/v1/jobs/${id}`), api.request(`/v1/jobs/${id}/events`)]);
  if (projectId !== state.projectId || state.selectedJob !== id) return;
  $("eventsPanel").hidden = false;
  $("events").replaceChildren(...history.events.map((event) => element("li", `${formatTime(event.created_at)} · ${labels[event.payload.status] || event.event_type}${event.payload.stage ? " · " + (stages[event.payload.stage] || event.payload.stage) : ""}${event.payload.message ? " · " + event.payload.message : ""}`)));
    if (job.status === "succeeded") {
    if (state.result?.jobId !== id) {
      const result = await api.request(`/v1/jobs/${id}/result`);
      if (projectId !== state.projectId || state.selectedJob !== id) return;
      state.result = { ...result, jobId: id };
      renderResult();
      await loadRequirements(result.document_version_id, true);
    } else {
      $("requirementsPanel").hidden = false;
    }
    $("resultPanel").hidden = false;
    if (!quiet) $("resultPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (job.status !== "succeeded") {
    $("resultPanel").hidden = true;
    $("requirementsPanel").hidden = true;
  }
}

function latestSucceededJobForVersion(versionId) {
  return state.jobs.find((job) => job.document_version_id === versionId && job.status === "succeeded");
}

async function openRequirements(versionId, jobId) {
  if (jobId) await viewJob(jobId, true);
  else if (state.result?.document_version_id !== versionId) {
    notify("请先完成该版本的解析，再打开要求清单", true);
    return;
  }
  await loadRequirements(versionId);
  $("requirementsPanel").hidden = false;
  $("requirementsPanel").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadRequirements(versionId, quiet = false) {
  if (!versionId) return;
  const projectId = state.projectId;
  const data = await api.request(`/v1/document-versions/${versionId}/requirements`);
  if (projectId !== state.projectId) return;
  state.requirementsVersionId = versionId;
  state.requirements = data.items || [];
  renderRequirements();
  $("requirementsPanel").hidden = false;
  if (!quiet && !state.requirements.length) {
    notify("尚无要求草稿。有编辑权限时可点「抽取／刷新」。");
  }
}

function filteredRequirements() {
  if (state.requirementCategory === "all") return state.requirements;
  return state.requirements.filter((item) => item.category === state.requirementCategory);
}

function renderRequirements() {
  const panel = $("requirementsPanel");
  if (!state.requirementsVersionId) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("extractRequirements").disabled = !canEdit();
  const counts = {};
  for (const item of state.requirements) counts[item.category] = (counts[item.category] || 0) + 1;
  const extractor = state.requirements[0]?.extractor_version || "";
  $("requirementsInfo").textContent = `${state.requirementsVersionId} · ${extractor || "未抽取"} · 共 ${state.requirements.length} 条 · 当前分类 ${filteredRequirements().length} 条`;
  const filters = $("requirementFilters");
  filters.replaceChildren();
  const tabs = [["overview", "概览"], ["qualification", "资格"], ["rejection", "废标"], ["commercial", "商务"], ["technical", "技术"], ["scoring", "评分"], ["all", "全部"]];
  for (const [key, label] of tabs) {
    const count = key === "all" ? state.requirements.length : (counts[key] || 0);
    const button = action(`${label} ${count}`, () => {
      state.requirementCategory = key;
      renderRequirements();
    });
    button.className = state.requirementCategory === key ? "active" : "";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", state.requirementCategory === key ? "true" : "false");
    filters.append(button);
  }
  const container = $("requirements");
  container.replaceChildren();
  const rows = filteredRequirements();
  if (!rows.length) {
    container.append(element("p", canEdit() ? "此分类暂无条目。可切换分类，或点击「抽取／刷新」。" : "此分类暂无条目。", "empty-list"));
    return;
  }
  for (const item of rows) container.append(renderRequirementCard(item));
}

function renderRequirementCard(item) {
  const card = element("article", "", "requirement");
  const top = element("div", "", "requirement-top");
  const title = element("div", "", "requirement-title");
  title.textContent = item.field_key ? `${item.title}（${item.field_key}）` : item.title;
  const meta = element("div", "", "requirement-meta");
  meta.append(
    element("span", categoryLabels[item.category] || item.category, "badge"),
    element("span", reviewLabels[item.review_status] || item.review_status, `state state-${item.review_status}`),
    element("span", `置信 ${(Number(item.confidence || 0) * 100).toFixed(0)}%`, "badge"),
  );
  top.append(title, meta);
  card.append(top);
  const valueText = item.normalized_value || item.raw_text || "";
  card.append(element("div", valueText.slice(0, 1200) + (valueText.length > 1200 ? "…" : ""), "requirement-value"));
  const ref = (item.source_refs || [])[0];
  if (ref) {
    const evidence = element("div", "", "requirement-evidence");
    const path = (ref.section_path || []).filter(Boolean).join(" / ");
    evidence.textContent = `证据${ref.page ? ` · 第 ${ref.page} 页` : ""}${path ? ` · ${path}` : ""}\n${ref.quote || ""}`;
    card.append(evidence);
  }
  const editor = document.createElement("textarea");
  editor.className = "requirement-edit";
  editor.value = item.normalized_value || item.raw_text || "";
  editor.rows = 3;
  editor.disabled = !canEdit() || item.review_status === "confirmed";
  editor.setAttribute("aria-label", `修正 ${item.title}`);
  card.append(editor);
  const actions = element("div", "", "actions");
  if (ref) actions.append(action("跳到原文", () => jumpToEvidence(item)));
  if (canEdit()) {
    if (item.review_status !== "confirmed") {
      actions.append(action("确认", async () => {
        await reviewRequirement(item.id, "confirmed", editor.value.trim());
      }));
    }
    if (item.review_status !== "rejected") {
      actions.append(action("驳回", async () => {
        await reviewRequirement(item.id, "rejected", editor.value.trim());
      }));
    }
    if (item.review_status !== "draft") {
      actions.append(action("恢复草稿", async () => {
        await reviewRequirement(item.id, "draft", editor.value.trim());
      }));
    }
  }
  card.append(actions);
  return card;
}

async function reviewRequirement(itemId, reviewStatus, normalizedValue) {
  await api.request(`/v1/requirements/${itemId}/review`, {
    method: "POST",
    body: { review_status: reviewStatus, normalized_value: normalizedValue || null },
  });
  notify(reviewStatus === "confirmed" ? "已确认该要求" : reviewStatus === "rejected" ? "已驳回该要求" : "已恢复为草稿");
  await loadRequirements(state.requirementsVersionId, true);
}

function jumpToEvidence(item) {
  const ref = (item.source_refs || [])[0];
  if (!ref) {
    notify("该条目没有可定位证据", true);
    return;
  }
  if ($("resultPanel").hidden) {
    notify("请先打开解析结果，再跳转原文", true);
    return;
  }
  const sections = [...$("sections").querySelectorAll("details")];
  let target = null;
  if (ref.section_index) {
    target = sections.find((node) => node.dataset.sectionIndex === String(ref.section_index))
      || sections[ref.section_index - 1]
      || null;
  }
  if (!target && ref.section_path?.length) {
    const title = String(ref.section_path[ref.section_path.length - 1] || "");
    target = sections.find((node) => (node.querySelector("summary")?.textContent || "").includes(title)) || null;
  }
  if (!target && ref.quote) {
    const needle = String(ref.quote).slice(0, 24);
    target = sections.find((node) => (node.textContent || "").includes(needle)) || null;
  }
  if (!target) {
    notify(`未定位到原文${ref.page ? `（约第 ${ref.page} 页）` : ""}`, true);
    return;
  }
  for (const node of sections) node.classList.remove("evidence-flash");
  target.open = true;
  target.classList.add("evidence-flash");
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  $("resultPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderResult() {
  const result = state.result;
  $("resultPanel").hidden = false;
  $("resultInfo").textContent = `${result.parse_method} · ${result.sections.length} 个章节 · ${result.document_version_id}`;
  $("resultWarnings").hidden = !result.warnings.length;
  $("resultWarnings").textContent = result.warnings.join("\n");
  $("reviewResult").hidden = !state.user?.is_admin;
  $("sections").replaceChildren(...result.sections.map((section, index) => {
    const details = element("details"); details.open = index === 0;
    details.dataset.sectionIndex = String(section.index || index + 1);
    details.append(element("summary", section.title || `章节 ${index + 1}`), element("pre", section.markdown || section.content));
    return details;
  }));
  $("structuredResult").textContent = JSON.stringify(result, null, 2);
}

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await api.request("/auth/login", { method: "POST", body: { username: $("username").value, password: $("password").value } }); $("password").value = ""; await loadIdentity(); }
  catch (error) { handleError(error); }
});
$("logout").addEventListener("click", async () => { try { await api.request("/auth/logout", { method: "POST" }); location.reload(); } catch (error) { handleError(error); } });
$("projectForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const created = await api.request("/v1/projects", { method: "POST", body: { title: $("projectTitle").value.trim() } });
    state.projectId = ""; state.selectedJob = ""; state.result = null;
    state.requirements = []; state.requirementsVersionId = "";
    localStorage.setItem("bid.workspace.project", created.id);
    $("resultPanel").hidden = true; $("requirementsPanel").hidden = true; $("eventsPanel").hidden = true;
    $("projectTitle").value = ""; await loadProjects();
  }
  catch (error) { handleError(error); }
});
$("extractRequirements").addEventListener("click", async () => {
  const versionId = state.requirementsVersionId || state.result?.document_version_id;
  if (!versionId) return notify("请先打开已解析版本的结果", true);
  $("extractRequirements").disabled = true;
  try {
    const body = {
      use_llm: Boolean($("useLlmRefine").checked),
      llm_vendor: "siliconflow",
      llm_model: "Qwen3-8B (轻量)",
    };
    if (state.result?.jobId && state.result.document_version_id === versionId) body.job_id = state.result.jobId;
    const data = await api.request(`/v1/document-versions/${versionId}/requirements/extract`, {
      method: "POST", body,
    });
    state.requirementsVersionId = versionId;
    state.requirements = data.items || [];
    renderRequirements();
    const mode = data.use_llm ? "规则+LLM" : "规则";
    notify(`已抽取 ${state.requirements.length} 条（${mode} · ${data.extractor_version || "rule"}）`);
    $("requirementsPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { handleError(error); }
  finally { $("extractRequirements").disabled = !canEdit(); }
});
$("reloadRequirements").addEventListener("click", () => {
  const versionId = state.requirementsVersionId || state.result?.document_version_id;
  if (!versionId) return notify("请先打开已解析版本", true);
  loadRequirements(versionId).catch(handleError);
});
$("memberForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await api.request(`/v1/projects/${state.projectId}/members`, { method: "POST", body: { username: $("memberName").value.trim(), role: $("memberRole").value } }); notify("项目成员权限已保存"); }
  catch (error) { handleError(error); }
});
$("uploadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = $("documentFile").files[0];
  if (!file || !state.projectId) return;
  const projectId = state.projectId;
  const data = new FormData(); data.append("file", file); data.append("kind", $("documentKind").value);
  if ($("targetDocument").value) data.append("document_id", $("targetDocument").value);
  if ($("parentDocument").value) data.append("parent_document_id", $("parentDocument").value);
  $("uploadButton").disabled = true;
  try {
    const result = await api.request(`/v1/projects/${projectId}/documents`, { method: "POST", body: data });
    if (projectId !== state.projectId) { notify("原件已保存到原项目"); return; }
    notify(result.created ? `原件已保存为 v${result.version.version}` : "相同内容已存在，已复用原版本");
    $("documentFile").value = "";
    if ($("parseAfterUpload").checked) await startParse(result.version.id); else await refreshProject();
  } catch (error) { handleError(error); }
  finally { $("uploadButton").disabled = !canEdit(); }
});
$("parseAfterUpload").addEventListener("change", () => { $("uploadButton").textContent = $("parseAfterUpload").checked ? "保存原件并解析" : "保存原件"; });
$("refresh").addEventListener("click", () => refreshProject().catch(handleError));
$("exportMarkdown").addEventListener("click", () => {
  if (!state.result) return;
  const url = URL.createObjectURL(new Blob([state.result.markdown], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = `${state.result.document_version_id}.md`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("reviewResult").addEventListener("click", () => {
  if (!state.result) return;
  // Store only a durable job reference; large results stay on the server.
  location.href = `./index.html?parseJob=${encodeURIComponent(state.result.jobId)}`;
});
setInterval(async () => {
  if (!state.user || !state.projectId || state.refreshing || document.hidden) return;
  state.refreshing = true;
  try { await refreshProject(); } catch (error) { handleError(error); }
  finally { state.refreshing = false; }
}, 3000);
loadIdentity().catch(handleError);
