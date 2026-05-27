# GitHub 仓库体检工具

一个本地运行的 GitHub 仓库健康分析 Web 工具。用户输入仓库 URL 后，系统会先用确定性规则生成系统评分、风险提示和可视化指标；在需要更深入判断时，可以单独启动 AI Agent，结合受控 GitHub API 工具和 Tavily 公开网页证据生成 AI 评分、发现、建议和引用。

公开仓库无需登录即可分析。私有仓库通过 GitHub App 安装授权访问，不支持也不应该配置静态 `GITHUB_TOKEN`。

## 功能概览

- 公开仓库匿名体检：输入 `https://github.com/owner/repo` 即可分析。
- 私有仓库体检：通过 GitHub App installation access token 临时访问授权仓库。
- 系统评分：100 分制，覆盖活跃维护、社区规范、协作健康、项目成熟度、代码组成和风险扣分。
- 可视化指标：Stars、Forks、Issues、Watchers、License、默认分支、语言分布、评分维度。
- 社区清单：README、License、CONTRIBUTING、Code of Conduct、Security Policy、Issue Template、PR Template。
- Agent 分析：单独触发，返回 AI 评分、置信度、结构化发现、建议和引用链接。
- 公开仓库 Agent：可使用 GitHub API 包装工具和 Tavily search/extract。
- 私有仓库 Agent：默认禁用 Tavily；发送私有仓库摘要给模型前需要用户显式确认。
- 安全边界：GitHub App 权限只读；不创建 Issue/PR；不修改仓库；不长期保存 installation token。

## 技术栈

- Python 3.11
- Flask
- requests
- python-dotenv
- PyJWT + cryptography
- OpenAI-compatible Chat Completions API
- Tavily API
- 原生 HTML/CSS/JavaScript
- pytest

## 目录结构

```text
app/
  agent/          # AI Agent、LLM、Tavily、GitHub 工具包装
  analyzer/       # GitHub 数据采集和系统评分
  github/         # GitHub URL、REST client、GitHub App 鉴权
  config.py       # .env 配置加载
  routes.py       # Web/API 路由
static/           # 前端 JS/CSS
templates/        # HTML 页面
tests/            # pytest 测试
docs/             # 需求、设计、实现说明
run.py            # 本地启动入口
```

更多设计细节见 [docs/design-details.md](docs/design-details.md)。

## 安装教程

以下命令以 Windows PowerShell 为例。

### 1. 创建 conda 环境

```powershell
conda init powershell
# 首次 init 后重新打开 PowerShell
conda create -n github-health python=3.11 -y
conda activate github-health
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

如果需要确认依赖版本没有冲突：

```powershell
python -m pip check
```

### 3. 创建本地配置文件

```powershell
Copy-Item .env.example .env
```

`.env` 是本地配置文件，已被 `.gitignore` 忽略。不要提交 `.env`、GitHub App 私钥、Tavily key、模型 key 或任何 token。

### 4. 启动服务

```powershell
python run.py
```

默认地址：

```text
http://127.0.0.1:5000
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
```

预期返回：

```json
{"status": "ok"}
```

## `.env` 配置教程

最小公开仓库体检不需要 GitHub App、Tavily 或模型配置，只要 Flask 能启动即可。

完整配置示例：

```env
FLASK_ENV=development
FLASK_SECRET_KEY=replace-with-local-secret
GITHUB_API_BASE_URL=https://api.github.com

GITHUB_APP_ID=replace-with-github-app-id
GITHUB_APP_SLUG=replace-with-github-app-slug
GITHUB_APP_PRIVATE_KEY_PATH=./secrets/github-app-private-key.pem
GITHUB_APP_SETUP_URL=http://127.0.0.1:5000/github-app/setup

TAVILY_API_KEY=replace-with-tavily-api-key

MODEL_BASE_URL=https://api.openai.com/v1
MODEL_API_KEY=replace-with-model-api-key
MODEL_NAME=gpt-4.1-mini
```

### 基础配置

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `FLASK_ENV` | 否 | 本地开发可用 `development`。 |
| `FLASK_SECRET_KEY` | 建议必填 | Flask session 密钥。配置 GitHub App 时必须使用非默认值。 |
| `GITHUB_API_BASE_URL` | 否 | 默认 `https://api.github.com`。当前页面仓库 URL 校验只支持 `github.com`，该配置主要用于测试或兼容同域 API 网关。 |

### Agent 模型配置

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `MODEL_BASE_URL` | Agent 必填 | OpenAI 兼容 Chat Completions API base URL，例如 `https://api.openai.com/v1`。 |
| `MODEL_API_KEY` | Agent 必填 | 模型服务 API key。 |
| `MODEL_NAME` | Agent 必填 | 模型名。必须是当前 base URL/key 可用的模型。 |

模型配置缺失时，系统评分仍可使用，Agent 按钮会被禁用或返回配置错误。

### Tavily 配置

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `TAVILY_API_KEY` | 否 | 公开仓库 Agent 使用 Tavily search/extract 补充外部公开证据。 |

未配置 Tavily 时，公开仓库 Agent 仍可使用 GitHub API 工具；私有仓库 Agent 默认始终不使用 Tavily。

## GitHub App 配置教程

私有仓库分析必须使用 GitHub App 安装授权。项目不读取 `.env` 中的 `GITHUB_TOKEN`，也不支持个人访问令牌作为私有仓库入口。

### 1. 创建 GitHub App

进入 GitHub 的 Developer settings，创建 GitHub App。

建议本地开发配置：

```text
Homepage URL: http://127.0.0.1:5000
Setup URL:    http://127.0.0.1:5000/github-app/setup
Webhook:      可以关闭或不配置
```

创建后记录：

- App ID -> `GITHUB_APP_ID`
- App slug -> `GITHUB_APP_SLUG`

### 2. 生成私钥

在 GitHub App 页面生成 private key，下载 `.pem` 文件，放到本地 `secrets/` 目录，例如：

```text
secrets/github-app-private-key.pem
```

然后配置：

```env
GITHUB_APP_PRIVATE_KEY_PATH=./secrets/github-app-private-key.pem
```

`secrets/` 已被 `.gitignore` 忽略，不要提交私钥。

### 3. 配置只读权限

基础私有仓库体检所需权限：

| GitHub App 权限 | 级别 | 用途 |
| --- | --- | --- |
| Metadata | Read-only | 读取仓库元数据。 |
| Contents | Read-only | README、社区文件、Release、提交、语言等。 |
| Pull requests | Read-only | Open PR 和协作积压。 |

增强 Agent 可用权限：

| GitHub App 权限 | 级别 | 用途 |
| --- | --- | --- |
| Issues | Read-only | Issue 摘要和积压。 |
| Actions | Read-only | GitHub Actions 最近运行和失败情况。 |
| Checks | Read-only | Check runs 状态。 |
| Deployments | Read-only | 部署环境和部署记录摘要。 |
| Administration | Read-only | 流量、rulesets 等只读信息。 |
| Repository security advisories | Read-only | 仓库安全公告摘要。 |
| Dependabot alerts | Read-only | 依赖漏洞告警摘要。 |
| Code scanning alerts | Read-only | 代码扫描告警摘要。 |
| Secret scanning alerts | Read-only | Secret scanning 告警摘要。 |

只配置基础权限也可以使用系统体检。增强权限缺失时，对应 Agent 工具会显示不可用，不阻塞其他分析。

### 4. 安装 GitHub App

启动本地服务后，打开页面右上角的 GitHub App 授权区域，点击“安装或更新授权”。在 GitHub 安装页选择账号/组织和仓库范围。安装完成后会回到：

```text
http://127.0.0.1:5000/github-app/setup?installation_id=...
```

页面会显示 installation 状态、授权仓库范围和已授予权限。

## 使用流程

### 公开仓库

1. 打开 `http://127.0.0.1:5000`。
2. 输入仓库 URL，例如：

   ```text
   https://github.com/pallets/flask
   ```

3. 选择“公开模式”。
4. 点击“开始体检”。
5. 查看系统评分、指标、图表、社区清单、风险和建议。
6. 如果模型配置可用，可点击“启动 AI 深度分析”。

### 私有仓库

1. 先完成 GitHub App 配置和安装授权。
2. 输入授权范围内的私有仓库 URL。
3. 选择“私有模式”。
4. 点击“开始体检”。
5. 如需 Agent 分析，勾选私有仓库数据发送给模型的确认项。
6. 点击“启动 AI 深度分析”。

## API 说明

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | Web 页面。 |
| `GET` | `/api/health` | 服务健康检查。 |
| `POST` | `/api/analyze` | 系统体检，返回 `analysis_id`、仓库信息、评分和图表数据。 |
| `POST` | `/api/agent/analyze` | 基于已完成系统体检的 Agent 分析。 |
| `GET` | `/github-app/install` | 跳转 GitHub App 安装页。 |
| `GET` | `/github-app/setup` | GitHub App 安装回调。 |
| `GET` | `/api/github-app/session` | 当前 GitHub App session 状态。 |
| `POST` | `/github-app/clear` | 清理本地 GitHub App session。 |

`POST /api/analyze` 示例：

```json
{
  "url": "https://github.com/pallets/flask",
  "private_mode": false
}
```

`POST /api/agent/analyze` 示例：

```json
{
  "analysis_id": "由 /api/analyze 返回",
  "confirm_private_data_to_model": true
}
```

公开仓库不需要 `confirm_private_data_to_model`；私有仓库必须显式传 `true`。

## 测试与验证

运行完整测试：

```powershell
python -m pytest -q
```

如果 Windows 临时目录权限异常，可指定项目内临时目录：

```powershell
python -m pytest -q -p no:cacheprovider --basetemp tmp\pytest_tmp
```

检查前端 JavaScript 语法：

```powershell
node --check static\js\app.js
```

手工验证建议：

1. 启动 `python run.py`。
2. 打开 `http://127.0.0.1:5000`。
3. 分析 `https://github.com/pallets/flask`。
4. 确认系统评分、语言图、维度图、社区清单、风险建议正常展示。
5. 配置模型和 Tavily 后，点击 Agent 分析，确认返回 AI 评分、发现、建议和引用。

## 安全约束

- 不在 `.env` 中配置 `GITHUB_TOKEN`。
- 不提交 `.env`、`secrets/`、私钥、模型 key、Tavily key 或 token。
- GitHub App installation token 按请求临时生成，不长期保存。
- GitHub App 权限保持只读。
- 私有仓库不使用 Tavily 公开搜索/提取。
- 私有仓库数据发送给模型前必须由用户确认。
- Agent 只能调用服务端白名单工具，不能执行任意 GitHub API 或任意 URL 请求。
- LLM provider 错误会被包装为结构化 502；provider message 仅对安全白名单错误码暴露并做脱敏。

## 文档索引

- [docs/README.md](docs/README.md)：文档入口。
- [docs/design-details.md](docs/design-details.md)：实现设计细节。
- [docs/superpowers/specs/2026-05-26-github-repo-health-design.md](docs/superpowers/specs/2026-05-26-github-repo-health-design.md)：原始需求说明书。
- [docs/superpowers/plans/2026-05-26-github-repo-health-implementation.md](docs/superpowers/plans/2026-05-26-github-repo-health-implementation.md)：实现计划。
