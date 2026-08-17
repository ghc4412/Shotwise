import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Clock3,
  Eye,
  History,
  LayoutGrid,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Workflow,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import type {
  WorkflowDefinitionDetail,
  WorkflowEvent,
  WorkflowNodeInput,
  WorkflowNodeLogEntry,
  WorkflowNodeRun,
  WorkflowRevisionSummary,
  WorkflowRunDetail,
  WorkflowEdgeInput,
  WorkflowAssetRef,
} from "@/types";
import { errMsg } from "@/utils/async";
import { FlowCanvas } from "./FlowCanvas";
import { FlowMonitor } from "./FlowMonitor";
import type { GroupMeta } from "./workflow-utils";

type CanvasMode = "simple" | "canvas";

const POLL_INTERVAL_MS = 2000;

/** Remember the last used view per user; first-time users land on the simple wizard. */
const FLOW_DEFAULT_VIEW_KEY = "shotwise-flow-default-view";

function readDefaultMode(): CanvasMode {
  try {
    return window.localStorage.getItem(FLOW_DEFAULT_VIEW_KEY) === "canvas" ? "canvas" : "simple";
  } catch {
    return "simple";
  }
}

function RunStatusBadge({ status }: { status: string }) {
  const tone: Record<string, string> = {
    succeeded: "var(--color-good)",
    running: "var(--color-accent-2)",
    failed: "var(--color-danger)",
    paused: "var(--color-warn)",
    waiting_review: "var(--color-warn)",
    cancelled: "var(--color-text-4)",
  };
  return (
    <span
      className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[9px]"
      style={{ color: tone[status] ?? "var(--color-text-3)", borderColor: tone[status] ?? "var(--color-hairline)" }}
    >
      {status}
    </span>
  );
}

interface FlowCanvasPageProps {
  projectName: string;
}

export function FlowCanvasPage({ projectName }: FlowCanvasPageProps) {
  const { t } = useTranslation("dashboard");
  const [mode, setModeState] = useState<CanvasMode>(readDefaultMode);
  const switchMode = useCallback((next: CanvasMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(FLOW_DEFAULT_VIEW_KEY, next);
    } catch {
      // persistence is best-effort
    }
  }, []);
  const setMode = switchMode;
  const [definition, setDefinition] = useState<WorkflowDefinitionDetail | null>(null);
  const [graphNodes, setGraphNodes] = useState<WorkflowNodeInput[]>([]);
  const [graphEdges, setGraphEdges] = useState<WorkflowEdgeInput[]>([]);
  const [graphGroups, setGraphGroups] = useState<GroupMeta[]>([]);
  const [run, setRun] = useState<WorkflowRunDetail | null>(null);
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [eventsCollapsed, setEventsCollapsed] = useState(true);
  const [nodeLogs, setNodeLogs] = useState<{ nodeKey: string; items: WorkflowNodeLogEntry[] } | null>(null);
  const [revisions, setRevisions] = useState<WorkflowRevisionSummary[]>([]);
  const [revisionsOpen, setRevisionsOpen] = useState(false);
  const [preview, setPreview] = useState<{ nodeKey: string; run: WorkflowNodeRun } | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollTimer = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const loadRunDetail = useCallback(
    async (runId: string, signal?: AbortSignal) => {
      try {
        const [detail, eventResult] = await Promise.all([
          API.getWorkflowRun(runId, { signal }),
          API.listWorkflowEvents(projectName, { signal }),
        ]);
        setRun(detail);
        setEvents([...eventResult.items].reverse());
        if (["succeeded", "failed", "cancelled"].includes(detail.status)) {
          stopPolling();
        }
      } catch (requestError) {
        if (!signal?.aborted) setError(errMsg(requestError));
      }
    },
    [projectName, stopPolling],
  );

  const startPolling = useCallback(
    (runId: string) => {
      stopPolling();
      pollTimer.current = window.setInterval(() => {
        void loadRunDetail(runId);
      }, POLL_INTERVAL_MS);
    },
    [loadRunDetail, stopPolling],
  );

  const loadDefinition = useCallback(async (signal?: AbortSignal) => {
    let list = { items: [] as Array<{ id: string }> };
    try {
      list = await API.listWorkflowDefinitions(projectName, { signal });
    } catch {
      if (signal?.aborted) return;
    }
    if (list.items.length === 0) {
      await API.migrateProjectWorkflow(projectName);
      list = await API.listWorkflowDefinitions(projectName, { signal });
    }
    if (list.items.length === 0) return;
    const detail = await API.getWorkflowDefinition(list.items[0].id, { signal });
    setDefinition(detail);
    if (detail.active_revision) {
      setGraphNodes(detail.active_revision.nodes);
      setGraphEdges(detail.active_revision.edges);
      const groups = detail.active_revision.template_lock?.canvas_groups;
      setGraphGroups(Array.isArray(groups) ? (groups as GroupMeta[]) : []);
    }
  }, [projectName]);

  const loadAll = useCallback(
    async (preferredRunId: string | null, signal?: AbortSignal) => {
      try {
        await loadDefinition(signal);
        const runResult = await API.listWorkflowRuns(projectName, { signal });
        const nextSelected =
          preferredRunId && runResult.items.some((item) => item.id === preferredRunId)
            ? preferredRunId
            : (runResult.items[0]?.id ?? null);
        if (nextSelected) {
          await loadRunDetail(nextSelected, signal);
          const selected = runResult.items.find((item) => item.id === nextSelected);
          if (selected && !["succeeded", "failed", "cancelled"].includes(selected.status)) {
            startPolling(nextSelected);
          }
        } else {
          setRun(null);
        }
        setError(null);
      } catch (requestError) {
        if (!signal?.aborted) setError(errMsg(requestError));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [loadDefinition, loadRunDetail, projectName, startPolling],
  );

  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load must seed run state
    void loadAll(null, controller.signal);
    return () => {
      controller.abort();
      stopPolling();
    };
  }, [loadAll, stopPolling]);

  const saveGraph = useCallback(
    async (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => {
      if (!definition) return;
      setMutating(true);
      try {
        const revision = await API.createWorkflowRevision(definition.id, {
          nodes,
          edges,
          template_lock: { template_schema_version: 1, canvas_groups: groups },
        });
        await API.publishWorkflowRevision(revision.id);
        setGraphGroups(groups);
        await loadDefinition();
        return revision.id;
      } catch (requestError) {
        setError(errMsg(requestError));
        return null;
      } finally {
        setMutating(false);
      }
    },
    [definition, loadDefinition],
  );

  const importWorkflow = useCallback(
    async (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => {
      const result = await saveGraph(nodes, edges, groups);
      if (result) {
        const list = await API.listWorkflowDefinitions(projectName);
        if (list.items[0]) {
          const detail = await API.getWorkflowDefinition(list.items[0].id);
          setDefinition(detail);
          if (detail.active_revision) {
            setGraphNodes(detail.active_revision.nodes);
            setGraphEdges(detail.active_revision.edges);
            const importedGroups = detail.active_revision.template_lock?.canvas_groups;
            setGraphGroups(Array.isArray(importedGroups) ? (importedGroups as GroupMeta[]) : []);
          }
        }
      }
    },
    [projectName, saveGraph],
  );

  const runWorkflow = useCallback(async (
    nodes: WorkflowNodeInput[] = graphNodes,
    edges: WorkflowEdgeInput[] = graphEdges,
    groups: GroupMeta[] = graphGroups,
  ) => {
    if (!definition) return;
    setMutating(true);
    try {
      const revision = await API.createWorkflowRevision(definition.id, {
        nodes,
        edges,
        template_lock: { template_schema_version: 1, canvas_groups: groups },
      });
      await API.publishWorkflowRevision(revision.id);
      setGraphNodes(nodes);
      setGraphEdges(edges);
      setGraphGroups(groups);
      const planned = await API.planWorkflowRun(revision.id, projectName);
      const started = await API.transitionWorkflowRun(planned.id, "start", planned.version);
      await loadRunDetail(started.id);
      startPolling(started.id);
    } catch (requestError) {
      setError(errMsg(requestError));
    } finally {
      setMutating(false);
    }
  }, [definition, graphNodes, graphEdges, graphGroups, loadRunDetail, projectName, startPolling]);

  const transition = useCallback(
    async (action: "start" | "pause" | "resume" | "cancel") => {
      if (!run) return;
      setMutating(true);
      try {
        const next = await API.transitionWorkflowRun(run.id, action, run.version);
        await loadRunDetail(next.id);
        if (action === "cancel") stopPolling();
        if (action === "start" || action === "resume") startPolling(next.id);
      } catch (requestError) {
        setError(errMsg(requestError));
      } finally {
        setMutating(false);
      }
    },
    [loadRunDetail, run, startPolling, stopPolling],
  );

  const viewNodeLogs = useCallback(
    async (nodeKey: string) => {
      if (!run) return;
      try {
        const result = await API.getWorkflowNodeLogs(run.id, nodeKey);
        setNodeLogs({ nodeKey, items: result.items });
      } catch (requestError) {
        setError(errMsg(requestError));
      }
    },
    [run],
  );

  const openNodePreview = useCallback(
    (nodeKey: string) => {
      const nodeRun = run?.nodes.find((node) => node.node_key === nodeKey);
      if (!nodeRun) return;
      setNodeLogs(null);
      setPreview({ nodeKey, run: nodeRun });
    },
    [run],
  );

  /** Resume a failed run from a node, keeping successful upstream outputs. */
  const retryRunFromNode = useCallback(
    async (nodeKey: string) => {
      if (!run) return;
      setMutating(true);
      try {
        const next = await API.retryWorkflowRun(run.id, nodeKey, true);
        await loadRunDetail(next.id);
        startPolling(next.id);
        setError(null);
      } catch (requestError) {
        setError(errMsg(requestError));
      } finally {
        setMutating(false);
      }
    },
    [loadRunDetail, run, startPolling],
  );

  const loadRevisions = useCallback(async () => {
    if (!definition) return;
    try {
      const result = await API.listWorkflowRevisions(definition.id);
      setRevisions(result.items);
    } catch (requestError) {
      setError(errMsg(requestError));
    }
  }, [definition]);

  /** Publish a new revision restoring an historical graph, then reload. */
  const revertToRevision = useCallback(
    async (revisionId: string) => {
      if (!definition) return;
      setMutating(true);
      try {
        const result = await API.revertWorkflowRevision(definition.id, revisionId);
        await loadDefinition();
        setRevisions((current) => current.map((item) => ({ ...item, is_active: item.id === result.revision_id })));
        await loadAll(run?.id ?? null);
        setError(null);
      } catch (requestError) {
        setError(errMsg(requestError));
      } finally {
        setMutating(false);
      }
    },
    [definition, loadAll, loadDefinition, run],
  );

  const runStatusMap = useMemo(() => {
    if (!run) return null;
    return Object.fromEntries(run.nodes.map((node) => [node.node_key, node]));
  }, [run]);

  const running = run !== null && ["planned", "running", "paused", "waiting_review"].includes(run.status);

  const action = useMemo(() => {
    if (!run) return null;
    if (run.status === "planned") return { name: "start" as const, icon: Play };
    if (run.status === "running") return { name: "pause" as const, icon: Pause };
    if (run.status === "paused" || run.status === "waiting_review") return { name: "resume" as const, icon: Play };
    return null;
  }, [run]);

  const ActionIcon = action?.icon;

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-bg">
      <header className="flex min-h-[72px] shrink-0 items-center justify-between gap-4 border-b border-hairline px-5 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex items-center gap-2 text-text">
            <Workflow aria-hidden className="h-4 w-4 text-accent-2" />
            <h2 className="text-[15px] font-semibold">{t("flow_title")}</h2>
          </div>
          <div
            className="inline-flex rounded-md border border-hairline p-0.5"
            role="tablist"
            aria-label={t("flow_mode_label")}
          >
            <button
              type="button"
              role="tab"
              aria-selected={mode === "simple"}
              onClick={() => setMode("simple")}
              className={`inline-flex h-7 items-center gap-1.5 rounded px-3 text-[11px] font-semibold transition-colors focus-ring ${
                mode === "simple" ? "bg-accent text-black" : "text-text-3 hover:text-text"
              }`}
            >
              <LayoutGrid aria-hidden className="h-3.5 w-3.5" />
              {t("flow_mode_simple")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "canvas"}
              onClick={() => setMode("canvas")}
              className={`inline-flex h-7 items-center gap-1.5 rounded px-3 text-[11px] font-semibold transition-colors focus-ring ${
                mode === "canvas" ? "bg-accent text-black" : "text-text-3 hover:text-text"
              }`}
            >
              <Workflow aria-hidden className="h-3.5 w-3.5" />
              {t("flow_mode_canvas")}
            </button>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {run ? (
            <>
              <RunStatusBadge status={run.status} />
              {action && ActionIcon ? (
                <button
                  type="button"
                  onClick={() => void transition(action.name)}
                  disabled={mutating}
                  className="grid h-8 w-8 place-items-center rounded-md bg-accent text-black focus-ring disabled:opacity-50"
                  title={t(`flow_${action.name}`)}
                  aria-label={t(`flow_${action.name}`)}
                >
                  <ActionIcon aria-hidden className="h-3.5 w-3.5" />
                </button>
              ) : null}
              {running ? (
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
            </>
          ) : null}
          <button
            type="button"
            onClick={() => {
              setRevisionsOpen((open) => !open);
              if (!revisionsOpen) void loadRevisions();
            }}
            disabled={!definition || mutating}
            className="grid h-8 w-8 place-items-center rounded-md border border-hairline text-text-3 transition-colors hover:bg-bg-raised hover:text-text focus-ring disabled:opacity-40"
            title={t("flow_versions")}
            aria-label={t("flow_versions")}
          >
            <History aria-hidden className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => void loadAll(run?.id ?? null)}
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
          <button type="button" onClick={() => setError(null)} aria-label={t("flow_close_error")} className="focus-ring">
            <X aria-hidden className="h-3 w-3" />
          </button>
        </div>
      ) : null}

      {revisionsOpen && definition ? (
        <div className="absolute right-4 top-14 z-40 flex max-h-[60vh] w-[380px] flex-col rounded-md border border-hairline bg-bg-raised shadow-lg">
          <header className="flex items-center justify-between border-b border-hairline px-3 py-2">
            <span className="flex items-center gap-2 text-[11px] font-semibold text-text">
              <History aria-hidden className="h-3.5 w-3.5 text-accent-2" />
              {t("flow_versions")}
            </span>
            <button
              type="button"
              onClick={() => setRevisionsOpen(false)}
              className="grid h-5 w-5 place-items-center rounded text-text-3 hover:bg-bg focus-ring"
              aria-label={t("flow_close_error")}
            >
              <X aria-hidden className="h-3 w-3" />
            </button>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {revisions.length === 0 ? (
              <div className="px-4 py-8 text-center text-[11px] text-text-4">{t("flow_no_events")}</div>
            ) : (
              revisions.map((item) => (
                <div key={item.id} className="flex items-center gap-3 border-b border-hairline-soft px-3 py-2.5 last:border-b-0">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] font-semibold text-text">v{item.revision_no}</span>
                      <span className="truncate font-mono text-[9px] text-text-4">{item.graph_hash.slice(0, 10)}</span>
                      {item.is_active ? (
                        <span className="rounded border border-good/40 px-1 py-px text-[9px] font-semibold text-good">{t("flow_version_active")}</span>
                      ) : null}
                    </div>
                    <time className="mt-0.5 block text-[9px] text-text-4">{new Date(item.created_at).toLocaleString()}</time>
                  </div>
                  {!item.is_active ? (
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm(t("flow_revert_confirm", { no: item.revision_no }))) {
                          void revertToRevision(item.id);
                          setRevisionsOpen(false);
                        }
                      }}
                      disabled={mutating}
                      className="inline-flex h-7 items-center gap-1 rounded border border-hairline px-2 text-[10px] font-semibold text-text-2 hover:bg-bg focus-ring disabled:opacity-40"
                    >
                      <RotateCcw aria-hidden className="h-3 w-3" />
                      {t("flow_revert")}
                    </button>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="grid flex-1 place-items-center text-text-4">
          <Loader2 aria-hidden className="h-5 w-5 motion-safe:animate-spin" />
        </div>
      ) : mode === "simple" ? (
        <div className="min-h-0 flex-1">
          <FlowMonitor
            projectName={projectName}
            nodes={graphNodes}
            onOpenCanvas={() => setMode("canvas")}
            onQuickConfigChange={(nodeKey, config) => {
              setGraphNodes((current) => current.map((node) => (node.node_key === nodeKey ? { ...node, config } : node)));
            }}
            onQuickRun={runWorkflow}
            onRetryFromNode={(nodeKey) => void retryRunFromNode(nodeKey)}
            onPreviewOutputs={(nodeKey) => openNodePreview(nodeKey)}
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <FlowCanvas
            initialNodes={graphNodes}
            initialEdges={graphEdges}
            initialGroups={graphGroups}
            runStatus={runStatusMap}
            running={running}
            defaultName={definition?.name ?? projectName}
            onSave={async (nodes, edges, groups) => {
              await saveGraph(nodes, edges, groups);
            }}
            onImportWorkflow={async (nodes, edges, groups) => {
              await importWorkflow(nodes, edges, groups);
            }}
            onRun={runWorkflow}
            onViewNodeLogs={(nodeKey) => void viewNodeLogs(nodeKey)}
            onRetryFromNode={(nodeKey) => void retryRunFromNode(nodeKey)}
            onPreviewOutputs={(nodeKey) => openNodePreview(nodeKey)}
          />

          {/* node log drawer */}
          {nodeLogs ? (
            <div className="absolute bottom-10 right-10 z-30 flex max-h-[320px] w-[360px] flex-col rounded-md border border-hairline bg-bg-raised shadow-lg">
              <header className="flex items-center justify-between border-b border-hairline px-3 py-2">
                <span className="truncate font-mono text-[10px] font-semibold text-text-2">{nodeLogs.nodeKey}</span>
                <button
                  type="button"
                  onClick={() => setNodeLogs(null)}
                  className="grid h-5 w-5 place-items-center rounded text-text-3 hover:bg-bg focus-ring"
                  aria-label={t("flow_close_logs")}
                >
                  <X aria-hidden className="h-3 w-3" />
                </button>
              </header>
              <div className="min-h-0 flex-1 overflow-y-auto p-2 font-mono text-[10px] leading-5">
                {nodeLogs.items.length === 0 ? (
                  <div className="px-2 py-6 text-center text-text-4">{t("flow_no_events")}</div>
                ) : (
                  nodeLogs.items.map((item) => (
                    <div key={item.seq} className="flex gap-2">
                      <span className="shrink-0 text-text-4">#{item.seq}</span>
                      <span className={item.level === "error" ? "text-danger" : item.level === "warn" ? "text-warn" : "text-text-2"}>
                        {item.line}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          ) : null}

          {/* node output preview drawer */}
          {preview ? (
            <OutputPreviewPanel
              projectName={projectName}
              nodeKey={preview.nodeKey}
              refs={Object.values(preview.run.output_refs ?? {}).flat()}
              onClose={() => setPreview(null)}
            />
          ) : null}

          {/* collapsible event log panel */}
          <div className="shrink-0 border-t border-hairline">
            <button
              type="button"
              onClick={() => setEventsCollapsed((collapsed) => !collapsed)}
              className="flex h-8 w-full items-center justify-between px-4 text-[11px] font-semibold text-text-2 hover:bg-bg-raised focus-ring"
              aria-expanded={!eventsCollapsed}
            >
              <span className="flex items-center gap-2">
                <Clock3 aria-hidden className="h-3.5 w-3.5 text-text-4" />
                {t("flow_events")}
                <span className="font-mono text-[9px] font-normal text-text-4">{events.length}</span>
              </span>
              {eventsCollapsed ? (
                <ChevronUp aria-hidden className="h-3.5 w-3.5 text-text-4" />
              ) : (
                <ChevronDown aria-hidden className="h-3.5 w-3.5 text-text-4" />
              )}
            </button>
            {!eventsCollapsed ? (
              <div className="max-h-[180px] overflow-y-auto border-t border-hairline-soft">
                {events.map((event) => (
                  <div
                    key={event.event_id}
                    className="grid min-h-8 grid-cols-[56px_minmax(0,1fr)_auto] items-center gap-2 border-b border-hairline-soft px-4 py-1 last:border-b-0"
                  >
                    <span className="font-mono text-[9px] text-text-4">#{event.seq}</span>
                    <span className="truncate text-[10px] text-text-2">{event.event_type}</span>
                    <time className="font-mono text-[9px] text-text-4">{new Date(event.created_at).toLocaleTimeString()}</time>
                  </div>
                ))}
                {events.length === 0 ? (
                  <div className="px-4 py-4 text-center text-[10px] text-text-4">{t("flow_no_events")}</div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

/** Drawer listing a node's produced assets (images / videos / files). */
function OutputPreviewPanel({
  projectName,
  nodeKey,
  refs,
  onClose,
}: {
  projectName: string;
  nodeKey: string;
  refs: WorkflowAssetRef[];
  onClose: () => void;
}) {
  const { t } = useTranslation("dashboard");
  return (
    <div className="absolute bottom-10 right-10 z-30 flex max-h-[70vh] w-[420px] flex-col rounded-md border border-hairline bg-bg-raised shadow-lg">
      <header className="flex items-center justify-between border-b border-hairline px-3 py-2">
        <span className="flex min-w-0 items-center gap-2">
          <Eye aria-hidden className="h-3.5 w-3.5 shrink-0 text-accent-2" />
          <span className="truncate font-mono text-[10px] font-semibold text-text-2">{nodeKey}</span>
        </span>
        <button
          type="button"
          onClick={onClose}
          className="grid h-5 w-5 shrink-0 place-items-center rounded text-text-3 hover:bg-bg focus-ring"
          aria-label={t("flow_close_error")}
        >
          <X aria-hidden className="h-3 w-3" />
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {refs.length === 0 ? (
          <div className="px-2 py-8 text-center text-[11px] text-text-4">{t("flow_output_empty")}</div>
        ) : (
          <div className="space-y-3">
            {refs.map((ref, index) => {
              const url = ref.path ? API.getFileUrl(projectName, ref.path) : null;
              return (
                <article key={`${ref.path ?? ref.label}-${index}`} className="rounded-md border border-hairline bg-bg p-2.5">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="truncate text-[10px] font-semibold text-text-2">{ref.label || ref.path || nodeKey}</span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      <span className="rounded border border-hairline px-1 py-px font-mono text-[9px] text-text-4">{ref.kind}</span>
                      {ref.count != null ? <span className="font-mono text-[9px] text-text-4">×{ref.count}</span> : null}
                    </span>
                  </div>
                  {url && (ref.kind === "image" || ref.kind === "asset") ? (
                    <img
                      src={url}
                      alt={ref.label || ref.path || ""}
                      className="max-h-[220px] w-full rounded border border-hairline bg-bg-raised object-contain"
                      loading="lazy"
                    />
                  ) : url && ref.kind === "video" ? (
                    <video src={url} controls className="max-h-[220px] w-full rounded border border-hairline bg-bg-raised" preload="metadata">
                      <track kind="captions" />
                    </video>
                  ) : url ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 block truncate rounded border border-hairline px-2 py-1.5 font-mono text-[10px] text-accent-2 hover:bg-bg-raised focus-ring"
                    >
                      {ref.path}
                    </a>
                  ) : (
                    <div className="truncate font-mono text-[10px] text-text-4">{ref.label || ref.path || "—"}</div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
