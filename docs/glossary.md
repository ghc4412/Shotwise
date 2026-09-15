# Shotwise 术语表

本术语表统一开发、测试和运行文档中的领域名称。实现细节以代码和相关 ADR 为准。

## 内容与生成

### `content_mode`
内容类型维度：`drama`（剧集）、`narration`（说书）或 `ad`（广告/短片）。它决定剧本结构和 Agent profile 变体，不表示视频生成路线。

### `generation_mode`
项目级生成路线：`storyboard`（分镜图驱动）或 `reference_video`（参考视频路线）。创建后不可更改；它与 `content_mode` 是两个独立维度。

## 源文与持久化 envelope

### `source_range`
项目账本中描述某集对应原始源文坐标的区间。它基于归一化文本坐标，不能把手动预拆分文件本身当作可验证的原始坐标。

### derived episode source（派生剧集源文）
按集保存的 `source/episode_N.txt` 文件及其补零别名。缺省源文解析时优先使用它，避免把整本原文误交给单集流程；它没有可验证坐标时不会反写 `source_range`。

### archive manifest（归档 manifest）
项目归档的结构化清单，描述归档内容和导入所需元数据。当前兼容规则包括缺失版本按 v1 读取、保留未知字段、拒绝未来版本和校验必需字段。

### draft/quarantine envelope（草稿隔离 envelope）
隔离草稿在保存、导入和晋升之间使用的版本化外层结构。当前 v1 对缺失 version 提供默认，对未知字段保持兼容，对未来版本明确拒绝。

## 能力与资产

### `supported_durations`
单个视频模型声明的离散合法时长集合，是 prompt、前端选择和视频请求体共享的能力真相源。缺失、为空或未知型号不得静默回退；Vidu endpoint-level 就近校正是明确的局部例外。

### character variant（角色衍生形态）
角色的一个稳定可引用变体，包含 stable id、slug、status 和图片引用校验。当前闭环覆盖 metadata 与 image reference，不等同于独立的 variant upload、媒体处理或版本历史产品。

### stable id
角色 variant 的稳定 UUID 标识。它用于跨重命名和引用保持身份稳定，不应使用展示名称代替。

### slug
角色 variant 的可读、可查询短标识。同一角色内应保持唯一；它可以变化，但不能取代 stable id 作为持久身份。

## 实时任务

### SSE cursor/reconnect
SSE 客户端用于记录事件位置并在断线后恢复消费的机制。重连应携带 cursor，客户端需要能处理重复事件；服务端需要定义可重放范围和过期 cursor 行为。

### durable batch state
持久化的批量任务状态，是批量操作在刷新、重连和异步执行期间的权威来源。前端本地状态只用于即时反馈，不能替代服务端状态。

### project event SSE
项目级变更事件流，用于通知前端刷新项目数据和任务终态。它不是每个生成任务的独立进度通道；中间态由任务查询兜底。
