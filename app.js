(() => {
  "use strict";

  window.REQUIREMENT_FLOW_REAL_APP = true;

  const UI_KEY = "project-flow-controller-v2";
  const stages = [
    { id: "input", label: "需求输入", title: "选择需求接入方式", description: "可创建新需求，或填写已有需求文档、执行 Plan 与 Worktree；接入前先做只读校验。" },
    { id: "discuss", label: "讨论澄清", title: "先讨论，只问会导致返工的问题", description: "Codex 先读取当前 Project Profile 的项目事实，再把高返工决策压缩为 1–3 个问题。" },
    { id: "plan", label: "Plan 验收", title: "验收范围、流程和完成标准", description: "Solution Plan Markdown 是执行契约草案，HTML 是同口径的逻辑验收视图。" },
    { id: "worktree", label: "Worktree", title: "准备隔离执行环境", description: "展示真实 dry-run、分支、基准和路径；只有点击后才创建 Worktree。" },
    { id: "execute", label: "执行", title: "选择速度后执行 Plan", description: "快速模式复用 Codex App Thread；标准模式保留独立 Code Review。" },
    { id: "verify", label: "人工验收", title: "按测试案例完成最终验收", description: "自动验证和人工结果分开记录；全部必测项通过后才进入 Commit。" },
    { id: "commit", label: "Commit", title: "确认真实 Diff 后提交", description: "提交前重新读取 Git 状态；状态摘要变化时会拒绝 Commit。" },
    { id: "bugfix", label: "Bug 修复", title: "提交后发现问题，进入修复循环", description: "填写复现信息后复用当前 Worktree 和任务记忆；可选快速修改或带独立 Review 的标准流程。" },
    { id: "knowledge", label: "沉淀", title: "提炼可复用经验", description: "从 Commit、代码、测试、Review 和人工验收中生成候选；人工审核前不会发布到项目。" }
  ];
  const askModule = {
    id: "ask",
    label: "Ask",
    title: "询问当前实现",
    description: "复用当前任务、Plan 和 Worktree 上下文进行只读问答；不会修改文件或改变任务阶段。"
  };
  const knowledgeCenterModule = {
    id: "knowledge-center",
    label: "沉淀中心",
    title: "跨任务沉淀中心",
    description: "集中审核所有任务的沉淀候选；保留或忽略只更新本地运行态，不会自动修改项目文档、Skill 或 Git。"
  };

  const defaultUi = {
    taskId: "",
    taskFilter: "all",
    knowledgeFilter: "pending",
    showArchived: false,
    taskViews: {},
    module: "flow",
    viewStage: "input",
    intakeMode: "new",
    workflowMode: "standard",
    sourceType: "link",
    title: "",
    sourceUrl: "",
    larkReader: "chrome_mcp",
    sourceText: "",
    sourceFileName: "",
    baseBranch: "main",
    existingDocumentPath: "",
    existingWorktreePath: "",
    answers: {},
    customAnswers: {},
    discussionNote: "",
    planView: "logic",
    agentMemoryOpen: false,
    executionMode: "fast",
    checks: [],
    verificationNote: "",
    commitMessage: "",
    commitConfirmed: false,
    bugfixDescription: "",
    askQuestion: ""
  };

  let ui = loadUi();
  let task = null;
  let taskSummaries = [];
  let knowledgeCandidates = [];
  let knowledgeLoading = false;
  let knowledgeLoaded = false;
  let knowledgeError = "";
  let scheduler = { maxConcurrentJobs: 2, runningJobs: 0, queuedJobs: 0 };
  let health = null;
  let projectBranches = [];
  let branchLoadError = "";
  let token = "";
  let selectedFile = null;
  const feedbackImages = new Map();
  let feedbackImageSequence = 0;
  let busy = false;
  let pollTimer = null;
  let toastTimer = null;
  let workspaceRefreshPending = false;
  let sectionNavigatorCleanup = null;

  const stepsEl = document.querySelector("#steps");
  const globalStatusEl = document.querySelector("#globalStatus");
  const stageTitleEl = document.querySelector("#stageTitle");
  const stageDescriptionEl = document.querySelector("#stageDescription");
  const stageContentEl = document.querySelector("#stageContent");
  const serviceBadgeEl = document.querySelector("#serviceBadge");
  const toastEl = document.querySelector("#toast");
  const taskListEl = document.querySelector("#taskList");
  const taskCountEl = document.querySelector("#taskCount");
  const taskQueueTitleEl = document.querySelector("#taskQueueTitle");
  const taskFiltersEl = document.querySelector(".task-filters");
  const archiveViewButtonEl = document.querySelector("#archiveViewButton");
  const knowledgeCenterButtonEl = document.querySelector("#knowledgeCenterButton");
  const createTaskButtonEl = document.querySelector("#createTaskButton");
  const schedulerNoteEl = document.querySelector("#schedulerNote");
  document.querySelector("#resetButton").addEventListener("click", newTask);
  createTaskButtonEl.addEventListener("click", newTask);
  archiveViewButtonEl.addEventListener("click", () => {
    ui.module = "flow";
    ui.showArchived = !ui.showArchived;
    saveUi();
    renderTaskConsole();
  });
  knowledgeCenterButtonEl.addEventListener("click", async () => {
    captureVisibleFields();
    ui.module = ui.module === "knowledge-center" ? "flow" : "knowledge-center";
    ui.showArchived = false;
    saveUi();
    render();
    if (ui.module === "knowledge-center") await refreshKnowledgeCenter();
  });
  stepsEl.addEventListener("click", (event) => {
    const moduleButton = event.target.closest("[data-module-jump]");
    if (moduleButton && !moduleButton.disabled) {
      captureVisibleFields();
      ui.module = moduleButton.dataset.moduleJump;
      render();
      return;
    }
    const button = event.target.closest("[data-stage-jump]");
    if (!button || button.disabled) return;
    captureVisibleFields();
    ui.module = "flow";
    ui.viewStage = button.dataset.stageJump;
    render();
  });
  document.querySelector(".task-filters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-task-filter]");
    if (!button) return;
    ui.taskFilter = button.dataset.taskFilter;
    saveUi();
    renderTaskConsole();
  });
  taskListEl.addEventListener("click", (event) => {
    const action = event.target.closest("[data-task-action]");
    if (action) {
      manageTask(action.dataset.taskId, action.dataset.taskAction);
      return;
    }
    const button = event.target.closest("[data-task-open]");
    if (button) switchTask(button.dataset.taskOpen);
  });

  const taskViewKeys = [
    "module", "viewStage", "knowledgeFilter", "intakeMode", "workflowMode", "sourceType", "title", "sourceUrl", "larkReader", "sourceText", "sourceFileName", "baseBranch",
    "existingDocumentPath", "existingWorktreePath",
    "answers", "customAnswers", "discussionNote", "planView", "agentMemoryOpen", "executionMode", "checks", "verificationNote", "commitMessage", "commitConfirmed", "bugfixDescription", "askQuestion"
  ];

  function taskViewSnapshot(source) {
    const result = {};
    taskViewKeys.forEach((key) => { result[key] = structuredClone(source[key]); });
    return result;
  }

  function loadUi() {
    try {
      const saved = JSON.parse(localStorage.getItem(UI_KEY));
      const merged = {
        ...structuredClone(defaultUi),
        ...(saved || {}),
        taskViews: { ...(saved?.taskViews || {}) },
        answers: { ...(saved?.answers || {}) },
        customAnswers: { ...(saved?.customAnswers || {}) }
      };
      if (saved?.taskId && !merged.taskViews[saved.taskId]) merged.taskViews[saved.taskId] = taskViewSnapshot(merged);
      return merged;
    } catch (_) {
      return structuredClone(defaultUi);
    }
  }

  function saveUi() {
    const viewKey = task?.id || "__new__";
    ui.taskViews ||= {};
    ui.taskViews[viewKey] = taskViewSnapshot(ui);
    localStorage.setItem(UI_KEY, JSON.stringify(ui));
  }

  function activateTaskView(taskId, fallback = {}) {
    const taskViews = ui.taskViews || {};
    const taskFilter = ui.taskFilter || "all";
    const showArchived = Boolean(ui.showArchived);
    const stored = taskViews[taskId] || fallback;
    ui = {
      ...structuredClone(defaultUi),
      ...stored,
      taskId: taskId === "__new__" ? "" : taskId,
      taskFilter,
      showArchived,
      taskViews,
      answers: { ...(stored.answers || {}) },
      customAnswers: { ...(stored.customAnswers || {}) },
      checks: [...(stored.checks || [])]
    };
  }

  function escapeHTML(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function isLarkLink(value) {
    try {
      const hostname = new URL(String(value || "")).hostname.toLowerCase().replace(/\.$/, "");
      return ["feishu.cn", "larksuite.com", "larkoffice.com"].some((suffix) => hostname === suffix || hostname.endsWith(`.${suffix}`));
    } catch (_) {
      return false;
    }
  }

  function formatTime(value) {
    if (!value) return "";
    try { return new Date(value).toLocaleTimeString("zh-CN", { hour12: false }); }
    catch (_) { return value; }
  }

  function formatDateTime(value) {
    if (!value) return "";
    try { return new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }); }
    catch (_) { return value; }
  }

  function feedbackImageKey(kind) {
    return `${task?.id || "__new__"}:${kind}`;
  }

  function feedbackImageItems(kind) {
    const key = feedbackImageKey(kind);
    if (!feedbackImages.has(key)) feedbackImages.set(key, []);
    return feedbackImages.get(key);
  }

  function feedbackImageLimits() {
    return {
      maxCount: Number(health?.limits?.feedbackImages?.maxCount) || 6,
      maxFileBytes: Number(health?.limits?.feedbackImages?.maxFileBytes) || 4 * 1024 * 1024,
      maxTotalBytes: Number(health?.limits?.feedbackImages?.maxTotalBytes) || 8 * 1024 * 1024,
      mimeTypes: health?.limits?.feedbackImages?.mimeTypes || ["image/png", "image/jpeg", "image/webp"]
    };
  }

  function formatBytes(value) {
    if (!value) return "0 KB";
    if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }

  function feedbackImagesPayload(kind) {
    return feedbackImageItems(kind).map(({ name, mimeType, base64 }) => ({ name, mimeType, base64 }));
  }

  function clearFeedbackImages(kind) {
    const key = feedbackImageKey(kind);
    (feedbackImages.get(key) || []).forEach((item) => URL.revokeObjectURL(item.previewUrl));
    feedbackImages.delete(key);
  }

  function removeFeedbackImage(kind, imageId) {
    const items = feedbackImageItems(kind);
    const index = items.findIndex((item) => item.id === imageId);
    if (index < 0) return;
    URL.revokeObjectURL(items[index].previewUrl);
    items.splice(index, 1);
    captureVisibleFields();
    render();
  }

  function fileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
      reader.onerror = () => reject(new Error(`无法读取图片：${file.name}`));
      reader.readAsDataURL(file);
    });
  }

  async function addFeedbackImages(kind, fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const items = feedbackImageItems(kind);
    const limits = feedbackImageLimits();
    if (items.length + files.length > limits.maxCount) {
      showToast(`一次最多添加 ${limits.maxCount} 张图片。`, true);
      return;
    }
    const unsupported = files.find((file) => !limits.mimeTypes.includes(file.type));
    if (unsupported) {
      showToast(`“${unsupported.name}”不是支持的图片，仅可使用 PNG、JPEG、WebP。`, true);
      return;
    }
    const oversized = files.find((file) => file.size > limits.maxFileBytes);
    if (oversized) {
      showToast(`“${oversized.name}”超过单张 ${formatBytes(limits.maxFileBytes)} 限制。`, true);
      return;
    }
    const totalBytes = [...items, ...files].reduce((sum, item) => sum + item.size, 0);
    if (totalBytes > limits.maxTotalBytes) {
      showToast(`图片总大小不能超过 ${formatBytes(limits.maxTotalBytes)}。`, true);
      return;
    }
    try {
      const encoded = await Promise.all(files.map(fileAsBase64));
      const additions = files.map((file, index) => {
        const sequence = ++feedbackImageSequence;
        return {
          id: `feedback-image-${sequence}`,
          name: file.name || `screenshot-${sequence}.png`,
          mimeType: file.type,
          size: file.size,
          base64: encoded[index],
          previewUrl: URL.createObjectURL(file)
        };
      });
      items.push(...additions);
      captureVisibleFields();
      render();
    } catch (error) {
      showToast(error.message || "图片读取失败。", true);
    }
  }

  function renderFeedbackImageInput(kind) {
    const items = feedbackImageItems(kind);
    const limits = feedbackImageLimits();
    const totalBytes = items.reduce((sum, item) => sum + item.size, 0);
    const inputId = `${kind}ImageInput`;
    return `<div class="feedback-images" data-feedback-kind="${escapeHTML(kind)}">
      <div class="image-drop-zone" data-image-drop-zone="${escapeHTML(kind)}" role="button" tabindex="0" aria-label="选择、粘贴或拖入问题截图">
        <input class="feedback-file-input" id="${escapeHTML(inputId)}" data-image-input="${escapeHTML(kind)}" type="file" accept="image/png,image/jpeg,image/webp" multiple>
        <div><strong>添加截图</strong><span>可选择、直接粘贴，或拖入 PNG / JPEG / WebP</span></div>
        <button class="small" type="button" data-image-pick="${escapeHTML(kind)}">选择图片</button>
      </div>
      ${items.length ? `<div class="feedback-image-grid" aria-label="已添加的图片">${items.map((item) => `<figure class="feedback-image-card"><img src="${escapeHTML(item.previewUrl)}" alt="${escapeHTML(item.name)} 的预览"><figcaption><span title="${escapeHTML(item.name)}">${escapeHTML(item.name)}</span><small>${formatBytes(item.size)}</small></figcaption><button type="button" data-image-remove="${escapeHTML(kind)}" data-image-id="${escapeHTML(item.id)}" aria-label="删除 ${escapeHTML(item.name)}">×</button></figure>`).join("")}</div>` : ""}
      <span class="hint">已添加 ${items.length} / ${limits.maxCount} 张，${formatBytes(totalBytes)} / ${formatBytes(limits.maxTotalBytes)}。图片只保存在任务运行目录，不进入 Worktree 或 Commit。</span>
    </div>`;
  }

  function updateFeedbackActionState(kind) {
    const config = kind === "verification"
      ? { textId: "verificationNote", buttonId: "returnToExecution" }
      : { textId: "bugfixDescription", buttonId: "startBugfix" };
    const button = document.getElementById(config.buttonId);
    const text = document.getElementById(config.textId)?.value.trim() || "";
    if (button) button.disabled = !text && !feedbackImageItems(kind).length;
  }

  function attachFeedbackImageHandlers(kind, textId) {
    const input = document.querySelector(`[data-image-input="${kind}"]`);
    const picker = document.querySelector(`[data-image-pick="${kind}"]`);
    const dropZone = document.querySelector(`[data-image-drop-zone="${kind}"]`);
    if (!input || !dropZone) return;

    picker?.addEventListener("click", (event) => {
      event.stopPropagation();
      input.click();
    });
    input.addEventListener("change", () => addFeedbackImages(kind, input.files));
    dropZone.addEventListener("click", (event) => {
      if (!event.target.closest("button")) input.click();
    });
    dropZone.addEventListener("keydown", (event) => {
      if (["Enter", " "].includes(event.key)) {
        event.preventDefault();
        input.click();
      }
    });
    ["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("is-dragging");
    }));
    dropZone.addEventListener("dragleave", (event) => {
      if (!dropZone.contains(event.relatedTarget)) dropZone.classList.remove("is-dragging");
    });
    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-dragging");
      addFeedbackImages(kind, event.dataTransfer?.files);
    });

    const pasteImages = (event) => {
      const files = Array.from(event.clipboardData?.items || [])
        .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter(Boolean);
      if (!files.length) return;
      event.preventDefault();
      addFeedbackImages(kind, files);
    };
    dropZone.addEventListener("paste", pasteImages);
    document.getElementById(textId)?.addEventListener("paste", pasteImages);
    document.querySelectorAll(`[data-image-remove="${kind}"]`).forEach((button) => button.addEventListener("click", () => {
      removeFeedbackImage(kind, button.dataset.imageId);
    }));
    updateFeedbackActionState(kind);
  }

  function showToast(message, error = false) {
    window.clearTimeout(toastTimer);
    toastEl.textContent = message;
    toastEl.hidden = false;
    toastEl.style.borderColor = error ? "#d8a0a6" : "#92bea9";
    toastEl.style.background = error ? "#fff0f1" : "#f1fbf6";
    toastEl.style.color = error ? "#7a2730" : "#174d38";
    toastTimer = window.setTimeout(() => { toastEl.hidden = true; }, error ? 5200 : 2600);
  }

  function applyHealth(nextHealth) {
    const previousDefaultBranch = defaultUi.baseBranch;
    health = nextHealth;
    token = health.token || "";
    scheduler = health.scheduler || scheduler;
    defaultUi.baseBranch = health.project?.defaultBaseBranch || "main";
    if (!ui.taskId && (!ui.baseBranch || ui.baseBranch === previousDefaultBranch)) ui.baseBranch = defaultUi.baseBranch;
    const projectName = health.project?.name || "Project";
    document.title = `${projectName} · DevConductor`;
    const projectEyebrow = document.querySelector("#projectEyebrow");
    if (projectEyebrow) projectEyebrow.textContent = `${projectName} · DevConductor`;
    serviceBadgeEl.textContent = health.ok ? `本地服务已连接 · ${health.codex.version}` : "本地服务预检失败";
    serviceBadgeEl.style.borderColor = health.ok ? "#92bea9" : "#d8a0a6";
    serviceBadgeEl.style.background = health.ok ? "#eaf7f1" : "#fff0f1";
    serviceBadgeEl.style.color = health.ok ? "#216e4e" : "#a2333e";
  }

  async function refreshSessionToken() {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.token) return false;
      applyHealth(payload);
      return true;
    } catch (_) {
      return false;
    }
  }

  async function api(path, options = {}, retryToken = true) {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Requirement-Flow-Token": token,
        ...(options.headers || {})
      }
    });
    if (response.status === 403 && retryToken && await refreshSessionToken()) return api(path, options, false);
    let payload;
    try { payload = await response.json(); }
    catch (_) { payload = { error: `本地服务返回了无法解析的响应（HTTP ${response.status}）。` }; }
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  }

  async function post(path, body = {}) {
    return api(path, { method: "POST", body: JSON.stringify(body) });
  }

  function setTask(next, followStage = true) {
    const changingTask = next?.id !== task?.id;
    const hasStoredView = Boolean(next?.id && ui.taskViews?.[next.id]);
    const draftFallback = !task && next ? taskViewSnapshot(ui) : { viewStage: next?.stage || "input" };
    if (changingTask) saveUi();
    task = next;
    if (changingTask) activateTaskView(next?.id || "__new__", draftFallback);
    ui.taskId = next?.id || "";
    if (next && (followStage || !hasStoredView)) {
      ui.module = "flow";
      ui.viewStage = next.stage;
    }
    if (next) upsertTaskSummary(next);
    saveUi();
    render();
    schedulePoll();
  }

  function summaryFromTask(value) {
    let state = "attention";
    if (value.archivedAt) state = "archived";
    else if (value.activeJob) state = value.jobState === "queued" ? "queued" : "running";
    else if (value.git?.committed) state = "done";
    else if ([value.discussion, value.plan, value.worktree, value.execution].some((section) => ["error", "interrupted"].includes(section?.status))) state = "error";
    return {
      id: value.id,
      title: value.title,
      createdAt: value.createdAt,
      updatedAt: value.updatedAt,
      stage: value.stage,
      maxStageIndex: value.maxStageIndex,
      activeJob: value.activeJob,
      jobState: value.jobState || "idle",
      executionPhase: value.execution?.phase || "",
      state,
      archivedAt: value.archivedAt || "",
      worktree: value.worktree,
      intakeMode: value.intake?.mode || "new",
      committed: Boolean(value.git?.committed),
      knowledge: {
        status: value.knowledge?.status || "idle",
        pending: (value.knowledge?.candidates || []).filter((item) => item.status === "pending").length,
        approved: (value.knowledge?.candidates || []).filter((item) => item.status === "approved").length
      },
      appLinked: Boolean(value.app?.threadId),
      agent: {
        id: String(value.agentMemory?.logicalAgentId || value.id).slice(0, 8),
        memoryVersion: value.agentMemory?.version || 1,
        memoryUpdatedAt: value.agentMemory?.updatedAt || value.updatedAt,
        sessionCount: Object.values(value.agentMemory?.sessions || {}).filter(Boolean).length
      }
    };
  }

  function upsertTaskSummary(value) {
    const summary = summaryFromTask(value);
    taskSummaries = [summary, ...taskSummaries.filter((item) => item.id !== summary.id)]
      .sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
  }

  async function refreshTaskSummaries() {
    const result = await api("/api/tasks");
    taskSummaries = result.tasks || [];
    scheduler = result.scheduler || scheduler;
    return result;
  }

  async function refreshKnowledgeCenter() {
    if (!token || knowledgeLoading) return;
    knowledgeLoading = true;
    knowledgeError = "";
    render();
    try {
      const result = await api("/api/knowledge");
      knowledgeCandidates = Array.isArray(result.candidates) ? result.candidates : [];
      knowledgeLoaded = true;
    } catch (error) {
      knowledgeError = error.message || "无法读取沉淀候选。";
    } finally {
      knowledgeLoading = false;
      render();
    }
  }

  async function refreshProjectBranches() {
    try {
      const result = await api("/api/branches");
      projectBranches = Array.isArray(result.branches) ? result.branches : [];
      branchLoadError = "";
      const names = new Set(projectBranches.map((item) => item.name));
      if (!ui.taskId && !names.has(ui.baseBranch)) {
        const preferred = projectBranches.find((item) => item.default)
          || projectBranches.find((item) => item.current)
          || projectBranches.find((item) => item.kind === "local")
          || projectBranches[0];
        if (preferred?.name) ui.baseBranch = preferred.name;
      }
      return result;
    } catch (error) {
      projectBranches = [];
      branchLoadError = error.message || "无法读取主仓库分支。";
      throw error;
    }
  }

  async function boot() {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      applyHealth(await response.json());
      try { await refreshProjectBranches(); }
      catch (_) { /* 输入页保留 Profile 默认分支，并展示读取错误。 */ }
      await refreshTaskSummaries();
      if (ui.module === "knowledge-center") await refreshKnowledgeCenter();
      if (ui.taskId) {
        try {
          const result = await api(`/api/tasks/${ui.taskId}`);
          task = result.task;
        } catch (error) {
          activateTaskView("__new__");
          task = null;
          saveUi();
          showToast(error.message, true);
        }
      }
    } catch (error) {
      health = { ok: false, warnings: ["无法连接本地服务。请使用 start.command 启动，不要直接双击 index.html。"] };
      serviceBadgeEl.textContent = "本地服务未连接";
      serviceBadgeEl.style.borderColor = "#d8a0a6";
      serviceBadgeEl.style.background = "#fff0f1";
      serviceBadgeEl.style.color = "#a2333e";
    }
    render();
    schedulePoll();
  }

  function schedulePoll() {
    window.clearTimeout(pollTimer);
    if (!token) return;
    pollTimer = window.setTimeout(async () => {
      try {
        const wasActive = task?.activeJob;
        const selectedId = task?.id;
        await refreshTaskSummaries();
        if (ui.module === "knowledge-center" && !knowledgeLoading) {
          const knowledgeResult = await api("/api/knowledge");
          const nextCandidates = Array.isArray(knowledgeResult.candidates) ? knowledgeResult.candidates : [];
          if (JSON.stringify(nextCandidates) !== JSON.stringify(knowledgeCandidates)) {
            knowledgeCandidates = nextCandidates;
            knowledgeLoaded = true;
            workspaceRefreshPending = true;
          }
        }
        const selectedSummary = taskSummaries.find((item) => item.id === selectedId);
        const selectedExecutionPhase = selectedSummary?.executionPhase ?? (selectedId === task?.id ? task?.execution?.phase || "" : "");
        const selectedTaskChanged = selectedSummary && (
          selectedSummary.updatedAt !== task.updatedAt
          || selectedSummary.stage !== task.stage
          || selectedSummary.maxStageIndex !== task.maxStageIndex
          || selectedSummary.activeJob !== task.activeJob
          || selectedSummary.jobState !== (task.jobState || "idle")
          || selectedExecutionPhase !== (task.execution?.phase || "")
        );
        if (selectedId && selectedTaskChanged) {
          const previousStage = task.stage;
          const wasViewingCurrentStage = ui.module === "flow" && ui.viewStage === previousStage;
          const result = await api(`/api/tasks/${selectedId}`);
          task = result.task;
          if (wasViewingCurrentStage && task.stage !== previousStage) ui.viewStage = task.stage;
          workspaceRefreshPending = true;
          if (wasActive && !task.activeJob) {
            const section = task[wasActive];
            showToast(section?.status === "error" ? `${jobLabel(wasActive)}失败：${section.error}` : `${jobLabel(wasActive)}已完成。`, section?.status === "error");
          }
        }
        if (workspaceRefreshPending && !stageEditorFocused()) render();
        else renderShell();
      } catch (error) {
        showToast(error.message, true);
      }
      schedulePoll();
    }, taskSummaries.some((item) => ["running", "queued"].includes(item.state)) ? 1200 : 3200);
  }

  function currentStageId() {
    if (!task) return "input";
    const max = Math.max(0, Number(task.maxStageIndex) || 0);
    const requested = Math.max(0, stages.findIndex((item) => item.id === ui.viewStage));
    return stages[Math.min(requested, max)]?.id || task.stage;
  }

  function activeFlowStageId() {
    if (!task) return "input";
    if (task.stage === "knowledge") return "knowledge";
    return task.git?.committed ? "bugfix" : task.stage;
  }

  function isCompletedStage(stageId) {
    if (!task) return false;
    if (stageId === "bugfix" && task.git?.committed) return false;
    const index = stages.findIndex((item) => item.id === stageId);
    const furthest = Math.max(0, Number(task.maxStageIndex) || 0);
    return index >= 0 && (index < furthest || (stageId === "commit" && Boolean(task.git?.committed)));
  }

  function isCompletedStageView(stageId = currentStageId()) {
    return Boolean(task && ui.module === "flow" && isCompletedStage(stageId));
  }

  function lockCompletedStageView(container) {
    if (!container) return;
    container.querySelectorAll("input, textarea, select").forEach((control) => {
      control.disabled = true;
      control.setAttribute("aria-disabled", "true");
    });
    container.querySelectorAll("button").forEach((button) => {
      const viewOnly = button.matches("[data-readonly-view], [data-plan-view], [data-copy-log], [data-manual-case-jump]");
      if (!viewOnly) {
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
      }
    });
    container.querySelectorAll("[contenteditable='true']").forEach((control) => {
      control.setAttribute("contenteditable", "false");
      control.setAttribute("aria-readonly", "true");
    });
  }

  function statusText() {
    if (!health?.ok) return "等待启动本地服务";
    if (ui.module === "knowledge-center") {
      const pending = knowledgeCandidates.filter((item) => item.status === "pending").length;
      return `沉淀中心 · ${pending} 条待审核`;
    }
    if (!task) return "等待输入需求";
    if (task.archivedAt) return "任务已归档 · 恢复后可继续";
    if (task.activeJob) {
      if (task.activeJob === "execution" && task.stage === "bugfix") {
        if (task.jobState === "queued") return "Bug 任务排队中";
        return task.execution?.phase === "review" ? "Bug 修改已完成 · Code Review 中" : "Bug 定向修改正在运行";
      }
      const label = task.activeJob === "execution" && task.execution?.mode === "acceptance_fix"
          ? "人工验收定向返修"
          : jobLabel(task.activeJob);
      return `${label}${task.jobState === "queued" ? "排队中" : "正在运行"}`;
    }
    if (task.git?.committed && task.stage !== "knowledge") return `Commit 完成 · ${task.git.commitId.slice(0, 12)}${task.stage === "bugfix" ? " · 可继续修 Bug" : ""}`;
    const map = {
      discuss: "等待讨论与口径确认",
      plan: "等待 Plan 逻辑验收",
      worktree: "等待创建 Worktree",
      execute: task.execution?.status === "needs_attention" ? "Review 仍有发现" : "等待执行 Plan",
      verify: "等待人工验收",
      commit: "等待 Commit 确认",
      bugfix: ({ running: "Bug 定向修改中", review: "Bug Review 等待继续修改", verify: "等待 Bug 人工复验", commit: "等待 Bug 修复 Commit" })[task.bugfix?.status] || "等待 Bug 反馈或进入沉淀",
      knowledge: ({ queued: "沉淀提炼排队中", running: "正在提炼沉淀候选", ready: "等待审核沉淀候选", error: "沉淀提炼需要处理", interrupted: "沉淀提炼已中断" })[task.knowledge?.status] || "等待生成沉淀候选"
    };
    return map[task.stage] || "等待操作";
  }

  function jobLabel(value) {
    return ({ discussion: "需求讨论", plan: "Plan 生成", worktree: "Worktree 创建", execution: "Plan 执行", knowledge: "沉淀提炼", ask: "Ask 只读问答" })[value] || value;
  }

  function render() {
    destroySectionNavigator();
    workspaceRefreshPending = false;
    renderShell();
    const knowledgeCenterActive = ui.module === "knowledge-center";
    const stageId = currentStageId();
    const askActive = Boolean(task && ui.module === "ask");
    const completedStageView = !knowledgeCenterActive && !askActive && isCompletedStageView(stageId);
    const meta = knowledgeCenterActive ? knowledgeCenterModule : askActive ? askModule : stages.find((item) => item.id === stageId) || stages[0];
    stageTitleEl.textContent = completedStageView
      ? `${meta.title} · 只读回看`
      : knowledgeCenterActive || askActive ? meta.title : task?.git?.committed && stageId === "commit" ? "Commit 已完成" : meta.title;
    stageDescriptionEl.textContent = completedStageView
      ? "该阶段已经完成，仅展示当时结果；所有会改变流程或重复执行的操作均已锁定。"
      : meta.description;
    const renderers = { input: renderInput, discuss: renderDiscuss, plan: renderPlan, worktree: renderWorktree, execute: renderExecute, verify: renderVerify, commit: renderCommit, bugfix: renderBugfix, knowledge: renderKnowledge };
    const archiveNotice = task?.archivedAt
      ? callout(`<strong>该任务已归档。</strong> 当前仅供回看；请从左侧归档列表恢复后再继续执行。`, "warning")
      : "";
    const activeStageId = activeFlowStageId();
    const currentMeta = stages.find((item) => item.id === activeStageId);
    const completedNotice = completedStageView
      ? `<section class="completed-stage-notice">${callout(`<strong>已完成阶段，只读回看。</strong> 为避免误判进度或重复执行，本阶段的输入和执行入口已锁定。当前进度：${escapeHTML(currentMeta?.label || activeStageId)}。`, "ok")}<button class="primary" id="goActiveStage" data-readonly-view type="button">返回当前阶段</button></section>`
      : "";
    const stageView = knowledgeCenterActive
      ? renderKnowledgeCenter()
      : askActive
        ? renderAsk()
        : `<div class="flow-stage-view ${completedStageView ? "completed-stage-view" : ""}">${renderers[stageId]()}</div>`;
    stageContentEl.innerHTML = knowledgeCenterActive
      ? stageView
      : `${archiveNotice}${renderCodexAppPanel()}${renderAgentMemory()}${completedNotice}${stageView}`;
    document.querySelector(".app-shell")?.classList.toggle("verification-layout-active", Boolean(stageContentEl.querySelector(".verification-case-layout")));
    attachHandlers(knowledgeCenterActive ? "knowledge-center" : askActive ? "ask" : stageId);
    if (completedStageView) lockCompletedStageView(stageContentEl);
    if (!knowledgeCenterActive && task?.archivedAt) {
      stageContentEl.querySelectorAll("button, input, textarea, select").forEach((control) => { control.disabled = true; });
    }
    setupSectionNavigator(knowledgeCenterActive ? "knowledge-center" : askActive ? "ask" : stageId);
    saveUi();
  }

  function destroySectionNavigator() {
    sectionNavigatorCleanup?.();
    sectionNavigatorCleanup = null;
    document.querySelector("#sectionNavigator")?.remove();
  }

  function sectionTitle(section) {
    const explicit = section.dataset.sectionTitle?.trim();
    if (explicit) return explicit;
    const heading = section.querySelector(":scope > h3, :scope > .section-heading h3, :scope > .progress-heading h3");
    if (heading?.textContent.trim()) return heading.textContent.trim();
    const fieldTitle = section.querySelector(":scope > .field > label, :scope > .field > span");
    if (fieldTitle?.textContent.trim()) return fieldTitle.textContent.trim();
    const summaryTitle = section.querySelector(":scope > .summary-grid .summary-item:first-child > span");
    return summaryTitle?.textContent.trim() || "";
  }

  function sectionSnapshot(section, title) {
    const preferred = section.querySelector(":scope > .section-copy, :scope > .summary-grid .summary-item:first-child strong, :scope > .callout, :scope > .checklist .check-row div span, :scope > .acceptance-log-list .acceptance-log-head strong, :scope > .field .hint, :scope > p");
    const raw = (preferred?.textContent || section.textContent || "").replace(/\s+/g, " ").trim();
    const snapshot = raw.startsWith(title) ? raw.slice(title.length).trim() : raw;
    if (!snapshot) return "打开查看本段内容";
    return snapshot.length > 82 ? `${snapshot.slice(0, 82)}…` : snapshot;
  }

  function setupSectionNavigator(stageId) {
    const stageRoot = stageContentEl.querySelector(".flow-stage-view") || stageContentEl;
    const sections = Array.from(stageRoot.querySelectorAll(".section"))
      .map((element) => {
        const title = sectionTitle(element);
        return { element, title, snapshot: sectionSnapshot(element, title) };
      })
      .filter((item) => item.title && !item.element.closest("details"));
    if (sections.length < 2) return;

    sections.forEach((item, index) => {
      item.element.id = `stage-section-${stageId}-${index + 1}`;
      item.element.classList.add("stage-section-anchor");
    });

    const navigator = document.createElement("aside");
    navigator.className = "section-navigator";
    navigator.id = "sectionNavigator";
    navigator.setAttribute("aria-label", "当前页面段落导航");
    navigator.innerHTML = `<div class="section-navigator-panel" id="sectionNavigatorPanel" aria-hidden="true"><div class="section-navigator-head"><strong>段落与快照</strong><span>${sections.length} 个</span></div><nav class="section-navigator-list" aria-label="段落标题">${sections.map((item, index) => `<button class="section-navigator-item" type="button" data-section-jump="${index}" title="跳转到：${escapeHTML(item.title)}"><span class="section-navigator-index">${String(index + 1).padStart(2, "0")}</span><span class="section-navigator-copy"><span class="section-navigator-label">${escapeHTML(item.title)}</span><small class="section-navigator-snapshot">${escapeHTML(item.snapshot)}</small></span></button>`).join("")}</nav></div><button class="section-navigator-toggle" type="button" aria-expanded="false" aria-controls="sectionNavigatorPanel" aria-label="段落导航，悬停展开" title="悬停查看段落">${sections.slice(0, 5).map((_, index) => `<span class="section-navigator-line ${index === 0 ? "is-active" : ""}" data-section-marker="${index}" aria-hidden="true"></span>`).join("")}</button>`;
    document.body.append(navigator);

    const toggle = navigator.querySelector(".section-navigator-toggle");
    const panel = navigator.querySelector(".section-navigator-panel");
    const items = Array.from(navigator.querySelectorAll("[data-section-jump]"));
    const markers = Array.from(navigator.querySelectorAll("[data-section-marker]"));
    let activeIndex = 0;
    let scrollFrame = 0;
    let open = false;

    const setOpen = (nextOpen) => {
      open = nextOpen;
      navigator.classList.toggle("is-open", nextOpen);
      panel.setAttribute("aria-hidden", String(!nextOpen));
      toggle.setAttribute("aria-expanded", String(nextOpen));
      toggle.setAttribute("aria-label", nextOpen ? "段落导航已展开" : "段落导航，悬停展开");
    };
    const setActive = (index) => {
      if (index === activeIndex && items[index]?.classList.contains("is-active")) return;
      activeIndex = index;
      items.forEach((item, itemIndex) => {
        const active = itemIndex === index;
        item.classList.toggle("is-active", active);
        if (active) item.setAttribute("aria-current", "location");
        else item.removeAttribute("aria-current");
      });
      const markerIndex = Math.min(index, markers.length - 1);
      markers.forEach((marker, itemIndex) => marker.classList.toggle("is-active", itemIndex === markerIndex));
      toggle.title = `当前：${sections[index].title}`;
    };
    const updatePosition = () => {
      const workspace = document.querySelector(".workspace");
      if (!workspace) return;
      const workspaceRect = workspace.getBoundingClientRect();
      const workflowRect = document.querySelector(".workflow-sidebar")?.getBoundingClientRect();
      const gapLeft = workflowRect?.right ?? workspaceRect.left - 18;
      const gapWidth = Math.max(1, Math.round(workspaceRect.left - gapLeft));
      navigator.style.setProperty("--section-nav-left", `${Math.round(gapLeft)}px`);
      navigator.style.setProperty("--section-nav-width", `${gapWidth}px`);
      const stageVisible = workspaceRect.top < window.innerHeight - 150 && workspaceRect.bottom > 150;
      navigator.classList.toggle("is-outside-stage", !stageVisible);
    };
    const updateActive = () => {
      scrollFrame = 0;
      const threshold = Math.min(180, window.innerHeight * .28);
      let nextIndex = 0;
      sections.forEach((item, index) => {
        if (item.element.getBoundingClientRect().top <= threshold) nextIndex = index;
      });
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 8) nextIndex = sections.length - 1;
      setActive(nextIndex);
      updatePosition();
    };
    const onScroll = () => {
      if (!scrollFrame) scrollFrame = window.requestAnimationFrame(updateActive);
    };
    const onDocumentClick = (event) => {
      if (!navigator.contains(event.target)) setOpen(false);
    };
    const onKeydown = (event) => {
      if (event.key === "Escape" && open) {
        toggle.focus();
        setOpen(false);
      }
    };

    navigator.addEventListener("pointerenter", () => setOpen(true));
    navigator.addEventListener("pointerleave", () => setOpen(false));
    navigator.addEventListener("focusin", () => setOpen(true));
    navigator.addEventListener("focusout", (event) => {
      if (!navigator.contains(event.relatedTarget)) setOpen(false);
    });
    toggle.addEventListener("click", () => setOpen(true));
    items.forEach((button, index) => button.addEventListener("click", () => {
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      sections[index].element.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
      setActive(index);
      setOpen(false);
    }));
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", updatePosition, { passive: true });
    document.addEventListener("click", onDocumentClick);
    document.addEventListener("keydown", onKeydown);
    updatePosition();
    setActive(0);
    updateActive();

    sectionNavigatorCleanup = () => {
      if (scrollFrame) window.cancelAnimationFrame(scrollFrame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", updatePosition);
      document.removeEventListener("click", onDocumentClick);
      document.removeEventListener("keydown", onKeydown);
      navigator.remove();
    };
  }

  function renderShell() {
    renderTaskConsole();
    renderSteps();
    globalStatusEl.textContent = statusText();
    const statusTextEl = globalStatusEl.closest(".status-text");
    statusTextEl?.classList.toggle("is-running", Boolean(task?.activeJob) && task?.jobState !== "queued");
    statusTextEl?.classList.toggle("is-queued", Boolean(task?.activeJob) && task?.jobState === "queued");
    saveUi();
  }

  function stageEditorFocused() {
    const active = document.activeElement;
    return Boolean(active && stageContentEl.contains(active) && active.matches("input, textarea, select, [contenteditable='true']"));
  }

  function taskManagementReady() {
    return Boolean(health?.features?.taskManagement);
  }

  function taskStateLabel(item) {
    if (item.archivedAt) return "已归档";
    const bugfixExecution = item.activeJob === "execution" && item.stage === "bugfix";
    const executionPhase = item.executionPhase || (item.id === task?.id ? task.execution?.phase || "" : "");
    if (item.state === "queued") return "排队中";
    if (item.state === "running") {
      if (bugfixExecution) return executionPhase === "review" ? "Bug Review 中" : "Bug 修改中";
      return `${jobLabel(item.activeJob)}中`;
    }
    if (item.state === "done") return "已完成";
    if (item.state === "error") return "需要处理";
    return "等待操作";
  }

  function renderTaskConsole() {
    const activeTasks = taskSummaries.filter((item) => !item.archivedAt);
    const archivedTasks = taskSummaries.filter((item) => item.archivedAt);
    const groups = {
      all: activeTasks,
      running: activeTasks.filter((item) => ["running", "queued"].includes(item.state)),
      attention: activeTasks.filter((item) => ["attention", "error"].includes(item.state)),
      done: activeTasks.filter((item) => item.state === "done")
    };
    const activeFilter = groups[ui.taskFilter] ? ui.taskFilter : "all";
    const labels = { all: "全部", running: "运行", attention: "待处理", done: "完成" };
    document.querySelectorAll("[data-task-filter]").forEach((button) => {
      const id = button.dataset.taskFilter;
      button.classList.toggle("active", id === activeFilter);
      button.textContent = `${labels[id]} ${groups[id].length}`;
      button.setAttribute("aria-pressed", id === activeFilter ? "true" : "false");
    });
    taskFiltersEl.hidden = ui.showArchived;
    taskQueueTitleEl.textContent = ui.showArchived ? "归档任务" : "需求队列";
    knowledgeCenterButtonEl.textContent = ui.module === "knowledge-center" ? "返回任务" : "沉淀中心";
    knowledgeCenterButtonEl.setAttribute("aria-pressed", ui.module === "knowledge-center" ? "true" : "false");
    knowledgeCenterButtonEl.disabled = busy || !health?.features?.knowledge;
    archiveViewButtonEl.textContent = ui.showArchived ? "返回队列" : `查看归档${archivedTasks.length ? ` ${archivedTasks.length}` : ""}`;
    archiveViewButtonEl.setAttribute("aria-pressed", ui.showArchived ? "true" : "false");
    const managementReady = taskManagementReady();
    archiveViewButtonEl.disabled = busy || !managementReady;
    archiveViewButtonEl.title = managementReady ? "" : "等待当前后台任务结束后安全更新本地服务";
    createTaskButtonEl.disabled = busy;
    taskCountEl.textContent = ui.showArchived
      ? `${archivedTasks.length} 条归档任务`
      : `${activeTasks.length} 条需求 · ${scheduler.runningJobs || 0} 运行${scheduler.queuedJobs ? ` / ${scheduler.queuedJobs} 排队` : ""}`;
    schedulerNoteEl.textContent = ui.showArchived
      ? "恢复后任务会回到原阶段；删除不会清理 Worktree、Plan 或 HTML。"
      : `最多并行 ${scheduler.maxConcurrentJobs || 2} 个后台任务；切换查看不会停止执行。`;
    const visible = ui.showArchived ? archivedTasks : groups[activeFilter];
    taskListEl.innerHTML = visible.length ? visible.map((item) => {
      const stage = stages.find((entry) => entry.id === item.stage)?.label || item.stage;
      const intake = ({ quick_change: "轻量直改", existing_requirement: "已有文档", existing_plan: "已有 Plan" })[item.intakeMode];
      const selected = item.id === task?.id;
      const action = item.archivedAt ? "restore" : "archive";
      const actionLabel = item.archivedAt ? "恢复" : "归档";
      const locked = busy || !managementReady || Boolean(item.activeJob);
      const lockTitle = item.activeJob
        ? "任务正在执行，完成后才能操作"
        : managementReady ? "" : "等待当前后台任务结束后安全更新本地服务";
      return `<article class="task-card ${selected ? "active" : ""}" data-state="${escapeHTML(item.state)}">
        <button type="button" class="task-card-main" data-task-open="${escapeHTML(item.id)}" ${selected ? 'aria-current="true"' : ""}>
          <span class="task-card-title">${escapeHTML(item.title)}</span>
          <span class="task-card-meta"><span>${escapeHTML(intake ? `${stage} · ${intake}` : stage)}</span><span>${escapeHTML(formatDateTime(item.archivedAt || item.updatedAt))}</span></span>
          <span class="task-card-state"><strong>${escapeHTML(taskStateLabel(item))}</strong><span>Agent ${escapeHTML(item.agent?.id || item.id.slice(0, 8))} · ${Number(item.agent?.sessionCount || 0)} 会话${item.appLinked ? " · App" : ""}</span></span>
        </button>
        <div class="task-card-actions"><button type="button" class="task-card-action" data-task-action="${action}" data-task-id="${escapeHTML(item.id)}" ${locked ? "disabled" : ""} title="${escapeHTML(lockTitle)}">${actionLabel}</button><button type="button" class="task-card-action danger" data-task-action="delete" data-task-id="${escapeHTML(item.id)}" ${locked ? "disabled" : ""} title="${escapeHTML(lockTitle)}">删除</button></div>
      </article>`;
    }).join("") : `<p class="task-empty">${ui.showArchived ? "还没有归档任务。" : activeFilter === "all" ? "还没有需求，点击上方“新建”。" : "当前筛选下没有需求。"}</p>`;
  }

  function renderSteps() {
    const current = Math.max(0, stages.findIndex((item) => item.id === currentStageId()));
    const furthest = task ? Math.max(0, Number(task.maxStageIndex) || 0) : 0;
    const flowSteps = stages.map((item, index) => {
      const reached = index <= furthest;
      const completed = isCompletedStage(item.id);
      const active = ui.module === "flow" && index === current;
      const cls = `${completed ? "completed" : ""} ${active ? "current" : ""}`.trim();
      const title = completed ? "已完成，仅供只读回看" : active ? "当前阶段" : reached ? "已到达" : "尚未到达";
      return `<button type="button" class="step ${cls}" data-stage-jump="${item.id}" ${reached ? "" : "disabled"} ${active ? 'aria-current="step"' : ""} title="${title}"><span class="step-number">${completed ? "✓" : index + 1}</span><span class="step-label">${item.label}</span>${completed ? '<span class="step-state">只读</span>' : ""}</button>`;
    }).join("");
    const askStep = `<div class="ask-module-nav"><button type="button" class="step ask-step ${ui.module === "ask" ? "current" : ""}" data-module-jump="ask" ${task ? "" : "disabled"} ${ui.module === "ask" ? 'aria-current="page"' : ""}><span class="step-number">?</span><span class="step-label">Ask · 只读问答</span></button><small>不改变流程阶段</small></div>`;
    stepsEl.innerHTML = `${flowSteps}${askStep}`;
  }

  function callout(text, type = "warning") {
    return `<div class="callout ${type}"><p>${text}</p></div>`;
  }

  function renderCodexAppPanel() {
    if (!task || !health?.features?.codexAppLink) return "";
    const app = task.app || {};
    const threadId = String(app.threadId || task.sessions?.app || "");
    const deepLink = app.deepLink || (threadId && /^[A-Za-z0-9_-]+$/.test(threadId) ? `codex://threads/${encodeURIComponent(threadId)}` : "");
    const linked = Boolean(threadId && deepLink);
    const status = ({
      idle: "尚未连接",
      ready: "已连接",
      running: "同一 Thread 正在执行",
      error: "连接需要处理",
      interrupted: "服务重启后可恢复"
    })[app.status] || (linked ? "已连接" : "尚未连接");
    const switchLocked = busy || Boolean(task.activeJob) || app.status === "running";
    const switchTitle = switchLocked ? "当前任务正在执行，完成或停止后才能切换聊天" : "";
    const action = task.archivedAt
      ? '<span class="app-link-button disabled">任务已归档</span>'
      : linked
        ? `<div class="app-thread-actions"><button class="app-link-button primary" id="openCodexApp" type="button" ${busy ? "disabled" : ""}>打开 Codex App</button><div class="app-thread-tools"><button id="newCodexAppChat" type="button" ${switchLocked ? "disabled" : ""} title="${escapeHTML(switchTitle)}">新建聊天</button><button class="danger" id="disconnectCodexApp" type="button" ${switchLocked ? "disabled" : ""} title="${escapeHTML(switchTitle)}">断开连接</button></div></div>`
        : `<button class="primary" id="openCodexApp" type="button" ${busy ? "disabled" : ""}>新建聊天并在 Codex App 打开</button>`;
    const workspace = app.cwd || (task.worktree?.status === "ready" ? task.worktree.path : health?.paths?.repo);
    return `<section class="codex-app-panel ${linked ? "linked" : ""}">
      <div class="codex-app-copy"><div class="codex-app-title"><span class="app-status-dot" aria-hidden="true"></span><div><p class="section-kicker">Codex App 联动</p><h3>${escapeHTML(status)}</h3></div></div>
      <p>${linked ? "这个需求已经绑定持久 Thread。控制台负责流程和验收，Codex App 负责交互式查看与随时补充指令。" : "为这个需求创建一个持久 Codex App Thread；后续快速修改会复用它，不必反复恢复上下文。"}</p>
      <div class="codex-app-meta"><span>${linked ? "当前连接目录" : "项目目录"} <code>${escapeHTML(workspace || "尚未绑定")}</code></span>${threadId ? `<span>Thread <code>${escapeHTML(`${threadId.slice(0, 12)}…`)}</code></span>` : ""}</div>
      ${app.error ? `<p class="app-error">${escapeHTML(app.error)}</p>` : ""}</div>
      <div class="codex-app-action">${action}<small>${linked ? "可继续当前聊天，或保留旧聊天后新建一个" : "只建立连接，不会执行 Plan"}</small></div>
    </section>`;
  }

  function renderExecutionModeSelector(context = "execution") {
    if (!health?.features?.quickMode) return "";
    const mode = ui.executionMode === "standard" ? "standard" : "fast";
    ui.executionMode = mode;
    const contextCopy = context === "bugfix"
      ? "本轮只处理 Bug 与直接回归。"
      : context === "acceptance"
        ? "退回后只处理本条人工验收反馈。"
        : "两种模式都只写当前 Worktree。";
    return `<section class="section execution-mode-section"><div class="section-heading"><div><p class="section-kicker">执行方式</p><h3>选择本轮速度</h3></div><span class="hint">${contextCopy}</span></div>
      <div class="execution-mode-grid" role="radiogroup" aria-label="选择执行方式">
        <label class="execution-mode-card ${mode === "fast" ? "selected" : ""}"><input type="radio" name="executionMode" value="fast" data-execution-mode="fast" ${mode === "fast" ? "checked" : ""}><span class="mode-card-head"><strong>快速修改</strong><em>推荐</em></span><span>复用持久 App Thread，一轮完成实现与自检；跳过第二个独立 Review。</span><small>仍保留人工验收与 Commit 门禁</small></label>
        <label class="execution-mode-card ${mode === "standard" ? "selected" : ""}"><input type="radio" name="executionMode" value="standard" data-execution-mode="standard" ${mode === "standard" ? "checked" : ""}><span class="mode-card-head"><strong>标准流程</strong><em>更完整</em></span><span>继续使用 codex exec，并启动独立 Code Review；更稳但耗时更长。</span><small>适合大改动、共享逻辑和高风险需求</small></label>
      </div>
    </section>`;
  }

  function eventLogDetails() {
    if (!task) return "";
    const operation = task.activeJob ? task[task.activeJob] : null;
    const logs = [...(task.events || []), ...(operation?.logs || [])].slice(-30).reverse();
    const rows = logs.length
      ? logs.map((item) => `<div class="event-row"><span class="mono">${escapeHTML(formatTime(item.time))}</span><span>${escapeHTML(item.message)}</span></div>`).join("")
      : '<span class="hint">还没有状态事件。</span>';
    return `<details><summary>查看真实状态记录</summary><div class="event-log">${rows}</div></details>`;
  }

  function memoryBlock(title, items) {
    const values = (items || []).filter(Boolean).slice(0, 8);
    if (!values.length) return "";
    return `<section class="agent-memory-block"><h3>${escapeHTML(title)}</h3><ul>${values.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul></section>`;
  }

  function renderAgentMemory() {
    if (!task) return "";
    const memory = task.agentMemory || {};
    const sessions = memory.sessions || {};
    const sessionCount = Object.values(sessions).filter(Boolean).length;
    const sessionSummary = ["discussion", "execution", "review", "ask", "app"]
      .map((key) => `${key}: ${sessions[key] ? `${String(sessions[key]).slice(0, 8)}…` : "未建立"}`)
      .join(" · ");
    const boundary = [...(memory.nonScope || []), ...(memory.assumptions || []).map((item) => `假设：${item}`)];
    const blocks = [
      memoryBlock("已确认事实", memory.confirmedFacts),
      memoryBlock("用户决策", memory.decisions),
      memoryBlock("范围与边界", [...(memory.scope || []), ...boundary]),
      memoryBlock("相关文件", memory.relevantFiles),
      memoryBlock("已完成步骤", memory.completedSteps),
      memoryBlock("验证证据", memory.verificationEvidence)
    ].filter(Boolean).join("");
    return `<details class="agent-memory" id="agentMemoryPanel" ${ui.agentMemoryOpen ? "open" : ""}><summary><span>逻辑 Agent ${escapeHTML(String(memory.logicalAgentId || task.id).slice(0, 8))} 的持久记忆</span><small>记忆 v${escapeHTML(memory.version || 1)} · ${sessionCount} 个会话 · ${escapeHTML(formatDateTime(memory.updatedAt || task.updatedAt))}</small></summary>
      <div class="agent-memory-body"><p>${escapeHTML(memory.summary || task.title)}</p><p class="agent-next">下一步：${escapeHTML(memory.nextAction || "按当前流程继续。")}</p>
      <div class="agent-memory-meta"><div><span>持久会话</span><strong class="mono">${escapeHTML(sessionSummary)}</strong></div><div><span>Plan 指纹</span><strong class="mono">${escapeHTML(memory.fingerprints?.planSha256 ? `${memory.fingerprints.planSha256.slice(0, 12)}…` : "尚未生成")}</strong></div><div><span>Worktree 目标</span><strong class="mono">${escapeHTML(memory.workspace?.worktree || "尚未创建")}</strong></div></div>
      ${blocks ? `<div class="agent-memory-grid">${blocks}</div>` : ""}</div></details>`;
  }

  function multilineHTML(value) {
    return escapeHTML(value || "").replaceAll("\n", "<br>");
  }

  function renderAsk() {
    const section = task.ask || { status: "idle", messages: [], logs: [], error: "" };
    const messages = section.messages || [];
    const conversation = messages.length
      ? messages.map((message) => {
        const evidence = (message.evidence || []).length
          ? `<div class="ask-evidence"><strong>依据</strong><ul>${message.evidence.map((item) => `<li><code>${escapeHTML(item.path)}</code><span>${escapeHTML(item.detail)}</span></li>`).join("")}</ul></div>`
          : "";
        const uncertainties = (message.uncertainties || []).length
          ? `<div class="ask-uncertainties"><strong>尚不能确认</strong><ul>${message.uncertainties.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul></div>`
          : "";
        const answer = message.answer
          ? `<div class="message ask-answer"><span class="message-role">Codex · Ask</span><p>${multilineHTML(message.answer)}</p>${evidence}${uncertainties}</div>`
          : `<div class="message"><span class="message-role">Codex · Ask</span><span class="hint">${section.status === "error" ? "本次回答失败，可在下方重新提问。" : "正在基于当前代码和任务事实查找答案……"}</span></div>`;
        return `<div class="message user"><span class="message-role">你 · ${escapeHTML(formatDateTime(message.askedAt))}</span>${multilineHTML(message.question)}</div>${answer}`;
      }).join("")
      : '<div class="message"><span class="message-role">Codex · Ask</span>可以询问“当前功能怎么实现”“状态从哪里读取”“涉及哪些文件”等问题。本模块严格只读。</div>';
    const running = ["queued", "running"].includes(section.status) && task.activeJob === "ask";
    const blocked = busy || Boolean(task.activeJob);
    const error = section.status === "error" ? callout(`<strong>Ask 失败：</strong>${escapeHTML(section.error)}`, "danger") : "";
    return `<section class="section">${callout("<strong>独立只读模块。</strong> Ask 会复用当前任务、Plan、持久记忆和已绑定 Worktree，只回答实现问题；不会写文件、执行 Plan 或改变当前流程阶段。", "ok")}${error}</section>
      <section class="section"><h3>问答记录</h3><div class="conversation ask-conversation">${conversation}</div></section>
      ${running ? renderProgress(section, "Ask 正在检查当前实现") : ""}
      <section class="section"><div class="field"><label for="askQuestion">询问当前实现</label><textarea id="askQuestion" maxlength="4000" placeholder="例如：这个功能现在是怎么实现的？状态保存在哪里？哪些文件负责这条调用链？" ${blocked ? "disabled" : ""}>${escapeHTML(ui.askQuestion)}</textarea><div class="source-tabs ask-templates" role="group" aria-label="Ask 快捷问题"><button type="button" data-ask-template="这个功能当前是怎么实现的？请说明关键调用链和相关文件。" ${blocked ? "disabled" : ""}>当前怎么实现</button><button type="button" data-ask-template="这个状态从哪里读取、在哪里更新和保存？" ${blocked ? "disabled" : ""}>状态从哪里来</button><button type="button" data-ask-template="如果要修改这块逻辑，最小影响范围和主要风险是什么？只分析，不要修改。" ${blocked ? "disabled" : ""}>修改影响范围</button></div><span class="hint">Ask 使用独立只读 Codex 会话，并在当前任务内保留对话记录。</span></div></section>
      <div class="actions"><div class="actions-secondary">${running ? '<button class="danger" id="cancelAsk">停止 Ask</button>' : '<span class="hint">当前任务有其他后台操作时，Ask 会暂时禁用。</span>'}</div><div class="actions-primary"><button class="primary" id="submitAsk" ${blocked || !ui.askQuestion.trim() ? "disabled" : ""}>发送问题</button></div></div>${running ? "" : eventLogDetails()}`;
  }

  function estimateProgress(section) {
    if (section?.status === "queued") return { value: 5, label: "等待执行槽位" };
    const messages = (section?.logs || []).map((item) => String(item.message || ""));
    let value = messages.length ? 10 : 8;
    let label = "正在启动";
    if (messages.some((message) => message.includes("启动 ") && message.includes("阶段"))) {
      value = Math.max(value, 12);
      label = "启动执行环境";
    }
    if (messages.some((message) => message.includes("会话已启动"))) {
      value = Math.max(value, 20);
      label = "建立 Codex 会话";
    }
    if (messages.some((message) => message.includes("正在读取事实"))) {
      value = Math.max(value, 30);
      label = "读取项目与任务上下文";
    }
    const activityMessages = messages.filter((message) => ["执行检查", "检查结束", "已应用文件改动", "已返回本阶段结果"].some((marker) => message.includes(marker)));
    if (activityMessages.length) {
      value = Math.max(value, Math.min(78, 40 + activityMessages.length * 5));
      label = messages.some((message) => message.includes("已应用文件改动")) ? "落地修改与自检" : messages.some((message) => message.includes("执行检查") || message.includes("检查结束")) ? "执行检查与验证" : "处理当前阶段结果";
    }
    if (section?.phase === "review") {
      value = Math.max(value, 88);
      label = "Code Review 与结果复核";
    } else if (section?.phase === "stopping") {
      label = "正在安全停止";
    }
    return { value, label };
  }

  function renderProgress(section, title) {
    const queued = section?.status === "queued";
    const logs = section?.logs || [];
    const estimate = estimateProgress(section);
    const rows = logs.length
      ? logs.slice(-12).map((item, index) => `<div class="run-step ${index === logs.length - 1 ? "running" : "done"}"><span class="run-mark">${index === logs.length - 1 ? "…" : "✓"}</span><div><strong>${escapeHTML(item.message)}</strong><div class="hint">${escapeHTML(formatTime(item.time))}</div></div><small>${index === logs.length - 1 ? "进行中" : "完成"}</small></div>`).join("")
      : `<div class="run-step running"><span class="run-mark">…</span><div><strong>${escapeHTML(title)}</strong><div class="hint">${queued ? "等待空闲并发槽位" : "等待 Codex 返回第一条事件"}</div></div><small>${queued ? "排队" : "进行中"}</small></div>`;
    const activity = `<span class="activity-state ${queued ? "queued" : ""}"><span class="activity-dots" aria-hidden="true"><i></i><i></i><i></i></span>${queued ? "排队等待" : "持续执行中"}</span>`;
    return `<section class="section">${callout(`<strong>${escapeHTML(title)}</strong> ${queued ? "任务已进入后台队列。" : "本地服务正在运行受控操作。"} 你可以切换查看其他需求；刷新后仍可恢复状态。`, "warning")}</section><section class="section progress-section" aria-live="polite"><div class="progress-heading"><h3>实时进度</h3>${activity}</div><div class="progress-estimate"><span>${escapeHTML(estimate.label)}</span><strong>${estimate.value}%</strong></div><div class="progress-track ${queued ? "queued" : ""}" role="progressbar" aria-label="预计执行进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${estimate.value}" aria-valuetext="${escapeHTML(estimate.label)}，预计 ${estimate.value}%"><span style="--progress-value:${estimate.value}%"></span></div><p class="progress-caption">按实时日志里程碑估算，仅表示当前执行阶段，不代表精确剩余时间。</p><div class="run-list">${rows}</div></section>${eventLogDetails()}`;
  }

  function renderInput() {
    const warning = !health?.ok
      ? callout(`<strong>本地服务不可用。</strong> ${(health?.warnings || []).map(escapeHTML).join(" ")}`, "danger")
      : (health.warnings || []).map((item) => callout(escapeHTML(item), "warning")).join("");
    const larkCli = health?.readers?.larkCli || { installed: false, authenticated: false, ready: false, version: "未安装", message: "需要先完成安装与授权。" };
    const larkCliReady = Boolean(larkCli.ready);
    const selectedLarkReader = ui.larkReader === "lark_cli" && larkCliReady ? "lark_cli" : "chrome_mcp";
    ui.larkReader = selectedLarkReader;
    const quickWorkflow = ui.workflowMode === "quick";
    ui.workflowMode = quickWorkflow ? "quick" : "standard";
    if (quickWorkflow) ui.sourceType = "paste";
    const larkReaderOptions = `<div id="larkReaderOptions" class="reader-mode-section" ${isLarkLink(ui.sourceUrl) ? "" : "hidden"}><div class="field-label-row"><span>飞书读取方式</span><span class="hint">仅对飞书 / Lark 链接生效</span></div>
      <div class="execution-mode-grid reader-mode-grid" role="radiogroup" aria-label="选择飞书读取方式">
        <label class="execution-mode-card ${selectedLarkReader === "chrome_mcp" ? "selected" : ""}"><input type="radio" name="larkReader" value="chrome_mcp" data-lark-reader="chrome_mcp" ${selectedLarkReader === "chrome_mcp" ? "checked" : ""}><span class="mode-card-head"><strong>Chrome MCP</strong><em>默认</em></span><span>复用当前 Chrome 登录态打开网页，只读提取需求内容。</span><small>无需配置飞书应用；页面结构变化时可能受影响</small></label>
        <label class="execution-mode-card ${selectedLarkReader === "lark_cli" ? "selected" : ""} ${larkCliReady ? "" : "disabled"}"><input type="radio" name="larkReader" value="lark_cli" data-lark-reader="lark_cli" ${selectedLarkReader === "lark_cli" ? "checked" : ""} ${larkCliReady ? "" : "disabled"}><span class="mode-card-head"><strong>官方 Lark CLI</strong><em>${larkCliReady ? "稳定读取" : "待配置"}</em></span><span>通过飞书官方接口和只读 Agent Skills 读取 Wiki / 文档正文。</span><small>${escapeHTML(larkCli.message)}${larkCliReady ? ` · ${escapeHTML(larkCli.version)}` : ""}</small></label>
      </div><span class="hint">Lark CLI 只用于读取需求；不会在 discussion 中创建、覆盖、移动或分享飞书内容，也不会自动扩大授权。</span></div>`;
    const panels = {
      link: `<div class="field"><label for="sourceUrl">策划文档链接</label><input id="sourceUrl" type="url" placeholder="https://docs.example.com/..." value="${escapeHTML(ui.sourceUrl)}"><span class="hint">飞书 / Lark 链接可选择 Chrome MCP 或已配置的官方 Lark CLI；其他公开链接由 Codex 尝试读取。</span>${larkReaderOptions}</div>`,
      file: `<div class="field"><label for="sourceFile">选择策划文档</label><input id="sourceFile" type="file" accept=".md,.txt,.pdf,.doc,.docx,.html"><span class="hint">${selectedFile ? `已选择：${escapeHTML(selectedFile.name)}` : ui.sourceFileName ? `刷新后需重新选择：${escapeHTML(ui.sourceFileName)}` : "文件保存在本地任务运行目录，最大 8 MB。"}</span></div>`,
      paste: `<div class="field"><label for="sourceText">粘贴策划内容</label><textarea id="sourceText" placeholder="粘贴需求目标、规则、流程或已有草稿……">${escapeHTML(ui.sourceText)}</textarea><span class="hint">材料会作为不可信需求输入交给只读 Codex 会话，不会被当作控制指令。</span></div>`
    };
    const intakeOptions = [
      { id: "new", label: "新需求" },
      { id: "existing_requirement", label: "已有需求文档" },
      { id: "existing_plan", label: "已有执行 Plan" }
    ];
    const selectedBranch = ui.baseBranch || health?.project?.defaultBaseBranch || "main";
    const knownBranches = new Set(projectBranches.map((item) => item.name));
    const branchOption = (item) => {
      const markers = [item.current ? "主仓库当前" : "", item.default ? "Profile 默认" : ""].filter(Boolean);
      return `<option value="${escapeHTML(item.name)}" ${item.name === selectedBranch ? "selected" : ""}>${escapeHTML(item.name)}${markers.length ? `（${escapeHTML(markers.join(" / "))}）` : ""}</option>`;
    };
    const localBranches = projectBranches.filter((item) => item.kind === "local");
    const remoteBranches = projectBranches.filter((item) => item.kind === "remote");
    const savedBranchOption = selectedBranch && !knownBranches.has(selectedBranch)
      ? `<option value="${escapeHTML(selectedBranch)}" selected>${escapeHTML(selectedBranch)}（当前保存值）</option>`
      : "";
    const branchOptions = `${savedBranchOption}${localBranches.length ? `<optgroup label="本地分支">${localBranches.map(branchOption).join("")}</optgroup>` : ""}${remoteBranches.length ? `<optgroup label="远端跟踪分支（未 Fetch）">${remoteBranches.map(branchOption).join("")}</optgroup>` : ""}`;
    const branchHint = branchLoadError
      ? `读取主仓库分支失败：${escapeHTML(branchLoadError)} 当前保留 Profile 默认值；可点击刷新重试。`
      : `来自主仓库 ${escapeHTML(health?.paths?.repo || "repoRoot")}：${localBranches.length} 个本地分支、${remoteBranches.length} 个远端跟踪分支；不自动 Fetch，创建前会执行真实 dry-run。`;
    const workflowSelector = `<div class="field"><div class="field-label-row"><span>处理方式</span><span class="hint">按需求风险选择</span></div><div class="execution-mode-grid" role="radiogroup" aria-label="选择需求处理方式">
      <label class="execution-mode-card ${quickWorkflow ? "" : "selected"}"><input type="radio" name="workflowMode" value="standard" data-workflow-mode="standard" ${quickWorkflow ? "" : "checked"}><span class="mode-card-head"><strong>标准需求</strong><em>默认</em></span><span>保留需求澄清、Solution Plan、逻辑 HTML 和可选独立 Review。</span><small>适合链接/文档、规则不明确、跨模块或高风险改动</small></label>
      <label class="execution-mode-card ${quickWorkflow ? "selected" : ""}"><input type="radio" name="workflowMode" value="quick" data-workflow-mode="quick" ${quickWorkflow ? "checked" : ""}><span class="mode-card-head"><strong>轻量直改</strong><em>可选</em></span><span>粘贴明确修改，跳过 discussion、完整 Plan Agent 和 HTML，直接准备 Worktree。</span><small>执行时复用持久 Thread，一轮完成修改与自检</small></label>
    </div></div>`;
    const quickSource = `<div class="field"><label for="sourceText">明确修改内容</label><textarea id="sourceText" maxlength="12000" placeholder="例如：把弹幕停留时间从 2 秒改为 1 秒；只改现有配置与直接相关测试，不调整动画路径。">${escapeHTML(ui.sourceText)}</textarea><span class="hint">最多 12000 字符。提交后本地生成最小执行单，不先调用 Codex；链接、长文档或存在方案分歧时请选标准需求。</span></div>`;
    const standardSource = `<div class="field"><span>需求来源</span><div class="source-tabs" role="group" aria-label="选择需求来源">${["link", "file", "paste"].map((id) => `<button type="button" class="${ui.sourceType === id ? "active" : ""}" data-source-type="${id}">${({ link: "粘贴链接", file: "上传文档", paste: "粘贴内容" })[id]}</button>`).join("")}</div><div class="source-panel">${panels[ui.sourceType]}</div></div>`;
    const newFields = `${workflowSelector}<div class="field"><div class="field-label-row"><label for="baseBranch">Worktree 基准</label><button class="small" id="refreshBranches" type="button" ${busy ? "disabled" : ""}>刷新分支</button></div><select id="baseBranch" class="mono">${branchOptions}</select><span class="hint">${branchHint}</span></div>
      ${quickWorkflow ? quickSource : standardSource}`;
    const isPlan = ui.intakeMode === "existing_plan";
    const existingFields = `${callout(isPlan
      ? `<strong>直接进入执行。</strong> Plan 必须是 Worktree 内或配置的文档目录 <code>${escapeHTML(health?.paths?.docs || "docsRoot")}</code> 内的 UTF-8 Markdown；本步只校验，不运行 Codex。`
      : "<strong>继续需求梳理。</strong> 将读取已有文档完成 discussion、ask-first、Plan 和 HTML；已有 Worktree 只做接入，不创建新目录。", "warning")}
      <div class="field"><label for="existingDocumentPath">${isPlan ? "执行 Plan 绝对路径" : "需求文档绝对路径"}</label><input id="existingDocumentPath" class="mono" type="text" placeholder="${escapeHTML(health?.paths?.workspace || "/absolute/project/path")}/${isPlan ? "plan.md" : "requirement.md"}" value="${escapeHTML(ui.existingDocumentPath)}"><span class="hint">${isPlan ? "仅支持 .md，最大 240 KB。" : "支持 md、txt、pdf、doc、docx、html，文件需位于 Profile 允许的项目路径。"}</span></div>
      <div class="field"><label for="existingWorktreePath">已有 Worktree 绝对路径</label><input id="existingWorktreePath" class="mono" type="text" placeholder="${escapeHTML(health?.paths?.worktrees || "/absolute/worktrees")}/${escapeHTML(health?.project?.worktreeNamePrefix || "Project")}_feature" value="${escapeHTML(ui.existingWorktreePath)}"><span class="hint">必须是当前 Profile 主仓库的独立 linked worktree；会校验 Git 根目录、分支和未完成操作，不切换分支。</span></div>`;
    const intro = ui.intakeMode === "new"
      ? quickWorkflow
        ? "<strong>轻量直改。</strong> 提交后不运行 discussion 或完整 Plan Agent，只生成最小执行单并展示 Worktree dry-run。"
        : "<strong>标准需求流程。</strong> 下一步只启动只读讨论，不写文档、不改代码。"
      : isPlan
        ? "<strong>接入已有执行资产。</strong> 校验通过后直接等待你点击“执行 Plan”。"
        : "<strong>接入已有需求资产。</strong> 校验通过后从只读讨论开始，并复用填写的 Worktree。";
    const actionHint = ui.intakeMode === "new"
      ? quickWorkflow ? "本步仅生成本地执行单并做只读 dry-run；下一步仍需单独确认创建 Worktree。" : "需求讨论使用 read-only sandbox。"
      : ui.intakeMode === "existing_requirement"
        ? "需求讨论使用 read-only sandbox；接入已有路径前先做本地只读校验。"
      : "这一步不运行 Codex、不写文件，只校验 Plan 与 Worktree。";
    const actionLabel = ui.intakeMode === "new" ? quickWorkflow ? "创建轻量直改任务" : "开始梳理需求" : isPlan ? "接入并进入执行" : "接入并开始梳理";
    return `<section class="section">${warning || callout(intro, "ok")}</section>
      <section class="section"><div class="field"><span>任务接入方式</span><div class="source-tabs" role="group" aria-label="选择任务接入方式">${intakeOptions.map((item) => `<button type="button" class="${ui.intakeMode === item.id ? "active" : ""}" data-intake-mode="${item.id}">${item.label}</button>`).join("")}</div></div>
      <div class="field"><label for="taskTitle">需求名称</label><input id="taskTitle" type="text" placeholder="例如：新手免费提示引导" value="${escapeHTML(ui.title)}"></div>
      ${ui.intakeMode === "new" ? newFields : existingFields}</section>
      <div class="actions"><div class="actions-secondary"><span class="hint">${actionHint}</span></div><div class="actions-primary"><button class="primary" id="startDiscussion" type="button" ${health?.ok && !busy ? "" : "disabled"}>${actionLabel}</button></div></div>`;
  }

  function renderDiscuss() {
    const section = task.discussion;
    if (task.activeJob === "plan" || ["queued", "running"].includes(task.plan?.status)) {
      return renderProgress(task.plan, "正在生成 Plan 与逻辑验收 HTML");
    }
    if (["queued", "running"].includes(section.status)) {
      const readerTitles = {
        chrome_mcp: "Chrome MCP 正在只读获取飞书需求并扫描项目事实",
        lark_cli: "官方 Lark CLI 正在只读获取飞书需求并扫描项目事实"
      };
      const title = readerTitles[task.source?.reader] || "discussion-only / ask-first 正在读取项目事实";
      return renderProgress(section, title);
    }
    if (["error", "interrupted"].includes(section.status)) {
      return `<section class="section">${callout(`<strong>讨论阶段未完成：</strong>${escapeHTML(section.error)}`, "danger")}</section><div class="actions"><div class="actions-secondary"><button id="newTaskButton">返回新建需求</button></div></div>${eventLogDetails()}`;
    }
    const result = section.result || {};
    const questions = result.questions || [];
    const messages = (section.messages || []).map((message) => `<div class="message user"><span class="message-role">你</span>${escapeHTML(message.note || Object.values(message.answers || {}).join("；") || "已提交回答")}</div>`).join("");
    const discussionActionLabel = questions.length ? "提交回答，继续讨论" : "发送补充，继续讨论";
    return `<section class="section"><div class="summary-grid"><div class="summary-item"><span>Codex 结论</span><strong>${escapeHTML(result.summary || "已完成事实扫描")}</strong></div><div class="summary-item"><span>Plan 就绪度</span><strong>${result.ready_for_plan ? "可以形成 Solution Plan" : "仍有高返工点待确认"}</strong></div></div></section>
      ${result.confirmed_facts?.length ? `<section class="section"><h3>已确认事实</h3><div class="checklist">${result.confirmed_facts.map((item) => staticCheck(item, "来自项目事实或当前需求材料")).join("")}</div></section>` : ""}
      <section class="section"><h3>Ask-first：${questions.length ? `确认 ${questions.length} 个高返工问题` : "当前没有新的阻塞问题"}</h3><div class="question-list">${questions.map(questionFieldset).join("")}</div></section>
      <section class="section"><h3>继续补充和讨论</h3><div class="conversation">${messages || '<div class="message"><span class="message-role">Codex · discussion-only</span>已读取需求和项目事实，等待你的回答。</div>'}</div><div class="field"><label for="discussionNote">补充说明</label><textarea id="discussionNote" placeholder="补充特殊口径，或在这里继续讨论……">${escapeHTML(ui.discussionNote)}</textarea></div></section>
      <div class="actions"><div class="actions-secondary"><button id="backToInput" type="button">新建另一条需求</button><button id="sendDiscussionNote" type="button">${discussionActionLabel}</button></div><div class="actions-primary"><button class="primary" id="generatePlan" type="button">确认口径并生成 Plan</button></div></div>${eventLogDetails()}`;
  }

  function questionFieldset(question, index) {
    const id = String(question.id || `q${index + 1}`);
    const selected = ui.answers[id] || "";
    return `<fieldset class="question"><legend>${index + 1}. ${escapeHTML(question.question)}</legend><p class="question-help">${escapeHTML(question.reason)}</p>${(question.options || []).map((option) => `<label class="choice"><input type="radio" name="question-${escapeHTML(id)}" data-question-id="${escapeHTML(id)}" value="${escapeHTML(option.value)}" ${selected === option.value ? "checked" : ""}><span>${escapeHTML(option.label)}${option.recommended ? ' <span class="recommended">推荐</span>' : ""}</span></label>`).join("")}
      <label class="choice"><input type="radio" name="question-${escapeHTML(id)}" data-question-id="${escapeHTML(id)}" value="__custom__" ${selected === "__custom__" ? "checked" : ""}><span>自定义回复</span></label>
      <div class="custom-answer" data-custom-wrap="${escapeHTML(id)}" ${selected === "__custom__" ? "" : "hidden"}><label>填写你的口径</label><textarea data-custom-id="${escapeHTML(id)}" placeholder="输入这道问题的自定义答案……">${escapeHTML(ui.customAnswers[id] || "")}</textarea></div></fieldset>`;
  }

  function collectAnswers() {
    const questions = task?.discussion?.result?.questions || [];
    const answers = {};
    for (const [index, question] of questions.entries()) {
      const id = String(question.id || `q${index + 1}`);
      const selected = ui.answers[id];
      if (!selected) throw new Error(`请先回答第 ${index + 1} 个问题。`);
      if (selected === "__custom__") {
        const custom = String(ui.customAnswers[id] || "").trim();
        if (!custom) throw new Error(`请填写第 ${index + 1} 个问题的自定义回复。`);
        answers[id] = custom;
      } else {
        const option = (question.options || []).find((item) => item.value === selected);
        answers[id] = option?.label || selected;
      }
    }
    return answers;
  }

  function renderPlan() {
    const section = task.plan;
    if (["queued", "running"].includes(section.status)) return renderProgress(section, "prd-to-plan / clear-html 正在生成方案草案");
    if (["error", "interrupted"].includes(section.status)) return `<section class="section">${callout(`<strong>Plan 生成失败：</strong>${escapeHTML(section.error)}`, "danger")}</section><div class="actions"><div class="actions-secondary"><button id="returnToDiscuss">返回讨论</button></div><div class="actions-primary"><button class="primary" id="retryPlan">重试生成 Plan</button></div></div>${eventLogDetails()}`;
    if (section.status !== "ready") return renderProgress(section, "等待生成 Plan");
    const result = section.result || {};
    if (task.intake?.mode === "existing_plan") {
      return `<section class="section">${callout("<strong>这是接入的已有执行 Plan。</strong> 控制台不会重新生成或覆盖它；执行前请在下方确认路径和内容。", "warning")}</section>
        <section class="section"><div class="path-list"><div class="path-row"><span>Plan</span><strong class="mono">${escapeHTML(section.finalPath)}</strong></div><div class="path-row"><span>Worktree</span><strong class="mono">${escapeHTML(task.worktree.path)}</strong></div><div class="path-row"><span>分支</span><strong class="mono">${escapeHTML(task.worktree.branch)}</strong></div></div><div class="preview"><pre>${escapeHTML(section.markdown)}</pre></div></section>
        <div class="actions"><div class="actions-secondary"><span class="hint">已有 Plan 已标记为批准；不会在此页面修改文件。</span></div><div class="actions-primary"><button class="primary" id="goCurrentStage">返回执行阶段</button></div></div>${eventLogDetails()}`;
    }
    if (task.intake?.mode === "quick_change") {
      return `<section class="section">${callout("<strong>这是轻量执行单。</strong> 内容直接来自你粘贴的明确修改；没有运行 discussion、完整 Plan Agent 或逻辑 HTML 生成。", "warning")}</section>
        <section class="section"><div class="summary-grid"><div class="summary-item"><span>执行摘要</span><strong>${escapeHTML(result.summary)}</strong></div><div class="summary-item"><span>风险边界</span><strong>跳过独立方案分析与 Review</strong></div></div><div class="preview"><pre>${escapeHTML(section.markdown)}</pre></div></section>
        <div class="actions"><div class="actions-secondary"><span class="hint">如发现需求存在分支或影响范围不明确，请新建标准需求。</span></div><div class="actions-primary"><button class="primary" id="goCurrentStage">返回 Worktree 阶段</button></div></div>${eventLogDetails()}`;
    }
    const logic = `<div class="callout ok"><p><strong>HTML 验收页已落地。</strong> <a href="${escapeHTML(section.htmlUrl)}" target="_blank" rel="noopener">在新窗口打开逻辑验收页</a></p></div><iframe title="逻辑验收 HTML" src="${escapeHTML(section.htmlUrl)}" style="width:100%;height:620px;margin-top:16px;border:1px solid var(--line);background:#fff"></iframe>`;
    const md = `<div class="preview"><pre>${escapeHTML(section.markdown)}</pre></div>`;
    const importedWorktree = task.intake?.mode === "existing_requirement";
    return `<section class="section"><div class="summary-grid"><div class="summary-item"><span>方案摘要</span><strong>${escapeHTML(result.summary)}</strong></div><div class="summary-item"><span>草案状态</span><strong>${section.approved ? "已批准" : "等待逻辑验收"}</strong></div></div></section>
      <section class="section"><div class="view-tabs"><button data-plan-view="logic" class="${ui.planView === "logic" ? "active" : ""}">逻辑 HTML</button><button data-plan-view="md" class="${ui.planView === "md" ? "active" : ""}">Markdown</button></div>${ui.planView === "logic" ? logic : md}</section>
      <section class="section"><h3>验收口径</h3><div class="checklist">${(result.acceptance || []).map((item) => staticCheck(item, "Plan 中的完成标准")).join("")}</div></section>
      <div class="actions"><div class="actions-secondary"><button id="returnToDiscuss" ${section.approved ? "disabled" : ""}>退回讨论</button></div><div class="actions-primary">${section.approved ? '<button class="primary" id="goCurrentStage">返回当前阶段</button>' : `<button class="primary" id="approvePlan">${importedWorktree ? "逻辑没问题，预检已有 Worktree" : "逻辑没问题，批准并预检 Worktree"}</button>`}</div></div>${eventLogDetails()}`;
  }

  function renderWorktree() {
    const section = task.worktree;
    const imported = Boolean(section.imported);
    if (["queued", "running"].includes(section.status)) return renderProgress(section, imported ? "正在重新验证已有 Worktree 并绑定 Plan" : `git-worktree 正在创建${health?.capabilities?.initializeSubmodules ? "并初始化 Submodule" : ""}`);
    const retryHint = imported ? "未覆盖已有文件；请按错误信息处理后重试绑定。" : "如果目录已部分创建，再次点击会只接管本任务预期的路径和分支并重试 Submodule。";
    const error = ["error", "partial", "interrupted"].includes(section.status) ? callout(`<strong>Worktree 未完成：</strong>${escapeHTML(section.error)}<br>${retryHint}`, "danger") : "";
    const quick = task.intake?.mode === "quick_change";
    const intro = imported
      ? "<strong>已有 Worktree 预检已完成。</strong> 不创建目录、不切换分支、不初始化 Submodule；点击后只把已批准 Plan 写入该 Worktree。"
      : quick
        ? "<strong>轻量执行单与 Worktree 预检已完成。</strong> 已跳过两次前置 Agent 等待；点击后只创建隔离 Worktree 并绑定执行单，不会开始改代码。"
        : "<strong>创建前预检已完成。</strong> 未提交的主仓库改动不会复制到新 Worktree；不会 Fetch、切换主仓库分支、Push 或 Merge。";
    return `<section class="section">${error || callout(intro, "warning")}</section>
      <section class="section"><div class="path-list"><div class="path-row"><span>主仓库</span><strong class="mono">${escapeHTML(health?.paths?.repo)}</strong></div>${imported ? "" : `<div class="path-row"><span>基准</span><strong class="mono">${escapeHTML(section.base)}</strong></div>`}<div class="path-row"><span>分支</span><strong class="mono">${escapeHTML(section.branch)}</strong></div><div class="path-row"><span>Worktree</span><strong class="mono">${escapeHTML(section.path)}</strong></div><div class="path-row"><span>Plan 目标</span><strong class="mono">${escapeHTML(task.paths.planRelative)}</strong></div></div></section>
      <section class="section"><h3>${imported ? "已有 Worktree 校验" : "真实 dry-run"}</h3><div class="preview"><pre>${escapeHTML(section.preview || "等待预检输出")}</pre></div></section>
      <div class="actions"><div class="actions-secondary"><button id="backToPlan">返回 Plan</button></div><div class="actions-primary"><button class="primary" id="createWorktree">${imported ? "绑定 Plan 到已有 Worktree" : section.status === "error" ? "重试创建 Worktree" : "创建 Worktree"}</button></div></div>${eventLogDetails()}`;
  }

  function reviewPanel(review) {
    if (!review) return "";
    const findings = review.findings || [];
    const skipped = review.verdict === "skipped";
    const passed = review.verdict === "pass";
    const label = skipped ? "快速自检完成" : passed ? "通过" : "仍需修复";
    const gaps = (review.verification_gaps || []).filter(Boolean);
    return `<section class="section"><h3>${skipped ? "快速模式检查" : "Code Review"}</h3>${callout(`<strong>${label}：</strong>${escapeHTML(review.summary)}`, passed ? "ok" : skipped ? "warning" : "danger")}${findings.length ? `<div class="checklist" style="margin-top:14px">${findings.map((item) => `<div class="check-row"><span>${escapeHTML(item.severity)}</span><div><strong>${escapeHTML(item.title)}</strong><span>${escapeHTML(item.file)}:${escapeHTML(item.line)} · ${escapeHTML(item.detail)}</span></div></div>`).join("")}</div>` : ""}${gaps.length ? `<ul class="review-gaps">${gaps.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>` : ""}</section>`;
  }

  function renderExecute() {
    const section = task.execution;
    if (["queued", "running"].includes(section.status)) {
      const targeted = section.mode === "acceptance_fix";
      const fast = section.flowMode === "fast";
      const title = targeted
        ? `${fast ? "快速" : "标准"}人工验收定向返修 · ${section.phase || "implementation"}`
        : fast ? `Codex App 快速修改 · ${section.phase || "implementation"}` : `workmission 标准执行 · ${section.phase || "implementation"}`;
      const fixMinutes = Math.ceil(Number(health?.limits?.acceptanceFixSeconds || 480) / 60);
      const reviewMinutes = Math.ceil(Number(health?.limits?.acceptanceReviewSeconds || 300) / 60);
      const quickMinutes = Math.ceil(Number(health?.limits?.quickExecutionSeconds || 600) / 60);
      const hint = fast
        ? `复用同一个 App Thread；本轮最长 ${quickMinutes} 分钟，不启动独立 Review。`
        : targeted ? `只处理验收备注；返修最长 ${fixMinutes} 分钟，定向 Review 最长 ${reviewMinutes} 分钟。` : "停止后保留已有实施结果与 Worktree 改动。";
      return `${renderProgress(section, title)}<div class="actions"><div class="actions-secondary"><span class="hint">${hint}</span></div><div class="actions-primary"><button class="danger" id="cancelExecution">停止当前执行</button></div></div>`;
    }
    const error = ["error", "interrupted"].includes(section.status) ? callout(`<strong>执行中断：</strong>${escapeHTML(section.error)}`, "danger") : "";
    const needs = section.status === "needs_attention";
    const fast = ui.executionMode !== "standard";
    const canResetSession = Boolean(error && (fast ? task.agentMemory?.sessions?.app : task.agentMemory?.sessions?.execution));
    const imported = task.worktree?.imported ? "已有 Worktree 已接入" : "隔离环境已绑定";
    return `<section class="section">${error || callout(`<strong>${imported}。</strong> Plan 位于 <code>${escapeHTML(task.plan.finalPath || task.paths.planRelative)}</code>；点击后 Codex 才会获得 Worktree 写权限。`, needs ? "danger" : "warning")}</section>
      <section class="section"><div class="summary-grid"><div class="summary-item"><span>执行目录</span><strong class="mono">${escapeHTML(task.worktree.path)}</strong></div><div class="summary-item"><span>Skill 链</span><strong>${escapeHTML([...(health?.skills?.execution || []), ...(health?.skills?.review || [])].join(" → ") || "通用项目规则")}</strong></div>${task.worktree?.imported ? `<div class="summary-item"><span>接入时 Git 改动</span><strong>${Number(task.git?.entries?.length || 0)} 个文件，Commit 前完整复核</strong></div>` : ""}</div></section>
      ${reviewPanel(section.review)}
      ${renderExecutionModeSelector("execution")}
      <div class="actions"><div class="actions-secondary"><span class="hint">不会 Commit、Push 或 Merge；快速模式不启动独立 Review。</span>${canResetSession ? `<button class="danger" id="resetExecutionSession">放弃旧${fast ? " App Thread" : " execution 会话"}，用任务记忆重建</button>` : ""}</div><div class="actions-primary"><button class="primary" id="executePlan">${needs ? fast ? "快速处理 Review 发现" : "根据 Review 继续执行" : ["error", "interrupted"].includes(section.status) && section.phase === "review" && section.result && !fast ? "只重试 Code Review" : ["error", "interrupted"].includes(section.status) ? fast ? "快速重试" : "重试原 execution 会话" : fast ? "快速执行 Plan" : "按标准流程执行 Plan"}</button></div></div>${eventLogDetails()}`;
  }

  function textItems(value) {
    if (Array.isArray(value)) return value.map((item) => String(item || "").trim()).filter(Boolean);
    const item = String(value || "").trim();
    return item ? [item] : [];
  }

  function isRequiredManualCase(item) {
    return item?.required !== false;
  }

  function requiredManualIndexes(cases) {
    return cases.map((item, index) => isRequiredManualCase(item) ? index : -1).filter((index) => index >= 0);
  }

  function logFilterToken(value) {
    const filter = String(value || "").trim();
    if (!filter) return '<span class="hint">无需额外筛选</span>';
    return `<span class="log-filter"><code>${escapeHTML(filter)}</code><button class="small" type="button" data-copy-log="${escapeHTML(filter)}" aria-label="复制日志筛选词 ${escapeHTML(filter)}">复制</button></span>`;
  }

  function renderMinimumVerification(minimum) {
    if (!minimum?.steps?.length) {
      return `<section class="section verification-minimum"><div class="section-heading"><div><p class="section-kicker">先做这个</p><h3>最小人工验证</h3></div></div>${callout("本次执行结果没有返回最小验证路径。请退回执行，让 Codex 补充 3–5 分钟的最短步骤和验收日志。", "warning")}</section>`;
    }
    return `<section class="section verification-minimum"><div class="section-heading"><div><p class="section-kicker">先做这个</p><h3>最小人工验证</h3></div><strong class="time-estimate">约 ${Number(minimum.estimated_minutes) || 5} 分钟</strong></div>
      <p class="section-copy">先用这条最短路径确认功能可测、主链路正常。详细回归仍以接下来的 P0 必测项为 Commit 门禁。</p>
      <ol class="minimum-steps">${minimum.steps.map((item) => `<li><div class="minimum-step-head"><strong>${escapeHTML(item.title)}</strong>${logFilterToken(item.log_filter)}</div><p><b>操作</b>${escapeHTML(item.action)}</p><p><b>页面/功能应看到</b>${escapeHTML(item.expected)}</p><p class="evidence-ok"><b>日志应看到</b>${escapeHTML(item.expected_log)}</p><p class="evidence-fail"><b>失败信号</b>${escapeHTML(item.failure_signal)}</p></li>`).join("")}</ol>
    </section>`;
  }

  function renderManualCase(item, index) {
    const required = isRequiredManualCase(item);
    const priority = item.priority || "P0";
    const steps = textItems(item.steps);
    const filters = textItems(item.log_filters);
    const expectedLogs = textItems(item.expected_logs);
    const failureSignals = textItems(item.failure_signals);
    return `<article class="test-case ${required ? "required" : "optional"}" id="manual-case-${index}" data-manual-case-index="${index}" tabindex="-1">
      <div class="test-case-head"><label class="test-case-check"><input type="checkbox" data-check-index="${index}" ${ui.checks[index] ? "checked" : ""}><span><strong>${escapeHTML(item.title)}</strong><small>${required ? "Commit 必测" : "补充回归"}</small></span></label><span class="priority priority-${escapeHTML(priority.toLowerCase())}">${escapeHTML(priority)}</span></div>
      <div class="test-case-body"><p class="precondition"><b>前置条件</b>${escapeHTML(item.precondition || "无特殊前置条件")}</p>
        <div class="test-case-grid"><div><h4>操作步骤</h4><ol>${steps.map((step) => `<li>${escapeHTML(step)}</li>`).join("")}</ol></div><div><h4>通过标准</h4><p>${escapeHTML(item.expected)}</p></div></div>
        <div class="case-evidence"><div><h4>Console / 设备日志筛选</h4><div class="log-filter-list">${filters.length ? filters.map(logFilterToken).join("") : '<span class="hint">本案例未指定日志筛选词</span>'}</div></div>
          <div class="evidence-ok"><h4>应看到</h4><ul>${expectedLogs.length ? expectedLogs.map((line) => `<li>${escapeHTML(line)}</li>`).join("") : "<li>以页面/功能预期结果为准。</li>"}</ul></div>
          <div class="evidence-fail"><h4>不能看到 / 失败信号</h4><ul>${failureSignals.length ? failureSignals.map((line) => `<li>${escapeHTML(line)}</li>`).join("") : "<li>异常、报错或与预期不一致。</li>"}</ul></div>
        </div>
      </div>
    </article>`;
  }

  function renderManualCaseNavigation(cases, requiredIndexes) {
    const completedRequired = requiredIndexes.filter((index) => ui.checks[index]).length;
    const completedAll = cases.filter((_, index) => ui.checks[index]).length;
    return `<aside class="manual-case-nav" aria-label="人工验收用例导航">
      <div class="manual-case-nav-head"><div><p class="section-kicker">固定清单</p><h3>验收用例</h3></div><strong class="manual-case-nav-progress">必测 ${completedRequired} / ${requiredIndexes.length}</strong></div>
      <p class="manual-case-nav-summary">全部完成 <span data-manual-case-completed>${completedAll}</span> / ${cases.length} · 点击可跳转</p>
      <div class="manual-case-nav-list">${cases.map((item, index) => {
        const required = isRequiredManualCase(item);
        const priority = item.priority || "P0";
        const complete = Boolean(ui.checks[index]);
        return `<button class="manual-case-nav-item ${complete ? "is-complete" : ""}" type="button" data-manual-case-jump="${index}">
          <span class="manual-case-nav-index" aria-hidden="true">${complete ? "✓" : index + 1}</span>
          <span class="manual-case-nav-copy"><strong>${escapeHTML(item.title)}</strong><small><b>${escapeHTML(priority)}</b>${required ? "必测" : "补充回归"}</small></span>
          <span class="manual-case-nav-state">${complete ? "已完成" : "待验证"}</span>
        </button>`;
      }).join("")}</div>
    </aside>`;
  }

  function renderAcceptanceLogs(logs) {
    if (!logs?.length) {
      return `<section class="section"><h3>验收日志</h3>${callout("本次执行结果没有单独列出验收日志。请退回执行，要求补充精确筛选词、触发动作、预期字段和失败信号。", "warning")}</section>`;
    }
    return `<section class="section"><div class="section-heading"><div><p class="section-kicker">验收证据</p><h3>关键日志怎么查</h3></div><span class="hint">点击筛选词即可复制</span></div><div class="acceptance-log-list">${logs.map((item) => {
      const failures = textItems(item.failure_signals);
      return `<article class="acceptance-log"><div class="acceptance-log-head"><div><strong>${escapeHTML(item.name)}</strong><span>${escapeHTML(item.source)}</span></div>${logFilterToken(item.filter)}</div><dl><div><dt>何时触发</dt><dd>${escapeHTML(item.trigger)}</dd></div><div><dt>应看到</dt><dd>${escapeHTML(item.expected)}</dd></div><div class="log-failure"><dt>失败信号</dt><dd>${failures.length ? failures.map((line) => escapeHTML(line)).join("；") : "异常或缺少预期日志"}</dd></div></dl></article>`;
    }).join("")}</div></section>`;
  }

  function renderVerification(inBugfix = false) {
    const result = task.execution.result || {};
    const reviewVerdict = task.execution.review?.verdict;
    const reviewLabel = reviewVerdict === "pass" ? "独立 Review 通过" : reviewVerdict === "skipped" ? "快速自检完成（未独立 Review）" : "请查看执行阶段";
    const cases = result.manual_cases?.length ? result.manual_cases : [{ title: "主流程", steps: "按 Plan 执行一次完整主流程。", expected: "结果与验收口径一致。" }];
    if (!inBugfix && isCompletedStageView("verify") && task.verification?.approved && Array.isArray(task.verification.checks)) {
      ui.checks = task.verification.checks.map(Boolean);
    }
    while (ui.checks.length < cases.length) ui.checks.push(false);
    ui.checks = ui.checks.slice(0, cases.length);
    const requiredIndexes = requiredManualIndexes(cases);
    const completedRequired = requiredIndexes.filter((index) => ui.checks[index]).length;
    const requiredDone = requiredIndexes.length > 0 && completedRequired === requiredIndexes.length;
    return `<section class="section" data-section-title="${inBugfix ? "Bug 修改结果概览" : "执行结果概览"}"><div class="summary-grid"><div class="summary-item"><span>${inBugfix ? "Bug 修改结果" : "执行结果"}</span><strong>${escapeHTML(result.summary || "实现已完成")}</strong></div><div class="summary-item"><span>检查方式</span><strong>${escapeHTML(reviewLabel)}</strong></div></div></section>
      ${renderMinimumVerification(result.minimum_manual_verification)}
      <section class="section"><h3>自动/逻辑验证</h3><div class="checklist">${(result.verification || []).map((item) => `<div class="check-row"><span>${item.status === "passed" ? "✓" : item.status === "failed" ? "!" : "–"}</span><div><strong>${escapeHTML(item.check)}</strong><span>${escapeHTML(item.result)} · ${escapeHTML(item.status)}</span></div></div>`).join("") || '<span class="hint">Codex 未返回自动验证条目。</span>'}</div></section>
      <div class="verification-case-layout"><section class="section verification-case-content"><div class="section-heading"><div><p class="section-kicker">逐条勾选</p><h3>详细测试用例</h3></div><strong class="gate-progress">P0 / 必测 ${completedRequired} / ${requiredIndexes.length}</strong></div><p class="section-copy">只有标记为“Commit 必测”的用例会阻塞提交；P1/P2 补充回归可按本次发布风险选择执行，并在备注中记录。</p><div class="test-case-list">${cases.map(renderManualCase).join("")}</div></section>${renderManualCaseNavigation(cases, requiredIndexes)}</div>
      ${renderAcceptanceLogs(result.acceptance_logs)}
      ${renderExecutionModeSelector("acceptance")}
      <section class="section" data-section-title="验收备注与问题"><div class="field"><label for="verificationNote">验收备注或发现的问题</label><textarea id="verificationNote" placeholder="记录设备、操作证据，或描述需要定向返修的问题……">${escapeHTML(ui.verificationNote)}</textarea>${renderFeedbackImageInput("verification")}<span class="hint">文字和图片可以单独或一起提交。退回后只处理这条人工反馈，不会重新执行整份 Plan；上一轮未受影响的测试用例会保留。</span></div></section>
      <div class="actions"><div class="actions-secondary"><button class="danger" id="returnToExecution" ${ui.verificationNote.trim() || feedbackImageItems("verification").length ? "" : "disabled"}>发现问题，启动定向返修</button></div><div class="actions-primary"><button class="primary" id="approveVerification" ${requiredDone ? "" : "disabled"}>${inBugfix ? "Bug 复验通过" : "P0 / 必测验证通过"}</button></div></div>${reviewPanel(task.execution.review)}${eventLogDetails()}`;
  }

  function renderVerify() {
    return renderVerification(false);
  }

  function renderCommit(inBugfix = false) {
    if (task.git?.committed) {
      const manual = task.git.commitSource === "manual";
      const pendingEntries = task.git.entries || [];
      return `<section class="section">${callout(`<strong>${manual ? "已确认人工 Commit" : "Commit 已完成"}。</strong> 提交：<code>${escapeHTML(task.git.commitId)}</code><br>${manual ? "控制台只记录当前 HEAD，没有执行 Git 写操作。" : "控制台没有执行 Push 或 Merge。"}`, "ok")}${pendingEntries.length ? callout(`<strong>Worktree 仍有 ${pendingEntries.length} 项未提交改动。</strong>这些改动没有被“确认人工提交”按钮处理，请按实际归属另行检查。`, "warning") : ""}</section><section class="section"><div class="path-list"><div class="path-row"><span>Worktree</span><strong class="mono">${escapeHTML(task.worktree.path)}</strong></div><div class="path-row"><span>分支</span><strong class="mono">${escapeHTML(task.git.branch)}</strong></div><div class="path-row"><span>Commit 来源</span><strong>${manual ? "人工提交（控制台仅确认）" : "控制台执行"}</strong></div><div class="path-row"><span>Commit Message</span><strong>${escapeHTML(task.git.message)}</strong></div></div></section>${pendingEntries.length ? `<section class="section"><h3>仍未提交的文件</h3><div class="diff-wrap"><table class="diff-table"><thead><tr><th>状态</th><th>文件</th></tr></thead><tbody>${pendingEntries.map((item) => `<tr><td class="diff-status">${escapeHTML(item.code)}</td><td class="mono">${escapeHTML(item.path)}</td></tr>`).join("")}</tbody></table></div></section>` : ""}<div class="actions"><div class="actions-primary"><button class="primary" id="newTaskButton">新建下一条需求</button></div></div>${eventLogDetails()}`;
    }
    const entries = task.git?.entries || [];
    const defaultMessage = `feat: complete ${task.worktree.name}`.slice(0, 120);
    if (!ui.commitMessage) ui.commitMessage = defaultMessage;
    return `<section class="section">${callout(`<strong>${inBugfix ? "Bug 修复的最后一道 Git 写入门" : "最后一道 Git 写入门"}。</strong> Commit 只作用于当前 Worktree。配套验收 HTML 位于配置的 docsRoot：<code>${escapeHTML(health?.paths?.docs || "")}</code>；若它在仓库外则不属于此 Git 提交。不会 Push 或 Merge。`, "warning")}</section>
      <section class="section"><h3>待提交文件 · ${escapeHTML(task.git.refreshedAt || "尚未刷新")}</h3><div class="diff-wrap"><table class="diff-table"><thead><tr><th>状态</th><th>文件</th></tr></thead><tbody>${entries.length ? entries.map((item) => `<tr><td class="diff-status">${escapeHTML(item.code)}</td><td class="mono">${escapeHTML(item.path)}</td></tr>`).join("") : '<tr><td colspan="2">当前没有改动</td></tr>'}</tbody></table></div>${task.git.diffStat ? `<div class="preview"><pre>${escapeHTML(task.git.diffStat)}</pre></div>` : ""}</section>
      <section class="section"><div class="field"><label for="commitMessage">Commit Message</label><input id="commitMessage" class="mono" type="text" maxlength="120" value="${escapeHTML(ui.commitMessage)}"></div><label class="choice"><input id="commitConfirmed" type="checkbox" ${ui.commitConfirmed ? "checked" : ""}><span>我已确认上方真实文件列表、自动验证和人工验收结果。</span></label></section>
      <div class="actions"><div class="actions-secondary"><button id="refreshGit">刷新 Git 状态</button>${inBugfix ? "" : '<button id="backToVerify">返回人工验收</button>'}</div><div class="actions-primary"><button id="confirmManualCommit" ${ui.commitConfirmed ? "" : "disabled"}>确认已人工提交</button><button class="primary" id="commitChanges" ${ui.commitConfirmed && entries.length ? "" : "disabled"}>Commit</button></div></div><p class="hint">“确认已人工提交”只记录当前 HEAD，不会再次执行 Commit；若仍有未提交改动，完成页会继续提示。</p>${eventLogDetails()}`;
  }

  function renderBugfix() {
    const cycle = task.bugfix || {};
    if (!task.git?.committed) {
      if (cycle.status === "verify") {
        const fast = task.execution?.flowMode === "fast";
        return `<section class="section">${callout(`<strong>${fast ? "Bug 快速修改与自检已完成；本轮未运行独立 Review。" : "Bug 修改与 Code Review 已通过。"}</strong> 直接在当前模块完成受影响范围的人工复验；不会跳回执行 Plan。`, fast ? "warning" : "ok")}</section>${renderVerification(true)}`;
      }
      if (cycle.status === "commit") {
        return `<section class="section">${callout("<strong>Bug 复验已通过。</strong> 继续在当前模块核对真实 Git 状态并完成新 Commit。", "ok")}</section>${renderCommit(true)}`;
      }
      const section = task.execution || {};
      if (["queued", "running"].includes(section.status)) {
        const targeted = section.mode === "acceptance_fix" ? "Bug 人工反馈定向返修" : section.flowMode === "fast" ? "Bug 快速修改" : "Bug 标准修改";
        const reviewing = section.phase === "review";
        const progressTitle = reviewing ? "Bug 修改已完成 · 正在 Code Review" : `${targeted} · ${section.phase || "implementation"}`;
        const progressHint = reviewing ? "Bug 修改结果已经保留；当前只复核本轮改动，不会重新执行 Plan。" : "只修改本 Bug 及 Review findings，不重新执行 Plan。";
        return `<section class="section">${cycle.description ? callout(`<strong>本轮 Bug：</strong>${escapeHTML(cycle.description)}`, "warning") : ""}</section>${renderProgress(section, progressTitle)}<div class="actions"><div class="actions-secondary"><span class="hint">${progressHint}</span></div><div class="actions-primary"><button class="danger" id="cancelExecution">${reviewing ? "停止 Code Review" : "停止当前修改"}</button></div></div>`;
      }
      const interrupted = ["error", "interrupted"].includes(section.status);
      const needsReviewFix = section.status === "needs_attention" || cycle.status === "review";
      const retryReviewOnly = interrupted && section.phase === "review" && section.result;
      const selectedFast = ui.executionMode !== "standard";
      return `<section class="section">${interrupted ? callout(`<strong>Bug 修改中断：</strong>${escapeHTML(section.error)}`, "danger") : callout(`<strong>Bug 修复 Review 仍有发现。</strong> 继续只处理本轮 finding，不会重新执行 Plan。`, needsReviewFix ? "danger" : "warning")}</section>
        ${cycle.description ? `<section class="section"><h3>本轮 Bug</h3><div class="preview"><pre>${escapeHTML(cycle.description)}</pre></div></section>` : ""}
        ${reviewPanel(section.review || section.previousReview)}
        ${renderExecutionModeSelector("bugfix")}
        <div class="actions"><div class="actions-secondary"><span class="hint">当前阶段始终保持在 Bug 修复模块。</span></div><div class="actions-primary"><button class="primary" id="continueBugfix">${retryReviewOnly && !selectedFast ? "只重试 Code Review" : interrupted ? selectedFast ? "快速重试 Bug 修改" : "重试 Bug 定向修改" : selectedFast ? "快速处理 Review 发现" : "根据 Review 继续修改"}</button></div></div>${eventLogDetails()}`;
    }
    const pendingEntries = task.git.entries || [];
    const completed = cycle.status === "complete";
    return `<section class="section">${callout(`<strong>当前版本已经提交。</strong>如果验收后又发现 Bug，可从这里直接启动定向修改；整个修改、Review、复验和 Commit 都留在本模块内。`, "ok")}${completed ? callout(`<strong>上一轮 Bug 修复已闭环。</strong>新提交：<code>${escapeHTML(cycle.resultCommit || task.git.commitId)}</code>`, "ok") : ""}${pendingEntries.length ? callout(`<strong>启动前注意：</strong>Worktree 当前还有 ${pendingEntries.length} 项未提交改动；修复 Agent 会被要求保留并区分无关改动。`, "warning") : ""}</section>
      <section class="section"><div class="path-list"><div class="path-row"><span>当前 HEAD</span><strong class="mono">${escapeHTML(task.git.head || task.git.commitId)}</strong></div><div class="path-row"><span>最近确认的 Commit</span><strong class="mono">${escapeHTML(task.git.commitId)}</strong></div><div class="path-row"><span>Worktree</span><strong class="mono">${escapeHTML(task.worktree.path)}</strong></div></div></section>
      ${renderExecutionModeSelector("bugfix")}
      <section class="section"><div class="field"><label for="bugfixDescription">Bug 描述与复现信息</label><textarea id="bugfixDescription" maxlength="8000" placeholder="建议填写：复现步骤、实际结果、预期结果、设备/版本、关键日志……">${escapeHTML(ui.bugfixDescription)}</textarea>${renderFeedbackImageInput("bugfix")}</div><p class="hint">文字和图片可以单独或一起提交。快速模式走“定向修改 → 自检 → 人工复验”，标准模式额外运行独立 Review；两者最后都需要新 Commit。不会自动 Push 或 Merge。</p></section>
      <div class="actions"><div class="actions-secondary"><button id="refreshGit">刷新 Git 状态</button><button id="newTaskButton">没有 Bug，新建下一条需求</button></div><div class="actions-primary">${health?.features?.knowledge ? `<button id="generateKnowledge" ${task.activeJob ? "disabled" : ""}>完成任务并生成沉淀建议</button>` : ""}<button class="primary" id="startBugfix" ${!task.activeJob && (ui.bugfixDescription.trim() || feedbackImageItems("bugfix").length) ? "" : "disabled"}>开始修复 Bug</button></div></div>${eventLogDetails()}`;
  }

  const knowledgeTypeLabels = {
    fact: "稳定事实",
    decision: "关键决策",
    runbook: "操作手册",
    pitfall: "踩坑",
    acceptance: "验收规律",
    skill: "Skill 候选",
    automation: "自动化候选"
  };

  function renderKnowledgeCandidate(candidate, center = false) {
    const status = ["pending", "approved", "ignored"].includes(candidate.status) ? candidate.status : "pending";
    const statusLabel = ({ pending: "待审核", approved: "已保留", ignored: "已忽略" })[status];
    const scopeLabel = candidate.scope === "global-candidate" ? "跨项目候选" : "当前项目";
    const archived = Boolean(candidate.taskArchivedAt);
    const evidence = (candidate.evidence || []).map((item) => `<li><strong>${escapeHTML(item.source)}</strong> · <span class="mono">${escapeHTML(item.reference)}</span>${item.detail ? ` — ${escapeHTML(item.detail)}` : ""}</li>`).join("");
    const appliesTo = (candidate.appliesTo || []).join("、") || "未限定";
    const nonScope = (candidate.nonScope || []).join("、") || "无";
    const locked = busy || archived;
    return `<article class="knowledge-card" data-status="${escapeHTML(status)}">
      <div class="knowledge-card-head"><div><div class="knowledge-badges"><span class="knowledge-badge">${escapeHTML(knowledgeTypeLabels[candidate.type] || candidate.type)}</span><span class="knowledge-badge scope">${escapeHTML(scopeLabel)}</span><span class="knowledge-badge">${escapeHTML(statusLabel)}</span></div><h3>${escapeHTML(candidate.title)}</h3>${center ? `<p class="knowledge-source">来源：${escapeHTML(candidate.taskTitle || "未命名需求")} · ${escapeHTML(formatDateTime(candidate.generatedAt))}${archived ? " · 已归档" : ""}</p>` : ""}</div>${center ? `<button type="button" data-knowledge-task="${escapeHTML(candidate.taskId)}">查看任务</button>` : ""}</div>
      <p class="knowledge-card-content">${escapeHTML(candidate.content)}</p>
      <div class="knowledge-meta"><span><strong>适用：</strong>${escapeHTML(appliesTo)}</span><span><strong>不适用：</strong>${escapeHTML(nonScope)}</span><span><strong>建议去向：</strong>${escapeHTML(candidate.suggestedTarget || "待审核时决定")}</span>${candidate.novelty ? `<span><strong>为何值得沉淀：</strong>${escapeHTML(candidate.novelty)}</span>` : ""}</div>
      ${evidence ? `<details><summary>核验证据 · ${(candidate.evidence || []).length}</summary><ul class="knowledge-evidence">${evidence}</ul></details>` : callout("这条候选没有足够的直接证据，建议忽略。", "warning")}
      <div class="knowledge-card-actions"><button type="button" data-knowledge-review="ignored" data-knowledge-task-id="${escapeHTML(candidate.taskId || task?.id || "")}" data-knowledge-candidate-id="${escapeHTML(candidate.id)}" ${locked || status === "ignored" ? "disabled" : ""}>${status === "ignored" ? "已忽略" : "忽略"}</button><button class="primary" type="button" data-knowledge-review="approved" data-knowledge-task-id="${escapeHTML(candidate.taskId || task?.id || "")}" data-knowledge-candidate-id="${escapeHTML(candidate.id)}" ${locked || status === "approved" ? "disabled" : ""}>${status === "approved" ? "已保留候选" : "保留候选"}</button></div>
      ${archived ? '<p class="hint">任务已归档；恢复后才能修改审核状态。</p>' : ""}
    </article>`;
  }

  function renderKnowledge() {
    const section = task.knowledge || { status: "idle", candidates: [] };
    if (["queued", "running"].includes(section.status)) {
      const minutes = Math.ceil(Number(health?.limits?.knowledgeSeconds || 240) / 60);
      return `${renderProgress(section, "正在从交付证据中提炼沉淀候选")}<p class="hint">最长约 ${minutes} 分钟；只读检查代码、Plan、Commit 和验证证据，不会修改项目文件或 Git。</p>`;
    }
    if (["error", "interrupted"].includes(section.status)) {
      return `<section class="section">${callout(`<strong>沉淀提炼未完成：</strong>${escapeHTML(section.error)}`, "danger")}</section><div class="actions"><div class="actions-secondary"><button id="backToBugfix">返回 Bug 修复</button></div><div class="actions-primary"><button class="primary" id="generateKnowledge">重试生成沉淀候选</button></div></div>${eventLogDetails()}`;
    }
    if (section.status !== "ready") {
      return `<section class="section">${callout("<strong>Commit 已闭环。</strong> 点击后会只读提炼最多 5 条可复用候选；不会自动写入项目文档、Skill 或 Git。", "warning")}</section><div class="actions"><div class="actions-secondary"><button id="backToBugfix">返回 Bug 修复</button></div><div class="actions-primary"><button class="primary" id="generateKnowledge">生成沉淀候选</button></div></div>${eventLogDetails()}`;
    }
    const candidates = section.candidates || [];
    const pending = candidates.filter((item) => item.status === "pending").length;
    const approved = candidates.filter((item) => item.status === "approved").length;
    const result = candidates.length
      ? `<div class="knowledge-grid">${candidates.map((item) => renderKnowledgeCandidate(item)).join("")}</div>`
      : callout("<strong>本任务无需沉淀。</strong> 没有发现比现有项目知识更稳定、可复用的新经验。", "ok");
    return `<section class="section">${callout("<strong>候选已生成，但尚未发布。</strong> “保留候选”只记录你的审核意见；后续如需写入项目知识库，仍应走单独的发布门禁。", "warning")}<div class="summary-grid" style="margin-top:16px"><div class="summary-item"><span>生成结果</span><strong>${escapeHTML(section.summary || `${candidates.length} 条候选`)}</strong></div><div class="summary-item"><span>审核进度</span><strong>${approved} 保留 · ${pending} 待审核</strong></div></div>${result}</section>
      <div class="actions"><div class="actions-secondary"><button id="backToBugfix">返回 Bug 修复</button><button id="newTaskButton">新建下一条需求</button></div><div class="actions-primary"><button id="generateKnowledge">重新生成候选</button></div></div>${eventLogDetails()}`;
  }

  function renderKnowledgeCenter() {
    const counts = { all: knowledgeCandidates.length, pending: 0, approved: 0, ignored: 0 };
    knowledgeCandidates.forEach((item) => { if (counts[item.status] !== undefined) counts[item.status] += 1; });
    const filter = counts[ui.knowledgeFilter] !== undefined ? ui.knowledgeFilter : "pending";
    const labels = { pending: "待审核", approved: "已保留", ignored: "已忽略", all: "全部" };
    const visible = filter === "all" ? knowledgeCandidates : knowledgeCandidates.filter((item) => item.status === filter);
    const filters = Object.entries(labels).map(([id, label]) => `<button type="button" data-knowledge-filter="${id}" class="${filter === id ? "active" : ""}">${label} ${counts[id]}</button>`).join("");
    const body = knowledgeLoading && !knowledgeLoaded
      ? renderProgress({ status: "running", logs: [] }, "正在读取跨任务沉淀候选")
      : knowledgeError
        ? callout(`<strong>沉淀中心读取失败：</strong>${escapeHTML(knowledgeError)}`, "danger")
        : visible.length
          ? `<div class="knowledge-grid">${visible.map((item) => renderKnowledgeCandidate(item, true)).join("")}</div>`
          : callout(filter === "pending" ? "<strong>没有待审核候选。</strong> 已完成的任务可以在“沉淀”阶段生成新候选。" : `<strong>${escapeHTML(labels[filter])}列表为空。</strong>`, "ok");
    return `<section class="section"><div class="knowledge-toolbar"><div><p class="section-kicker">Knowledge Review</p><h3>统一审核，不自动发布</h3><p class="section-copy">这里聚合所有任务的候选。审核只写入 <code>.runtime</code>；不会修改项目文档、Skill、代码或 Git。</p></div><button id="refreshKnowledgeCenter" type="button" ${knowledgeLoading ? "disabled" : ""}>刷新</button></div><div class="knowledge-filters" style="margin-top:16px">${filters}</div>${body}</section>`;
  }

  function staticCheck(title, detail) {
    return `<div class="check-row"><span aria-hidden="true">✓</span><div><strong>${escapeHTML(title)}</strong><span>${escapeHTML(detail)}</span></div></div>`;
  }

  function captureVisibleFields() {
    const values = {
      title: document.querySelector("#taskTitle")?.value,
      sourceUrl: document.querySelector("#sourceUrl")?.value,
      sourceText: document.querySelector("#sourceText")?.value,
      baseBranch: document.querySelector("#baseBranch")?.value,
      existingDocumentPath: document.querySelector("#existingDocumentPath")?.value,
      existingWorktreePath: document.querySelector("#existingWorktreePath")?.value,
      discussionNote: document.querySelector("#discussionNote")?.value,
      verificationNote: document.querySelector("#verificationNote")?.value,
      commitMessage: document.querySelector("#commitMessage")?.value,
      bugfixDescription: document.querySelector("#bugfixDescription")?.value,
      askQuestion: document.querySelector("#askQuestion")?.value
    };
    Object.entries(values).forEach(([key, value]) => { if (value !== undefined) ui[key] = value; });
    saveUi();
  }

  function attachHandlers(stageId) {
    document.querySelectorAll("[data-source-type]").forEach((button) => button.addEventListener("click", () => {
      captureVisibleFields();
      ui.sourceType = button.dataset.sourceType;
      render();
    }));
    document.querySelectorAll("[data-intake-mode]").forEach((button) => button.addEventListener("click", () => {
      captureVisibleFields();
      ui.intakeMode = button.dataset.intakeMode;
      render();
    }));
    document.querySelectorAll("[data-workflow-mode]").forEach((input) => input.addEventListener("change", () => {
      captureVisibleFields();
      ui.workflowMode = input.value === "standard" ? "standard" : "quick";
      if (ui.workflowMode === "quick") ui.sourceType = "paste";
      saveUi();
      render();
    }));
    document.querySelectorAll("[data-plan-view]").forEach((button) => button.addEventListener("click", () => {
      ui.planView = button.dataset.planView;
      render();
    }));
    document.querySelectorAll("[data-execution-mode]").forEach((input) => input.addEventListener("change", () => {
      ui.executionMode = input.value === "standard" ? "standard" : "fast";
      saveUi();
      render();
    }));
    document.querySelectorAll("[data-lark-reader]").forEach((input) => input.addEventListener("change", () => {
      ui.larkReader = input.value === "lark_cli" ? "lark_cli" : "chrome_mcp";
      saveUi();
      render();
    }));
    document.querySelectorAll("[data-question-id]").forEach((input) => input.addEventListener("change", () => {
      ui.answers[input.dataset.questionId] = input.value;
      const wrap = document.querySelector(`[data-custom-wrap="${CSS.escape(input.dataset.questionId)}"]`);
      if (wrap) wrap.hidden = input.value !== "__custom__";
      saveUi();
    }));
    document.querySelectorAll("[data-custom-id]").forEach((input) => input.addEventListener("input", () => {
      ui.customAnswers[input.dataset.customId] = input.value;
      saveUi();
    }));
    document.querySelectorAll("[data-check-index]").forEach((input) => input.addEventListener("change", () => {
      ui.checks[Number(input.dataset.checkIndex)] = input.checked;
      saveUi();
      const cases = task?.execution?.result?.manual_cases?.length ? task.execution.result.manual_cases : [{ title: "主流程", steps: "按 Plan 执行一次完整主流程。", expected: "结果与验收口径一致。" }];
      const requiredIndexes = requiredManualIndexes(cases);
      const completedRequired = requiredIndexes.filter((index) => ui.checks[index]).length;
      const completedAll = cases.filter((_, index) => ui.checks[index]).length;
      const approve = document.querySelector("#approveVerification");
      if (approve) approve.disabled = !requiredIndexes.length || completedRequired !== requiredIndexes.length;
      const progress = document.querySelector(".gate-progress");
      if (progress) progress.textContent = `P0 / 必测 ${completedRequired} / ${requiredIndexes.length}`;
      const navProgress = document.querySelector(".manual-case-nav-progress");
      if (navProgress) navProgress.textContent = `必测 ${completedRequired} / ${requiredIndexes.length}`;
      const navCompleted = document.querySelector("[data-manual-case-completed]");
      if (navCompleted) navCompleted.textContent = String(completedAll);
      const index = Number(input.dataset.checkIndex);
      const navItem = document.querySelector(`[data-manual-case-jump="${index}"]`);
      if (navItem) {
        navItem.classList.toggle("is-complete", input.checked);
        const navIndex = navItem.querySelector(".manual-case-nav-index");
        const navState = navItem.querySelector(".manual-case-nav-state");
        if (navIndex) navIndex.textContent = input.checked ? "✓" : String(index + 1);
        if (navState) navState.textContent = input.checked ? "已完成" : "待验证";
      }
    }));
    document.querySelectorAll("[data-manual-case-jump]").forEach((button) => button.addEventListener("click", () => {
      const index = Number(button.dataset.manualCaseJump);
      const target = document.getElementById(`manual-case-${index}`);
      if (!target) return;
      document.querySelectorAll("[data-manual-case-jump]").forEach((item) => {
        item.classList.toggle("is-active", item === button);
        if (item === button) item.setAttribute("aria-current", "true");
        else item.removeAttribute("aria-current");
      });
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
      target.focus({ preventScroll: true });
    }));
    document.querySelectorAll("[data-copy-log]").forEach((button) => button.addEventListener("click", async () => {
      try {
        await copyText(button.dataset.copyLog || "");
        showToast("日志筛选词已复制。");
      } catch (_) {
        showToast("复制失败，请手动选择日志筛选词。", true);
      }
    }));
    on("sourceFile", "change", (event) => {
      selectedFile = event.target.files?.[0] || null;
      ui.sourceFileName = selectedFile?.name || "";
      saveUi();
      render();
    });
    on("startDiscussion", "click", startDiscussion);
    on("sendDiscussionNote", "click", () => submitDiscussion(false));
    on("generatePlan", "click", () => submitDiscussion(true));
    on("retryPlan", "click", () => submitDiscussion(true));
    on("approvePlan", "click", approvePlan);
    on("createWorktree", "click", createWorktree);
    on("openCodexApp", "click", openCodexApp);
    on("newCodexAppChat", "click", newCodexAppChat);
    on("disconnectCodexApp", "click", disconnectCodexApp);
    on("executePlan", "click", () => executePlan(""));
    on("cancelExecution", "click", cancelExecution);
    on("resetExecutionSession", "click", () => executePlan("", true));
    on("agentMemoryPanel", "toggle", (event) => { ui.agentMemoryOpen = event.currentTarget.open; saveUi(); });
    on("returnToExecution", "click", () => {
      captureVisibleFields();
      if (!ui.verificationNote.trim() && !feedbackImageItems("verification").length) return showToast("请填写发现的问题，或至少添加一张问题截图。", true);
      executePlan(ui.verificationNote.trim());
    });
    on("approveVerification", "click", approveVerification);
    on("refreshGit", "click", refreshGit);
    on("confirmManualCommit", "click", confirmManualCommit);
    on("commitChanges", "click", commitChanges);
    on("startBugfix", "click", startBugfix);
    on("continueBugfix", "click", () => executePlan(""));
    on("generateKnowledge", "click", generateKnowledge);
    on("backToBugfix", "click", () => { ui.module = "flow"; ui.viewStage = "bugfix"; render(); });
    on("refreshKnowledgeCenter", "click", refreshKnowledgeCenter);
    document.querySelectorAll("[data-knowledge-filter]").forEach((button) => button.addEventListener("click", () => {
      ui.knowledgeFilter = button.dataset.knowledgeFilter || "pending";
      saveUi();
      render();
    }));
    document.querySelectorAll("[data-knowledge-review]").forEach((button) => button.addEventListener("click", () => {
      reviewKnowledge(
        button.dataset.knowledgeTaskId,
        button.dataset.knowledgeCandidateId,
        button.dataset.knowledgeReview
      );
    }));
    document.querySelectorAll("[data-knowledge-task]").forEach((button) => button.addEventListener("click", () => openKnowledgeTask(button.dataset.knowledgeTask)));
    on("submitAsk", "click", submitAsk);
    on("cancelAsk", "click", () => cancelActiveJob("Ask"));
    on("askQuestion", "input", (event) => {
      ui.askQuestion = event.target.value;
      saveUi();
      const submit = document.querySelector("#submitAsk");
      if (submit) submit.disabled = busy || Boolean(task?.activeJob) || !ui.askQuestion.trim();
    });
    document.querySelectorAll("[data-ask-template]").forEach((button) => button.addEventListener("click", () => {
      ui.askQuestion = button.dataset.askTemplate || "";
      saveUi();
      render();
      document.querySelector("#askQuestion")?.focus();
    }));
    on("bugfixDescription", "input", (event) => {
      ui.bugfixDescription = event.target.value;
      saveUi();
      updateFeedbackActionState("bugfix");
    });
    on("verificationNote", "input", () => updateFeedbackActionState("verification"));
    on("commitConfirmed", "change", (event) => { ui.commitConfirmed = event.target.checked; saveUi(); render(); });
    on("backToInput", "click", newTask);
    on("newTaskButton", "click", newTask);
    on("returnToDiscuss", "click", () => { ui.viewStage = "discuss"; render(); });
    on("backToPlan", "click", () => { ui.viewStage = "plan"; render(); });
    on("backToVerify", "click", () => { ui.viewStage = "verify"; render(); });
    const goToActiveStage = () => { ui.viewStage = activeFlowStageId(); render(); };
    on("goActiveStage", "click", goToActiveStage);
    on("goCurrentStage", "click", goToActiveStage);
    ["taskTitle", "sourceText", "existingDocumentPath", "existingWorktreePath", "discussionNote", "verificationNote", "commitMessage", "askQuestion"].forEach((id) => on(id, "input", captureVisibleFields));
    on("sourceUrl", "input", (event) => {
      captureVisibleFields();
      const options = document.querySelector("#larkReaderOptions");
      if (options) options.hidden = !isLarkLink(event.target.value);
    });
    on("baseBranch", "change", captureVisibleFields);
    on("refreshBranches", "click", () => {
      captureVisibleFields();
      withAction(async () => {
        await refreshProjectBranches();
        showToast(`已从主仓库刷新 ${projectBranches.length} 个分支。`);
      });
    });
    attachFeedbackImageHandlers("verification", "verificationNote");
    attachFeedbackImageHandlers("bugfix", "bugfixDescription");
  }

  function on(id, eventName, handler) {
    document.getElementById(id)?.addEventListener(eventName, handler);
  }

  async function copyText(value) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const input = document.createElement("textarea");
    input.value = value;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    const copied = document.execCommand("copy");
    input.remove();
    if (!copied) throw new Error("copy failed");
  }

  async function withAction(action) {
    if (busy) return;
    busy = true;
    render();
    try { await action(); }
    catch (error) { showToast(error.message, true); }
    finally { busy = false; render(); }
  }

  function fileBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
      reader.onerror = () => reject(new Error("无法读取上传文件。"));
      reader.readAsDataURL(file);
    });
  }

  async function startDiscussion() {
    captureVisibleFields();
    if (!ui.title.trim()) return showToast("请先填写需求名称。", true);
    if (ui.intakeMode !== "new") {
      if (!ui.existingDocumentPath.trim()) return showToast("请填写已有文档的绝对路径。", true);
      if (!ui.existingWorktreePath.trim()) return showToast("请填写已有 Worktree 的绝对路径。", true);
      await withAction(async () => {
        const result = await post("/api/tasks/import", {
          title: ui.title.trim(),
          intakeMode: ui.intakeMode,
          documentPath: ui.existingDocumentPath.trim(),
          worktreePath: ui.existingWorktreePath.trim()
        });
        ui.answers = {};
        ui.customAnswers = {};
        ui.discussionNote = "";
        setTask(result.task, true);
        showToast(ui.intakeMode === "existing_plan" ? "已有 Plan 与 Worktree 已接入，等待执行授权。" : "已有需求文档与 Worktree 已接入，开始只读讨论。" );
      });
      return;
    }
    if (ui.sourceType === "link" && !ui.sourceUrl.trim()) return showToast("请填写策划文档链接。", true);
    if (ui.sourceType === "paste" && !ui.sourceText.trim()) return showToast("请粘贴需求内容。", true);
    if (ui.sourceType === "file" && !selectedFile) return showToast("请重新选择要上传的策划文档。", true);
    await withAction(async () => {
      const body = { title: ui.title.trim(), workflowMode: ui.workflowMode, sourceType: ui.sourceType, sourceUrl: ui.sourceUrl.trim(), larkReader: ui.larkReader, sourceText: ui.sourceText, baseBranch: ui.baseBranch.trim() || health?.project?.defaultBaseBranch || "main" };
      if (selectedFile) {
        if (selectedFile.size > 8 * 1024 * 1024) throw new Error("上传文件不能超过 8 MB。");
        body.fileName = selectedFile.name;
        body.fileBase64 = await fileBase64(selectedFile);
      }
      const result = await post("/api/tasks", body);
      ui.answers = {};
      ui.customAnswers = {};
      ui.discussionNote = "";
      setTask(result.task, true);
      if (result.task.intake?.mode === "quick_change") showToast("轻量执行单已生成；确认 dry-run 后即可创建 Worktree。" );
      if (result.task.source?.reader === "chrome_mcp") showToast("已交给 Chrome MCP 读取飞书需求；只读，不会编辑网页。" );
      if (result.task.source?.reader === "lark_cli") showToast("已交给官方 Lark CLI 读取飞书需求；只读，不会修改飞书内容。" );
    });
  }

  async function submitDiscussion(generatePlan) {
    captureVisibleFields();
    const questions = task?.discussion?.result?.questions || [];
    if (!generatePlan && !questions.length && !ui.discussionNote.trim()) {
      return showToast("请先填写要继续讨论的补充说明。", true);
    }
    await withAction(async () => {
      const answers = collectAnswers();
      const result = await post(`/api/tasks/${task.id}/${generatePlan ? "plan" : "discussion"}`, { answers, note: ui.discussionNote.trim() });
      ui.discussionNote = "";
      if (!generatePlan) { ui.answers = {}; ui.customAnswers = {}; }
      if (generatePlan && result.task?.activeJob === "plan") {
        result.task.stage = "plan";
        result.task.maxStageIndex = Math.max(Number(result.task.maxStageIndex) || 0, stages.findIndex((item) => item.id === "plan"));
      }
      setTask(result.task, generatePlan);
    });
  }

  async function approvePlan() {
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/plan/approve`, { approved: true });
      setTask(result.task, true);
      showToast(task.worktree?.imported ? "Plan 已批准，已有 Worktree 校验完成；尚未写入 Plan。" : "Plan 已批准，Worktree dry-run 完成。这里只预检，尚未创建。" );
    });
  }

  async function createWorktree() {
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/worktree`, { confirmed: true });
      setTask(result.task, true);
      if (task.worktree?.imported) showToast("Plan 已绑定到已有 Worktree。" );
    });
  }

  async function openCodexApp() {
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/app/open`, {});
      const deepLink = result.task?.app?.deepLink;
      setTask(result.task, false);
      if (!deepLink) throw new Error("服务已建立 App Thread，但没有返回可打开的链接。");
      showToast("已同步当前项目目录并打开 Codex App。" );
      window.location.href = deepLink;
    });
  }

  async function newCodexAppChat() {
    if (task?.activeJob || task?.app?.status === "running") return showToast("当前任务正在执行，完成或停止后才能新建聊天。", true);
    const confirmed = window.confirm("为当前需求新建一个 Codex App 聊天？\n\n旧聊天不会删除，但控制台后续会改为复用新聊天。");
    if (!confirmed) return;
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/app/new`, {});
      const deepLink = result.task?.app?.deepLink;
      setTask(result.task, false);
      if (!deepLink) throw new Error("新聊天已创建，但没有返回可打开的链接。");
      showToast("已在当前项目目录新建 Codex App 聊天。" );
      window.location.href = deepLink;
    });
  }

  async function disconnectCodexApp() {
    if (task?.activeJob || task?.app?.status === "running") return showToast("当前任务正在执行，完成或停止后才能断开连接。", true);
    const confirmed = window.confirm("断开当前需求与 Codex App 聊天的连接？\n\n旧聊天不会删除；快速模式下次需要时会自动建立新聊天。");
    if (!confirmed) return;
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/app/disconnect`, {});
      setTask(result.task, false);
      showToast("已断开 Codex App 聊天；旧聊天仍保留。" );
    });
  }

  async function executePlan(feedback, resetSession = false) {
    await withAction(async () => {
      const verificationFeedback = task?.stage === "verify" || (task?.stage === "bugfix" && task?.bugfix?.status === "verify");
      const images = verificationFeedback && !resetSession ? feedbackImagesPayload("verification") : [];
      const result = await post(`/api/tasks/${task.id}/execute`, { feedback, resetSession, images, mode: ui.executionMode });
      ui.checks = [];
      ui.verificationNote = "";
      clearFeedbackImages("verification");
      setTask(result.task, true);
    });
  }

  async function cancelExecution() {
    return cancelActiveJob("当前执行");
  }

  async function cancelActiveJob(label) {
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/cancel`, {});
      setTask(result.task, false);
      showToast(`已请求停止${label}；已有结果和任务状态会保留。`);
    });
  }

  async function submitAsk() {
    captureVisibleFields();
    const question = ui.askQuestion.trim();
    if (!question) return showToast("请先填写要询问的问题。", true);
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/ask`, { question });
      ui.askQuestion = "";
      setTask(result.task, false);
      showToast("Ask 已进入只读队列。" );
    });
  }

  async function approveVerification() {
    captureVisibleFields();
    const cases = task?.execution?.result?.manual_cases || [];
    const requiredIndexes = requiredManualIndexes(cases);
    if (!requiredIndexes.length || requiredIndexes.some((index) => !ui.checks[index])) return showToast("请先完成全部 P0 / 必测人工验收项。", true);
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/verification`, { checks: ui.checks, note: ui.verificationNote });
      ui.commitConfirmed = false;
      setTask(result.task, true);
    });
  }

  async function refreshGit() {
    await withAction(async () => {
      const result = await api(`/api/tasks/${task.id}/git-status`);
      ui.commitConfirmed = false;
      setTask(result.task, false);
      showToast("已重新读取 Worktree Git 状态，请再次核对。" );
    });
  }

  async function commitChanges() {
    captureVisibleFields();
    if (!ui.commitConfirmed) return showToast("请先确认真实文件列表和验收结果。", true);
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/commit`, { message: ui.commitMessage.trim(), digest: task.git.digest });
      ui.commitConfirmed = false;
      setTask(result.task, true);
      showToast(`Commit 完成：${result.commitId.slice(0, 12)}`);
    });
  }

  async function confirmManualCommit() {
    captureVisibleFields();
    if (!ui.commitConfirmed) return showToast("请先确认真实文件列表和验收结果。", true);
    const pendingCount = task.git?.entries?.length || 0;
    const suffix = pendingCount ? `\n\n当前仍有 ${pendingCount} 项未提交改动；这些改动会保留并继续显示。` : "";
    const confirmed = window.confirm(`把当前 HEAD ${task.git.head.slice(0, 12)} 标记为“已人工提交”？\n\n控制台不会执行 git commit。${suffix}`);
    if (!confirmed) return;
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/commit/confirm-manual`, { digest: task.git.digest });
      ui.commitConfirmed = false;
      setTask(result.task, true);
      showToast(`已确认人工 Commit：${result.commitId.slice(0, 12)}`);
    });
  }

  async function startBugfix() {
    captureVisibleFields();
    const description = ui.bugfixDescription.trim();
    const images = feedbackImagesPayload("bugfix");
    if (!description && !images.length) return showToast("请填写 Bug 描述，或至少添加一张问题截图。", true);
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/bugfix`, { description, digest: task.git.digest, images, mode: ui.executionMode });
      ui.bugfixDescription = "";
      ui.checks = [];
      ui.verificationNote = "";
      ui.commitConfirmed = false;
      clearFeedbackImages("bugfix");
      setTask(result.task, true);
      showToast("Bug 定向修改已在当前模块进入队列。" );
    });
  }

  async function generateKnowledge() {
    if (!task?.id) return;
    await withAction(async () => {
      const result = await post(`/api/tasks/${task.id}/knowledge`, {});
      setTask(result.task, true);
      showToast("沉淀提炼已进入只读后台队列。" );
    });
  }

  async function reviewKnowledge(taskId, candidateId, decision) {
    if (!taskId || !candidateId || !["approved", "ignored"].includes(decision)) return;
    await withAction(async () => {
      const result = await post(`/api/tasks/${taskId}/knowledge/${candidateId}/review`, { decision });
      if (task?.id === taskId) {
        task = result.task;
        upsertTaskSummary(task);
      }
      const centerActive = ui.module === "knowledge-center";
      if (centerActive) await refreshKnowledgeCenter();
      showToast(decision === "approved" ? "候选已保留在本地审核清单；尚未发布到项目。" : "候选已忽略。" );
    });
  }

  async function openKnowledgeTask(taskId) {
    if (!taskId) return;
    if (task?.id === taskId) {
      ui.module = "flow";
      ui.viewStage = task.stage;
      saveUi();
      render();
      return;
    }
    captureVisibleFields();
    saveUi();
    await withAction(async () => {
      const result = await api(`/api/tasks/${taskId}`);
      selectedFile = null;
      setTask(result.task, false);
      ui.module = "flow";
      ui.viewStage = result.task.stage;
      saveUi();
      render();
    });
  }

  async function manageTask(taskId, action) {
    if (!taskId || !["archive", "restore", "delete"].includes(action)) return;
    const summary = taskSummaries.find((item) => item.id === taskId);
    if (!summary) return showToast("任务状态已经变化，请等待列表刷新。", true);
    if (summary.activeJob) return showToast("任务正在执行，完成后才能归档或删除。", true);
    if (action === "delete") {
      const confirmed = window.confirm(`删除“${summary.title}”的控制台任务记录？\n\n记录会移入本地回收目录；不会删除 Worktree、Plan、HTML 或 Git 改动。`);
      if (!confirmed) return;
    }
    captureVisibleFields();
    saveUi();
    await withAction(async () => {
      const selected = task?.id === taskId;
      const result = await post(`/api/tasks/${taskId}/${action}`, {});
      if (action === "delete") delete ui.taskViews?.[taskId];
      await refreshTaskSummaries();
      if (selected && action === "restore") {
        task = result.task;
        ui.taskId = task.id;
      } else if (selected) {
        task = null;
        selectedFile = null;
        activateTaskView("__new__");
      }
      saveUi();
      const messages = { archive: "任务已归档。", restore: "任务已恢复到需求队列。", delete: "任务记录已移入本地回收目录。" };
      showToast(messages[action]);
    });
  }

  async function switchTask(taskId) {
    if (!taskId || taskId === task?.id) return;
    captureVisibleFields();
    saveUi();
    await withAction(async () => {
      const result = await api(`/api/tasks/${taskId}`);
      selectedFile = null;
      setTask(result.task, false);
    });
  }

  function newTask() {
    captureVisibleFields();
    saveUi();
    task = null;
    selectedFile = null;
    const taskViews = ui.taskViews || {};
    delete taskViews.__new__;
    ui.showArchived = false;
    activateTaskView("__new__");
    ui.module = "flow";
    saveUi();
    render();
    schedulePoll();
  }

  boot();
})();
