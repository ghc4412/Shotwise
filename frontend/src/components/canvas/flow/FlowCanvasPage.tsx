import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Clock3,
  Eye,
  History,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Workflow,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
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
import { WorkflowTemplateLauncher } from "./WorkflowTemplateLauncher";
import { WorkflowRunBudgetPanel } from "./WorkflowRunBudgetPanel";
import { WorkflowTemplateUpgradeNotice } from "./WorkflowTemplateUpgradeNotice";
import type { GroupMeta } from "./workflow-utils";
import { validateWorkflowGraph } from "./workflow-preflight";

type CanvasMode = "template" | "canvas";

const POLL_INTERVAL_MS = 2000;

function graphFingerprint(nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]): string {
  return JSON.stringify({ nodes, edges, groups });
}

function getTemplateSourceId(templateLock: Record<string, unknown> | null | undefined): string | null {
  const value = templateLock?.template_id;
  return typeof value === "string" && value.length > 0 ? value : null;
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
  const [, navigate] = useLocation();
  const canvasSaveRef = useRef<(() => Promise<boolean>) | null>(null);
  const [mode, setMode] = useState<CanvasMode>("template");
  const [definition, setDefinition] = useState<WorkflowDefinitionDetail | null>(null);
  const [graphNodes, setGraphNodes] = useState<WorkflowNodeInput[]>([]);
  const [graphEdges, setGraphEdges] = useState<WorkflowEdgeInput[]>([]);
  const [graphGroups, setGraphGroups] = useState<GroupMeta[]>([]);
  const [sourceTemplateId, setSourceTemplateId] = useState<string | null>(null);
  const [draftStatus, setDraftStatus] = useState<"saved" | "dirty" | "saving">("saved");
  const savedGraphFingerprint = useRef<string | null>(null);
  const [liveGraphNodes, setLiveGraphNodes] = useState<WorkflowNodeInput[]>(graphNodes);
  const [liveGraphEdges, setLiveGraphEdges] = useState<WorkflowEdgeInput[]>(graphEdges);

  useEffect(() => {
    // The server graph is an external source of truth for the local canvas draft.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the draft after a server graph load
    setLiveGraphNodes(graphNodes);
    setLiveGraphEdges(graphEdges);
  }, [graphEdges, graphNodes]);

  const handleGraphChange = useCallback(
    (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => {
      setLiveGraphNodes(nodes);
      setLiveGraphEdges(edges);
      setDraftStatus(graphFingerprint(nodes, edges, groups) === savedGraphFingerprint.current ? "saved" : "dirty");
    },
    [],
  );
  const [run, setRun] = useState<WorkflowRunDetail | null>(null);
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [eventsCollapsed, setEventsCollapsed] = useState(true);
  const [nodeLogs, setNodeLogs] = useState<{ nodeKey: string; items: WorkflowNodeLogEntry[] } | null>(null);
  const [revisions, setRevisions] = useState<WorkflowRevisionSummary[]>([]);
  const [revisionsOpen, setRevisionsOpen] = useState(false);
  const [preflightOpen, setPreflightOpen] = useState(false);
  const [preview, setPreview] = useState<{ nodeKey: string; run: WorkflowNodeRun } | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [savingAndExiting, setSavingAndExiting] = useState(false);
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
    const selectedRevision = detail.draft_revision ?? detail.active_revision;
    if (selectedRevision) {
      const groups = selectedRevision.template_lock?.canvas_groups;
      const nextGroups = Array.isArray(groups) ? (groups as GroupMeta[]) : [];
      setGraphNodes(selectedRevision.nodes);
      setGraphEdges(selectedRevision.edges);
      setGraphGroups(nextGroups);
      setSourceTemplateId(getTemplateSourceId(selectedRevision.template_lock));
      savedGraphFingerprint.current = graphFingerprint(selectedRevision.nodes, selectedRevision.edges, nextGroups);
      setDraftStatus("saved");
    } else {
      setSourceTemplateId(null);
      savedGraphFingerprint.current = graphFingerprint([], [], []);
      setDraftStatus("saved");
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
      if (!definition) return false;
      setMutating(true);
      setDraftStatus("saving");
      try {
        const templateLock = {
          template_schema_version: 1,
          canvas_groups: groups,
          ...(sourceTemplateId ? { template_id: sourceTemplateId } : {}),
        };
        await API.createWorkflowRevision(definition.id, {
          nodes,
          edges,
          template_lock: templateLock,
        });
        setGraphNodes(nodes);
        setGraphEdges(edges);
        setGraphGroups(groups);
        savedGraphFingerprint.current = graphFingerprint(nodes, edges, groups);
        setDraftStatus("saved");
        return true;
      } catch (requestError) {
        setDraftStatus("dirty");
        setError(errMsg(requestError));
        return false;
      } finally {
        setMutating(false);
      }
    },
    [definition, sourceTemplateId],
  );

  const registerCanvasSave = useCallback((save: (() => Promise<boolean>) | null) => {
    canvasSaveRef.current = save;
  }, []);

  const saveAndExit = useCallback(async () => {
    if (savingAndExiting) return;
    setSavingAndExiting(true);
    try {
      const save = canvasSaveRef.current;
      const saved = draftStatus === "dirty" ? Boolean(save && (await save())) : true;
      if (saved) navigate(`/app/projects/${encodeURIComponent(projectName)}`);
    } catch (requestError) {
      setError(errMsg(requestError));
    } finally {
      setSavingAndExiting(false);
    }
  }, [draftStatus, navigate, projectName, savingAndExiting]);

  const importWorkflow = useCallback(
    async (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => {
      await saveGraph(nodes, edges, groups);
    },
    [saveGraph],
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
        template_lock: {
          template_schema_version: 1,
          canvas_groups: groups,
          ...(sourceTemplateId ? { template_id: sourceTemplateId } : {}),
        },
      });
      await API.publishWorkflowRevision(revision.id);
      setGraphNodes(nodes);
      setGraphEdges(edges);
      setGraphGroups(groups);
      savedGraphFingerprint.current = graphFingerprint(nodes, edges, groups);
      setDraftStatus("saved");
      const planned = await API.planWorkflowRun(revision.id, projectName);
      const started = await API.transitionWorkflowRun(planned.id, "start", planned.version);
      await loadRunDetail(started.id);
      startPolling(started.id);
    } catch (requestError) {
      setError(errMsg(requestError));
    } finally {
      setMutating(false);
    }
  }, [definition, graphNodes, graphEdges, graphGroups, loadRunDetail, projectName, sourceTemplateId, startPolling]);

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
  const unpublishedTemplateMessage = t("flow_template_not_published", {
    defaultValue: "该模板尚未发布，暂时无法使用。",
  });
  const displayError = error && error.toLowerCase().replace(/[^a-z0-9]/g, "").includes("workflowtemplatenotpublished")
    ? unpublishedTemplateMessage === "flow_template_not_published"
      ? "该模板尚未发布，暂时无法使用。"
      : unpublishedTemplateMessage
    : error;
  const preflight = useMemo(
    () => validateWorkflowGraph(liveGraphNodes, liveGraphEdges, {
      contentMode: definition?.active_revision?.content_mode,
      generationMode: definition?.active_revision?.generation_mode,
    }),
    [definition?.active_revision?.content_mode, definition?.active_revision?.generation_mode, liveGraphEdges, liveGraphNodes],
  );

  return (
    <section className={mode === "template" ? "relative min-w-0 overflow-y-auto bg-bg" : "relative flex h-full min-w-0 flex-col overflow-hidden bg-bg"}>
      {mode === "canvas" ? <WorkflowRunBudgetPanel run={run} /> : null}
      {mode === "template" ? (
        <WorkflowTemplateLauncher
          projectName={projectName}
          onDerived={() => void loadAll(null)}
          onOpenCanvas={() => setMode("canvas")}
        />
      ) : null}

      {mode === "canvas" ? (
        <section className="shrink-0 border-b border-hairline bg-bg-raised/70">
          <button
            type="button"
            onClick={() => setPreflightOpen((open) => !open)}
            className="flex h-8 w-full items-center justify-between gap-3 px-5 text-left text-[10px] hover:bg-bg-raised focus-ring"
            aria-expanded={preflightOpen}
          >
            <span className="flex min-w-0 items-center gap-2">
              <ShieldCheck aria-hidden className={preflight.canRun ? "h-3.5 w-3.5 text-good" : "h-3.5 w-3.5 text-danger"} />
              <span className="font-semibold text-text-2">{t("flow_preflight_title")}</span>
              <span className={preflight.canRun ? "text-good" : "text-danger"}>
                {preflight.canRun ? t("flow_preflight_ready") : t("flow_preflight_blocked")}
              </span>
              {preflight.warnings.length > 0 ? <span className="text-warn">{t("flow_preflight_warning_count", { count: preflight.warnings.length })}</span> : null}
            </span>
            {preflightOpen ? <ChevronUp aria-hidden className="h-3.5 w-3.5 text-text-4" /> : <ChevronDown aria-hidden className="h-3.5 w-3.5 text-text-4" />}
          </button>
          {preflightOpen ? (
            <div className="space-y-1 border-t border-hairline-soft px-5 py-2">
              {[...preflight.errors, ...preflight.warnings].map((item) => (
                <div key={`${item.code}-${item.params?.node ?? "graph"}`} className={item.severity === "error" ? "flex items-start gap-2 text-[10px] text-danger" : "flex items-start gap-2 text-[10px] text-warn"}>
                  <span aria-hidden>{item.severity === "error" ? "!" : "•"}</span>
                  <span>{t(item.messageKey, item.params)}</span>
                </div>
              ))}
              {preflight.errors.length === 0 && preflight.warnings.length === 0 ? <span className="text-[10px] text-text-4">{t("flow_preflight_no_issues")}</span> : null}
            </div>
          ) : null}
        </section>
      ) : null}
      {mode === "canvas" ? (
        <WorkflowTemplateUpgradeNotice
          definitionId={definition?.id ?? null}
          onApplied={() => void loadAll(run?.id ?? null)}
        />
      ) : null}
      {mode === "canvas" ? (
        <header className="relative flex min-h-[72px] shrink-0 items-center justify-between gap-4 border-b border-hairline px-5 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex items-center gap-2 text-text">
            <Workflow aria-hidden className="h-4 w-4 text-accent-2" />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-[15px] font-semibold">{t("flow_title")}</h2>
                <span className={draftStatus === "dirty" ? "rounded border border-warn/50 px-1.5 py-0.5 text-[9px] font-semibold text-warn" : draftStatus === "saving" ? "rounded border border-accent-2/40 px-1.5 py-0.5 text-[9px] font-semibold text-accent-2" : "rounded border border-good/40 px-1.5 py-0.5 text-[9px] font-semibold text-good"}>
                  {draftStatus === "dirty" ? t("flow_draft_dirty") : draftStatus === "saving" ? t("flow_draft_saving") : t("flow_draft_saved")}
                </span>
              </div>
              <div className="mt-0.5 truncate text-[9px] text-text-4">
                {sourceTemplateId ? t("flow_source_template", { template: sourceTemplateId }) : t("flow_source_blank")}
              </div>
            </div>
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
          <button
            type="button"
            onClick={() => void saveAndExit()}
            disabled={!definition || loading || mutating || savingAndExiting || ["running", "paused", "waiting_review"].includes(run?.status ?? "")}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-accent-2/45 bg-accent-2/10 px-2.5 text-[11px] font-semibold text-accent-2 transition-colors hover:bg-accent-2/20 focus-ring disabled:opacity-40"
            title={t("flow_save_exit")}
            aria-label={t("flow_save_exit")}
          >
            <Save aria-hidden className="h-3.5 w-3.5" />
            <span>{savingAndExiting ? t("flow_saving_exit") : t("flow_save_exit")}</span>
          </button>
        </div>
        </header>
      ) : null}

      {displayError && mode === "canvas" ? (
        <div className="flex items-center gap-2 border-b border-danger/30 bg-danger/10 px-5 py-2 text-[11px] text-danger">
          <AlertTriangle aria-hidden className="h-3.5 w-3.5" />
          <span className="min-w-0 flex-1 truncate">{displayError}</span>
          <button type="button" onClick={() => setError(null)} aria-label={t("flow_close_error")} className="focus-ring">
            <X aria-hidden className="h-3 w-3" />
          </button>
        </div>
      ) : null}

      {revisionsOpen && definition ? (
        <div className="absolute right-4 top-24 z-40 flex max-h-[60vh] w-[380px] flex-col rounded-md border border-hairline bg-bg-raised shadow-lg">
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
      ) : mode === "canvas" ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <FlowCanvas
            onSaveReady={registerCanvasSave}
            onGraphChange={handleGraphChange}
            initialNodes={graphNodes}
            initialEdges={graphEdges}
            initialGroups={graphGroups}
            runStatus={runStatusMap}
            running={running}
            canRun={preflight.canRun}
            runDisabledReason={preflight.errors[0] ? t(preflight.errors[0].messageKey, preflight.errors[0].params) : undefined}
            defaultName={definition?.name ?? projectName}
            onSave={(nodes, edges, groups) => saveGraph(nodes, edges, groups)}
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
      ) : null}
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
