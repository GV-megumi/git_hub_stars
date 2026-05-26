const chartColors = [
  "#285c8f",
  "#2e6f58",
  "#9a6400",
  "#8b4e8d",
  "#9a3d35",
  "#4f6f2d",
  "#6f5c2e",
  "#47606a",
];

const state = {
  githubApp: null,
  lastAnalysis: null,
  lastAnalysisUrl: null,
  analysisVersion: 0,
};

const els = {};

document.addEventListener("DOMContentLoaded", () => {
  bindElements();
  bindEvents();
  renderInitialState();
  loadGithubAppSession();
});

function bindElements() {
  [
    "repo-form",
    "repo-url",
    "mode-public",
    "mode-private",
    "analyze-button",
    "form-message",
    "github-app-status",
    "github-app-badge",
    "github-app-detail",
    "github-app-meta",
    "github-app-install",
    "github-app-clear",
    "score-value",
    "score-status",
    "repo-name",
    "repo-description",
    "mode-badge",
    "community-health",
    "partial-errors-count",
    "metrics-grid",
    "language-chart",
    "score-chart",
    "language-total",
    "score-dimension-count",
    "language-legend",
    "community-list",
    "activity-list",
    "risk-list",
    "recommendation-list",
    "partial-errors-list",
    "agent-note",
    "agent-private-confirm-row",
    "agent-private-confirm",
    "agent-button",
    "agent-status",
    "agent-result",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function bindEvents() {
  els["repo-form"].addEventListener("submit", analyzeRepository);
  els["repo-url"].addEventListener("input", invalidateAnalysisForInputChange);
  els["mode-public"].addEventListener("change", handleModeChange);
  els["mode-private"].addEventListener("change", handleModeChange);
  els["github-app-clear"].addEventListener("click", clearGithubAppSession);
  els["agent-button"].addEventListener("click", runAgentAnalysis);
  els["agent-private-confirm"].addEventListener("change", renderAgentAvailability);

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (state.lastAnalysis) {
        renderCharts(state.lastAnalysis);
      } else {
        drawEmptyCharts();
      }
    }, 120);
  });
}

function renderInitialState() {
  syncModeBadge();
  els["score-value"].textContent = "--";
  els["score-value"].className = "score-value";
  els["score-status"].textContent = "等待分析";
  els["repo-name"].textContent = "输入 GitHub 仓库 URL 后开始体检。";
  els["repo-description"].textContent = "系统会读取仓库基础信息、社区健康、活跃度和语言组成。";
  els["community-health"].textContent = "社区健康 --";
  els["community-health"].className = "state-badge neutral";
  els["partial-errors-count"].textContent = "部分错误 0";
  els["partial-errors-count"].className = "state-badge neutral";
  renderMetrics({});
  renderCommunity({}, null);
  renderActivity({});
  renderTextList(els["risk-list"], [], "暂无风险数据。");
  renderTextList(els["recommendation-list"], [], "暂无建议数据。");
  renderTextList(els["partial-errors-list"], [], "暂无部分错误。");
  drawEmptyCharts();
  renderAgentControls(false);
}

function resetAnalysisState() {
  state.analysisVersion += 1;
  state.lastAnalysis = null;
  state.lastAnalysisUrl = null;
  renderInitialState();
}

async function loadGithubAppSession() {
  try {
    const response = await fetch("/api/github-app/session", { headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "读取 GitHub App 状态失败。");
    }
    state.githubApp = payload;
    renderGithubAppSession(payload);
  } catch (error) {
    state.githubApp = null;
    els["github-app-status"].textContent = "GitHub App 状态不可用";
    els["github-app-badge"].textContent = "不可用";
    els["github-app-badge"].className = "state-badge danger";
    els["github-app-detail"].textContent = error.message || "读取状态失败。";
    els["github-app-meta"].replaceChildren();
    els["github-app-clear"].disabled = true;
  }
}

async function clearGithubAppSession() {
  els["github-app-clear"].disabled = true;
  try {
    const response = await fetch("/github-app/clear", { method: "POST", headers: { Accept: "application/json" } });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.message || "清除授权状态失败。");
    }
    resetAnalysisState();
    setFormMessage("已清除本地 GitHub App 授权状态。", "success");
    await loadGithubAppSession();
  } catch (error) {
    setFormMessage(error.message || "清除授权状态失败。", "error");
  } finally {
    els["github-app-clear"].disabled = !(state.githubApp && state.githubApp.installed);
  }
}

function renderGithubAppSession(session) {
  const configured = Boolean(session.configured);
  const installed = Boolean(session.installed);
  const account = session.account && session.account.login ? session.account.login : "--";
  const repositories = Array.isArray(session.repositories) ? session.repositories : [];

  els["github-app-status"].textContent = installed
    ? `已连接 ${account}`
    : configured
      ? "GitHub App 已配置，尚未授权"
      : "GitHub App 未配置";

  els["github-app-badge"].textContent = installed ? "已授权" : configured ? "未授权" : "未配置";
  els["github-app-badge"].className = installed
    ? "state-badge"
    : configured
      ? "state-badge warning"
      : "state-badge neutral";

  els["github-app-detail"].textContent = installed
    ? "私有仓库可使用当前 installation 的只读授权。"
    : configured
      ? "公开仓库可直接体检；私有仓库请先安装或更新授权。"
      : "公开仓库可直接体检；私有仓库需要配置 GitHub App。";

  els["github-app-meta"].replaceChildren(
    createMetaItem("账户", account),
    createMetaItem("仓库范围", session.repository_selection || "--"),
    createMetaItem("仓库数量", repositories.length ? String(repositories.length) : "--"),
    createMetaItem("AI Agent", session.agent_configured ? "可用" : "未配置"),
    createMetaItem("权限", summarizePermissions(session.permissions))
  );

  els["github-app-clear"].disabled = !installed;
  if (configured) {
    els["github-app-install"].href = "/github-app/install";
    els["github-app-install"].setAttribute("aria-disabled", "false");
  } else {
    els["github-app-install"].removeAttribute("href");
    els["github-app-install"].setAttribute("aria-disabled", "true");
  }
  renderAgentControls(Boolean(state.lastAnalysis));
}

async function analyzeRepository(event) {
  event.preventDefault();

  const url = els["repo-url"].value.trim();
  const privateMode = els["mode-private"].checked;
  if (!url) {
    setFormMessage("请输入 GitHub 仓库 URL。", "error");
    return;
  }

  const requestVersion = beginAnalysisRefresh();
  setLoading(true);
  setFormMessage("分析中...", "neutral");

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ url, private_mode: privateMode }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.message || "分析失败。");
    }
    if (requestVersion !== state.analysisVersion) {
      return;
    }
    state.lastAnalysis = payload;
    state.lastAnalysisUrl = url;
    setFormMessage("分析完成。", "success");
    renderAnalysis(payload);
  } catch (error) {
    if (requestVersion !== state.analysisVersion) {
      return;
    }
    resetAnalysisState();
    setFormMessage(error.message || "分析失败。", "error");
  } finally {
    setLoading(false);
  }
}

function renderAnalysis(data) {
  const repo = data.repository || {};
  const score = data.score || {};
  const community = data.community || {};
  const activity = data.activity || {};
  const partialErrors = Array.isArray(data.partial_errors) ? data.partial_errors : [];

  const numericScore = Number.isFinite(Number(score.score)) ? Number(score.score) : null;
  els["score-value"].textContent = numericScore === null ? "--" : String(numericScore);
  els["score-value"].className = scoreClass(numericScore);
  els["score-status"].textContent = score.status || "未评级";
  els["repo-name"].textContent = repo.full_name || "未知仓库";
  els["repo-description"].textContent = repo.description || "暂无仓库描述。";
  els["mode-badge"].textContent = data.private_mode ? "私有模式" : "公开模式";
  els["community-health"].textContent = `社区健康 ${formatValue(community.health_percentage, "%")}`;
  els["partial-errors-count"].textContent = `部分错误 ${partialErrors.length}`;
  els["partial-errors-count"].className = partialErrors.length ? "state-badge warning" : "state-badge neutral";

  renderMetrics(repo);
  renderCommunity(community.files || {}, community.health_percentage);
  renderActivity(activity);
  renderRisksAndRecommendations(score, partialErrors);
  renderCharts(data);
  renderAgentControls(true);
}

function renderMetrics(repo) {
  const metrics = [
    ["Stars", formatNumber(repo.stars)],
    ["Forks", formatNumber(repo.forks)],
    ["Issues", formatNumber(repo.open_issues)],
    ["Watchers", formatNumber(repo.watchers)],
    ["默认分支", repo.default_branch || "--"],
    ["License", repo.license_spdx || "--"],
    ["仓库大小", formatValue(repo.size_kb, " KB")],
    ["最近更新", formatDate(repo.updated_at)],
    ["最近推送", formatDate(repo.pushed_at)],
    ["Fork 仓库", repo.fork ? "是" : repo.fork === false ? "否" : "--"],
  ];

  els["metrics-grid"].replaceChildren(...metrics.map(([label, value]) => createMetricTile(label, value)));
}

function renderCommunity(files, healthPercentage) {
  const checklist = [
    { label: "README", aliases: ["readme"] },
    { label: "License", aliases: ["license"] },
    { label: "CONTRIBUTING", aliases: ["contributing"] },
    { label: "Code of Conduct", aliases: ["code_of_conduct"] },
    { label: "Security Policy", aliases: ["security", "security_policy", "security_policy_file"] },
    { label: "Issue Template", aliases: ["issue_template"] },
    { label: "PR Template", aliases: ["pull_request_template", "pr_template"] },
  ];
  const rows = checklist.map((item) => (
    createCheckItem(item.label, item.aliases.some((alias) => Boolean(files[alias])))
  ));

  if (healthPercentage !== null && healthPercentage !== undefined) {
    rows.unshift(createCheckItem(`社区健康 ${healthPercentage}%`, Number(healthPercentage) >= 70));
  }

  els["community-list"].replaceChildren(...rows);
}

function renderActivity(activity) {
  const facts = [
    ["近 30 天提交", formatNumber(activity.commits_30d_count)],
    ["近 90 天提交", formatNumber(activity.commits_90d_count)],
    ["最近提交样本", formatNumber(activity.recent_commits_count)],
    ["贡献者", formatNumber(activity.contributors_count)],
    ["Releases", formatNumber(activity.releases_count)],
    ["Open PRs", formatNumber(activity.open_pulls_count)],
    ["最新 Release", formatDate(activity.latest_release_at)],
  ];

  els["activity-list"].replaceChildren(...facts.map(([label, value]) => createFactItem(label, value)));
}

function renderRisksAndRecommendations(score, partialErrors) {
  const risks = Array.isArray(score.risks) ? score.risks : [];
  const recommendations = Array.isArray(score.recommendations) ? score.recommendations : [];

  renderObjectList(els["risk-list"], risks, "暂无风险。", (risk) => {
    const level = risk.level ? `${risk.level}: ` : "";
    return `${level}${risk.message || risk.code || "未知风险"}`;
  });
  renderTextList(els["recommendation-list"], recommendations, "暂无建议。");
  renderObjectList(els["partial-errors-list"], partialErrors, "暂无部分错误。", describePartialError);
}

function renderCharts(data) {
  drawLanguageChart(data.languages || {});
  drawScoreChart((data.score && data.score.dimensions) || {});
}

function drawEmptyCharts() {
  drawCanvasEmpty(els["language-chart"], "暂无语言数据");
  drawCanvasEmpty(els["score-chart"], "暂无维度评分");
  els["language-total"].textContent = "无数据";
  els["score-dimension-count"].textContent = "无数据";
  els["language-legend"].replaceChildren();
}

function drawLanguageChart(languages) {
  const entries = Object.entries(languages)
    .map(([name, value]) => [name, Number(value)])
    .filter(([, value]) => Number.isFinite(value) && value > 0)
    .sort((a, b) => b[1] - a[1]);

  if (!entries.length) {
    drawCanvasEmpty(els["language-chart"], "暂无语言数据");
    els["language-total"].textContent = "无数据";
    els["language-legend"].replaceChildren();
    return;
  }

  const { ctx, width, height } = prepareCanvas(els["language-chart"]);
  ctx.clearRect(0, 0, width, height);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const radius = Math.min(width, height) * 0.28;
  const innerRadius = radius * 0.58;
  const cx = width / 2;
  const cy = height / 2;
  let start = -Math.PI / 2;

  entries.forEach(([, value], index) => {
    const angle = (value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, start, start + angle);
    ctx.closePath();
    ctx.fillStyle = chartColors[index % chartColors.length];
    ctx.fill();
    start += angle;
  });

  ctx.beginPath();
  ctx.arc(cx, cy, innerRadius, 0, Math.PI * 2);
  ctx.fillStyle = "#f9faf7";
  ctx.fill();

  ctx.fillStyle = "#1d2528";
  ctx.font = "700 18px Segoe UI, Microsoft YaHei, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(`${entries.length} 项`, cx, cy - 7);
  ctx.fillStyle = "#657076";
  ctx.font = "12px Segoe UI, Microsoft YaHei, sans-serif";
  ctx.fillText("语言", cx, cy + 14);

  els["language-total"].textContent = `${entries.length} 项语言`;
  els["language-legend"].replaceChildren(...entries.slice(0, 8).map(([name, value], index) => {
    const item = document.createElement("div");
    item.className = "legend-item";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.backgroundColor = chartColors[index % chartColors.length];
    const label = document.createElement("span");
    label.className = "legend-label";
    label.textContent = `${name} ${formatPercent(value)}`;
    item.append(swatch, label);
    return item;
  }));
}

function drawScoreChart(dimensions) {
  const entries = Object.entries(dimensions)
    .map(([name, value]) => [name, Number(value)])
    .filter(([, value]) => Number.isFinite(value))
    .slice(0, 8);

  if (!entries.length) {
    drawCanvasEmpty(els["score-chart"], "暂无维度评分");
    els["score-dimension-count"].textContent = "无数据";
    return;
  }

  const { ctx, width, height } = prepareCanvas(els["score-chart"]);
  ctx.clearRect(0, 0, width, height);

  const left = Math.min(132, Math.max(86, width * 0.28));
  const right = 36;
  const top = 22;
  const bottom = 20;
  const plotWidth = Math.max(100, width - left - right);
  const rowHeight = (height - top - bottom) / entries.length;
  const barHeight = Math.min(26, Math.max(14, rowHeight * 0.52));

  ctx.strokeStyle = "#d9dfd5";
  ctx.fillStyle = "#657076";
  ctx.font = "12px Segoe UI, Microsoft YaHei, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  [0, 25, 50, 75, 100].forEach((tick) => {
    const x = left + (tick / 100) * plotWidth;
    ctx.beginPath();
    ctx.moveTo(x, top - 4);
    ctx.lineTo(x, height - bottom + 3);
    ctx.stroke();
    ctx.fillText(String(tick), x, 4);
  });

  entries.forEach(([name, value], index) => {
    const y = top + index * rowHeight + rowHeight / 2;
    const safeValue = Math.max(0, Math.min(100, value));
    const barWidth = (safeValue / 100) * plotWidth;

    ctx.fillStyle = "#1d2528";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.font = "700 12px Segoe UI, Microsoft YaHei, sans-serif";
    ctx.fillText(truncateCanvasText(ctx, name, left - 12), left - 12, y);

    ctx.fillStyle = "#eef2ee";
    roundRect(ctx, left, y - barHeight / 2, plotWidth, barHeight, 5);
    ctx.fill();

    ctx.fillStyle = chartColors[index % chartColors.length];
    roundRect(ctx, left, y - barHeight / 2, barWidth, barHeight, 5);
    ctx.fill();

    ctx.fillStyle = "#1d2528";
    ctx.textAlign = "left";
    ctx.font = "700 12px Segoe UI, Microsoft YaHei, sans-serif";
    ctx.fillText(String(Math.round(safeValue)), left + Math.min(plotWidth - 24, barWidth + 7), y);
  });

  els["score-dimension-count"].textContent = `${entries.length} 个维度`;
}

function drawCanvasEmpty(canvas, message) {
  const { ctx, width, height } = prepareCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#f9faf7";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d9dfd5";
  ctx.setLineDash([5, 6]);
  ctx.strokeRect(18, 18, width - 36, height - 36);
  ctx.setLineDash([]);
  ctx.fillStyle = "#657076";
  ctx.font = "700 14px Segoe UI, Microsoft YaHei, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(message, width / 2, height / 2);
}

function prepareCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const computed = window.getComputedStyle(canvas);
  const width = Math.max(280, rect.width || 640);
  const height = Math.max(220, parseFloat(computed.height) || 300);
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width, height };
}

function roundRect(ctx, x, y, width, height, radius) {
  const safeRadius = Math.min(radius, height / 2, width / 2);
  ctx.beginPath();
  ctx.moveTo(x + safeRadius, y);
  ctx.lineTo(x + width - safeRadius, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + safeRadius);
  ctx.lineTo(x + width, y + height - safeRadius);
  ctx.quadraticCurveTo(x + width, y + height, x + width - safeRadius, y + height);
  ctx.lineTo(x + safeRadius, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - safeRadius);
  ctx.lineTo(x, y + safeRadius);
  ctx.quadraticCurveTo(x, y, x + safeRadius, y);
  ctx.closePath();
}

function syncModeBadge() {
  const privateMode = els["mode-private"].checked;
  els["mode-badge"].textContent = privateMode ? "私有模式" : "公开模式";
  els["mode-badge"].className = privateMode ? "state-badge warning" : "state-badge";
}

function handleModeChange() {
  syncModeBadge();
  invalidateAnalysisForInputChange();
}

function invalidateAnalysisForInputChange() {
  state.analysisVersion += 1;
  if (!state.lastAnalysis && !state.lastAnalysisUrl) {
    return;
  }
  state.lastAnalysis = null;
  state.lastAnalysisUrl = null;
  renderAgentControls(false);
  els["score-status"].textContent = "输入已变更，请重新体检";
}

function beginAnalysisRefresh() {
  state.analysisVersion += 1;
  state.lastAnalysis = null;
  state.lastAnalysisUrl = null;
  renderAgentControls(false);
  return state.analysisVersion;
}

function renderAgentControls(hasAnalysis) {
  const privateMode = Boolean(state.lastAnalysis && state.lastAnalysis.private_mode);
  const modelReady = isAgentConfigured();
  if (hasAnalysis && !modelReady) {
    els["agent-note"].textContent = "模型参数未配置，AI 深度分析暂不可用。";
  } else {
    els["agent-note"].textContent = hasAnalysis
      ? privateMode
        ? "私有仓库 AI 分析需要单独确认后再发送体检摘要和受控 GitHub API 摘要。"
        : "公开仓库 AI 分析会结合系统评分、GitHub API 摘要和可用公开网页证据。"
      : "系统体检完成后，可单独启动 AI 深度分析。";
  }
  els["agent-private-confirm-row"].classList.toggle("hidden", !privateMode || !hasAnalysis);
  els["agent-private-confirm"].checked = false;
  els["agent-status"].textContent = "";
  els["agent-status"].style.color = "#657076";
  els["agent-result"].replaceChildren();
  els["agent-button"].textContent = "启动 AI 深度分析";
  renderAgentAvailability();
}

function renderAgentAvailability() {
  const hasAnalysis = Boolean(state.lastAnalysis);
  const privateMode = Boolean(state.lastAnalysis && state.lastAnalysis.private_mode);
  const confirmed = Boolean(els["agent-private-confirm"].checked);
  els["agent-button"].disabled = !hasAnalysis || !isAgentConfigured() || (privateMode && !confirmed);
}

async function runAgentAnalysis() {
  if (!state.lastAnalysis) {
    setAgentStatus("请先完成系统体检。", "error");
    return;
  }
  if (!isAgentConfigured()) {
    setAgentStatus("模型参数未配置，无法启动 AI 深度分析。", "error");
    renderAgentAvailability();
    return;
  }
  if (!state.lastAnalysis.analysis_id) {
    setAgentStatus("当前体检缺少 analysis_id，请重新体检。", "error");
    renderAgentAvailability();
    return;
  }

  const privateMode = Boolean(state.lastAnalysis.private_mode);
  const agentAnalysisVersion = state.analysisVersion;
  const agentAnalysis = state.lastAnalysis;
  const agentAnalysisUrl = state.lastAnalysisUrl;
  if (privateMode && !els["agent-private-confirm"].checked) {
    setAgentStatus("私有仓库需要先确认数据发送范围。", "error");
    renderAgentAvailability();
    return;
  }

  setAgentLoading(true);
  setAgentStatus("AI 分析中...", "neutral");
  els["agent-result"].replaceChildren();

  try {
    const response = await fetch("/api/agent/analyze", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(buildAgentPayload(privateMode)),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.message || "AI 分析失败。");
    }
    if (
      agentAnalysisVersion !== state.analysisVersion ||
      agentAnalysis !== state.lastAnalysis ||
      agentAnalysisUrl !== state.lastAnalysisUrl
    ) {
      return;
    }
    setAgentStatus("AI 分析完成。", "success");
    renderAgentResult(payload);
  } catch (error) {
    if (
      agentAnalysisVersion !== state.analysisVersion ||
      agentAnalysis !== state.lastAnalysis ||
      agentAnalysisUrl !== state.lastAnalysisUrl
    ) {
      return;
    }
    setAgentStatus(error.message || "AI 分析失败。", "error");
  } finally {
    setAgentLoading(false);
  }
}

function buildAgentPayload(privateMode) {
  return {
    analysis_id: state.lastAnalysis.analysis_id,
    confirm_private_data_to_model: privateMode ? els["agent-private-confirm"].checked : undefined,
  };
}

function isAgentConfigured() {
  return Boolean(state.githubApp && state.githubApp.agent_configured);
}

function renderAgentResult(result) {
  const blocks = [];
  blocks.push(createAgentScoreBlock(result));
  blocks.push(createAgentSection("发现", result.findings, "暂无发现。", describeAgentItem));
  blocks.push(createAgentSection("建议", result.recommendations, "暂无建议。", describeAgentItem));
  blocks.push(createAgentSection("引用", result.references, "暂无引用。", describeReference));
  blocks.push(createAgentToolBlock(result));
  els["agent-result"].replaceChildren(...blocks);
}

function createAgentScoreBlock(result) {
  const block = document.createElement("div");
  block.className = "agent-score-block";
  const score = document.createElement("strong");
  score.textContent = formatAgentScore(result.ai_score);
  const summary = document.createElement("p");
  summary.textContent = result.summary || "AI 未返回摘要。";
  const meta = document.createElement("span");
  meta.textContent = `置信度 ${result.confidence || "unknown"}`;
  block.append(score, summary, meta);
  return block;
}

function createAgentSection(title, items, emptyText, describe) {
  const section = document.createElement("div");
  section.className = "agent-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const list = document.createElement("ul");
  list.className = "stack-list compact-list";
  renderObjectList(list, Array.isArray(items) ? items : [], emptyText, describe);
  section.append(heading, list);
  return section;
}

function createAgentToolBlock(result) {
  const section = document.createElement("div");
  section.className = "agent-section";
  const heading = document.createElement("h3");
  heading.textContent = "工具";
  const facts = document.createElement("div");
  facts.className = "fact-list compact-facts";
  const usedTools = Array.isArray(result.used_tools) ? result.used_tools : [];
  const attemptedTools = Array.isArray(result.attempted_tools) ? result.attempted_tools : [];
  const toolErrors = Array.isArray(result.tool_errors) ? result.tool_errors : [];
  facts.replaceChildren(
    createFactItem("Tavily", result.tavily_enabled ? "已启用" : "未启用"),
    createFactItem("已使用工具", usedTools.length ? usedTools.join(", ") : "--"),
    createFactItem("已尝试工具", attemptedTools.length ? String(attemptedTools.length) : "--"),
    createFactItem("工具错误", toolErrors.length ? String(toolErrors.length) : "0")
  );
  section.append(heading, facts);
  if (toolErrors.length) {
    const list = document.createElement("ul");
    list.className = "stack-list compact-list";
    renderObjectList(list, toolErrors, "暂无工具错误。", describeToolError);
    section.append(list);
  }
  return section;
}

function describeAgentItem(item) {
  if (item && typeof item === "object") {
    const title = item.title || item.summary || item.code;
    const message = item.message && item.message !== title ? item.message : "";
    const detail = [title, message].filter(Boolean).join(" - ") || item.message;
    const level = item.level || item.severity || item.type;
    return [level, detail].filter(Boolean).join(": ") || JSON.stringify(item);
  }
  return String(item);
}

function describeReference(item) {
  if (item && typeof item === "object") {
    const title = item.title || item.name || item.url || "引用";
    return item.url ? `${title} ${item.url}` : String(title);
  }
  return String(item);
}

function describeToolError(item) {
  if (item && typeof item === "object") {
    return `${item.tool || "tool"}: ${item.message || item.error || "执行失败"}`;
  }
  return String(item);
}

function formatAgentScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) {
    return "--";
  }
  return String(Math.round(score));
}

function setAgentLoading(isLoading) {
  els["agent-button"].disabled = true;
  els["agent-button"].textContent = isLoading ? "分析中..." : "启动 AI 深度分析";
  if (!isLoading) {
    renderAgentAvailability();
  }
}

function setAgentStatus(message, tone) {
  els["agent-status"].textContent = message;
  els["agent-status"].style.color = tone === "success" ? "#2e6f58" : tone === "neutral" ? "#657076" : "#9a3d35";
}

function setLoading(isLoading) {
  els["analyze-button"].disabled = isLoading;
  els["analyze-button"].textContent = isLoading ? "体检中..." : "开始体检";
}

function setFormMessage(message, tone) {
  els["form-message"].textContent = message;
  els["form-message"].style.color = tone === "success" ? "#2e6f58" : tone === "neutral" ? "#657076" : "#9a3d35";
}

function createMetricTile(label, value) {
  const tile = document.createElement("div");
  tile.className = "metric-tile";
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const valueEl = document.createElement("strong");
  valueEl.textContent = value;
  tile.append(labelEl, valueEl);
  return tile;
}

function createMetaItem(label, value) {
  const item = document.createElement("div");
  item.className = "meta-item";
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const valueEl = document.createElement("strong");
  valueEl.textContent = value;
  item.append(labelEl, valueEl);
  return item;
}

function createCheckItem(label, present) {
  const item = document.createElement("div");
  item.className = "check-item";
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const stateEl = document.createElement("span");
  stateEl.className = present ? "check-state" : "check-state missing";
  stateEl.textContent = present ? "已具备" : "缺失";
  item.append(labelEl, stateEl);
  return item;
}

function createFactItem(label, value) {
  const item = document.createElement("div");
  item.className = "fact-item";
  const labelEl = document.createElement("span");
  labelEl.textContent = label;
  const valueEl = document.createElement("strong");
  valueEl.textContent = value;
  item.append(labelEl, valueEl);
  return item;
}

function createPlainBlock(text, className) {
  const item = document.createElement("div");
  item.className = className;
  item.textContent = text;
  return item;
}

function renderTextList(list, items, emptyText) {
  const normalized = Array.isArray(items) ? items : [];
  if (!normalized.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = emptyText;
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...normalized.map((item) => {
    const li = document.createElement("li");
    li.textContent = String(item);
    return li;
  }));
}

function renderObjectList(list, items, emptyText, describe) {
  const normalized = Array.isArray(items) ? items : [];
  if (!normalized.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = emptyText;
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...normalized.map((item) => {
    const li = document.createElement("li");
    li.textContent = describe(item);
    return li;
  }));
}

function describePartialError(error) {
  if (!error || typeof error !== "object") {
    return "未知数据获取错误。";
  }
  const area = error.area || error.endpoint || error.source || "GitHub 数据";
  const message = error.message || error.error || "获取失败";
  return `${area}: ${message}`;
}

function summarizePermissions(permissions) {
  if (!permissions || typeof permissions !== "object") {
    return "--";
  }
  const entries = Object.entries(permissions);
  if (!entries.length) {
    return "--";
  }
  return entries.slice(0, 3).map(([name, level]) => `${name}:${level}`).join(", ");
}

function scoreClass(score) {
  if (score === null) {
    return "score-value";
  }
  if (score < 55) {
    return "score-value has-danger";
  }
  if (score < 70) {
    return "score-value has-warning";
  }
  return "score-value";
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return String(value);
  }
  return new Intl.NumberFormat("zh-CN").format(number);
}

function formatValue(value, suffix) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  return `${formatNumber(value)}${suffix}`;
}

function formatPercent(value) {
  if (!Number.isFinite(value)) {
    return "--";
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)}%`;
}

function formatDate(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function truncateCanvasText(ctx, text, maxWidth) {
  const value = String(text);
  if (ctx.measureText(value).width <= maxWidth) {
    return value;
  }
  let truncated = value;
  while (truncated.length > 1 && ctx.measureText(`${truncated}...`).width > maxWidth) {
    truncated = truncated.slice(0, -1);
  }
  return `${truncated}...`;
}
