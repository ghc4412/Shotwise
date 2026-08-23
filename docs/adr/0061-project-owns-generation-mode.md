# Project 是生成模式的唯一真相源

Status: accepted

Project 独自拥有 content_mode、generation_mode 和 grid_storyboard 的生效值。Creation Plan 创建时只能从 Project 读取这些值并保存为不可变快照，同时记录创作 Skill 与 Workflow Revision 的兼容性检查结果；Creation Plan 不接受、覆盖或修改 generation_mode，也不能让同一 Project 混用 storyboard 与 reference_video 两条生成路线。

## Considered Options

- 让 Creation Plan 自己拥有 generation_mode：拒绝，因为一次创作计划会取代 Project 成为路线真相源，重试、项目级设置和现有生产画布会产生分歧。
- 让 Workflow Template 决定项目生成模式：拒绝，因为模板只描述能力实现，不能改变项目级生成路线。

## Consequences

- Project 是所有生成入口读取生成路线的唯一来源。
- 计划失效时记录兼容性事件，供后续决策和 Skill 改进使用，而不是静默切换路线。
- 计划中的路线字段是历史快照，Project 后续变化不会回写或改造既有计划。
