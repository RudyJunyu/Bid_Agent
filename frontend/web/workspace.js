import { ApiClient } from "./api.js";

const api = new ApiClient();
const $ = (id) => document.getElementById(id);
const state = { user: null, auth: false, projects: [], documents: [], jobs: [], projectId: "", selectedJob: "", result: null, refreshing: false };
const labels = { queued: "排队中", running: "解析中", retry_wait: "等待重试", succeeded: "已完成", failed: "失败", cancelling: "取消中", cancelled: "已取消" };
const stages = { queued: "等待 Worker 领取", starting: "开始处理", verifying_source: "校验原件", parsing: "解析文档", normalizing: "统一结构", succeeded: "完成", failed: "失败", cancelled: "已取消", cancelling: "等待当前步骤结束", retry_wait: "等待自动重试" };
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
    renderDocuments();
    renderJobs();
    $("resultPanel").hidden = true;
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
      actions.append(link, action("解析此版", () => startParse(version.id), !canEdit()));
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
    }
    $("resultPanel").hidden = false;
    if (!quiet) $("resultPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (job.status !== "succeeded") {
    $("resultPanel").hidden = true;
  }
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
    localStorage.setItem("bid.workspace.project", created.id);
    $("resultPanel").hidden = true; $("eventsPanel").hidden = true;
    $("projectTitle").value = ""; await loadProjects();
  }
  catch (error) { handleError(error); }
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
