# Github 仓库体检工具需求说明书

## 1. 项目背景

本工具用于分析公开 Github 仓库的基础状态、活跃度、社区规范和潜在维护风险。用户可以先通过 Github 登录授权，系统使用登录会话中的授权访问 Github API；用户输入一个公开仓库 URL 后，系统先返回确定性的系统检测结果和系统评分，再允许用户单独触发 AI agent 深度分析。

第一版目标是做成一个本地 Web 工具，技术栈使用 Python 后端和 HTML/CSS/JavaScript 前端，环境通过 conda 初始化。

## 2. 用户目标

- 快速判断一个公开 Github 仓库是否活跃、规范、值得关注或依赖。
- 用图表看清 Star、Fork、Issue、语言分布、维护活跃度等基础指标。
- 获得明确的健康状态和可执行建议，而不是只看原始数字。
- 在需要时单独启动 AI agent 分析，让 agent 结合搜索结果、仓库页面和基础检测信息给出更深入的评分和建议。

## 3. 核心流程

1. 用户打开 Web 页面。
2. 用户点击“使用 Github 登录”，完成 OAuth 授权。
3. 用户输入公开 Github 仓库 URL，例如 `https://github.com/fastapi/fastapi`。
4. 用户点击“开始体检”。
5. 后端解析出 `owner/repo`。
6. 后端优先使用登录会话中的 Github OAuth access token 调用 Github REST API 获取基础数据。
7. 系统生成确定性的系统评分、健康状态、图表数据和风险提示。
8. 前端优先展示系统评分和状态。
9. 用户可点击“AI 深度分析”单独启动 agent 分析。
10. AI agent 接收仓库链接、系统提示词和已探测到的基础信息，自行调用 Tavily 搜索/网页提取能力补充上下文，最后返回 AI 评分、分析结论和建议。

## 4. 功能范围

### 4.1 MVP 必须支持

- 输入公开 Github 仓库 URL。
- 校验 URL 是否为 Github 仓库地址。
- 支持 Github 登录、登录状态展示和退出登录。
- 不在 `.env` 中配置静态 `GITHUB_TOKEN`；Github API token 来自用户 OAuth 登录会话。
- 获取仓库基础信息：名称、描述、Owner、默认分支、创建时间、更新时间、最近 push 时间、仓库大小、是否 archived、是否 fork。
- 获取热度指标：Star 数、Fork 数、Watcher/Subscriber 数、Open Issues 数。
- 获取语言分布：调用 Github Languages API，计算各语言字节占比。
- 获取社区健康信息：README、LICENSE、CONTRIBUTING、CODE_OF_CONDUCT、Issue Template、PR Template 等状态。
- 获取维护活跃信息：近 30/90 天提交数量、贡献者数量、Release 数、最近 Release。
- 生成系统评分、状态等级和风险提示。
- 通过图表展示语言分布、评分维度、关键指标。
- 支持错误提示：URL 无效、仓库不存在、API 限流、Github 网络失败。

### 4.2 Github 登录

Github 登录用于替代静态 Github token 配置。系统只在 `.env` 中保存 OAuth App 配置，不保存用户 access token。

登录设计：

- 使用 Github OAuth App。
- `.env` 保存 `GITHUB_CLIENT_ID`、`GITHUB_CLIENT_SECRET`、`GITHUB_OAUTH_CALLBACK_URL` 和 Flask 会话密钥。
- 用户 access token 存在服务端 session 中，默认不落盘、不写日志、不写 `.env`。
- 第一版只分析公开仓库，不申请私有仓库 `repo` scope。
- 登录失败、授权取消、session 过期时给出明确提示。
- 未登录时可以提示用户先登录；如果后续决定保留游客模式，游客模式只支持低频公开仓库分析。

### 4.3 扩展功能：AI Agent 分析

AI agent 分析是扩展功能，不阻塞基础体检结果。默认检测流程必须先给出系统评分和状态，agent 分析由用户单独触发。

agent 需要具备：

- 输入：仓库 URL、基础检测 JSON、系统评分、风险提示、分析提示词。
- 工具：Tavily API 包装的网页搜索和网页提取能力，或直接对接 Tavily MCP。
- 模型配置：从 `.env` 读取模型 `base_url`、`api_key` 和 `model`。
- 行为：围绕该仓库主动查找 Github 页面、README、Release、Issue/PR 讨论、文档站、社区讨论等公开信息。
- 输出：AI 评分、评分理由、关键发现、风险解释、改进建议、引用链接。

第一版可以先预留接口和页面入口；agent 实现可作为第二阶段开发。

## 5. 体检指标

### 5.1 基础热度

- Stars：仓库关注度。
- Forks：复用和二次开发活跃度。
- Watchers/Subscribers：持续关注人数。
- Open Issues：待处理问题规模。
- Topics：仓库主题和生态定位。

### 5.2 代码组成

- 主语言。
- 语言字节分布。
- 语言占比图。
- 仓库大小。

### 5.3 活跃维护

- 最近 push 时间。
- 最近更新时间。
- 近 30 天提交数。
- 近 90 天提交数。
- 最近 Release 时间。
- Release 总数。
- 贡献者数量。

### 5.4 协作状态

- Open Issues 数。
- Open PR 数。
- Issue/PR 积压提示。
- 是否长期无维护迹象。

### 5.5 社区规范

- README 是否存在。
- LICENSE 是否存在。
- CONTRIBUTING 是否存在。
- CODE_OF_CONDUCT 是否存在。
- Issue Template 是否存在。
- Pull Request Template 是否存在。
- Security Policy 是否存在。
- Github Community Profile 的 `health_percentage`。

### 5.6 风险提示

- 仓库 archived。
- 仓库 disabled。
- 长期无提交或无 Release。
- 无 License。
- 无 README。
- Issue/PR 积压明显。
- Fork 仓库且不是源项目。
- Github API 数据不完整或接口受限。

## 6. 评分体系

评分分为两套：系统评分和 AI 评分。页面优先展示系统评分，因为系统评分来自可重复、可解释的结构化数据；AI 评分作为增强分析，单独触发、单独展示。

### 6.1 系统评分

系统评分总分 100，基于确定性规则计算。

| 维度 | 分值 | 说明 |
| --- | ---: | --- |
| 活跃维护 | 30 | 最近 push、近 30/90 天提交、Release 新鲜度 |
| 社区规范 | 25 | README、LICENSE、贡献指南、行为准则、模板、安全策略 |
| 协作健康 | 15 | Issue/PR 数量、积压情况、是否长期无人处理 |
| 项目成熟度 | 15 | Star、Fork、贡献者、Release、Topics |
| 代码组成 | 10 | 语言分布是否可识别、是否有实际代码 |
| 风险扣分 | -5 到 0 | archived、disabled、无 license、长期未维护等 |

系统评分状态：

| 分数 | 状态 | 含义 |
| ---: | --- | --- |
| 85-100 | 优秀 | 活跃、规范、风险较低 |
| 70-84 | 良好 | 基本健康，有少量改进项 |
| 55-69 | 一般 | 可用但存在明显维护或规范缺口 |
| 40-54 | 风险 | 维护、社区或协作状态存在较大风险 |
| 0-39 | 高风险 | 可能不适合作为关键依赖，需要人工复核 |

### 6.2 AI 评分

AI 评分总分 100，但不替代系统评分。AI 评分关注系统数据之外的上下文，例如项目定位、README 质量、Issue 讨论质量、Release 说明、外部文档、社区反馈、是否有迁移公告、是否存在维护者说明等。

AI agent 输入示例：

```json
{
  "repository_url": "https://github.com/owner/repo",
  "system_score": 76,
  "system_status": "良好",
  "detected_metrics": {
    "stars": 12000,
    "forks": 800,
    "open_issues": 120,
    "last_push_at": "2026-05-20T10:00:00Z",
    "languages": {
      "Python": 82.5,
      "HTML": 10.0,
      "JavaScript": 7.5
    },
    "community_files": {
      "readme": true,
      "license": true,
      "contributing": false,
      "code_of_conduct": false
    }
  }
}
```

AI agent 提示词要点：

- 你是 Github 仓库健康分析 agent。
- 先阅读系统提供的基础检测结果。
- 使用 Tavily 搜索和网页提取工具查找该仓库的 Github 页面、README、Release、Issue、PR、官方文档和外部讨论。
- 判断系统评分是否遗漏了重要背景。
- 给出 AI 评分、评分理由、主要风险、改进建议。
- 每条关键判断必须附带来源链接。
- 如果公开信息不足，明确说明不确定性，不要编造结论。

AI 输出结构：

```json
{
  "ai_score": 82,
  "confidence": "medium",
  "summary": "项目活跃且文档较完整，但贡献流程不够明确。",
  "findings": [
    {
      "level": "warning",
      "title": "贡献指南缺失",
      "evidence_url": "https://github.com/owner/repo",
      "detail": "系统未检测到 CONTRIBUTING 文件。"
    }
  ],
  "recommendations": [
    "补充 CONTRIBUTING.md",
    "为 Issue 增加模板",
    "在 README 中说明项目维护状态"
  ]
}
```

## 7. 数据来源

优先使用 Github 官方 REST API：

- 仓库信息：`GET /repos/{owner}/{repo}`
- 语言分布：`GET /repos/{owner}/{repo}/languages`
- 社区健康：`GET /repos/{owner}/{repo}/community/profile`
- 提交列表：`GET /repos/{owner}/{repo}/commits`
- 贡献者：`GET /repos/{owner}/{repo}/contributors`
- Release：`GET /repos/{owner}/{repo}/releases`
- Issue/PR：`GET /repos/{owner}/{repo}/issues` 和 `GET /repos/{owner}/{repo}/pulls`
- Topics：`GET /repos/{owner}/{repo}/topics`

参考链接：

- Github Repository API: https://docs.github.com/en/enterprise-server%403.17/rest/repos/repos
- Github Languages API: https://docs.github.com/en/enterprise-server%403.17/rest/repos/repos#list-repository-languages
- Github Community Metrics API: https://docs.github.com/en/rest/metrics/community
- Github REST API Rate Limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- Github OAuth Apps: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
- OpenSSF Scorecard: https://github.com/ossf/scorecard
- Tavily API: https://docs.tavily.com/

## 8. 页面设计

页面第一屏是可用工具，不做营销页。

主要区域：

- 顶部登录区：Github 登录按钮、当前登录用户、退出登录按钮。
- 顶部输入区：仓库 URL 输入框、开始体检按钮。
- 状态总览区：仓库名称、描述、系统健康分、状态标签、最近更新时间。
- 指标卡片区：Stars、Forks、Open Issues、Contributors、Last Push、Latest Release。
- 图表区：语言分布图、评分维度图、活跃趋势图。
- 社区检查区：README、LICENSE、CONTRIBUTING 等检查清单。
- 风险建议区：按严重程度列出风险和建议。
- AI 分析区：独立按钮“启动 AI 深度分析”，显示 agent 分析进度和结果。

## 9. 技术方案

### 9.1 后端

- Python 3.11+
- Flask
- requests
- python-dotenv
- Authlib
- pydantic 或 dataclasses 组织返回数据

后端接口：

- `GET /`：返回页面。
- `GET /auth/github/login`：跳转 Github OAuth 授权页。
- `GET /auth/github/callback`：处理 Github OAuth 回调，保存登录会话。
- `POST /auth/logout`：退出登录并清理 session。
- `GET /api/session`：返回当前登录状态和 Github 用户基础信息。
- `POST /api/analyze`：执行系统体检，返回系统评分和图表数据。
- `POST /api/agent/analyze`：执行 AI agent 深度分析，扩展功能。
- `GET /api/health`：服务健康检查。

服务分层：

- `auth_service`：处理 Github OAuth 登录、回调、退出和 session token 读取。
- `github_client`：封装 Github REST API 请求，优先使用 session token。
- `health_analyzer`：把 Github API 数据转换为系统评分、状态和风险提示。
- `agent_service`：扩展功能，封装 LLM、Tavily 搜索和网页提取。
- `config`：从 `.env` 读取 Flask、Github OAuth、Tavily 和模型配置。

### 9.2 前端

- HTML
- CSS
- 原生 JavaScript
- Chart.js

前端状态：

- idle：等待输入。
- unauthenticated：未登录 Github。
- authenticated：已登录 Github。
- loading：系统体检中。
- ready：系统体检完成。
- agent_loading：AI agent 分析中。
- error：错误提示。

### 9.3 环境

使用 conda 初始化：

```powershell
conda create -n github-health python=3.11 -y
conda activate github-health
pip install flask requests python-dotenv authlib
```

使用 `.env` 加载配置。`.env` 只保存应用配置、OAuth App 配置、Tavily 配置和模型配置，不保存用户 Github access token。

`.env` 示例：

```env
FLASK_ENV=development
FLASK_SECRET_KEY=replace-with-local-secret

GITHUB_CLIENT_ID=replace-with-github-oauth-client-id
GITHUB_CLIENT_SECRET=replace-with-github-oauth-client-secret
GITHUB_OAUTH_CALLBACK_URL=http://127.0.0.1:5000/auth/github/callback

TAVILY_API_KEY=replace-with-tavily-api-key

MODEL_BASE_URL=https://api.openai.com/v1
MODEL_API_KEY=replace-with-model-api-key
MODEL_NAME=gpt-4.1-mini
```

未配置 Github OAuth App 时，页面提示需要配置登录后才能使用完整体检流程。未配置 `TAVILY_API_KEY`、`MODEL_BASE_URL`、`MODEL_API_KEY` 或 `MODEL_NAME` 时，隐藏或禁用 AI agent 分析入口，但系统评分仍可正常使用。

## 10. 错误处理

- URL 格式错误：提示用户输入 `https://github.com/{owner}/{repo}`。
- 仓库不存在或非公开：显示 404 说明。
- Github API 限流：显示剩余额度和重置时间。
- 网络超时：允许重试。
- Github OAuth 配置缺失：提示配置 `.env` 中的 OAuth App 信息。
- Github 登录失败或 session 过期：提示重新登录。
- Community Profile 不可用：不阻断整体分析，相关项标记为未知。
- Agent 分析失败：保留系统评分结果，只提示 AI 分析失败原因。

## 11. 非目标

第一版不做：

- 私有仓库分析。
- 多仓库批量对比。
- 数据持久化。
- 定时监控。
- 自动创建 Github Issue 或 PR。
- 强制接入 OpenSSF Scorecard。
- 长期保存用户 Github OAuth token。

## 12. 验收标准

- 输入合法公开仓库 URL 后，页面能展示系统评分和状态。
- 页面能展示 Star、Fork、Open Issues、License、默认语言、最近更新时间。
- 页面能展示语言分布图。
- 页面能展示社区健康检查清单。
- 页面能给出风险提示和改进建议。
- API 限流、仓库不存在、URL 无效时有明确错误提示。
- README 写明 conda 初始化和启动方式。
- README 写明 `.env` 配置项；`.env` 不包含静态 `GITHUB_TOKEN`。
- 页面支持 Github 登录、登录状态展示和退出登录。
- AI agent 分析入口与系统检测解耦；未配置 Tavily 时系统检测仍可正常使用。
- 配置 Tavily 和模型参数后，可以单独启动 agent 分析，并得到 AI 评分、引用链接和建议。
