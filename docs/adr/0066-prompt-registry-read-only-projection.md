# ADR 0066：提示词模板注册表采用只读投影

- 状态：Accepted
- 日期：2026-09-25

## 背景

设置页需要「按流程环节浏览当前发行版携带的全部提示词模板」。ArcReel v0.31.0 把大量 prompt 整段模板化，并为每条声明制作步骤、触发方与 `protected` 片段，设置页只读浏览并可切换变体。

Shotwise 的现状不同：

- 提示词配置的单一真相是磁盘上的 `agent_runtime_profile/`（`CLAUDE.*.md`、`.claude/agents/`、`.claude/skills/`、`.claude/references/`），运行时由智能体直接加载，不经由任何注册表。
- 已有 `prompt_preview` 能力，用于在真正组装前预览请求 prompt，但它覆盖的是编排层拼装的产物，不是「有哪些模板文件」这件事。
- `lib/profile_manifest.py` 已经用 manifest + sha256 管「内置 profile 同步到用户项目、且不覆盖用户改动」，说明 profile 文件本身有独立生命周期，不该被第二个写者接手。

## 决策

新增 `lib/prompt_registry.py`，作为 `agent_runtime_profile` 的**只读元数据投影**：

- 扫描系统提示词、subagent、skill、参考文档四组文件，从既有文件结构与文件头推导分组、内容模式、标题、描述与小节列表。
- 只读：不改写模板、不落库、不参与运行时 prompt 组装。运行时仍由 `agent_runtime_profile` 直接加载，注册表只是同一批文件的可浏览视图。
- 无登记表：分组与标题全部从文件推导，新增模板文件自动进入注册表，无需在此登记。
- 暴露 `GET /api/v1/prompts/registry`（列表）与 `GET /api/v1/prompts/registry/{template_path:path}`（详情）；路径经安全校验，越界返回 `prompt_template_not_found`。
- 前端在 `/settings` 增加只读的 `prompt-templates` 分区，不提供编辑与保存入口。

**明确不做**：不整体替换现有 prompt builder，不引入可切换的 prompt 变体。

## 理由

- ArcReel 的模板注册表与其编排层同源演进，替换 builder 是一次高风险提示词回归；Shotwise 的编排层与 profile 是两套独立机制，复制会同时动两处。
- 只读投影能立刻满足「看得见有哪些模板、按流程分组」的诉求，却不引入第二个 prompt 写者，也不与 `profile_manifest` 的用户改动保护冲突。
- 变体切换需要先把「用户改动」与「内置版本」的关系定义清楚（谁优先、如何回滚），而 `profile_manifest` 今天的选择是「保留用户改动、不覆盖」，与「运行时按注册表切换变体」并不兼容，需要新 ADR 才能收敛。

## 后果

- 设置页可只读浏览全部模板与正文，作为排查与理解编排的入口。
- 注册表与磁盘必须保持一致；新增模板文件无需改注册表代码，但文件头格式（`# 标题`、`## 小节`、可选 `<!-- mode: ... -->`）成为约定。
- 若未来要支持编辑或变体切换，必须先解决写者归属与用户改动保护，再出新 ADR 重审本决策。

## 参考

- `lib/prompt_registry.py`
- `server/routers/prompt_registry.py`
- `frontend/src/components/pages/settings/PromptRegistrySection.tsx`
- `lib/profile_manifest.py`（manifest + sha256 的同步与用户改动保护）
- `docs/adr/0067-endpoint-marketplace-deferred.md`
