# Github 仓库体检工具

一个本地 Web 工具，用于分析 Github 仓库健康度。公开仓库无需登录即可分析；私有仓库通过 GitHub App 安装授权访问。页面优先展示确定性的系统评分，AI agent 分析作为单独触发的扩展功能。

## 当前状态

仓库目前包含需求文档、实施计划和项目初始化文件。业务代码尚未实现。

- 需求文档：`docs/superpowers/specs/2026-05-26-github-repo-health-design.md`
- 实施计划：`docs/superpowers/plans/2026-05-26-github-repo-health-implementation.md`

## 主要能力

- 输入公开 Github 仓库 URL，匿名调用 Github API 生成系统体检报告。
- 使用 GitHub App installation token 分析授权范围内的私有仓库。
- 展示 Star、Fork、Issue、语言分布、社区规范、维护活跃度、风险建议等指标。
- 系统评分优先输出，AI agent 评分单独触发。
- 公开仓库 agent 可使用 Tavily 和受控 Github API 工具。
- 私有仓库 agent 默认只使用受控 Github API 工具，增强权限可开启 Actions、Checks、Traffic、安全告警、SBOM、Deployments 等工具。

## 环境初始化

```powershell
conda create -n github-health python=3.11 -y
conda activate github-health
pip install -r requirements.txt
```

复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

## `.env` 配置

`.env` 只保存应用配置、GitHub App 配置、Tavily 配置和模型配置，不保存静态 `GITHUB_TOKEN` 或 installation token。

公开仓库分析无需 GitHub App 配置。私有仓库分析需要配置 GitHub App：

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

## GitHub App 权限

基础只读权限：

- Metadata: read
- Contents: read
- Issues: read
- Pull requests: read
- Commit statuses: read

私有仓库增强体检可增加：

- Actions: read
- Checks: read
- Code scanning alerts: read
- Dependabot alerts: read
- Secret scanning alerts: read
- Repository security advisories: read
- Administration: read
- Deployments: read

本项目不申请写权限，不修改用户仓库，不创建 Issue 或 Pull Request。

## 运行和测试

实现完成后使用：

```powershell
pytest -v
python run.py
```

本地地址：

```text
http://127.0.0.1:5000
```

## 安全约束

- `.env`、`secrets/`、GitHub App 私钥和所有 token 都不提交到 git。
- 私有仓库不使用 Tavily 搜索或网页提取。
- 私有仓库数据发送给模型前必须有明确用户确认。
- Agent 工具只能调用白名单 Github API 包装函数。

