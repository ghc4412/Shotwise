import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Circle,
  Clock3,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Workflow,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import type { WorkflowEvent, WorkflowNodeRun, WorkflowRunDetail, WorkflowRunSummary } from "@/types";
import { errMsg } from "@/utils/async";

const DEFAULT_NODES = [
  "source_import",
  "script_generate",
  "script_review",
  "character_reference",
  "storyboard_generate",
  "storyboard_review",
  "shot_image_generate",
  "shot_video_generate",
  "voice_generate",
  "subtitle_generate",
  "compose",
  "quality_check",
  "export",
] as const;

const DEFAULT_REVISION = {
  nodes: DEFAULT_NODES.map((nodeKey, index) => ({
    node_key: nodeKey,
    node_type: nodeKey,
    node_type_version: "1",
    config_schema_version: "1",
    weight: nodeKey.includes("generate") ? 2 : 1,
    ui_position: { x: index * 220, y: 0 },
    approval_policy: nodeKey.endsWith("review") ? { required: true } : null,
  })),
  edges: DEFAULT_NODES.slice(1).map((target, index) => ({
    edge_key: `${DEFAULT_NODES[index]}-${target}`,
    source_node_key: DEFAULT_NODES[index],
    target_node_key: target,
    on_failure: "stop",
    priority: 0,
  })),
  template_lock: { template_schema_version: 1 },
};

interface NodeTone {
  color: string;
  background: string;
  border: string;
}

/** 夜间（默认）主题：深色霓虹风状态底色。 */
const STATUS_TONE_DARK: Record<string, NodeTone> = {
  succeeded: { color: "var(--color-good)", background: "oklch(0.22 0.045 155 / 0.42)", border: "oklch(0.55 0.12 155 / 0.38)" },
  running: { color: "var(--color-accent-2)", background: "var(--color-accent-dim)", border: "oklch(0.62 0.12 230 / 0.42)" },
  paused: { color: "var(--color-warn)", background: "oklch(0.25 0.04 75 / 0.4)", border: "oklch(0.62 0.12 75 / 0.42)" },
  waiting_review: { color: "var(--color-warn)", background: "oklch(0.25 0.04 75 / 0.4)", border: "oklch(0.62 0.12 75 / 0.42)" },
  failed: { color: "var(--color-danger)", background: "oklch(0.24 0.055 25 / 0.4)", border: "oklch(0.58 0.16 25 / 0.4)" },
  cancelled: { color: "var(--color-text-4)", background: "var(--color-shell-btn)", border: "var(--color-hairline)" },
};

const DEFAULT_TONE_DARK: NodeTone = {
  color: "var(--color-text-3)",
  background: "oklch(0.205 0.01 265 / 0.58)",
  border: "var(--color-hairline-soft)",
};

/** 日间主题：浅色半透明底，叠在浅色工作台上是干净的淡彩卡片。 */
const STATUS_TONE_LIGHT: Record<string, NodeTone> = {
  succeeded: { color: "var(--color-good)", background: "oklch(0.93 0.045 155 / 0.55)", border: "oklch(0.62 0.11 155 / 0.42)" },
  running: { color: "var(--color-accent-2)", background: "var(--color-accent-dim)", border: "oklch(0.62 0.12 230 / 0.45)" },
  paused: { color: "var(--color-warn)", background: "oklch(0.95 0.05 85 / 0.55)", border: "oklch(0.66 0.10 85 / 0.45)" },
  waiting_review: { color: "var(--color-warn)", background: "oklch(0.95 0.05 85 / 0.55)", border: "oklch(0.66 0.10 85 / 0.45)" },
  failed: { color: "var(--color-danger)", background: "oklch(0.95 0.035 25 / 0.55)", border: "oklch(0.62 0.13 25 / 0.45)" },
  cancelled: { color: "var(--color-text-4)", background: "var(--color-shell-btn)", border: "var(--color-hairline)" },
};

const DEFAULT_TONE_LIGHT: NodeTone = {
  color: "var(--color-text-3)",
  background: "oklch(0.92 0.015 250 / 0.55)",
  border: "var(--color-hairline-soft)",
};

function tone(status: string, isLight: boolean): NodeTone {
  const table = isLight ? STATUS_TONE_LIGHT : STATUS_TONE_DARK;
  return table[status] ?? (isLight ? DEFAULT_TONE_LIGHT : DEFAULT_TONE_DARK);
}

function StatusIcon({ status }: { status: string }) {
  const cls = "h-3.5 w-3.5";
  if (status === "succeeded") return <Check aria-hidden className={cls} />;
  if (status === "running") return <Loader2 aria-hidden className={`${cls} motion-safe:animate-spin`} />;
  if (status === "failed") return <AlertTriangle aria-hidden className={cls} />;
  if (status === "paused" || status === "waiting_review") return <Clock3 aria-hidden className={cls} />;
  if (status === "cancelled") return <X aria-hidden className={cls} />;
  return <Circle aria-hidden className={cls} />;
}

function NodeCell({ node, isLight }: { node: WorkflowNodeRun; isLight: boolean }) {
  const statusTone = tone(node.status, isLight);
  const progress = node.progress == null ? null : Math.round(node.progress * 100);
  return (
    <article
      className="relative h-[126px] w-[184px] shrink-0 overflow-hidden rounded-md border p-3"
      style={{ background: statusTone.background, borderColor: statusTone.border }}
    >
      <div className="flex items-center justify-between gap-2" style={{ color: statusTone.color }}>
        <StatusIcon status={node.status} />
        <span className="font-mono text-[10px] tabular-nums">A{node.attempt_no}</span>
      </div>
      <h3 className="mt-3 line-clamp-2 text-[12px] font-semibold leading-4 text-text">
        {node.node_key.replaceAll("_", " ")}
      </h3>
      <div className="mt-2 flex items-center justify-between gap-2 font-mono text-[9px] text-text-4">
        <span>{node.phase_code ?? node.status}</span>
        <span>{progress == null ? "--" : `${progress}%`}</span>
      </div>
      <div className="absolute inset-x-3 bottom-3 h-[3px] overflow-hidden bg-black/25">
        <span
          className="block h-full transition-[width] duration-300"
          style={{ width: `${progress ?? 0}%`, background: statusTone.color }}
        />
      </div>
    </article>
  );
}

interface FlowMonitorProps {
  projectName: string;
}

export function FlowMonitor({ projectName }: FlowMonitorProps) {
  const { t } = useTranslation("dashboard");
  const isLight = useAppStore((s) => s.theme) === "light";
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [run, setRun] = useState<WorkflowRunDetail | null>(null);
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async (preferredRunId: string | null, signal?: AbortSignal) => {
    try {
      const [runResult, eventResult] = await Promise.all([
        API.listWorkflowRuns(projectName, { signal }),
        API.listWorkflowEvents(projectName, { signal }),
      ]);
      const nextSelected = preferredRunId && runResult.items.some((item) => item.id === preferredRunId)
        ? preferredRunId
        : (runResult.items[0]?.id ?? null);
      const detail = nextSelected ? await API.getWorkflowRun(nextSelected, { signal }) : null;
      setRuns(runResult.items);
      setSelectedRunId(nextSelected);
      setRun(detail);
      setEvents([...eventResult.items].reverse());
      setError(null);
    } catch (requestError) {
      if (signal?.aborted) return;
      setError(errMsg(requestError));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [projectName]);

  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- project changes require a fresh workflow snapshot
    void loadData(null, controller.signal);
    return () => controller.abort();
  }, [loadData]);

  const refresh = () => {
    setLoading(true);
    void loadData(selectedRunId);
  };

  const selectRun = (runId: string) => {
    setSelectedRunId(runId);
    setLoading(true);
    void loadData(runId);
  };

  const createFlow = async () => {
    setMutating(true);
    try {
      const definition = await API.createWorkflowDefinition(projectName);
      const revision = await API.createWorkflowRevision(definition.id, DEFAULT_REVISION);
      await API.publishWorkflowRevision(revision.id);
      await API.planWorkflowRun(revision.id, projectName);
      await loadData(null);
    } catch (requestError) {
      setError(errMsg(requestError));
    } finally {
      setMutating(false);
    }
  };

  const transition = async (action: "start" | "pause" | "resume" | "cancel") => {
    if (!run) return;
    setMutating(true);
    try {
      await API.transitionWorkflowRun(run.id, action, run.version);
      await loadData(run.id);
    } catch (requestError) {
      setError(errMsg(requestError));
    } finally {
      setMutating(false);
    }
  };

  const action = useMemo(() => {
    if (!run) return null;
    if (run.status === "planned") return { name: "start" as const, icon: Play, label: t("flow_start") };
    if (run.status === "running") return { name: "pause" as const, icon: Pause, label: t("flow_pause") };
    if (run.status === "paused" || run.status === "waiting_review") {
      return { name: "resume" as const, icon: Play, label: t("flow_resume") };
    }
    return null;
  }, [run, t]);

  const ActionIcon = action?.icon;
  const runTone = tone(run?.status ?? "planned", isLight);

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-bg">
      <header className="flex min-h-[72px] shrink-0 items-center justify-between gap-4 border-b border-hairline px-5 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-text">
            <Workflow aria-hidden className="h-4 w-4 text-accent-2" />
            <h2 className="text-[15px] font-semibold">{t("flow_title")}</h2>
          </div>
          <p className="mt-1 text-[11px] text-text-4">{t("flow_cursor", { cursor: events[0]?.seq ?? 0 })}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {runs.length > 0 ? (
            <select
              value={selectedRunId ?? ""}
              onChange={(event) => selectRun(event.target.value)}
              className="h-8 max-w-[220px] rounded-md border border-hairline bg-bg-raised px-2 text-[11px] text-text focus-ring"
              aria-label={t("flow_select_run")}
            >
              {runs.map((item) => (
                <option key={item.id} value={item.id}>{item.id.slice(0, 8)} / {item.status}</option>
              ))}
            </select>
          ) : null}
          <button
            type="button"
            onClick={refresh}
            disabled={loading || mutating}
            className="grid h-8 w-8 place-items-center rounded-md border border-hairline text-text-3 transition-colors hover:bg-bg-raised hover:text-text focus-ring disabled:opacity-40"
            title={t("flow_refresh")}
            aria-label={t("flow_refresh")}
          >
            <RefreshCw aria-hidden className={`h-3.5 w-3.5 ${loading ? "motion-safe:animate-spin" : ""}`} />
          </button>
        </div>
      </header>

      {error ? (
        <div className="flex items-center gap-2 border-b border-danger/30 bg-danger/10 px-5 py-2 text-[11px] text-danger">
          <AlertTriangle aria-hidden className="h-3.5 w-3.5" />
          <span className="min-w-0 flex-1 truncate">{error}</span>
        </div>
      ) : null}

      {!loading && !run ? (
        <div className="grid flex-1 place-items-center p-6">
          <div className="max-w-sm text-center">
            <Workflow aria-hidden className="mx-auto h-9 w-9 text-text-4" />
            <h3 className="mt-4 text-[15px] font-semibold text-text">{t("flow_empty_title")}</h3>
            <button
              type="button"
              onClick={() => void createFlow()}
              disabled={mutating}
              className="mt-5 inline-flex h-9 items-center gap-2 rounded-md bg-accent px-3 text-[12px] font-semibold text-black focus-ring disabled:opacity-50"
            >
              {mutating ? <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" /> : <Workflow aria-hidden className="h-3.5 w-3.5" />}
              {t("flow_create")}
            </button>
          </div>
        </div>
      ) : null}

      {run ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex items-center justify-between gap-4 border-b border-hairline-soft px-5 py-3">
            <div className="flex items-center gap-3">
              <span
                className="inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-[11px] font-semibold"
                style={{ color: runTone.color, background: runTone.background, borderColor: runTone.border }}
              >
                <StatusIcon status={run.status} />
                {run.status}
              </span>
              <span className="font-mono text-[10px] text-text-4">v{run.version} / {run.mode}</span>
            </div>
            <div className="flex items-center gap-1">
              {action && ActionIcon ? (
                <button
                  type="button"
                  onClick={() => void transition(action.name)}
                  disabled={mutating}
                  className="grid h-8 w-8 place-items-center rounded-md bg-accent text-black focus-ring disabled:opacity-50"
                  title={action.label}
                  aria-label={action.label}
                >
                  <ActionIcon aria-hidden className="h-3.5 w-3.5" />
                </button>
              ) : null}
              {run.status === "running" || run.status === "paused" || run.status === "waiting_review" ? (
                <button
                  type="button"
                  onClick={() => void transition("cancel")}
                  disabled={mutating}
                  className="grid h-8 w-8 place-items-center rounded-md border border-danger/35 text-danger hover:bg-danger/10 focus-ring disabled:opacity-50"
                  title={t("flow_cancel")}
                  aria-label={t("flow_cancel")}
                >
                  <X aria-hidden className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          </div>

          <div className="border-b border-hairline px-5 py-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-[11px] font-semibold text-text-2">{t("flow_nodes")}</h3>
              <span className="font-mono text-[9px] text-text-4">{run.nodes.length} NODES</span>
            </div>
            <div className="flex min-w-0 gap-2 overflow-x-auto pb-2">
              {run.nodes.map((node) => <NodeCell key={node.id} node={node} isLight={isLight} />)}
            </div>
          </div>

          <div className="px-5 py-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="text-[11px] font-semibold text-text-2">{t("flow_events")}</h3>
              <span className="font-mono text-[9px] text-text-4">{t("flow_event_count", { count: events.length })}</span>
            </div>
            <div className="border-y border-hairline-soft">
              {events.map((event) => (
                <div key={event.event_id} className="grid min-h-10 grid-cols-[64px_minmax(0,1fr)_auto] items-center gap-3 border-b border-hairline-soft px-2 py-2 last:border-b-0">
                  <span className="font-mono text-[10px] text-text-4">#{event.seq}</span>
                  <span className="truncate text-[11px] text-text-2">{event.event_type}</span>
                  <time className="font-mono text-[9px] text-text-4">{new Date(event.created_at).toLocaleTimeString()}</time>
                </div>
              ))}
              {events.length === 0 ? <div className="px-2 py-6 text-center text-[11px] text-text-4">{t("flow_no_events")}</div> : null}
            </div>
          </div>
        </div>
      ) : null}

      {loading && !run ? (
        <div className="grid flex-1 place-items-center text-text-4">
          <Loader2 aria-hidden className="h-5 w-5 motion-safe:animate-spin" />
        </div>
      ) : null}
    </section>
  );
}
