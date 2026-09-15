---
name: episode-editing
description: 为已通过导演审阅的视频单元建立和校验正式持久化的成片时间线计划；不执行最终渲染。
user-invocable: false
---

# Episode editing contract

这是 Phase 2A 的内部 Agent Skill，供成片编排流程调用。它只负责读取媒体清单、建立时间线草稿和执行确定性校验，不是最终成片能力。

## 工作流

1. 先调用 `mcp__shotwise__inspect_director_review`，要求导演审阅已经实际查看首帧、中帧、尾帧；没有通过审阅时不得把计划标为通过。
2. 调用 `mcp__shotwise__get_episode_media_manifest` 获取当前剧集的有序视频单元、源路径、媒体探测结果和 fingerprint。不要从对话记忆猜测素材路径。
3. 调用 `mcp__shotwise__create_timeline_plan` 创建草稿。默认 `audio.unit_audio_policy` 为 `duck`：保留视频环境声并降低其音量；用户明确选择静音时才用 `mute`。
4. 如需调整顺序、裁剪、转场、字幕、片头片尾、封面或音频轨，调用 `mcp__shotwise__update_timeline_plan`，一次只提交允许字段的 patch。
5. 调用 `mcp__shotwise__validate_timeline_plan`。只有 `validation.valid=true` 且导演审阅状态为 `approved` 或 `keep` 时，才向用户报告“可交给后端成片服务”。
6. 向用户展示计划的 revision、素材 fingerprint、时间线顺序、音频策略、字幕/片头片尾配置和阻塞问题，等待用户确认。

## 计划字段约定

- `timeline_items`：按播放顺序排列，每项引用一个 manifest `unit_id`，不复制媒体文件。
- `director_review`：导演审阅闸门的摘要；不能由 Skill 自行伪造通过状态。
- `audio`：包含视频单元音频策略和额外音频轨配置；默认 `duck`，可切换 `mute`。
- `subtitles`：保存字幕模式、cue 和来源草案；时间码最终应由后端确定性编排层确认。
- `intro` / `outro` / `cover`：仅保存模板化配置，不在本 Skill 中生成媒体。
- `render_profile`：只保存预览/最终输出意图，不表示已经渲染。
- `persistence=database`：计划保存到正式数据库，返回 `plan_id` 和当前 `revision`；关闭 Agent 会话后仍可通过 MCP 读取。
- 每次更新或校验都会创建 immutable revision；使用后端返回的 revision 做并发控制，不覆盖其他用户或其他会话的修改。
- `source_snapshot` 由后端 service 根据项目、剧集、视频单元、媒体路径、版本、媒体探测和文件 fingerprint 自动生成；不要依赖或伪造调用方 snapshot。

## 与后端工作包的接口假设

- MCP 的 `create/get/update/validate` 已经通过 `media_assembly` service 读写正式 `AssemblyPlan` / `AssemblyPlanRevision`；MCP 不直接操作数据库。
- 后端 service 使用自动生成的 source snapshot fingerprint 检测视频单元、版本、文件或媒体状态变化，并将旧计划标为 stale，而不是静默复用。
- 后端应把 `director_review`、用户确认和 `preview_ready` 作为渲染前闸门；本 Skill 不调用最终渲染工具，也不能伪造预览完成或用户确认状态。
- 后端媒体执行器负责 FFmpeg、音视频混合、字幕烧录、预览和最终渲染；Agent 不得拼接 shell 命令。
- 当前契约不定义数据库表、HTTP 路由或任务队列类型；这些由后端工作包实现时保持字段语义兼容。

## 禁止事项

- 不调用 FFmpeg，不创建 render job，不生成 MP4，不导出，不发布。
- 不修改剧本、视频单元、资产或项目配置。
- 不绕过导演审阅，不自动重生成，不把音频缺失升级为第一阶段阻塞项。
- 不把未进入数据库的临时对象描述为已保存的正式成片计划；正式计划必须带有 `persistence=database`、`plan_id` 和 `revision`。
