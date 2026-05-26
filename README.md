# Github 仓库体检工具

本项目是一个本地 Web 工具，用于分析 Github 仓库健康度。公开仓库无需登录即可分析；私有仓库通过 GitHub App 安装授权访问。页面先展示确定性的系统评分和可视化指标，AI agent 分析作为单独触发的扩展功能。

权威文档：

- 需求说明：[docs/superpowers/specs/2026-05-26-github-repo-health-design.md](docs/superpowers/specs/2026-05-26-github-repo-health-design.md)
- 实施计划：[docs/superpowers/plans/2026-05-26-github-repo-health-implementation.md](docs/superpowers/plans/2026-05-26-github-repo-health-implementation.md)

## 主要能力

- 输入公开 Github 仓库 URL，匿名调用 Github REST API 生成系统体检报告。
- 使用 GitHub App installation token 分析授权范围内的私有仓库。
- 展示 Star、Fork、Open Issues、默认分支、License、语言分布、社区清单、维护活跃度、风险建议等指标。
- 生成 100 分制系统评分，并按活动维护、社区规范、协作健康、成熟度、代码组成和风险扣分拆分。
- 后端支持单独触发 AI agent 分析，返回 AI 评分、发现、建议和引用；浏览器页面中的 Agent 操作入口仍是预留状态。
- 公开仓库 agent 可使用受控 Github API 工具和 Tavily 搜索/提取。
- 私有仓库 agent 默认禁用 Tavily，只使用受控 Github API 工具；发送私有仓库数据给模型前需要用户确认。

## 环境初始化

```powershell
conda init powershell
# 首次初始化后重开 PowerShell
conda create -n github-health python=3.11 -y
conda activate github-health
pip install -r requirements.txt
```

复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

启动本地服务：

```powershell
python run.py
```

访问地址：

```text
http://127.0.0.1:5000
```

## 测试

```powershell
pytest -v
```

如果 Windows 临时目录权限异常，可指定项目内临时目录：

```powershell
pytest -q -p no:cacheprovider --basetemp tmp\pytest_tmp
```

## `.env` 配置

`.env` 只保存应用配置、GitHub App 配置、Tavily 配置和模型配置。不要配置静态 `GITHUB_TOKEN` 或 installation token；GitHub App 私钥文件放在本地 `secrets/`，`.env` 只配置 `GITHUB_APP_PRIVATE_KEY_PATH`；真实 Tavily key 和模型 key 可放本地 `.env`，不要提交到 git。

公开仓库系统分析无需 GitHub App、Tavily 或模型配置。AI agent 需要配置 `MODEL_BASE_URL`、`MODEL_API_KEY`、`MODEL_NAME`；公开仓库 agent 如需外部网页证据，再配置 `TAVILY_API_KEY`。

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

## GitHub App

私有仓库访问使用 GitHub App installation authorization，不使用 OAuth App、个人访问令牌或 `.env` 中的静态 Github token。

系统体检基础只读权限：

- Metadata: read
- Contents: read
- Pull requests: read

AI agent 增强只读权限：

- Issues: read
- Actions: read
- Checks: read
- Deployments: read
- Code scanning alerts: read
- Dependabot alerts: read
- Repository security advisories: read
- Secret scanning alerts: read
- Administration: read

对应 installation token 权限字段：

- `metadata`: read
- `contents`: read
- `pull_requests`: read
- `issues`: read
- `actions`: read
- `checks`: read
- `deployments`: read
- `security_events`: read，用于 code scanning alerts
- `vulnerability_alerts`: read，用于 Dependabot alerts
- `repository_advisories`: read，用于 repository security advisories
- `secret_scanning_alerts`: read
- `administration`: read

本项目不申请写权限，不修改用户仓库，不创建 Issue 或 Pull Request。

## API

- `GET /`: Web 页面。
- `GET /api/health`: 服务健康检查。
- `POST /api/analyze`: 系统体检，返回系统评分和 `analysis_id`。
- `POST /api/agent/analyze`: AI agent 深度分析，必须传入本会话一次已完成系统体检返回的 `analysis_id`；私有仓库还必须传入 `confirm_private_data_to_model: true`。
- `GET /github-app/install`: 跳转 GitHub App 安装页。
- `GET /github-app/setup`: GitHub App 安装回调。
- `GET /api/github-app/session`: 当前安装授权状态。
- `POST /github-app/clear`: 清理本地 GitHub App session。

## 安全约束

- `.env`、`secrets/`、GitHub App 私钥和所有 token 都不提交到 git。
- Installation token 只按当前请求临时生成，不写入 `.env`、日志或长期存储。
- GitHub App 权限保持只读。
- 私有仓库不使用 Tavily 搜索或网页提取。
- 私有仓库数据发送给模型前必须有明确用户确认。
- Agent 工具只能调用白名单 Github API 包装函数，固定端点、固定页大小、摘要化输出。
