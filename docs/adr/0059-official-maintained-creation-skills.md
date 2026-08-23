# 创作 Skill 只允许官方维护

Status: accepted

创作 Skill 是面向用户的产品能力，首期只允许官方维护、版本化发布，用户不能创建、上传、发布或交易创作 Skill。这样可以把产品能力的安全性、兼容性和版本生命周期集中在官方维护边界内，同时避免它与 agent_runtime_profile 中的 Agent Skill 混淆。

## Consequences

- Workflow Template 作为创作 Skill 的执行实现随官方版本发布。
- 用户的自定义需求通过 Skill 输入和项目数据表达，而不是上传可执行工作流。
- Agent Skill 继续只属于智能体运行时配置，不成为用户可见的创作 Skill。
