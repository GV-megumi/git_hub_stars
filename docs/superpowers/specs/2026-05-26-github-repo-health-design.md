# Github 仓库体检工具需求说明书

## 1. 项目背景

本工具用于分析 Github 仓库的基础状态、活跃度、社区规范和潜在维护风险。公开仓库无需登录即可分析；私有仓库通过 GitHub App 安装授权访问。用户输入仓库 URL 后，系统先返回确定性的系统检测结果和系统评分，再允许用户单独触发 AI agent 深度分析。

第一版目标是做成一个本地 Web 工具，技术栈使用 Python 后端和 HTML/CSS/JavaScript 前端，环境通过 conda 初始化。

## 2. 用户目标

- 快速判断一个公开仓库或已授权私有仓库是否活跃、规范、值得关注或依赖。
- 用图表看清 Star、Fork、Issue、语言分布、维护活跃度等基础指标。
- 获得明确的健康状态和可执行建议，而不是只看原始数字。
- 在需要时单独启动 AI agent 分析，让 agent 结合搜索结果、仓库页面和基础检测信息给出更深入的评分和建议。

## 3. 核心流程

1. 用户打开 Web 页面。
2. 用户输入仓库 URL，例如 `https://github.com/fastapi/fastapi`。
3. 用户点击“开始体检”。
4. 后端解析出 `owner/repo`。
5. 如果仓库是公开仓库，后端直接使用 Github 公开 REST API 获取基础数据，无需登录。
6. 如果公开 API 返回私有或无权限错误，页面提示用户安装/授权 GitHub App。
7. 用户完成 GitHub App 安装授权后，后端使用 installation access token 访问授权范围内的私有仓库。
8. 系统生成确定性的系统评分、健康状态、图表数据和风险提示。
9. 前端优先展示系统评分和状态。
10. 用户可点击“AI 深度分析”单独启动 agent 分析。
11. AI agent 接收仓库链接、系统提示词和已探测到的基础信息，自行调用 Tavily 搜索/网页提取能力补充上下文，最后返回 AI 评分、分析结论和建议。

## 4. 功能范围

### 4.1 MVP 必须支持

- 输入公开 Github 仓库 URL，或输入 GitHub App 已授权访问的私有仓库 URL。
- 校验 URL 是否为 Github 仓库地址。
- 公开仓库无需登录即可分析。
- 支持 GitHub App 安装授权状态展示、安装入口和取消本地授权状态。
- 不在 `.env` 中配置静态 `GITHUB_TOKEN`；私有仓库访问 token 由 GitHub App installation token 临时生成。
- 获取仓库基础信息：名称、描述、Owner、默认分支、创建时间、更新时间、最近 push 时间、仓库大小、是否 archived、是否 fork。
- 获取热度指标：Star 数、Fork 数、Watcher/Subscriber 数、Open Issues 数。
- 获取语言分布：调用 Github Languages API，计算各语言字节占比。
- 获取社区健康信息：README、LICENSE、CONTRIBUTING、CODE_OF_CONDUCT、Issue Template、PR Template 等状态。
- 获取维护活跃信息：近 30/90 天提交数量、贡献者数量、Release 数、最近 Release。
- 生成系统评分、状态等级和风险提示。
- 通过图表展示语言分布、评分维度、关键指标。
- 支持错误提示：URL 无效、仓库不存在、API 限流、Github 网络失败、私有仓库未授权。

### 4.2 GitHub App 安装授权

GitHub App 安装授权用于私有仓库分析。公开仓库必须支持无需登录分析；只有当用户要分析私有仓库，或公开 API 额度不足时，才引导用户安装/授权 GitHub App。

授权设计：

- 使用 GitHub App，不使用 OAuth App，也不使用个人访问令牌。
- 用户在 GitHub 安装页选择安装到个人账号或组织。
- 用户可选择授权全部仓库或指定仓库。
- GitHub App 权限采用最小权限原则，第一版只申请只读权限。
- `.env` 保存 GitHub App 的 App ID、App slug、私钥路径、安装回调 URL 和 Flask 会话密钥。
- 后端通过 App JWT 调用 GitHub API，为具体 installation 生成短期 installation access token。
- 创建 installation access token 时，按需限制到当前仓库和当前接口所需权限，不能扩大到 GitHub App 未被授予的权限。
- installation access token 默认只短期存在于服务端内存/session，不写入 `.env`、日志或长期存储。
- 用户取消授权、安装被移除、安装未包含目标仓库、权限不足时给出明确提示。

建议的 GitHub App 只读权限：

| 权限 | 级别 | 用途 |
| --- | --- | --- |
| Metadata | Read-only | 读取仓库基础元数据，GitHub App 默认需要 |
| Contents | Read-only | 读取 README、社区文件、提交、Release、语言相关内容 |
| Issues | Read-only | 读取 Issue 统计和积压状态 |
| Pull requests | Read-only | 读取 PR 统计和积压状态 |
| Commit statuses | Read-only | 可选，用于后续扩展 CI/状态检查 |

如果后续增加安全扫描、依赖分析或 CI 状态分析，再按功能单独增加只读权限，并在页面解释新增权限原因。

### 4.3 扩展功能：AI Agent 分析

AI agent 分析是扩展功能，不阻塞基础体检结果。默认检测流程必须先给出系统评分和状态，agent 分析由用户单独触发。

agent 需要具备：

- 输入：仓库 URL、基础检测 JSON、系统评分、风险提示、分析提示词。
- 工具：Tavily API 包装的网页搜索和网页提取能力，或直接对接 Tavily MCP。
- 模型配置：从 `.env` 读取模型 `base_url`、`api_key` 和 `model`。
- 行为：围绕该仓库主动查找 Github 页面、README、Release、Issue/PR 讨论、文档站、社区讨论等公开信息。
- 输出：AI 评分、评分理由、关键发现、风险解释、改进建议、引用链接。
- 私有仓库保护：私有仓库的 agent 分析默认不把仓库私有内容发送给 Tavily；Tavily 只用于搜索公开网页。是否把私有仓库基础检测信息发送给模型，需要在页面上明确提示并由用户单独确认。

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
- GitHub App 注册: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app
- GitHub App 权限: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app
- GitHub App 安装: https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app
- GitHub App installation access token: https://docs.github.com/en/rest/apps/apps?apiVersion=2022-11-28#create-an-installation-access-token-for-an-app
- OpenSSF Scorecard: https://github.com/ossf/scorecard
- Tavily API: https://docs.tavily.com/

## 8. 页面设计

页面第一屏是可用工具，不做营销页。

主要区域：

- 顶部授权区：GitHub App 安装按钮、当前 installation 状态、授权仓库范围提示、取消本地授权状态按钮。
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
- PyJWT
- cryptography
- pydantic 或 dataclasses 组织返回数据

后端接口：

- `GET /`：返回页面。
- `GET /github-app/install`：跳转 GitHub App 安装页。
- `GET /github-app/setup`：处理 GitHub App 安装后的 setup/callback，记录 `installation_id` 和安装状态。
- `POST /github-app/clear`：清理本地 installation 会话状态，不卸载 GitHub App。
- `GET /api/github-app/session`：返回当前 GitHub App installation 状态和授权范围。
- `POST /api/analyze`：执行系统体检，返回系统评分和图表数据。
- `POST /api/agent/analyze`：执行 AI agent 深度分析，扩展功能。
- `GET /api/health`：服务健康检查。

服务分层：

- `github_app_service`：处理 GitHub App 安装回调、App JWT、installation access token 和权限错误。
- `github_client`：封装 Github REST API 请求；公开仓库走匿名请求，私有仓库走 installation token。
- `health_analyzer`：把 Github API 数据转换为系统评分、状态和风险提示。
- `agent_service`：扩展功能，封装 LLM、Tavily 搜索和网页提取。
- `config`：从 `.env` 读取 Flask、GitHub App、Tavily 和模型配置。

### 9.2 前端

- HTML
- CSS
- 原生 JavaScript
- Chart.js

前端状态：

- idle：等待输入。
- public_mode：公开仓库匿名分析模式。
- app_uninstalled：未安装 GitHub App，无法分析私有仓库。
- app_installed：GitHub App 已安装，可分析授权范围内的私有仓库。
- loading：系统体检中。
- ready：系统体检完成。
- agent_loading：AI agent 分析中。
- error：错误提示。

### 9.3 环境

使用 conda 初始化：

```powershell
conda create -n github-health python=3.11 -y
conda activate github-health
pip install flask requests python-dotenv pyjwt cryptography
```

使用 `.env` 加载配置。`.env` 只保存应用配置、GitHub App 配置、Tavily 配置和模型配置，不保存静态 Github token 或 installation access token。

`.env` 示例：

```env
FLASK_ENV=development
FLASK_SECRET_KEY=replace-with-local-secret

GITHUB_APP_ID=replace-with-github-app-id
GITHUB_APP_SLUG=replace-with-github-app-slug
GITHUB_APP_PRIVATE_KEY_PATH=./secrets/github-app-private-key.pem
GITHUB_APP_SETUP_URL=http://127.0.0.1:5000/github-app/setup

TAVILY_API_KEY=replace-with-tavily-api-key

MODEL_BASE_URL=https://api.openai.com/v1
MODEL_API_KEY=replace-with-model-api-key
MODEL_NAME=gpt-4.1-mini
```

未配置 GitHub App 时，公开仓库匿名分析仍可使用；私有仓库分析入口提示需要配置 GitHub App。未配置 `TAVILY_API_KEY`、`MODEL_BASE_URL`、`MODEL_API_KEY` 或 `MODEL_NAME` 时，隐藏或禁用 AI agent 分析入口，但系统评分仍可正常使用。

## 10. 错误处理

- URL 格式错误：提示用户输入 `https://github.com/{owner}/{repo}`。
- 仓库不存在：显示 404 说明。
- 私有仓库未授权：提示安装 GitHub App 或调整安装仓库范围。
- Github API 限流：显示剩余额度和重置时间。
- 网络超时：允许重试。
- GitHub App 配置缺失：公开仓库可继续匿名分析，私有仓库提示配置 `.env` 中的 GitHub App 信息。
- GitHub App 安装失败、installation 失效或权限不足：提示重新安装或调整权限。
- Community Profile 不可用：不阻断整体分析，相关项标记为未知。
- Agent 分析失败：保留系统评分结果，只提示 AI 分析失败原因。

## 11. 非目标

第一版不做：

- 多仓库批量对比。
- 数据持久化。
- 定时监控。
- 自动创建 Github Issue 或 PR。
- 强制接入 OpenSSF Scorecard。
- 长期保存 GitHub App installation access token。
- 申请写权限或修改用户仓库内容。

## 12. 验收标准

- 输入合法公开仓库 URL 后，页面能展示系统评分和状态。
- 输入 GitHub App 已授权访问的私有仓库 URL 后，页面能展示系统评分和状态。
- 页面能展示 Star、Fork、Open Issues、License、默认语言、最近更新时间。
- 页面能展示语言分布图。
- 页面能展示社区健康检查清单。
- 页面能给出风险提示和改进建议。
- API 限流、仓库不存在、URL 无效时有明确错误提示。
- README 写明 conda 初始化和启动方式。
- README 写明 `.env` 配置项；`.env` 不包含静态 `GITHUB_TOKEN` 或 installation access token。
- 公开仓库无需登录即可完成系统体检。
- 页面支持 GitHub App 安装入口、installation 状态展示和本地授权状态清理。
- 授权范围内的私有仓库可以通过 GitHub App installation token 体检。
- AI agent 分析入口与系统检测解耦；未配置 Tavily 时系统检测仍可正常使用。
- 配置 Tavily 和模型参数后，可以单独启动 agent 分析，并得到 AI 评分、引用链接和建议。
