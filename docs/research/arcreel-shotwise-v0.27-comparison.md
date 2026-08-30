# ArcReel v0.27.0 与 Shotwise 差异分析

> 目的：回答“ArcReel v0.27.0 哪些功能或 Bug 修复适合 Shotwise”，并为临时体验提供隔离方案。本文只做分析，不把 ArcReel 代码直接合入 Shotwise。

## 1. 比较范围与结论先行

- Shotwise 当前工作区：`d0809728024baa71e5c6c19d7cf20297bdbf0d73`。
- ArcReel 发布标签：`v0.27.0`，提交 `894b9383605e3c1b5ca93fc2a6f7c867f8a46686`，发布日期为 2026-08-24。
- `v0.27.0` 的发布提交主要是版本与变更日志元数据；功能变化来自 `v0.26.0` 之后至该标签的完整提交范围。
- Shotwise 当前有 22 个用户未提交改动，均未被本次分析修改。
- 结论：**不能把 v0.27.0 当作 Shotwise 的可直接升级版本**。它引入的是一套围绕“产物清单、产物现势、制作计划、迁移阻断、草稿晋升、逐项生成结果”的完整生产状态系统。Shotwise 的 Creative Platform、Flow Canvas、Media Library、Creative Board 和当前 episode-management 改动已经覆盖了部分用户体验，但数据边界与运行时契约不相同。

ArcReel 主要发布证据：
- [v0.27.0 CHANGELOG](https://github.com/ArcReel/ArcReel/blob/v0.27.0/CHANGELOG.md)
- [v0.27.0 tag](https://github.com/ArcReel/ArcReel/releases/tag/v0.27.0)

## 2. 分级标准

- **已有，可直接体验**：Shotwise 当前已经提供相同或足够接近的用户路径，不需要移植 ArcReel 实现。
- **部分已有，建议体验后再适配**：用户路径存在，但缺少 ArcReel 的权威性、覆盖范围或失败语义。
- **值得适配**：目标与 Shotwise 架构相容，但需要新增契约、数据结构或 API，不宜 cherry-pick 单个提交。
- **不建议直接移植**：依赖 ArcReel 的旧领域模型或与 Shotwise 当前 Creative Platform/episode-management 边界冲突。

## 3. v0.27.0 核心功能矩阵

| v0.27.0 项目 | Shotwise 当前情况 | 分类 | 建议 |
|---|---|---|---|
| Agent 修改已定稿分集改走草稿晋升，避免覆盖网页保存（`83769a6`） | Shotwise 已有 `episode_drafts_dir`（`lib/episode_paths.py`）、参考视频草稿校验（`lib/reference_video/draft_validation.py`）和剧本审阅草稿 UI（`frontend/src/components/canvas/timeline/ScriptReviewGate.tsx`）。但尚未证明所有 finalized episode 的 Agent 写入都统一走“草稿→验证→晋升”。 | 部分已有 | 高优先级核对。优先把 Agent 写入边界与当前 episode-management 的删除/重编号行为做一致性测试，不直接移植 ArcReel 文件。 |
| Agent 统一用户术语、摘要隐藏工具名和状态枚举（`270aba6d`） | Shotwise 已有 zh/en/vi i18n，Agent Runtime 和 Creation Skills 也已有产品化文案，但需要逐项审计 Agent profile、SDK tool 返回值和摘要模板。 | 部分已有 | 低风险、可单独适配；适合先做文案审计，不影响数据模型。 |
| 逐项返回成功/失败/受阻，失效产物不重复付费重生（`6adc823`） | Shotwise 有统一 `GenerationQueue`、依赖级 blocked 任务和前端任务刷新，但没有 ArcReel 的 `lib/generation_result.py` 统一结果协议，也没有对应的批量 SDK tool 结果层。 | 值得适配 | 高优先级。对 `enqueue_*` 返回值增加稳定的 item-level result，而不是直接复用 ArcReel 模块。 |
| 项目内跨角色/场景/道具防重复名称（`9e43a96`） | `lib/db/models/asset.py` 有 `(type, name)` 唯一约束；这只能保证同一类型内唯一，不能保证不同资产类型之间的项目级名称唯一。Shotwise 还存在 project.json 资产引用。 | 部分已有 | 中高优先级。需先确定 Shotwise 的全局资产库与 project.json 的命名真相源，再加项目级校验和三语错误。 |
| 官方文档站、产品语言统一（`90cd531`、`e505735c`） | Shotwise 已有 README、CONTEXT、architecture、workflows、ADR 体系以及三语前端。 | 已有/不必移植 | 可借鉴文档导航和公开契约，不需要部署 ArcReel 文档站。 |
| 项目变更通知跟随界面语言（`feafcb4`） | Shotwise 已有项目事件 SSE 与 zh/en/vi i18n；需现场检查通知 payload 是否仍携带固定中文。 | 部分已有 | 低风险体验项。切换语言后触发项目事件即可验收。 |
| 统一发声媒体来源与付费历史（`0d4dbc1`） | Shotwise 有音频版本、旁白、角色参考音频和费用/供应商相关能力，但未发现与 ArcReel 同等的统一 voice-media billing history 契约。 | 值得适配 | 中优先级，适合与现有 MediaAsset/音频版本模型合并设计，不能单独复制。 |
| 可验证产物状态、产物清单与来源依据（`e61feae`、`aa4a99c`、`9a5b3b6`） | Shotwise 没有 `artifact_manifest.py`、`artifact_activation.py` 或 `generation_result.py`。参考视频有读时 stale 签名和版本化写回（`server/routers/reference_videos.py`、`server/services/reference_video_tasks.py`），但这是局部能力。 | 值得适配，但属大型改造 | 最高优先级之一。应围绕 Shotwise 的 MediaAsset、Creative Board 和项目级 generation_mode 重新设计“产物清单/现势/激活”模型。 |
| 项目列表按制作状态和可用产物显示（`e347f2b`） | Shotwise 已有 `lib/status_calculator.py`、`ProjectsPage.tsx` 和 `ProjectCard.tsx`，能按 current phase 显示项目状态。 | 部分已有 | 可直接体验现有页面；若要达到 ArcReel 语义，需把状态来源从粗粒度阶段扩展到权威产物清单。 |
| 数据升级失败标记“需要修复”，对话修复后重试（`4ae96b2`、`253b8b7`、`a25f2ad`、`9721dd7`） | Shotwise 有自动 project migration、validation 和 MediaAsset index diagnostics，但当前代码检索未发现 ArcReel 同等的项目级 migration-repair banner/入口/SDK 拒绝协议。 | 值得适配 | 高优先级，尤其要覆盖旧项目、迁移中断和当前用户的 episode 删除改动；不能只把异常文本显示给 Agent。 |
| 参考视频台词/画外音与画面描述同一行（`eb5ff24c`） | Shotwise 的 reference-video draft validation 已有 dialogue/voiceover 解析，前端有 prompt 高亮和 reference mention 工具；当前能处理一部分结构化发声行，但是否允许全部 same-line 形式需用实际样例验收。 | 部分已有 | 可直接在隔离实例用几种 same-line 文本测试；通过后再补解析边界测试。 |
| 参考图按正文提及顺序解析（`cfe3117`） | Shotwise 已有 `frontend/src/utils/reference-mentions.ts`、`useShotPromptHighlight.ts` 和 reference unit 编辑逻辑，存在按文本解析引用的基础。 | 部分已有/接近已有 | 优先做行为验收，不建议移植 ArcReel parser；重点验证增删引用、重复引用和保存后生成顺序。 |
| 统一生成预检与报价（`6252c64`） | Flow Canvas 有 `workflow-preflight.ts`；参考视频也有 duration gate。两者不是统一的媒体生成 admission/quote API，当前 grep 未发现等价的统一报价契约。 | 部分已有 | 中高优先级。把“能否生成、会生成什么、预计费用、阻断原因”抽为后端权威预检，前端各路线复用。 |
| narration Step 1 隔离草稿通道（`6d8174ae`） | Shotwise 已有 `episode_drafts_dir`、`ScriptReviewGate`，类型中包含 `NarrationStep1Draft`，说明 narration 已有隔离审阅路径。 | 已有/接近已有 | 这是最适合先体验的 v0.27 目标之一：生成 narration Step 1，编辑后不应覆盖正式脚本，确认/晋升后才进入后续生产。 |
| 剧集卡/画布显示可用视频数和旧产物数（`8c3f4a0`） | Shotwise EpisodeCard、Timeline/Reference canvas 已有视频和 stale 相关展示，但 stale 的来源主要是局部签名/版本逻辑，不是统一 artifact manifest。 | 部分已有 | 可直接体验现有展示；要达到 v0.27 语义需先完成产物清单。 |
| 批量视频整批准入，任一单元失败则零任务入队（`d76443e`） | Shotwise 有任务去重、队列取消和参考视频单元校验，但未发现独立的 all-or-nothing `batch_admission.py` 与统一批量结果。当前批量行为不能默认等价。 | 值得适配 | 高优先级。先在后端预检全部 units，再一次性入队；明确与用户现有“删除 episode/取消任务”改动的交互。 |
| 使用当前旁白生成单个视频（`ed71819`） | Shotwise 已有单镜头/单单元生成 action、旁白生成和 reference/storyboard 路线；是否把“当前旁白”作为明确生成输入仍需按界面路径验收。 | 部分已有 | 可直接体验单元生成和旁白存在性；若当前 UI 会隐式读取旧旁白，应补显式 current narration 语义。 |
| 统一成片预览、下载、剪映/Jianying 导出（`46e77e0`） | Shotwise 已有 `server/services/jianying_draft_service.py`、项目导出接口、媒体卡和历史版本能力。 | 已有/接近已有 | 直接体验，不需要引入 ArcReel `PresentationPlayer`；只需检查 ad/reference/grid 三条路线是否一致。 |
| 视频生成重启后安全接续（`643d996`） | Shotwise `GenerationWorker` 已有 video resume、execution checkpoint 和 provider job id 路径；但 image/audio 重启后明确标记 `restart_lost`，且仅部分 video backend 支持 resume。 | 部分已有 | 可直接在支持 resume 的 video backend 上做重启测试；不要宣称达到 ArcReel 全覆盖。 |
| 视觉产物内容变化准确识别（`2f01717`） | Shotwise reference-video 有读时 stale 签名，generation services 也有 stale 写回；未发现跨 storyboard/grid/reference/media 的统一 visual provenance。 | 部分已有 | 适合纳入统一产物清单设计，避免再造第二套 stale 逻辑。 |
| 工作台展示服务端权威制作状态与受控修复入口（`830e95c`、`7b1f7cb`、`5bbc8c5`） | Shotwise Flow Canvas 有服务端 workflow definition/run、preflight、pause/resume/cancel 和 repair suggestions；普通 Studio 状态仍主要由项目状态与局部产物推导。 | 部分已有 | 可先体验 Flow；不要把 Flow run 状态等同于全项目 artifact production status。 |
| 四类资产图提示词版式统一（`a1b972e`） | Shotwise 已有角色/场景/道具/产品资产路由和 Creation Skills，但当前未证明四类提示词共享 ArcReel 的最新版式。 | 值得适配/低优先级 | 先比较输出 prompt 与项目现有 Creation Skills；若要改，应以 Shotwise 官方 Creation Skill 为入口。 |
| image MIME 从字节识别（`012128b`） | Shotwise `lib/image_backends/base.py`、`lib/dashscope_shared.py` 等路径仍有按扩展名推 MIME 的实现；MediaAsset 也保存 mime_type，但并非所有生成请求从文件字节确认。 | 值得适配 | 中优先级的独立 bug 修复，适合写成纯函数和测试，不需引入 ArcReel 其它产物系统。 |
| Kling 多图参考路线保留音频开关（`b40eab1`） | Shotwise 已有 `audio_switch_controllable`、`has_audio_track` 和 `require_audio_switch_supported`，参考视频任务也有 reference audio wiring。 | 部分已有/接近已有 | 用 Kling 多图 + 音频开关做真实配置验收；若复现静默丢配置，再定向修复。 |
| 恒有声按视频型号声明（`a080db9`，实际属于 v0.26 范围） | Shotwise AGENTS 记录的能力真相源已明确音轨能力按视频模型声明，前端也有模型级音轨开关测试。 | 已有 | 无需移植；保留现有模型能力边界。 |

## 4. 最值得在 Shotwise 执行的项目

### P0：产物清单 + 现势 + 批量准入

ArcReel v0.27 的真正核心不是某个按钮，而是让系统知道“哪个文件是当前内容的有效产物、哪个旧了、哪个失败了、哪个可以安全重生”。Shotwise 已有 MediaAsset、版本历史、Creative Board 和局部 stale 判定，具备落点，但需要统一模型。建议先产出设计和只读诊断，不立刻改数据库。

### P1：Agent 草稿晋升与迁移修复

Shotwise 当前已具备 narration/reference 的草稿编辑入口，应继续确认三条路线的写入边界统一：Agent 不能直接覆盖正式 episode/script；网页保存不能覆盖 Agent 尚未晋升的草稿；迁移失败项目必须在普通编辑和 Agent 写入入口都被阻断，并给出可执行的修复入口。

### P1：逐项生成结果与 all-or-nothing admission

这直接改善用户对批量生成的可控性，也和当前用户正在做的 episode 删除/任务取消改动有关：入队前必须列出所有无效单元；入队中断时必须区分已入队和未入队；失败不能默默触发重复付费。

### P2：MIME、Kling 音频开关、术语/i18n

这些是低耦合、容易写测试的独立修复，适合在核心产物模型稳定后执行。

## 5. 哪些可以现在直接体验

在不修改代码的前提下，推荐体验以下现有 Shotwise 路径，而不是把 ArcReel tag 覆盖到当前项目：

1. **narration Step 1 草稿**：生成/编辑/确认，验证正式脚本是否保持不变，确认后再进入生产。
2. **reference-video 文本解析**：测试同一行画面描述 + 台词/画外音、多个 `@` 参考图、重复引用和调整顺序。
3. **Flow Canvas preflight 与 repair**：验证运行前阻断、warning、暂停/恢复/取消和失败后的建议修复。
4. **视频重启接续**：只在明确支持 resume 的视频 backend 上做；不要用 image/audio 任务推断全局能力。
5. **成片预览、下载和 Jianying 导出**：分别从 storyboard、reference-video、grid/ad 路径检查产物是否一致。
6. **项目列表与 EpisodeCard 状态**：观察项目阶段、可用视频和 stale 标识；把它作为现有 UX 基线，不当作 v0.27 artifact manifest 的等价实现。

## 6. 临时部署方案与边界

ArcReel `v0.27.0` 可以单独运行，但它是 ArcReel 原版，不会包含 Shotwise 后续的 Creative Platform、Media Library、Creative Board 和当前未提交 episode-management 改动。因此临时部署的意义是“体验 ArcReel v0.27 原生生产流程”，不是“在 Shotwise 上预览这些功能”。

安全隔离要求：

- 使用 detached worktree，例如 `G:\Shotwise-v027`，不切换当前 `G:\Shotwise` 分支。
- 使用没有被占用的监听端口。已知 `43120` 是当前 DeepSeek Harness GUI，`5173` 已被现有 Node 进程使用，`18080` 也已被占用；候选端口需启动前再次确认，优先 `18081`。
- 设置独立的 `SHOTWISE_DATA_DIR`，例如 `G:\Shotwise-v027-data`。
- 设置独立 SQLite，例如 `DATABASE_URL=sqlite+aiosqlite:///G:/Shotwise-v027-data/.SHOTWISE.db`，不要复用当前 `projects/.SHOTWISE.db`。
- 不复制当前项目数据、凭证或 `.env`；如需 API key，应在隔离实例自己的设置页配置，并确认服务不会读取当前实例数据库。
- Windows 下使用 tag 自带的开发启动入口或等价的 Proactor-safe 入口；不要让新实例监听 `43120` 或替换现有 `5173`。
- 体验结束只停止临时进程并删除 worktree/data 目录即可，当前工作区和 GUI 不受影响。

当前只读检查已确认 Shotwise 自身支持 `SHOTWISE_DATA_DIR`（`lib/app_data_dir.py`）和 `DATABASE_URL`（`lib/db/engine.py`），因此如果后续要体验 Shotwise 当前版本，也可以用同样的隔离策略启动独立实例。

## 7. 不应宣称的结论

- 不能说 Shotwise 已经“升级到 ArcReel v0.27.0”。本地没有这些 ArcReel 提交，且 Shotwise 领域模型已经分叉。
- 不能说现有 `status_calculator` 等同于 ArcReel 的 artifact manifest/status system。
- 不能说 Shotwise 的局部 stale、draft 或 Flow preflight 已覆盖所有 v0.27 失败路径。
- 不能说本地 GenerationWorker 的 video resume 覆盖 image/audio 或所有 video provider。
- 不能直接 cherry-pick `v0.27.0` 的大提交；它们会触及大量 ArcReel 专属数据模型、Agent profile、迁移和前端契约。

## 8. 建议的下一步

先在隔离的 ArcReel `v0.27.0` 实例体验“产物状态/批量准入/草稿晋升”原生流程，再在 Shotwise 隔离实例体验对应现有路径。对照体验完成后，优先为 Shotwise 写一份不改代码的 artifact manifest/admission 设计，之后再按 P0/P1 拆分实现和测试。
