# ADR 0065：Task 行级 lease / fencing / 幂等字段保持保留态

- 状态：Accepted
- 日期：2026-09-24

## 背景

`c1shotwise001_add_workflow_execution_contract` 迁移在给 `tasks` 表补 workflow 执行契约时，一并加了四列：`lease_owner`、`lease_until`、`fencing_token`、`request_idempotency_key`。同一批迁移里的 `workflow_node_runs`、`external_executions` 有同名列，且那两张表的列有真实写者。

`tasks` 表的这四列**没有任何写者**：

- `TaskRepository.claim_next` 的原子 claim 只改 `status` / `started_at` / `updated_at`，条件更新 `WHERE status='queued'` 靠 rowcount 守卫防重复认领——不涉及 lease 或 fencing。
- `_task_to_dict`（`lib/db/repositories/task_repo.py`）是唯一透出点，且只透出 `lease_until`，该字段在任务字典里恒为 `null`。
- `lease_owner` / `fencing_token` / `request_idempotency_key` 在整个 `lib/`、`server/`、`frontend/` 里只有模型定义，没有任何读写点。

同时，**进程级**选主已经真实接线并在用：`WorkerLease` 表 + `GenerationQueue.acquire_or_renew_worker_lease`，`GenerationWorker._run_loop` 每轮续约，只有持 lease 的进程才 claim 与扫孤儿（`_owns_lease` / `_orphan_handled_once` / `_ORPHAN_RESCAN_LEASE_LOST_MULT`）。也就是说「多 worker 协调」有一个已接线的机制，只是它落在 `WorkerLease` 表，而不是 Task 行。

前置约束：

- ADR 0007 声明 worker 与 server 主进程捆绑、单进程部署是前提，孤儿判定**不为**多进程场景预留逻辑。
- ADR 0006 的 cancel 走 in-process 信号 + `cancelling` 中间态，秒级响应依赖「发信号的进程就是跑任务的进程」。
- `CONTEXT.md` 的 `worker` 词条把代码里的 lease / heartbeat / `requeue_running` 记为「早期遗留的多 worker 协调脚手架，从未被多进程使用」。

## 决策

### 四列保持保留态：既不删列，也暂不接线

- **不删**：它们是 workflow 执行契约的预留，与同批迁移里已在用的 `external_executions.fencing_token` 等同名同义。删列是破坏性迁移，当下无收益，却会让未来的行级执行契约再走一次加列迁移。
- **不接线**：给 Task 行加 lease / fencing 属于「行级认领」语义，需要重审 ADR 0006（cancel 由谁送达）与 ADR 0007（孤儿由谁判定），是状态机级改动，超出「backend / 客户端层」范围。

### 不变量：Task 行级 lease 不是 claim 隔离依据

- 这四列不是 Task 状态机的一部分，任何代码**不得**把它们的取值当作 claim 或终态写入的隔离依据。
- 今天唯一的写者隔离是「`WorkerLease` 单活选主 + 单 in-process worker」。要判断「这个任务有没有别人在跑」，看的是进程 `_owns_lease` 与内存 `SlotTable`，不是 `tasks.lease_owner`。

### 字段处置

- `lease_until` 继续作为恒 `null` 字段出现在 `_task_to_dict`（前端未消费）；本次不做 API 面收敛，避免无收益的接口 churn。
- 模型层（`lib/db/models/task.py`）为这四列补注释，标明「保留态、无写者」，避免后来者误以为已接线。

## 后果

- 队列正确性今天依赖两个前提：进程级单活（`WorkerLease`）+ 单 uvicorn 进程内 worker。
- 多副本部署**不安全**且当前不被支持：非持 lease 的进程不 claim（这部分是对的），但持 lease 进程的 orphan 扫描会把其它进程内存里仍在跑的 `running` 任务判成孤儿并标 `failed`——这正是 ADR 0007 明说不为多进程预留的那一环。
- 若未来要支持多副本，必须先出新 ADR 重审 0006 / 0007，并**同时**激活三件事，只做其中一部分不构成安全的多 worker 语义：
  1. claim 时写 `lease_owner` / `lease_until`；
  2. 终态写入带 `fencing_token` 守卫（防止过期 holder 落终态）；
  3. `request_idempotency_key` 承担提交去重。
- 保留的静态代价：`tasks` 表多四列（`fencing_token` 带 `NOT NULL DEFAULT 0`），任务字典多一个恒 `null` 的 `lease_until`。
- 若将来确认永不使用，可由一份纯 drop-column 迁移 + 模型清理收口，无行为影响；本 ADR 记录当前选择为「保留」。

## 参考

- `docs/adr/0006-cancelling-intermediate-state.md`
- `docs/adr/0007-orphan-tasks-not-requeued-on-restart.md`
- `docs/adr/0042-custom-provider-concurrency-typed-columns.md`（平台配置加列的同源先例，对照本 ADR 明确不走接线）
- `CONTEXT.md` 的 `worker` / `孤儿任务` / `slot` 词条
