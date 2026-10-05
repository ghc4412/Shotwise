# ADR 0068：待编写状态采用读时只读推导，不引入持久化标记

- 状态：Accepted
- 日期：2026-09-25

## 背景

ArcReel v0.31.0 为条目引入 `pending_authoring` 标记，让「生成提示词」只处理有改动的条目：内容变动时置位、视觉层编写后清除，并接进全部写路径（内容物化、时间线编辑、晋升、提示词编写）。

Shotwise 的现状不同：

- 官方剧本（`episode_N.json` / `step1.json` / 参考路线 step1）是**内容单一真相**，内容与视觉层（`image_prompt` / `video_prompt`）经同一批 PATCH 路由写入同一份条目。
- 结构化 step1 中间态（`drafts/episode_N/step1_*.json`）是本流程里唯一一份与视觉编写分离的正文契约；官方剧本侧的同名字段是 step2 合并时的透传副本。
- 没有「上次编写时的正文」基线快照。合并是**全量覆盖**语义：drama 缺 `scene_id` 抛 `DramaVisualMergeError`、narration 缺 `segment_id` 抛 `ValueError`、reference 条目数不等抛 `DraftViolation(unit_count_changed)`。也就是说 step2 侧不接受部分条目。

## 决策

新增 `lib/pending_authoring.py`，**不引入持久化标记**，只做读时纯计算：一个条目的视觉层是与当前正文配套的；当正文自上次编写后变了，该条目的视觉层即与正文脱钩、须重新生成提示词。

- 正文的「当前值」取自该变体的 step1 结构化中间态；两侧按条目 id（`scene_id` / `segment_id` / `unit_id`）对齐。
- 只比对 step1 定稿、step2 不重写的字段（内容投影）：
  - drama：场景除视觉层外的字段；`scene_description` 是 step1-only、合并时被剔除，不参与。
  - narration：片段除视觉层外的全部字段。
  - reference_video：unit 的 `duration_seconds` 与 `references`；`shots[*].text` 由 step2 视觉展开改写、`source_text` 是 step1-only，两者都不参与。
- 内容投影**以 step1 声明过的键为契约**（而非两侧键的并集）：官方剧本条目带的 `note` / `transition_to_next` / `generated_assets` 是 step1 没有的 UI / 运行时字段，取并集会把它们算成差异、让每个条目恒判待编写。
- 三种原因：`missing_visual`（step1 有、剧本没有）、`stale_visual`（同 id 但内容投影不一致）、`orphan_item`（剧本有、step1 没有）。
- 暴露 `GET /api/v1/projects/{project_name}/episodes/{episode}/pending-authoring`（`server/routers/script_review.py`），以 `asyncio.to_thread` 卸同步 I/O。

### 退化边界：损坏数据报「无从比对」，不报「整集待编写」

`_item_list` 在顶层非对象、键缺失、键不是列表时返回 `None`（**不是空列表**）：空列表会被上层读成「另一侧一个条目都没有」，把损坏剧本报成整集孤儿、把缺失基线报成整集待编写。任何一侧无从比对即返回空 items，`script_present` 如实反映剧本是否在场（剧本未产出时 `script_present=False`、items 为空）。元素非对象一律跳过——这是只读提示，单个脏条目不值得让整条路径 fail-loud，真正的结构约束由 step1 / 剧本各自的校验器负责。

### 不做后端过滤 LLM 输出

本投影只回答「哪些条目待编写」，**不用它过滤喂给 LLM 的条目**。step2 合并要求全量覆盖（见上「背景」的三种抛错），按 pending 子集喂入会让合并失败或产出缺条目。要支持真正的增量编写，必须同时改合并契约，属于另一个决策。

## 理由

- 官方剧本是内容单一真相，内容与视觉层同批写入；引入 `pending_authoring` 这类跨写路径标记需要接入内容物化、时间线编辑、晋升、编写全部写路径才能保持，任一漏接都会让标记与事实脱钩。
- 无法区分「改了正文且同步改了提示词」与「只改了正文」——没有基线快照。持久化标记同样解决不了这个语义缺口，只是把不确定性搬到了写入侧。
- 读时推导零状态、零迁移、零漏接写路径风险；对「step1 侧改动」（重拆分、编辑中间态、晋升）是权威的。

## 后果

- 该推导对 step1 侧改动权威；对「直接在官方脚本上改正文」只能给出提示——那种改动没有留下基线，本模块无法区分同步改了提示词的情况。要精确覆盖后者，需要把「上次编写时的正文指纹」持久化到条目上，届时须出新 ADR 重审本决策，并定义该指纹的全部写路径。
- `lib/pending_authoring.py` 的 docstring 与本 ADR 互为引用，改动语义时两者须同步。
- 前端可据此展示待编写徽标；不改变任何生成或合并行为。

## 参考

- `lib/pending_authoring.py`
- `server/routers/script_review.py`
- `lib/script_review.py`（`step1_kind` / `content_fingerprint_of_data` / `step1_path`）
- `lib/episode_paths.py`（`STEP1_FILENAMES` / `REFERENCE_VIDEO_STEP1_FILENAME`）
- `lib/script_models.py`（`merge_drama_visual_into_scenes` 的全量覆盖语义）
- `docs/adr/0067-endpoint-marketplace-deferred.md`
