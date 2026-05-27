# 文档索引

本目录记录 GitHub 仓库体检工具的需求、实现设计和开发约束。

## 面向使用者

- [根目录 README](../README.md)：项目功能、安装、配置、运行、测试和 GitHub App 教程。

## 面向维护者

- [实现设计细节](design-details.md)：系统架构、数据流、评分规则、Agent 编排、权限和安全边界。
- [需求说明书](superpowers/specs/2026-05-26-github-repo-health-design.md)：早期需求和验收标准。
- [实施计划](superpowers/plans/2026-05-26-github-repo-health-implementation.md)：按任务拆分的开发计划。

## 当前实现原则

- 公开仓库必须无需登录即可分析。
- 私有仓库只能通过 GitHub App installation token 访问。
- 不支持静态 `GITHUB_TOKEN`。
- GitHub App 权限保持只读，不修改用户仓库。
- 系统评分优先展示，AI Agent 是独立触发的增强功能。
- 私有仓库默认禁用 Tavily；发送给模型前需要明确用户确认。
- Agent 工具必须是固定端点、固定分页、字段裁剪后的服务端包装工具。
