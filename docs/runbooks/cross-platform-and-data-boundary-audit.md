# 跨平台与数据边界审计 Runbook

## 目的与状态

本 runbook 用于审计 Shotwise 在 Windows、异步子进程、凭证边界、归档/草稿导入和能力配置方面的行为。它记录当前约束、可接受的例外和验证入口；“已具备控制”不等于已经完成全仓性能或安全审计。

## Windows 与异步 I/O

### 开发服务器与事件循环

Windows 开发环境使用 `uv run python server/run_dev.py`。该入口负责 reload 范围和 Windows 事件循环兼容性；不要用裸 `uvicorn --reload` 替代它。需要启动 Agent 子进程的代码必须在 Windows 下走现有 loop patch 路径，并通过真实的最小流程验证。

### 文件系统

- 临时目录使用 `tempfile.gettempdir()`，禁止硬编码 `/tmp`。
- 文本文件读写显式指定 `encoding="utf-8"`。
- `os.O_NOFOLLOW`、`os.O_DIRECT` 等 POSIX-only 常量使用 `getattr` 或等价保护；不能假设 Windows 提供这些常量。
- `os.chmod(..., 0o600)` 仅在 POSIX 上执行；Windows 凭证文件使用用户级目录和平台 ACL 保护。
- 路径必须经过项目根目录边界校验；不要用字符串拼接代替 `Path` 解析和安全检查。

### 子进程与媒体工具

- 使用 `asyncio.create_subprocess_exec` 的参数列表；禁止 `shell=True`、拼接 shell 命令或把用户输入嵌入命令字符串。
- 调用 ffmpeg/ffprobe 前使用 `shutil.which()` 探测。
- 缺失 ffmpeg/ffprobe 时按调用场景降级并返回可操作错误，不要把缺少外部工具表现成无上下文的 `FileNotFoundError`。
- 修改子进程、临时文件或媒体探测代码后，至少在目标平台运行一个最小 smoke test；无法提供目标平台时，运行静态检查并记录未验证平台。

## 凭证与错误边界

凭证、API key、Authorization header、登录响应 token 和自定义供应商密钥不得进入 logger、异常文本、SSE payload、API 响应、项目归档或调试结果。对供应商错误做结构化脱敏，只保留定位问题所需的 provider、模型、请求阶段和稳定错误类别。

审计时重点检查：异常链是否包含原始响应、请求体是否包含密钥、重试/任务记录是否持久化敏感字段，以及前端错误展示是否直接渲染后端原文。测试应使用占位凭证，并断言序列化结果不含占位凭证。

## 归档 manifest 与 draft/quarantine envelope

### Archive manifest

归档导入必须：

1. 校验 envelope/manifest 版本，缺失版本按当前支持的 v1 兼容读取；
2. 对未知字段保持向前兼容，不因附加字段拒绝导入；
3. 对缺失必需字段、错误类型和不支持的未来版本返回明确 validation 错误；
4. 在项目根目录边界内解析路径，不能由归档内容逃逸到外部路径；
5. 不把未知字段误解释成当前语义，也不静默丢弃影响完整性的核心字段。

### Draft/quarantine envelope

草稿隔离数据按 v1 envelope 读取：缺失 version 使用 v1 默认；已知字段按当前 schema 校验；未知字段保留，以便重新导出或前向兼容；未来版本明确拒绝，而不是按旧 schema 猜测解析。新增字段时同时覆盖旧 envelope、缺失字段、未知字段和未来版本测试。

## 项目列表性能

项目列表缓存按输入 fingerprint 复用结果，并保证每个 distinct JSON 输入最多一次读取。单元测试覆盖缓存命中、失效、删除源文件和读取次数；可重复的合成基准入口为 `scripts/benchmark_project_list_cache.py`。

运行：

```powershell
uv run python scripts/benchmark_project_list_cache.py
uv run python scripts/benchmark_project_list_cache.py --projects 500 --episodes 20 --concurrent-requests 8
```

默认基准（100 个项目、每项目 10 集、1100 个 distinct JSON 输入、8 路并发）验证了：冷缓存读取 1100 次，即每个输入 1 次；热缓存顺序请求和并发请求均新增 0 次读取；同时输出冷/热顺序与并发热缓存的 P50/P95 延迟。该结果只证明缓存行为和合成数据下的基线，不代表生产规模响应目标已经达成。项目列表性能 P2 仍需使用真实项目数量、episode/asset 数量、JSON 文件大小和目标部署环境建立并记录 P50/P95 基准。

## 视频时长能力审计

审计范围必须同时覆盖：

- provider backend 的请求构造与 duration 校正；
- registry/model capability 声明；
- 自定义供应商 endpoint 和 model 配置；
- prompt、前端选择器、请求体之间的能力传递；
- 缺失、空集、未知型号和未登记型号的 fallback 行为。

model-level `supported_durations` 缺失、为空或无法解析时必须 fail loud；不能用 `[4, 8]`、`[4, 6, 8]` 或 model_id 启发式默认掩盖配置错误。Vidu 的 endpoint-level `_coerce_duration` 是有意保留的例外：它只针对 endpoint 声明的合法集合做就近校正，并产生 warning，不改变 model-level 能力真相源的 fail-loud 规则。

## Episode source resolver 边界

单集源文发现、路径安全、UTF-8 读取和归一化统一使用 `lib.episode_source.resolve_episode_source`。`episode_planner.py` 和 `episode_reset.py` 保留跨文件连续窗口、cursor、fingerprint、区间连续性和删除/归档判断，因为这些是跨文件坐标职责，不是单文件 resolver 的职责。迁移或审计时应确认两者共享 discovery/normalization 规则，但不能为了形式统一破坏坐标语义。

## Character variant 边界

当前角色 variant 提供 stable id、slug、status、image path 校验和项目级 CRUD，可形成 metadata/image-reference 闭环。它还不是独立的 variant upload 产品：不能据此声称已有独立上传、媒体处理、权限、版本历史或完整 UI 工作流。新增能力时应继续保持稳定 id 与引用完整性，并为路径和状态迁移提供兼容测试。

## SSE 与批量状态

SSE 消费者必须保存 cursor，在断线后带 cursor 重连，并处理重复事件和过期 cursor；服务端应保持事件顺序和可重放边界。批量任务状态以 durable batch state 为准，前端刷新不能仅依赖本地乐观状态；终态由项目事件触发刷新，中间态和兜底使用任务查询。

## 建议验证命令

```powershell
uv run pytest `
  tests/test_character_variants.py `
  tests/test_project_archive_service.py `
  tests/lib/test_reference_video_quarantine.py `
  tests/server/test_project_list_cache.py `
  tests/test_projects_router.py -q

uv run ruff check `
  lib/project_manager.py `
  lib/character_variants.py `
  server/services/project_archive.py `
  server/routers/projects.py `
  tests/test_character_variants.py `
  tests/test_project_archive_service.py `
  tests/server/test_project_list_cache.py

uv run ruff format --check `
  lib/project_manager.py `
  lib/character_variants.py `
  server/services/project_archive.py `
  server/routers/projects.py `
  tests/test_character_variants.py `
  tests/test_project_archive_service.py `
  tests/server/test_project_list_cache.py
```

涉及 Agent 子进程、Windows loop、ffmpeg 或凭证边界时，再运行对应模块的 targeted tests；如果只能在非 Windows 平台验证，必须把 Windows smoke test 标为未执行。
