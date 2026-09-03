import { useState } from "react";
import { Check, ChevronDown, Clipboard, Loader2, Package, RefreshCw, RotateCcw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { DurableBatchResponse, DurableBatchStatus, DurableBatchTaskSummary } from "@/types/batch";
import { copyText } from "@/utils/clipboard";
import { useAppStore } from "@/stores/app-store";
import { useDurableBatches } from "@/hooks/useDurableBatches";

const STATUS_COLORS: Record<DurableBatchStatus, string> = {
  admitted: "var(--color-accent-2)",
  running: "var(--color-accent-2)",
  succeeded: "var(--color-good)",
  partially_succeeded: "var(--color-warn)",
  failed: "oklch(0.72 0.18 25)",
  cancelled: "var(--color-text-3)",
};

const ACTIVE_STATUSES: readonly DurableBatchStatus[] = ["admitted", "running"];

function shortId(value: string): string {
  return value.length > 16 ? value.slice(0, 8) + "..." + value.slice(-6) : value;
}

function getTaskCounts(tasks: DurableBatchTaskSummary[]) {
  return {
    succeeded: tasks.filter((task) => task.status === "succeeded").length,
    failed: tasks.filter((task) => task.status === "failed").length,
    active: tasks.filter(
      (task) => task.status === "queued" || task.status === "running" || task.status === "cancelling",
    ).length,
    cancelled: tasks.filter((task) => task.status === "cancelled").length,
  };
}

function TaskStatusIcon({ status }: { status: DurableBatchTaskSummary["status"] }) {
  if (status === "queued" || status === "running" || status === "cancelling") {
    return <Loader2 className="h-3 w-3 animate-spin" style={{ color: "var(--color-accent-2)" }} aria-hidden />;
  }
  if (status === "succeeded") {
    return <Check className="h-3 w-3" style={{ color: "var(--color-good)" }} aria-hidden />;
  }
  return <X className="h-3 w-3" style={{ color: status === "failed" ? STATUS_COLORS.failed : STATUS_COLORS.cancelled }} aria-hidden />;
}

function BatchStatus({ status }: { status: DurableBatchStatus }) {
  const { t } = useTranslation("dashboard");
  return (
    <span className="inline-flex items-center gap-1 text-[10.5px]" style={{ color: STATUS_COLORS[status] }}>
      {(status === "admitted" || status === "running") && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
      {status === "succeeded" && <Check className="h-3 w-3" aria-hidden />}
      {(status === "partially_succeeded" || status === "failed" || status === "cancelled") && <X className="h-3 w-3" aria-hidden />}
      {t("durable_batch_status_" + status)}
    </span>
  );
}

function BatchTaskList({ tasks }: { tasks: DurableBatchTaskSummary[] }) {
  const { t } = useTranslation("dashboard");
  return (
    <div className="space-y-0.5 border-t px-3 py-1.5" style={{ borderColor: "var(--color-hairline-soft)" }}>
      {tasks.map((task) => (
        <div key={task.item_id + ":" + task.task_id} className="flex min-w-0 items-center gap-2 py-1 text-[10.5px]">
          <TaskStatusIcon status={task.status} />
          <span className="min-w-0 flex-1 truncate" style={{ color: "var(--color-text-3)" }}>{task.item_id}</span>
          <span className="num shrink-0" style={{ color: "var(--color-text-4)" }}>{shortId(task.task_id)}</span>
          <span className="shrink-0" style={{ color: "var(--color-text-4)" }}>{t("durable_batch_task_status_" + task.status)}</span>
        </div>
      ))}
    </div>
  );
}

function BatchRow({
  batch,
  onCancel,
  onRetry,
}: {
  batch: DurableBatchResponse;
  onCancel: (batchId: string) => Promise<void>;
  onRetry: (batchId: string) => Promise<void>;
}) {
  const { t } = useTranslation("dashboard");
  const pushToast = useAppStore((state) => state.pushToast);
  const [expanded, setExpanded] = useState(batch.status === "partially_succeeded" || batch.status === "failed");
  const [confirmation, setConfirmation] = useState<"cancel" | "retry" | null>(null);
  const [working, setWorking] = useState(false);
  const counts = getTaskCounts(batch.tasks);
  const total = batch.tasks.length;
  const terminal = counts.succeeded + counts.failed + counts.cancelled;
  const progress = total === 0 ? 0 : Math.round((terminal / total) * 100);
  const canCancel = ACTIVE_STATUSES.includes(batch.status);
  const canRetry = batch.status === "partially_succeeded" || batch.status === "failed";

  const runAction = async (action: "cancel" | "retry") => {
    setWorking(true);
    try {
      if (action === "cancel") await onCancel(batch.batch_id);
      else await onRetry(batch.batch_id);
      setConfirmation(null);
    } catch (error) {
      pushToast(error instanceof Error ? error.message : t("durable_batch_action_failed"), "error");
    } finally {
      setWorking(false);
    }
  };

  const copyId = async () => {
    try {
      await copyText(batch.batch_id);
      pushToast(t("durable_batch_id_copied"), "success");
    } catch {
      pushToast(t("durable_batch_copy_failed"), "error");
    }
  };

  return (
    <div className="border-b" style={{ borderColor: "var(--color-hairline-soft)" }}>
      <div className="px-3 py-2.5">
        <div className="flex items-start gap-2">
          <button
            type="button"
            className="focus-ring mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded"
            aria-expanded={expanded}
            aria-label={expanded ? t("durable_batch_collapse_tasks") : t("durable_batch_expand_tasks")}
            onClick={() => setExpanded((value) => !value)}
          >
            <ChevronDown className={"h-3.5 w-3.5 transition-transform " + (expanded ? "rotate-180" : "")} style={{ color: "var(--color-text-4)" }} aria-hidden />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span className="truncate text-[11.5px] font-medium" style={{ color: "var(--color-text-2)" }}>{t("durable_batch_label")}</span>
              <BatchStatus status={batch.status} />
            </div>
            <div className="mt-1 flex min-w-0 items-center gap-1.5">
              <span className="num min-w-0 truncate text-[10px]" style={{ color: "var(--color-text-4)" }} title={batch.batch_id}>{shortId(batch.batch_id)}</span>
              <button type="button" className="focus-ring shrink-0 rounded p-0.5" title={t("durable_batch_copy_id")} aria-label={t("durable_batch_copy_id")} onClick={() => void copyId()}>
                <Clipboard className="h-3 w-3" style={{ color: "var(--color-text-4)" }} aria-hidden />
              </button>
            </div>
          </div>
          <div className="shrink-0 text-right text-[10px]" style={{ color: "var(--color-text-4)" }}>
            <div className="num" style={{ color: "var(--color-text-2)" }}>{terminal}/{total}</div>
            <div>{t("durable_batch_tasks", { count: total })}</div>
          </div>
        </div>
        <div className="mt-2 h-1 overflow-hidden rounded-full" style={{ background: "var(--color-shell-hud-track)" }}>
          <div className="h-full rounded-full transition-[width]" style={{ width: progress + "%", background: STATUS_COLORS[batch.status] }} />
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10px]" style={{ color: "var(--color-text-4)" }}>
          <span>{t("durable_batch_succeeded", { count: counts.succeeded })}</span>
          <span style={{ color: counts.failed > 0 ? STATUS_COLORS.failed : undefined }}>{t("durable_batch_failed", { count: counts.failed })}</span>
          <span>{t("durable_batch_active_count", { count: counts.active })}</span>
          {counts.cancelled > 0 && <span>{t("durable_batch_cancelled", { count: counts.cancelled })}</span>}
        </div>
        {confirmation && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded px-2 py-1.5 text-[10.5px]" style={{ background: confirmation === "cancel" ? "var(--color-shell-hud-danger)" : "var(--color-shell-hud-warn)", color: "var(--color-text-2)" }}>
            <span>{t(confirmation === "cancel" ? "durable_batch_cancel_confirm" : "durable_batch_retry_confirm")}</span>
            <span className="flex shrink-0 gap-1">
              <button type="button" className="focus-ring rounded px-1.5 py-0.5" disabled={working} onClick={() => void runAction(confirmation)}>
                {working ? <Loader2 className="h-3 w-3 animate-spin" aria-label={t("durable_batch_working")} /> : t("durable_batch_confirm")}
              </button>
              <button type="button" className="focus-ring rounded px-1.5 py-0.5" disabled={working} onClick={() => setConfirmation(null)}>{t("go_back")}</button>
            </span>
          </div>
        )}
        {!confirmation && (canCancel || canRetry) && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {canCancel && <button type="button" className="focus-ring inline-flex items-center gap-1 rounded px-2 py-1 text-[10.5px]" style={{ color: STATUS_COLORS.failed, background: "var(--color-shell-hud-danger)" }} onClick={() => setConfirmation("cancel")}><X className="h-3 w-3" aria-hidden />{t("durable_batch_cancel")}</button>}
            {canRetry && <button type="button" className="focus-ring inline-flex items-center gap-1 rounded px-2 py-1 text-[10.5px]" style={{ color: "var(--color-warn)", background: "var(--color-shell-hud-warn)" }} onClick={() => setConfirmation("retry")}><RotateCcw className="h-3 w-3" aria-hidden />{t("durable_batch_retry_failed")}</button>}
          </div>
        )}
      </div>
      {expanded && <BatchTaskList tasks={batch.tasks} />}
    </div>
  );
}

export function BatchPanel({ projectName }: { projectName: string | null }) {
  const { t } = useTranslation("dashboard");
  const { batches, loading, refreshing, error, hasActiveBatches, refresh, cancel, retryFailed } = useDurableBatches(projectName);
  const [open, setOpen] = useState(true);

  if (!projectName) return null;

  return (
    <section aria-label={t("durable_batch_title")} style={{ borderBottom: "1px solid var(--color-hairline-soft)" }}>
      <button type="button" className="focus-ring flex w-full items-center gap-2 px-4 py-2.5 text-left" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded" style={{ background: "var(--color-accent-dim)", color: "var(--color-accent-2)" }}><Package className="h-3.5 w-3.5" aria-hidden /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-[11.5px] font-medium" style={{ color: "var(--color-text-2)" }}>{t("durable_batch_title")}</span>
          <span className="block text-[10px]" style={{ color: "var(--color-text-4)" }}>{batches.length ? t("durable_batch_summary", { count: batches.length }) : t("durable_batch_empty")}</span>
        </span>
        {hasActiveBatches && <span className="num rounded px-1.5 py-px text-[10px]" style={{ color: "var(--color-accent-2)", background: "var(--color-accent-dim)" }}>{t("durable_batch_active")}</span>}
        <span className="flex shrink-0 items-center gap-1">
          <span role="status" aria-live="polite">{refreshing && <Loader2 className="h-3 w-3 animate-spin" style={{ color: "var(--color-text-4)" }} aria-label={t("durable_batch_refreshing")} />}</span>
          <ChevronDown className={"h-3.5 w-3.5 transition-transform " + (open ? "rotate-180" : "")} style={{ color: "var(--color-text-4)" }} aria-hidden />
        </span>
      </button>
      {open && (
        <>
          <div className="flex items-center justify-between gap-2 px-4 pb-2">
            <span className="min-w-0 text-[10px]" style={{ color: error ? STATUS_COLORS.failed : "var(--color-text-4)" }}>{error ? t("durable_batch_refresh_failed") : t("durable_batch_persisted_hint")}</span>
            <button type="button" className="focus-ring inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-1 text-[10.5px]" title={t("durable_batch_refresh")} aria-label={t("durable_batch_refresh")} onClick={() => void refresh()}><RefreshCw className={"h-3 w-3 " + (refreshing ? "animate-spin" : "")} aria-hidden />{t("durable_batch_refresh")}</button>
          </div>
          {loading ? <div className="flex items-center gap-2 px-4 pb-3 text-[10.5px]" style={{ color: "var(--color-text-4)" }}><Loader2 className="h-3 w-3 animate-spin" aria-hidden />{t("durable_batch_loading")}</div> : batches.length === 0 ? <div className="px-4 pb-3 text-[10.5px]" style={{ color: "var(--color-text-4)" }}>{t("durable_batch_no_registered")}</div> : <div className="max-h-72 overflow-y-auto">{batches.map((batch) => <BatchRow key={batch.batch_id} batch={batch} onCancel={cancel} onRetry={retryFailed} />)}</div>}
        </>
      )}
    </section>
  );
}
