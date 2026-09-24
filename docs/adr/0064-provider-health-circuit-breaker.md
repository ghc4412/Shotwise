# ADR 0064：供应商泳道健康度熔断与动态降并发

- 状态：Accepted
- 日期：2026-09-24

## 背景

生成任务按 `(provider_id, media_type)` 分配到独立泳道，每条泳道的并发上限由用户配置（`CapacityTable`）。上游供应商持续故障时，现有行为是：每个 cycle 照常把任务 dispatch 进泳道，任务在上游超时/502/连接失败后走 `with_retry_async` 重试，重试耗尽再 `mark_task_failed`。结果是泳道槽位被注定失败的任务占满，队列被反复打满，同一 lane 上其他健康供应商的可跑任务被排头阻塞。

需要一种「上游持续故障就暂时不要把任务送进去」的机制：既不把可重试的抖动直接判成用户可见的失败，也不让故障泳道持续消耗槽位。用户早前提出的「供应商健康度熔断 + 动态降并发」即落在这一层。

约束：

- ADR 0006 禁止在 worker 外层用 `asyncio.timeout()` 包 `execute_generation_task`。
- ADR 0007 规定孤儿任务不自动 requeue、image 不做 resume。
- 改动只能落在 backend / 客户端层，不触碰任务状态机与终态语义。

## 决策

新增纯内存的 `lib/provider_health.py::ProviderHealthTable`，以 `(provider_id, media_type)` 为一条泳道记录健康账，与 `CapacityTable`、`SlotTable` 正交。它只提供「有效并发上限」与「claim 黑名单」两个查询，本身不写 DB、不解析 provider、不决定任务终态；状态管理交给 `GenerationWorker`。

### 与容量表、占用表的关系

- `CapacityTable` 表达用户配置的并发**上限**，其 `0` 是「该供应商不支持该媒体类型」的配置事实。
- `ProviderHealthTable` 只在该上限之上做**健康折减**，折减只收紧不放开：`capacity()` 的返回值永不超过传入上限，且只要上限 ≥ 1，折减结果也永远 ≥ 1（`OPEN` 除外）。
- `SlotTable` 继续只承载占用台账，容量无关。`GenerationWorker` 用 `_effective_capacity()` 把「配置上限 → 健康折减后上限」收敛成单点，claim 与占用校验都读它。

### 状态机

- `CLOSED`：正常。有效并发 = 上限 − 连续瞬态失败数，下限 1；任一成功即复原满血（连续失败清零、熔断轮次清零）。
- `OPEN`：连续瞬态失败达到 `failure_threshold`。有效并发 0，泳道进 claim 黑名单；已 claim 的该泳道任务**回队**（`_defer_claimed_task`）而非 `mark_failed`——上游抖动是暂时的，判失败会把可重试任务变成用户可见的失败。
- `HALF_OPEN`：冷却到期后由 `state()` 自动读出（纯函数，不落写）。有效并发压到 1，放一个真实任务当探针：成功 → `CLOSED`，失败 → 重新 `OPEN` 且冷却翻倍。

### open 与 half-open 的差异化处置

- 只有 `OPEN` 进 `blocked_providers()` 黑名单，`HALF_OPEN` 不入内——否则探针永远放不进去。
- `blocked_providers()` 只对容量表里 `> 0` 的 provider 生效：容量为 0 的泳道继续走 worker 二次校验的 fail-fast 终态，而不是被 SQL 静默 drop。健康折减到 0（熔断）走独立分支，其语义正是「回队等探针」。

### 失败分类的单一真相

是否计入健康账由 `lib/retry.py::is_transient_upstream_error` 判定，它与 `with_retry_async` 的重试判定同源（复用 `_should_retry` + `BASE_RETRYABLE_ERRORS`）：两者本质都是「这次失败是否代表上游暂时不健康」，分两份实现迟早漂移。因此：

- `NonRetryableError` 子类（能力不支持、参数非法、本地资产缺失等）恒为 `False`，不计健康账——计进去只会让泳道被无关错误熔断。
- `asyncio.CancelledError` 继承 `BaseException`，天然落在判定之外：用户取消不是上游不健康信号。
- 成功分支显式 `record_success()`；取消分支不动健康账。

### 持久化与调参

健康账不落库、进程重启即清零，与「单 lease 单活 worker」的部署形态一致（多进程各自熔断、互不可见，不影响正确性，只影响收敛速度）。三项参数经环境变量覆盖，调参不需要数据库迁移：

- `PROVIDER_HEALTH_FAILURE_THRESHOLD`（默认 3）
- `PROVIDER_HEALTH_OPEN_SECONDS`（默认 60）
- `PROVIDER_HEALTH_MAX_OPEN_SECONDS`（默认 600，冷却退避封顶）

`from_env()` 对封顶值小于首轮冷却的非法组合取大者而非抛错，避免配置失误让 worker 起不来；解析非法值 `logger.warning` + 回退默认。

## 后果

- 上游持续故障时，故障泳道被短暂移出 claim 轮转，不再占满槽位、不再阻塞同 lane 的健康供应商；恢复由半开探针自动完成，无需人工介入。
- 健康折减只收紧不放开，容量表与健康表语义不重叠，`0` 的两种含义（不支持 vs 熔断）在调用方显式分开处理。
- 熔断只推迟认领，任务始终留在 `queued`，不新增终态、不触碰 ADR 0006 / 0007 的状态机约束。
- 服务重启后熔断状态清零，抖动窗口内可能重复试探上游一次；这是纯内存设计的已知代价，换取零迁移、零外部依赖。
- `ProviderHealthTable.snapshot()` 暴露非满血泳道的只读快照（状态、连续失败数、熔断轮次、冷却剩余秒），供后续队列可观测性复用。