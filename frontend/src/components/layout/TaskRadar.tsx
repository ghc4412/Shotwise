import { useCallback, useMemo, useRef, useState } from "react";
import { useLocation } from "wouter";
import { Activity, CheckCircle2, ChevronRight, Clock3, Eye, Filter, Loader2, Square, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { GlassPopover } from "@/components/ui/GlassPopover";
import { API } from "@/api";
import { useEscapeClose } from "@/hooks/useEscapeClose";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useTasksStore } from "@/stores/tasks-store";
import { buildTaskFailureTarget } from "@/utils/task-target";
import type { TaskItem } from "@/types";

type RadarFilter = "all" | "active" | "review" | "completed" | "failed";

const STATUS_COLORS: Record<string, string> = {
  queued: "var(--color-text-4)",
  running: "var(--color-accent-2)",
  cancelling: "var(--color-text-3)",
  succeeded: "var(--color-good)",
  failed: "oklch(0.72 0.18 25)",
  cancelled: "var(--color-text-3)",
};

export function isReviewTask(task: TaskItem): boolean {
  const values = [task.payload.status, task.payload.workflow_status, task.payload.review_status, task.payload.approval_status];
  const status = values.find((value) => typeof value === "string");
  const normalized = typeof status === "string" ? status.toLowerCase() : "";
  return normalized === "waiting_review" || normalized === "pending_review" || normalized === "needs_review";
}

export function taskProgress(task: TaskItem): number | null {
  if (task.status === "succeeded") return 100;
  const values = [task.payload.progress_percent, task.payload.progress, task.payload.percent, task.result?.progress_percent, task.result?.progress];
  const value = values.find((candidate) => typeof candidate === "number");
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const normalized = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(normalized)));
}

function episodeLabel(task: TaskItem, t: (key: string, options?: Record<string, unknown>) => string): string | null {
  const payloadEpisode = task.payload.episode;
  const match = task.script_file?.match(/(?:episode|ep)[_-]?(\d+)/i);
  const episode = typeof payloadEpisode === "number" ? payloadEpisode : match ? Number(match[1]) : null;
  return episode != null && Number.isFinite(episode)
    ? t("task_radar_episode", { defaultValue: "Episode {{episode}}", episode })
    : null;
}

function statusLabel(task: TaskItem, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (isReviewTask(task)) return t("task_radar_status_review", { defaultValue: "Waiting for review" });
  const keys: Record<TaskItem["status"], string> = {
    queued: "queued_status",
    running: "generating_status",
    cancelling: "cancelling_status",
    succeeded: "completed_status",
    failed: "failed_status",
    cancelled: "cancelled_status",
  };
  return t(keys[task.status], { defaultValue: task.status });
}

export function matchesRadarFilter(task: TaskItem, filter: RadarFilter): boolean {
  if (filter === "all") return true;
  if (filter === "active") return task.status === "queued" || task.status === "running" || task.status === "cancelling";
  if (filter === "review") return isReviewTask(task);
  if (filter === "failed") return task.status === "failed";
  return task.status === "succeeded" && !isReviewTask(task);
}

function TaskStatusIcon({ task }: { task: TaskItem }) {
  if (isReviewTask(task)) return <Eye className="h-3.5 w-3.5" style={{ color: "var(--color-warn, #e2a93b)" }} />;
  if (task.status === "running" || task.status === "cancelling") {
    return <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: STATUS_COLORS[task.status] }} />;
  }
  if (task.status === "queued") return <Clock3 className="h-3.5 w-3.5" style={{ color: STATUS_COLORS.queued }} />;
  if (task.status === "failed") return <XCircle className="h-3.5 w-3.5" style={{ color: STATUS_COLORS.failed }} />;
  return <CheckCircle2 className="h-3.5 w-3.5" style={{ color: STATUS_COLORS[task.status] }} />;
}

function TaskRadarRow({ task, onOpen }: { task: TaskItem; onOpen: (task: TaskItem) => void }) {
  const { t } = useTranslation("dashboard");
  const progress = taskProgress(task);
  const episode = episodeLabel(task, t);
  const source = t("task_radar_source_" + task.source, { defaultValue: task.source });
  const title = t("task_type_" + task.task_type, { defaultValue: task.task_type });

  return (
    <button type="button" className="group w-full rounded-md px-2.5 py-2 text-left transition-colors hover:bg-white/[0.045] focus-ring" onClick={() => onOpen(task)} aria-label={t("task_radar_view_detail", { defaultValue: "View task details" })}>
      <span className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0"><TaskStatusIcon task={task} /></span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="truncate text-[12px] font-medium" style={{ color: "var(--color-text-1)" }}>{title}</span>
            <span className="shrink-0 text-[10px]" style={{ color: STATUS_COLORS[task.status] }}>{statusLabel(task, t)}</span>
          </span>
          <span className="mt-0.5 flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[10px]" style={{ color: "var(--color-text-4)" }}>
            <span className="truncate">{task.resource_id}</span>
            <span>{source}</span>
            <span className="truncate">{task.project_name}</span>
            {episode ? <span>{episode}</span> : null}
          </span>
          <span className="mt-1.5 flex items-center gap-2">
            <span className="h-1 flex-1 overflow-hidden rounded-full" style={{ background: "var(--color-shell-hud-track)" }}>
              {progress != null ? <span className="block h-full rounded-full" style={{ width: progress + "%", background: STATUS_COLORS[task.status] }} /> : null}
            </span>
            <span className="w-7 text-right text-[10px] tabular-nums" style={{ color: "var(--color-text-4)" }}>{progress != null ? progress + "%" : "—"}</span>
            <ChevronRight className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" style={{ color: "var(--color-text-3)" }} />
          </span>
        </span>
      </span>
    </button>
  );
}

export function TaskRadar() {
  const { t } = useTranslation("dashboard");
  const [, setLocation] = useLocation();
  const anchorRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<RadarFilter>("all");
  const [stopConfirm, setStopConfirm] = useState<{ count: number; projectName: string } | null>(null);
  const [stopping, setStopping] = useState(false);
  const { tasks, stats, refreshTasks } = useTasksStore();
  const { currentProjectData, currentProjectName } = useProjectsStore();
  const setTaskHudOpen = useAppStore((s) => s.setTaskHudOpen);
  const triggerScrollTo = useAppStore((s) => s.triggerScrollTo);

  useEscapeClose(() => {
    if (stopConfirm) {
      setStopConfirm(null);
    } else {
      setOpen(false);
    }
  }, open || Boolean(stopConfirm));

  const reviewCount = useMemo(() => tasks.filter(isReviewTask).length, [tasks]);
  const completedCount = Math.max(0, stats.succeeded - reviewCount);
  const filteredTasks = useMemo(() => tasks.filter((task) => matchesRadarFilter(task, filter)).slice(0, 8), [filter, tasks]);
  const activeCount = stats.queued + stats.running + stats.cancelling;
  const totalCount = stats.total || tasks.length;

  const handleStopAll = useCallback(async () => {
    if (!currentProjectName || stats.queued <= 0 || stopping) return;
    try {
      const { queued_count } = await API.cancelAllPreview(currentProjectName);
      if (queued_count > 0) {
        setStopConfirm({ count: queued_count, projectName: currentProjectName });
      }
    } catch {
      // The task list will reconcile on its next refresh if the preview races with completion.
    }
  }, [currentProjectName, stats.queued, stopping]);

  const confirmStopAll = useCallback(async () => {
    if (!stopConfirm) return;
    setStopping(true);
    try {
      await API.cancelAllQueued(stopConfirm.projectName);
      await refreshTasks();
    } finally {
      setStopping(false);
      setStopConfirm(null);
    }
  }, [refreshTasks, stopConfirm]);

  const openTask = (task: TaskItem) => {
    setOpen(false);
    const projectData = task.project_name === currentProjectName ? currentProjectData : null;
    const target = buildTaskFailureTarget(task, projectData);
    if (target) {
      setLocation(target.route);
      triggerScrollTo({ type: target.type, id: target.id, route: target.route, highlight_style: target.highlight_style ?? "flash", expires_at: Date.now() + 3000 });
      return;
    }
    setLocation("~/app/projects/" + encodeURIComponent(task.project_name));
  };

  const filters: { id: RadarFilter; label: string; count: number }[] = [
    { id: "all", label: t("task_radar_filter_all", { defaultValue: "All" }), count: totalCount },
    { id: "active", label: t("task_radar_filter_active", { defaultValue: "Active" }), count: activeCount },
    { id: "review", label: t("task_radar_filter_review", { defaultValue: "Review" }), count: reviewCount },
    { id: "completed", label: t("task_radar_filter_completed", { defaultValue: "Completed" }), count: completedCount },
    { id: "failed", label: t("task_radar_filter_failed", { defaultValue: "Failed" }), count: stats.failed },
  ];

  return (
    <div ref={anchorRef} className="relative">
      <button type="button" className="pointer-events-auto inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium transition-colors focus-ring" style={{ color: open || activeCount > 0 ? "var(--color-accent-2)" : "var(--color-text-3)", background: open ? "var(--color-accent-dim)" : "transparent" }} onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-label={t("task_radar_toggle", { defaultValue: "Open task radar" })} title={t("task_radar_toggle", { defaultValue: "Open task radar" })}>
        <Activity className={"h-3.5 w-3.5 " + (activeCount > 0 ? "animate-shot-pulse" : "")} />
        <span className="hidden xl:inline">{t("task_radar_title", { defaultValue: "Task radar" })}</span>
        <span className="tabular-nums">{activeCount}</span>
      </button>
      <GlassPopover open={open} onClose={() => setOpen(false)} anchorRef={anchorRef} sideOffset={6} width="w-[25rem]">
        <div className="p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--color-text-1)" }}>{t("task_radar_title", { defaultValue: "Task radar" })}</p>
              <p className="mt-0.5 text-[10px]" style={{ color: "var(--color-text-4)" }}>{t("task_radar_subtitle", { defaultValue: "A live view of work across your projects" })}</p>
            </div>
            <Filter className="mt-0.5 h-3.5 w-3.5" style={{ color: "var(--color-text-4)" }} />
          </div>
          <div className="mt-3 flex items-stretch gap-1" role="group" aria-label={t("task_radar_filter_group", { defaultValue: "Filter tasks" })}>
            <div className="grid min-w-0 flex-1 grid-cols-5 gap-1">
              {filters.map((item) => <button key={item.id} type="button" className="rounded px-1 py-1.5 text-[10px] transition-colors focus-ring" style={{ color: filter === item.id ? "var(--color-text-1)" : "var(--color-text-4)", background: filter === item.id ? "var(--color-accent-dim)" : "transparent" }} onClick={() => setFilter(item.id)} aria-pressed={filter === item.id}><span className="block truncate">{item.label}</span><span className="mt-0.5 block tabular-nums">{item.count}</span></button>)}
            </div>
            <button
              type="button"
              className="focus-ring inline-flex w-8 shrink-0 items-center justify-center rounded border transition-colors disabled:cursor-not-allowed disabled:opacity-40"
              style={{ color: "oklch(0.72 0.18 25)", borderColor: "oklch(0.72 0.18 25 / 0.35)", background: "oklch(0.72 0.18 25 / 0.06)" }}
              onClick={() => void handleStopAll()}
              disabled={!currentProjectName || stats.queued <= 0 || stopping}
              aria-label={t("task_radar_stop_all_aria")}
              title={t("task_radar_stop_all")}
            >
              {stopping ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5 fill-current" />}
            </button>
          </div>
          {stopConfirm && (
            <div className="mt-2 rounded-md px-2.5 py-2" role="alertdialog" aria-label={t("task_radar_stop_confirm_aria")} style={{ background: "oklch(0.72 0.18 25 / 0.08)", border: "1px solid oklch(0.72 0.18 25 / 0.22)" }}>
              <p className="text-[11px]" style={{ color: "var(--color-text-2)" }}>{t("task_radar_stop_confirm", { count: stopConfirm.count })}</p>
              <div className="mt-2 flex gap-2">
                <button type="button" className="focus-ring rounded px-2 py-1 text-[10px] font-medium text-white transition-opacity disabled:opacity-50" style={{ background: "oklch(0.55 0.20 25)" }} onClick={() => void confirmStopAll()} disabled={stopping}>
                  {stopping ? t("cancelling") : t("task_radar_stop_confirm_action")}
                </button>
                <button type="button" className="focus-ring rounded px-2 py-1 text-[10px]" style={{ color: "var(--color-text-3)", border: "1px solid var(--color-hairline)" }} onClick={() => setStopConfirm(null)} disabled={stopping}>
                  {t("task_radar_stop_cancel")}
                </button>
              </div>
            </div>
          )}
          <div className="mt-2 max-h-[21rem] overflow-y-auto pr-0.5">
            {filteredTasks.length > 0 ? filteredTasks.map((task) => <TaskRadarRow key={task.task_id} task={task} onOpen={openTask} />) : <div className="py-8 text-center text-xs" style={{ color: "var(--color-text-4)" }}>{t("task_radar_empty", { defaultValue: "No tasks match this view" })}</div>}
          </div>
          <div className="mt-2 flex items-center justify-between border-t pt-2" style={{ borderColor: "var(--color-hairline)" }}>
            <span className="text-[10px]" style={{ color: "var(--color-text-4)" }}>{t("task_radar_summary", { defaultValue: "{{queued}} queued · {{running}} running · {{failed}} failed", queued: stats.queued, running: stats.running, failed: stats.failed })}</span>
            <button type="button" className="inline-flex items-center gap-1 text-[11px] font-medium text-accent focus-ring" onClick={() => { setOpen(false); setTaskHudOpen(true); }}>{t("task_radar_view_all", { defaultValue: "View all tasks" })}<ChevronRight className="h-3 w-3" /></button>
          </div>
        </div>
      </GlassPopover>
    </div>
  );
}
