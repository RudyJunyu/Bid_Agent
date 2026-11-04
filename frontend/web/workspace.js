import { ApiClient } from "./api.js";

const api = new ApiClient();
const $ = (id) => document.getElementById(id);
const state = {
  user: null, auth: false, projects: [], documents: [], jobs: [], projectId: "", selectedJob: "",
  result: null, refreshing: false, requirements: [], requirementsVersionId: "", requirementCategory: "overview",
  stages: [], bidVersions: [], selectedBidId: "", selectedSections: [], selectedSectionId: "",
  matrixRows: [], matrixSummary: null, matrixMissing: [], findings: [], reviewReadiness: null,
  reviewRuns: [], auditLogs: [], findingFilter: "open", projectAssets: [], expiredAssets: [], exports: [],
};
const assetCategoryLabels = {
  qualification: "资质", personnel: "人员", financial: "财务", performance: "业绩",
  case: "案例", template: "模板", other: "其他",
};
const assetStatusLabels = {
  draft: "草稿", pending_review: "待核实", active: "有效", expired: "过期", disabled: "停用",
};
const labels = { queued: "排队中", running: "解析中", retry_wait: "等待重试", succeeded: "已完成", failed: "失败", cancelling: "取消中", cancelled: "已取消" };
const stages = { queued: "等待 Worker 领取", starting: "开始处理", verifying_source: "校验原件", parsing: "解析文档", normalizing: "统一结构", succeeded: "完成", failed: "失败", cancelled: "已取消", cancelling: "等待当前步骤结束", retry_wait: "等待自动重试" };
const categoryLabels = {
  overview: "概览", qualification: "资格", rejection: "废标",
  commercial: "商务", technical: "技术", scoring: "评分",
};
const reviewLabels = { draft: "草稿", confirmed: "已确认", rejected: "已驳回", conflict: "冲突" };
const matrixStatusLabels = {
  uncovered: "未覆盖", mapped: "已映射", drafted: "有草稿",
  responded: "已响应", waived: "豁免", missing_material: "缺材料",
};
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
    state.stages = [];
    state.bidVersions = [];
    state.selectedBidId = "";
    state.selectedSections = [];
    state.selectedSectionId = "";
    state.matrixRows = [];
    state.matrixSummary = null;
    state.matrixMissing = [];
    state.findings = [];
    state.reviewReadiness = null;
    state.reviewRuns = [];
    state.auditLogs = [];
    state.projectAssets = [];
    state.expiredAssets = [];
    state.exports = [];
    renderDocuments();
    renderJobs();
    renderRequirements();
    renderAssets();
    renderStages();
    renderBids();
    renderSectionEditor();
    renderMatrix();
    renderFindings();
    renderExports();
    $("resultPanel").hidden = true;
    $("requirementsPanel").hidden = true;
    $("assetsPanel").hidden = true;
    $("pipelinePanel").hidden = true;
    $("outlinePanel").hidden = true;
    $("sectionsPanel").hidden = true;
    $("matrixPanel").hidden = true;
    $("reviewPanel").hidden = true;
    $("exportPanel").hidden = true;
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
  await loadPipeline(true);
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
    state.stages = []; state.bidVersions = []; state.selectedBidId = "";
    state.findings = []; state.exports = [];
    localStorage.setItem("bid.workspace.project", created.id);
    $("resultPanel").hidden = true; $("requirementsPanel").hidden = true; $("eventsPanel").hidden = true;
    $("pipelinePanel").hidden = true; $("outlinePanel").hidden = true;
    $("reviewPanel").hidden = true; $("exportPanel").hidden = true;
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

async function loadPipeline(quiet = false) {
  if (!state.projectId) return;
  const projectId = state.projectId;
  const [stages, bids, findings, runs, projectAssets, exports] = await Promise.all([
    api.request(`/v1/projects/${projectId}/stages`),
    api.request(`/v1/projects/${projectId}/bid-versions`),
    api.request(`/v1/projects/${projectId}/review-findings`),
    api.request(`/v1/projects/${projectId}/review-runs`),
    api.request(`/v1/projects/${projectId}/assets`),
    api.request(`/v1/projects/${projectId}/exports`),
  ]);
  if (projectId !== state.projectId) return;
  state.stages = stages.stages || [];
  state.reviewReadiness = stages.review_readiness || findings.readiness || null;
  state.bidVersions = bids.bid_versions || [];
  if (!state.selectedBidId && state.bidVersions.length) state.selectedBidId = state.bidVersions[0].id;
  state.findings = findings.findings || [];
  state.reviewRuns = runs.runs || [];
  state.projectAssets = projectAssets.assets || [];
  state.expiredAssets = projectAssets.expired || [];
  state.exports = exports.exports || [];
  $("assetsPanel").hidden = false;
  $("pipelinePanel").hidden = false;
  $("outlinePanel").hidden = false;
  $("sectionsPanel").hidden = false;
  $("matrixPanel").hidden = false;
  $("reviewPanel").hidden = false;
  $("exportPanel").hidden = false;
  renderAssets();
  renderStages();
  renderBids();
  await loadSelectedBidSections(quiet);
  await loadMatrix(true);
  renderFindings();
  renderExports();
  await loadExportTemplates();
  if (!quiet) notify("已刷新资产、阶段、目录、章节、矩阵、审查与导出");
}

function renderAssets() {
  const list = $("assetList");
  const expiredBox = $("assetExpired");
  if (!list || !expiredBox) return;
  list.replaceChildren();
  expiredBox.replaceChildren();
  $("createAsset").disabled = !canEdit();
  const usable = state.projectAssets.filter((item) => item.usable).length;
  $("assetsInfo").textContent = `本项目关联 ${state.projectAssets.length} 项 · 可用 ${usable} · 过期 ${state.expiredAssets.length}（过期不可用于生成）`;
  if (state.expiredAssets.length) {
    expiredBox.append(element("h3", "过期／不可用关联资产"));
    for (const item of state.expiredAssets.slice(0, 10)) {
      const card = element("article", "", "asset-item expired");
      card.append(element("div", `${item.title} · 到期 ${item.expires_on || "-"}`));
      expiredBox.append(card);
    }
  }
  for (const item of state.projectAssets) {
    const card = element("article", "", `asset-item${item.usable ? "" : " expired"}`);
    card.append(element("div", item.title || "资产", "matrix-title"));
    const meta = element("div", "", "matrix-meta");
    meta.append(element("span", assetCategoryLabels[item.category] || item.category, "badge"));
    meta.append(element("span", assetStatusLabels[item.status] || item.status, `state state-${item.usable ? "confirmed" : "rejected"}`));
    meta.append(element("span", item.usable ? "可用于生成" : "不可用于生成", "muted"));
    if (item.expires_on) meta.append(element("span", `到期 ${item.expires_on}`, "muted"));
    card.append(meta);
    if (item.latest_version) {
      const link = element("a", `附件 v${item.latest_version.version} · ${item.latest_version.file_name}`);
      link.href = `${api.base}/v1/enterprise-asset-versions/${item.latest_version.id}/download`;
      card.append(link);
    } else {
      card.append(element("div", "尚无附件版本", "muted"));
    }
    if (canEdit()) {
      const actions = element("div", "", "actions");
      if (item.status === "draft" || item.status === "pending_review") {
        actions.append(action("标为有效", async () => {
          await api.request(`/v1/enterprise-assets/${item.id}`, {
            method: "PATCH", body: { status: "active" },
          });
          await loadPipeline(true);
        }));
      }
      actions.append(action("取消关联", async () => {
        await api.request(`/v1/projects/${state.projectId}/assets/${item.id}`, { method: "DELETE" });
        notify("已取消关联");
        await loadPipeline(true);
      }));
      card.append(actions);
    }
    list.append(card);
  }
  if (!state.projectAssets.length) list.append(element("p", "尚未关联企业资产。可在上方创建并关联。", "empty-list"));
}

async function loadMatrix(quiet = true) {
  if (!state.selectedBidId) {
    state.matrixRows = [];
    state.matrixSummary = null;
    state.matrixMissing = [];
    renderMatrix();
    return;
  }
  try {
    const data = await api.request(`/v1/bid-versions/${state.selectedBidId}/response-matrix`);
    state.matrixRows = data.rows || [];
    state.matrixSummary = data.summary || null;
    state.matrixMissing = data.missing_materials || [];
  } catch (error) {
    if (!quiet) throw error;
    state.matrixRows = [];
    state.matrixSummary = null;
    state.matrixMissing = [];
  }
  renderMatrix();
}

async function loadSelectedBidSections(quiet = true) {
  if (!state.selectedBidId) {
    state.selectedSections = [];
    state.selectedSectionId = "";
    renderSectionEditor();
    return;
  }
  const detail = await api.request(`/v1/bid-versions/${state.selectedBidId}`);
  if (!quiet && detail.id !== state.selectedBidId) return;
  state.selectedSections = detail.sections || [];
  $("outlinePreview").textContent = detail.outline_markdown || "";
  const stats = detail.content_stats || {};
  $("outlineInfo").textContent = `${detail.id} · 覆盖 ${((detail.score_coverage?.coverage_rate || 0) * 100).toFixed(0)}% · 正文 ${stats.filled || 0}/${stats.total || 0}`;
  if (state.selectedSectionId && !state.selectedSections.some((item) => item.id === state.selectedSectionId)) {
    state.selectedSectionId = "";
  }
  renderSectionEditor();
}

function renderStages() {
  const container = $("stageList");
  if (!container) return;
  container.replaceChildren();
  for (const stage of state.stages) {
    const row = element("div", "", "stage-item");
    const meta = element("div", "", "stage-meta");
    meta.append(
      element("strong", stage.label || stage.stage),
      element("div", `${stage.stage} · ${stage.notes || "无备注"}`, "muted"),
    );
    const actions = element("div", "", "actions");
    actions.append(element("span", stage.status, `state state-${stage.status}`));
    if (canEdit()) {
      if (!stage.passed) {
        actions.append(action("通过", async () => {
          const body = { status: "passed", notes: "工作台确认" };
          if (stage.stage === "check" && state.reviewReadiness?.open_high_risk) {
            const ok = window.confirm(`仍有 ${state.reviewReadiness.open_high_risk} 条高风险未处理。强制通过并记备注？`);
            if (!ok) return;
            body.force_skip_high_risk = true;
            body.notes = $("reviewDecisionNotes")?.value.trim() || "工作台强制通过检查闸门";
          }
          await api.request(`/v1/projects/${state.projectId}/stages/${stage.stage}`, {
            method: "POST", body,
          });
          await loadPipeline(true);
        }));
      } else {
        actions.append(action("重置", async () => {
          await api.request(`/v1/projects/${state.projectId}/stages/${stage.stage}`, { method: "DELETE" });
          await loadPipeline(true);
        }));
      }
    }
    row.append(meta, actions);
    container.append(row);
  }
  if (!state.stages.length) container.append(element("p", "选择项目后显示阶段闸门。", "empty-list"));
}

function renderBids() {
  const container = $("bidVersions");
  if (!container) return;
  container.replaceChildren();
  $("buildOutline").disabled = !canEdit();
  for (const item of state.bidVersions) {
    const row = element("article", "", "bid-item");
    const rate = item.score_coverage?.coverage_rate;
    const filled = item.content_stats?.filled;
    const total = item.content_stats?.total;
    const fillLabel = total == null ? "" : ` · 正文 ${filled || 0}/${total}`;
    row.append(element("div", `${item.title} · ${item.id}${rate == null ? "" : ` · 覆盖 ${(Number(rate) * 100).toFixed(0)}%`}${fillLabel}`));
    const actions = element("div", "", "actions");
    actions.append(action(item.id === state.selectedBidId ? "当前版本" : "选用", async () => {
      state.selectedBidId = item.id;
      state.selectedSectionId = "";
      await loadSelectedBidSections(true);
      await loadMatrix(true);
      renderBids();
    }));
    row.append(actions);
    container.append(row);
  }
  if (!state.bidVersions.length) {
    $("outlinePreview").textContent = "";
    state.selectedSections = [];
    state.selectedSectionId = "";
    renderSectionEditor();
    container.append(element("p", "尚未保存目录版本。通过要求闸门后可生成。", "empty-list"));
  }
}

function renderSectionEditor() {
  const list = $("sectionList");
  const editor = $("sectionEditor");
  if (!list || !editor) return;
  list.replaceChildren();
  $("saveSection").disabled = !canEdit();
  $("seedSection").disabled = !canEdit();
  if ($("generateEvidenceSection")) $("generateEvidenceSection").disabled = !canEdit();
  if (!state.selectedBidId) {
    $("sectionsInfo").textContent = "请先生成并选用目录版本。";
    editor.hidden = true;
    list.append(element("p", "尚无目录版本。", "empty-list"));
    return;
  }
  const filled = state.selectedSections.filter((item) => (item.body_markdown || "").trim()).length;
  $("sectionsInfo").textContent = `当前版本 ${state.selectedBidId} · 已填 ${filled}/${state.selectedSections.length} 章；保存后刷新可恢复。`;
  for (const item of state.selectedSections) {
    const row = element("article", "", `section-edit-item${item.id === state.selectedSectionId ? " active" : ""}`);
    const hasBody = Boolean((item.body_markdown || "").trim());
    const indent = Number(item.level || 1) > 1 ? "　".repeat(Number(item.level) - 1) : "";
    row.append(element("div", `${indent}${item.title}`));
    const actions = element("div", "", "actions");
    actions.append(element("span", hasBody ? "已填" : "空", `state state-${hasBody ? "confirmed" : "draft"}`));
    actions.append(action(item.id === state.selectedSectionId ? "编辑中" : "编辑", async () => {
      state.selectedSectionId = item.id;
      renderSectionEditor();
    }));
    row.append(actions);
    list.append(row);
  }
  if (!state.selectedSections.length) {
    editor.hidden = true;
    list.append(element("p", "该目录版本没有章节。", "empty-list"));
    return;
  }
  const current = state.selectedSections.find((item) => item.id === state.selectedSectionId);
  if (!current) {
    editor.hidden = true;
    return;
  }
  editor.hidden = false;
  $("sectionEditorTitle").textContent = current.title || "章节";
  $("sectionEditorMeta").textContent = `${current.section_key} · ${current.id}${current.updated_at ? ` · 更新于 ${formatTime(current.updated_at)}` : ""}`;
  $("sectionBody").value = current.body_markdown || "";
  $("sectionBody").disabled = !canEdit();
}

function renderMatrix() {
  const rowsBox = $("matrixRows");
  const missingBox = $("matrixMissing");
  if (!rowsBox || !missingBox) return;
  rowsBox.replaceChildren();
  missingBox.replaceChildren();
  $("rebuildMatrix").disabled = !canEdit() || !state.selectedBidId;
  if (!state.selectedBidId) {
    $("matrixInfo").textContent = "请先生成并选用目录版本，再重建响应矩阵。";
    rowsBox.append(element("p", "尚无标书版本。", "empty-list"));
    return;
  }
  const summary = state.matrixSummary;
  if (summary) {
    $("matrixInfo").textContent = `${state.selectedBidId} · 共 ${summary.total} 条 · 强制待闭环 ${summary.mandatory_open}/${summary.mandatory_total} · 覆盖 ${((summary.coverage_rate || 0) * 100).toFixed(0)}%`;
  } else {
    $("matrixInfo").textContent = "尚未构建矩阵。通过目录闸门后点击「重建矩阵」。";
  }
  if (state.matrixMissing.length) {
    missingBox.append(element("h3", "缺失材料／待办"));
    for (const item of state.matrixMissing.slice(0, 20)) {
      const card = element("article", "", "matrix-item mandatory");
      card.append(element("div", item.requirement_title || "要求", "matrix-title"));
      card.append(element("div", (item.materials || []).join("；") || "待处理", "muted"));
      missingBox.append(card);
    }
  }
  if (!state.matrixRows.length) {
    rowsBox.append(element("p", "矩阵为空。生成目录并抽取要求后，点击「重建矩阵」。", "empty-list"));
    return;
  }
  for (const row of state.matrixRows) {
    const card = element("article", "", `matrix-item${row.is_mandatory ? " mandatory" : ""}`);
    card.append(element("div", row.requirement_title || "要求", "matrix-title"));
    const meta = element("div", "", "matrix-meta");
    meta.append(element("span", categoryLabels[row.requirement_category] || row.requirement_category || "-", "badge"));
    meta.append(element("span", row.is_mandatory ? "强制" : "普通", "badge"));
    meta.append(element("span", matrixStatusLabels[row.response_status] || row.response_status, `state state-${row.response_status === "responded" || row.response_status === "drafted" ? "confirmed" : row.response_status === "waived" ? "skipped" : "draft"}`));
    meta.append(element("span", row.section_title ? `章节：${row.section_title}` : "未映射章节", "muted"));
    card.append(meta);
    if ((row.missing_materials || []).length) {
      card.append(element("div", `待补：${row.missing_materials.join("；")}`, "muted"));
    }
    if (canEdit()) {
      const statusSelect = document.createElement("select");
      statusSelect.className = "matrix-select";
      for (const [value, label] of Object.entries(matrixStatusLabels)) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        if (value === row.response_status) option.selected = true;
        statusSelect.append(option);
      }
      const sectionSelect = document.createElement("select");
      sectionSelect.className = "matrix-select";
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "（不关联章节）";
      sectionSelect.append(empty);
      for (const section of state.selectedSections) {
        const option = document.createElement("option");
        option.value = section.id;
        option.textContent = `${section.title}${section.level > 1 ? "" : ""}`;
        if (section.id === row.section_id) option.selected = true;
        sectionSelect.append(option);
      }
      const notes = document.createElement("textarea");
      notes.className = "matrix-notes";
      notes.placeholder = "响应说明／豁免理由";
      notes.value = row.response_summary || row.notes || "";
      const actions = element("div", "", "actions");
      actions.append(action("保存", async () => {
        await api.request(`/v1/requirement-responses/${row.id}`, {
          method: "PATCH",
          body: {
            response_status: statusSelect.value,
            section_id: sectionSelect.value || null,
            clear_section: !sectionSelect.value,
            response_summary: notes.value.trim(),
            notes: notes.value.trim(),
          },
        });
        notify("响应矩阵条目已更新");
        await loadMatrix(false);
      }));
      card.append(statusSelect, sectionSelect, notes, actions);
    }
    rowsBox.append(card);
  }
}

function filteredFindings() {
  const filter = state.findingFilter || $("findingFilter")?.value || "open";
  if (filter === "all") return state.findings;
  if (filter === "high") {
    return state.findings.filter((item) => item.decision_status === "open" && ["high", "critical"].includes(item.severity));
  }
  return state.findings.filter((item) => item.decision_status === "open");
}

function renderFindings() {
  const container = $("reviewFindings");
  if (!container) return;
  container.replaceChildren();
  $("runReview").disabled = !canEdit();
  if ($("approveReview")) $("approveReview").disabled = !canEdit() || !state.reviewRuns.length;
  const open = state.findings.filter((item) => item.decision_status === "open");
  const openHigh = state.findings.filter((item) => item.decision_status === "open" && ["high", "critical"].includes(item.severity));
  const latest = state.reviewRuns[0];
  const approval = latest?.approval_status || "pending";
  $("reviewInfo").textContent = `共 ${state.findings.length} 条 · 待处理 ${open.length} · 高风险待闭环 ${openHigh.length} · 最近审批 ${approval}`;
  const rows = filteredFindings();
  for (const item of rows.slice(0, 40)) {
    const card = element("article", "", "finding");
    card.append(element("div", `${item.title} · ${item.check_name}`, `finding-title sev-${item.severity}`));
    card.append(element("div", `${item.severity} · ${item.detail || ""}`, "muted"));
    if (item.decided_by) {
      card.append(element("div", `处理：${item.decision_status} · ${item.decision_notes || "无备注"} · ${formatTime(item.decided_at)}`, "muted"));
    }
    const actions = element("div", "", "actions");
    actions.append(element("span", item.decision_status, `state state-${item.decision_status === "open" ? "pending" : "confirmed"}`));
    if (canEdit() && item.decision_status === "open") {
      for (const status of [["accepted", "接受"], ["waived", "豁免"], ["fixed", "已修复"]]) {
        actions.append(action(status[1], async () => {
          const notes = ($("reviewDecisionNotes")?.value || "").trim();
          const needNotes = status[0] === "waived" || ["high", "critical"].includes(item.severity);
          if (needNotes && !notes) return notify("高风险处理或豁免必须填写备注", true);
          await api.request(`/v1/review-findings/${item.id}/decide`, {
            method: "POST", body: { decision_status: status[0], notes: notes || "工作台处理" },
          });
          await loadPipeline(true);
        }));
      }
    }
    actions.append(action("历程", async () => {
      const data = await api.request(`/v1/review-findings/${item.id}/history`);
      let box = card.querySelector(".finding-history");
      if (!box) {
        box = element("div", "", "finding-history");
        card.append(box);
      }
      box.replaceChildren();
      if (!(data.events || []).length) {
        box.append(element("div", "尚无处理记录"));
      } else {
        for (const event of data.events) {
          box.append(element("div", `${formatTime(event.created_at)} · ${event.from_status || "-"} → ${event.to_status} · ${event.notes || "无备注"}`));
        }
      }
    }));
    card.append(actions);
    container.append(card);
  }
  if (!state.findings.length) container.append(element("p", "尚未运行审查。", "empty-list"));
  else if (!rows.length) container.append(element("p", "当前筛选下无发现。", "empty-list"));
}

function renderAuditLogs() {
  const box = $("auditLogs");
  if (!box) return;
  box.hidden = false;
  box.replaceChildren(element("h3", "项目审计日志"));
  if (!state.auditLogs.length) {
    box.append(element("p", "暂无审计记录。", "empty-list"));
    return;
  }
  for (const item of state.auditLogs.slice(0, 30)) {
    const row = element("article", "", "audit-item");
    row.append(element("div", `${formatTime(item.created_at)} · ${item.action}`));
    row.append(element("div", `${item.summary} · ${item.object_type}/${item.object_id}`, "muted"));
    box.append(row);
  }
}

function renderExports() {
  const container = $("exportList");
  if (!container) return;
  container.replaceChildren();
  $("exportDocx").disabled = !canEdit();
  for (const item of state.exports) {
    const row = element("article", "", "export-item");
    const kind = (item.kind || "docx").toUpperCase();
    const template = item.template_id ? ` · 模板 ${item.template_id}` : "";
    row.append(element("div", `${kind} · ${item.file_name} · ${(item.size_bytes / 1024).toFixed(1)} KB${template} · ${formatTime(item.created_at)}`));
    const link = element("a", `下载 ${kind}`);
    link.href = `${api.base}/v1/exports/${item.id}/download`;
    row.append(link);
    if (item.checklist?.structure) {
      const structure = item.checklist.structure;
      row.append(element("div", `结构：目录=${structure.has_toc ? "有" : "无"} · 页码=${structure.has_page_numbers ? "有" : "无"} · 缺项附录=${structure.has_missing_appendix ? "有" : "无"}`, "muted"));
    }
    container.append(row);
  }
  if (!state.exports.length) container.append(element("p", "尚无导出物。", "empty-list"));
}

async function loadExportTemplates() {
  const select = $("exportTemplate");
  if (!select) return;
  try {
    const data = await api.request("/v1/export-templates");
    const current = select.value || "full";
    select.replaceChildren();
    for (const item of data.templates || []) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = `${item.label}${item.dark_bid ? "（暗标）" : ""}`;
      select.append(option);
    }
    select.value = [...select.options].some((item) => item.value === current) ? current : "full";
    $("exportInfo").textContent = data.pdf_converter_available
      ? `模板版本 ${data.template_version}；本环境可尝试 LibreOffice 转 PDF。`
      : `模板版本 ${data.template_version}；未检测到 LibreOffice，PDF 转换将跳过。`;
  } catch (error) {
    // Keep default option if templates API unavailable.
  }
}

$("reloadStages").addEventListener("click", () => loadPipeline().catch(handleError));
$("reloadAssets").addEventListener("click", () => loadPipeline(true).catch(handleError));
$("createAsset").addEventListener("click", async () => {
  if (!state.projectId) return notify("请先选择项目", true);
  const title = $("assetTitle").value.trim();
  if (!title) return notify("请填写资产标题", true);
  $("createAsset").disabled = true;
  try {
    const asset = await api.request("/v1/enterprise-assets", {
      method: "POST",
      body: {
        category: $("assetCategory").value,
        title,
        subject_name: $("assetSubject").value.trim(),
        certificate_no: $("assetCertNo").value.trim(),
        issuer: $("assetIssuer").value.trim(),
        issued_on: $("assetIssuedOn").value || null,
        expires_on: $("assetExpiresOn").value || null,
        status: $("assetStatus").value,
      },
    });
    const file = $("assetFile").files?.[0];
    if (file) {
      const form = new FormData();
      form.append("file", file);
      form.append("notes", "工作台上传");
      await api.request(`/v1/enterprise-assets/${asset.id}/versions`, { method: "POST", body: form });
    }
    await api.request(`/v1/projects/${state.projectId}/assets/${asset.id}/link`, { method: "POST", body: {} });
    $("assetTitle").value = "";
    $("assetSubject").value = "";
    $("assetCertNo").value = "";
    $("assetIssuer").value = "";
    $("assetIssuedOn").value = "";
    $("assetExpiresOn").value = "";
    $("assetFile").value = "";
    notify(`已创建并关联：${asset.title}${asset.usable ? "" : "（当前不可用于生成）"}`);
    await loadPipeline(true);
  } catch (error) { handleError(error); }
  finally { $("createAsset").disabled = !canEdit(); }
});
$("reloadBids").addEventListener("click", () => loadPipeline(true).catch(handleError));
$("reloadSections").addEventListener("click", () => loadSelectedBidSections(false).catch(handleError));
$("reloadMatrix").addEventListener("click", () => loadMatrix(false).catch(handleError));
$("rebuildMatrix").addEventListener("click", async () => {
  if (!state.selectedBidId) return notify("请先选用目录版本", true);
  $("rebuildMatrix").disabled = true;
  try {
    const data = await api.request(`/v1/bid-versions/${state.selectedBidId}/response-matrix/rebuild`, {
      method: "POST", body: {},
    });
    state.matrixRows = data.rows || [];
    state.matrixSummary = data.summary || null;
    state.matrixMissing = data.missing_materials || [];
    renderMatrix();
    notify(`矩阵已重建：${data.summary?.total || 0} 条，强制待闭环 ${data.summary?.mandatory_open || 0}`);
  } catch (error) { handleError(error); }
  finally { $("rebuildMatrix").disabled = !canEdit() || !state.selectedBidId; }
});
$("reloadFindings").addEventListener("click", () => loadPipeline(true).catch(handleError));
$("findingFilter")?.addEventListener("change", () => {
  state.findingFilter = $("findingFilter").value;
  renderFindings();
});
$("approveReview")?.addEventListener("click", async () => {
  const latest = state.reviewRuns[0];
  if (!latest) return notify("请先运行审查", true);
  $("approveReview").disabled = true;
  try {
    const notes = ($("reviewDecisionNotes")?.value || "").trim();
    const force = Boolean(state.reviewReadiness?.open_high_risk);
    if (force && !notes) return notify("仍有高风险未闭环时，强制批准必须填写备注", true);
    await api.request(`/v1/review-runs/${latest.id}/approve`, {
      method: "POST",
      body: { approval_status: "approved", notes: notes || "工作台批准", force },
    });
    notify("审查任务已批准");
    await loadPipeline(true);
  } catch (error) { handleError(error); }
  finally { $("approveReview").disabled = !canEdit() || !state.reviewRuns.length; }
});
$("reloadAudit")?.addEventListener("click", async () => {
  if (!state.projectId) return;
  try {
    const data = await api.request(`/v1/projects/${state.projectId}/audit-logs?limit=50`);
    state.auditLogs = data.logs || [];
    renderAuditLogs();
  } catch (error) { handleError(error); }
});
$("reloadExports").addEventListener("click", () => loadPipeline(true).catch(handleError));
$("saveSection").addEventListener("click", async () => {
  if (!state.selectedSectionId) return notify("请先选择章节", true);
  $("saveSection").disabled = true;
  try {
    const data = await api.request(`/v1/bid-sections/${state.selectedSectionId}`, {
      method: "PATCH",
      body: {
        body_markdown: $("sectionBody").value,
        mark_generate_gate: Boolean($("markGenerateGate").checked),
      },
    });
    notify(`已保存：${data.section?.title || "章节"}（${data.content_stats?.filled || 0}/${data.content_stats?.total || 0}）`);
    await loadPipeline(true);
    state.selectedSectionId = data.section?.id || state.selectedSectionId;
    await loadSelectedBidSections(true);
  } catch (error) { handleError(error); }
  finally { $("saveSection").disabled = !canEdit(); }
});
$("seedSection").addEventListener("click", async () => {
  if (!state.selectedSectionId) return notify("请先选择章节", true);
  $("seedSection").disabled = true;
  try {
    const overwrite = Boolean(($("sectionBody").value || "").trim());
    const data = await api.request(`/v1/bid-sections/${state.selectedSectionId}/seed-placeholder`, {
      method: "POST",
      body: { overwrite },
    });
    state.selectedSectionId = data.section?.id || state.selectedSectionId;
    notify(`已写入待补草稿：${data.section?.title || "章节"}`);
    await loadPipeline(true);
  } catch (error) { handleError(error); }
  finally { $("seedSection").disabled = !canEdit(); }
});
$("generateEvidenceSection")?.addEventListener("click", async () => {
  if (!state.selectedSectionId) return notify("请先选择章节", true);
  $("generateEvidenceSection").disabled = true;
  try {
    const overwrite = Boolean(($("sectionBody").value || "").trim());
    const data = await api.request(`/v1/bid-sections/${state.selectedSectionId}/generate-from-evidence`, {
      method: "POST",
      body: { overwrite, mark_generate_gate: Boolean($("markGenerateGate").checked), use_llm: false },
    });
    state.selectedSectionId = data.section?.id || state.selectedSectionId;
    notify(`证据约束成章：要求 ${data.evidence_summary?.requirement_count || 0} · 待补 ${data.evidence_summary?.pending_placeholders || 0}`);
    await loadPipeline(true);
    await loadSelectedBidSections(true);
  } catch (error) { handleError(error); }
  finally { $("generateEvidenceSection").disabled = !canEdit(); }
});
$("reloadMineru").addEventListener("click", async () => {
  try {
    const data = await api.request("/v1/integrations/mineru");
    $("mineruStatus").textContent = data.configured
      ? `MinerU：已配置（${data.token_masked}），超时 ${data.timeout}s`
      : "MinerU：未配置 token（仅影响扫描件／远程解析）";
  } catch (error) { handleError(error); }
});
$("buildOutline").addEventListener("click", async () => {
  if (!state.projectId) return;
  $("buildOutline").disabled = true;
  try {
    const body = {};
    if (state.requirementsVersionId) body.document_version_id = state.requirementsVersionId;
    const data = await api.request(`/v1/projects/${state.projectId}/outline/from-requirements`, {
      method: "POST", body,
    });
    state.selectedBidId = data.bid_version?.id || state.selectedBidId;
    state.selectedSectionId = "";
    $("outlinePreview").textContent = data.outline_markdown || "";
    notify(`目录已保存，评分覆盖 ${((data.score_coverage?.coverage_rate || 0) * 100).toFixed(0)}%`);
    await loadPipeline(true);
  } catch (error) { handleError(error); }
  finally { $("buildOutline").disabled = !canEdit(); }
});
$("runReview").addEventListener("click", async () => {
  if (!state.projectId) return;
  $("runReview").disabled = true;
  try {
    const body = {
      use_llm: Boolean($("useLlmReview").checked),
      bid_version_id: state.selectedBidId || null,
      document_version_id: state.requirementsVersionId || state.result?.document_version_id || null,
    };
    const run = await api.request(`/v1/projects/${state.projectId}/review-runs`, { method: "POST", body });
    notify(`审查完成：${run.summary?.finding_count || 0} 条，风险 ${run.summary?.risk_level || "-"}`);
    await loadPipeline(true);
  } catch (error) { handleError(error); }
  finally { $("runReview").disabled = !canEdit(); }
});
$("exportDocx").addEventListener("click", async () => {
  if (!state.projectId || !state.selectedBidId) return notify("请先生成并选用目录版本", true);
  $("exportDocx").disabled = true;
  try {
    const data = await api.request(`/v1/projects/${state.projectId}/export-jobs`, {
      method: "POST",
      body: {
        bid_version_id: state.selectedBidId,
        force_skip_gate: Boolean($("forceExport").checked),
        notes: $("exportNotes").value.trim(),
        bidder_name: $("bidderName").value.trim(),
        template_id: $("exportTemplate")?.value || "full",
        convert_pdf: Boolean($("convertPdf")?.checked),
      },
    });
    const pdfNote = data.pdf_artifact
      ? `；PDF ${data.pdf_artifact.file_name}`
      : (data.pdf_status && !data.pdf_status.ok ? `；PDF 跳过：${data.pdf_status.reason || ""}` : "");
    notify(`已导出 ${data.artifact?.file_name || "DOCX"}（模板 ${data.template?.id || "full"}）${pdfNote}`);
    await loadPipeline(true);
  } catch (error) { handleError(error); }
  finally { $("exportDocx").disabled = !canEdit(); }
});

setInterval(async () => {
  if (!state.user || !state.projectId || state.refreshing || document.hidden) return;
  state.refreshing = true;
  try { await refreshProject(); } catch (error) { handleError(error); }
  finally { state.refreshing = false; }
}, 3000);
loadIdentity().catch(handleError);
