import { AlertTriangle, Check, ChevronRight, Circle, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { API } from "@/api";
import type { WorkflowReviewItem } from "@/types/workflow";

type ReviewDecision = "start" | "approve" | "reject" | "changes_requested";
type ReviewRecord = Record<string, unknown>;

type ReviewView = {
  id: string;
  name: string;
  description: string;
  templateType: string;
  status: string;
  revision: string;
  nodes: ReviewRecord[];
  edges: ReviewRecord[];
  riskTags: string[];
  history: ReviewRecord[];
  estimatedCost: number | null;
  staticValid: boolean;
};

function asRecord(value: unknown): ReviewRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as ReviewRecord) : {};
}

function asRecords(value: unknown): ReviewRecord[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== undefined && value !== null && value !== "");
}

function readText(...values: unknown[]): string {
  const value = firstValue(...values);
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function readNumber(...values: unknown[]): number | null {
  const value = firstValue(...values);
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function readTags(...values: unknown[]): string[] {
  const value = firstValue(...values);
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
  return typeof value === "string" && value.trim() ? [value] : [];
}

function toReviewView(item: WorkflowReviewItem): ReviewView {
  const raw = item as unknown as ReviewRecord;
  const template = asRecord(raw.template);
  const revision = asRecord(firstValue(raw.revision, raw.draft_revision, raw.latest_revision));
  const graph = asRecord(firstValue(revision.graph, raw.graph));
  const nodes = asRecords(firstValue(graph.nodes, revision.nodes, raw.nodes));
  const edges = asRecords(firstValue(graph.edges, revision.edges, raw.edges));
  const nodeKeys = new Set(nodes.map((node) => readText(node.node_key, node.key, node.id)).filter(Boolean));
  const contract = asRecord(firstValue(revision.contract, raw.contract));
  const serverValidation = asRecord(raw.static_validation);
  const computedStaticValid = nodes.length > 0 && edges.every((edge) => {
    const source = readText(edge.source_node_key, edge.source, edge.source_id);
    const target = readText(edge.target_node_key, edge.target, edge.target_id);
    return nodeKeys.has(source) && nodeKeys.has(target);
  });
  const staticValid = typeof serverValidation.valid === "boolean" ? serverValidation.valid : computedStaticValid;

  return {
    id: readText(raw.id, raw.template_id, template.id),
    name: readText(raw.name, raw.template_name, template.name) || "—",
    description: readText(raw.description, template.description),
    templateType: readText(raw.template_type, raw.content_mode, template.template_type, template.content_mode),
    status: readText(raw.status, revision.status, template.status) || "—",
    revision: readText(revision.version, revision.revision_number, raw.revision_version) || "—",
    nodes,
    edges,
    riskTags: readTags(raw.risk_tags, raw.risk_labels, raw.risk_tag, template.risk_tags),
    history: asRecords(firstValue(raw.review_history, raw.reviews, raw.review_records)),
    estimatedCost: readNumber(
      contract.estimated_episode_cost,
      contract.estimated_cost,
      revision.estimated_episode_cost,
      revision.estimated_cost,
      raw.estimated_episode_cost,
      raw.estimated_cost,
    ),
    staticValid,
  };
}

function nodeLabel(node: ReviewRecord, fallback: string): string {
  return readText(node.node_key, node.key, node.id, node.name) || fallback;
}

export function WorkflowTemplateReviewSection() {
  const { t } = useTranslation("dashboard");
  const [items, setItems] = useState<WorkflowReviewItem[]>([]);
  const [templateType, setTemplateType] = useState<"all" | "manga" | "short_drama">("all");
  const [riskTag, setRiskTag] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [decision, setDecision] = useState<ReviewDecision>("start");
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await API.listWorkflowReviewQueue({
        template_type: templateType === "all" ? undefined : templateType,
        risk_tag: riskTag.trim() || undefined,
      });
      setItems(response.items);
    } catch {
      setError(t("workflow_admin_load_error"));
    } finally {
      setLoading(false);
    }
  }, [riskTag, t, templateType]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadQueue();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadQueue]);

  const views = useMemo(() => items.map(toReviewView), [items]);
  const selected = views.find((view) => view.id === selectedId) ?? views[0] ?? null;

  const submitReview = async () => {
    if (!selected || !comment.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await API.reviewWorkflowTemplate(selected.id, { decision, comment: comment.trim() });
      setComment("");
      await loadQueue();
    } catch {
      setError(t("workflow_admin_submit_error"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="min-h-full px-8 py-8" aria-labelledby="workflow-admin-title">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-start justify-between gap-5 border-b border-hairline-soft pb-6">
          <div>
            <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-accent">{t("workflow_admin_kicker")}</p>
            <h1 id="workflow-admin-title" className="mt-2 text-[28px] font-semibold tracking-[-0.02em] text-text">{t("workflow_admin_title")}</h1>
            <p className="mt-2 max-w-2xl text-[13px] leading-6 text-text-3">{t("workflow_admin_subtitle")}</p>
          </div>
          <button type="button" className="inline-flex items-center gap-2 rounded-[8px] border border-hairline-soft px-3 py-2 text-[12px] font-medium text-text transition-colors hover:border-accent/50 hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-50" onClick={() => void loadQueue()} disabled={loading || submitting}>
            <RefreshCw className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} aria-hidden="true" />
            {t("workflow_admin_refresh")}
          </button>
        </div>

        <div className="mt-6 flex flex-wrap items-end gap-4 rounded-[10px] border border-hairline-soft bg-shell-2 p-4">
          <label className="flex min-w-[180px] flex-col gap-1.5 text-[12px] text-text-2">
            <span className="font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-text-4">{t("workflow_admin_template_type")}</span>
            <select className="rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 text-[12px] text-text outline-none focus:border-accent" value={templateType} onChange={(event) => setTemplateType(event.target.value as typeof templateType)}>
              <option value="all">{t("workflow_admin_all_types")}</option>
              <option value="manga">{t("workflow_admin_type_manga")}</option>
              <option value="short_drama">{t("workflow_admin_type_short_drama")}</option>
            </select>
          </label>
          <label className="flex min-w-[240px] flex-1 flex-col gap-1.5 text-[12px] text-text-2">
            <span className="font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-text-4">{t("workflow_admin_risk_label")}</span>
            <input className="rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 text-[12px] text-text outline-none placeholder:text-text-4 focus:border-accent" value={riskTag} onChange={(event) => setRiskTag(event.target.value)} placeholder={t("workflow_admin_risk_placeholder")} />
          </label>
        </div>

        {error ? <div className="mt-5 flex items-start gap-2 rounded-[8px] border border-warm/35 bg-warm-tint px-4 py-3 text-[12px] text-warm-bright" role="alert"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{error}</div> : null}

        {loading ? (
          <div className="mt-8 flex items-center gap-2 text-[12px] text-text-3" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />{t("workflow_admin_loading")}</div>
        ) : views.length === 0 ? (
          <div className="mt-8 rounded-[10px] border border-dashed border-hairline-soft px-6 py-12 text-center text-[12px] text-text-3">{t("workflow_admin_empty")}</div>
        ) : (
          <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(360px,1.05fr)]">
            <div className="space-y-2.5" aria-label={t("workflow_admin_queue")}>
              {views.map((view) => {
                const isSelected = selected?.id === view.id;
                const cardClass = "group w-full rounded-[9px] border p-4 text-left transition-colors " + (isSelected ? "border-accent/50 bg-accent-dim" : "border-hairline-soft bg-shell-2 hover:border-accent/35");
                return <button key={view.id} type="button" onClick={() => setSelectedId(view.id)} className={cardClass}>
                  <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h2 className="truncate text-[13px] font-semibold text-text">{view.name}</h2><p className="mt-1 text-[11px] text-text-4">{view.templateType || "—"} · {view.status} · {t("workflow_admin_revision")} {view.revision}</p></div><ChevronRight className="h-4 w-4 shrink-0 text-text-4" aria-hidden="true" /></div>
                  <div className="mt-4 grid grid-cols-2 gap-2 text-[11px] text-text-3 sm:grid-cols-4"><span>{t("workflow_admin_nodes")}: {view.nodes.length}</span><span>{t("workflow_admin_edges")}: {view.edges.length}</span><span>{t("workflow_admin_expected_cost")}: {view.estimatedCost === null ? t("workflow_admin_not_provided") : view.estimatedCost.toFixed(2)}</span><span className={view.staticValid ? "text-accent" : "text-warm-bright"}>{view.staticValid ? t("workflow_admin_static_pass") : t("workflow_admin_static_fail")}</span></div>
                </button>;
              })}
            </div>

            {selected ? <article className="rounded-[10px] border border-hairline-soft bg-shell-2 p-5">
              <div className="flex items-start gap-3 border-b border-hairline-soft pb-4"><div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[7px] bg-accent-dim text-accent"><ShieldCheck className="h-4 w-4" aria-hidden="true" /></div><div className="min-w-0"><h2 className="truncate text-[16px] font-semibold text-text">{selected.name}</h2>{selected.description ? <p className="mt-1 text-[12px] leading-5 text-text-3">{selected.description}</p> : null}</div></div>
              <div className="mt-5 grid grid-cols-2 gap-2.5 sm:grid-cols-4"><div className="rounded-[7px] bg-shell px-3 py-2.5"><span className="text-[10px] text-text-4">{t("workflow_admin_nodes")}</span><div className="mt-1 text-[15px] font-semibold text-text">{selected.nodes.length}</div></div><div className="rounded-[7px] bg-shell px-3 py-2.5"><span className="text-[10px] text-text-4">{t("workflow_admin_edges")}</span><div className="mt-1 text-[15px] font-semibold text-text">{selected.edges.length}</div></div><div className="rounded-[7px] bg-shell px-3 py-2.5"><span className="text-[10px] text-text-4">{t("workflow_admin_expected_cost")}</span><div className="mt-1 text-[15px] font-semibold text-text">{selected.estimatedCost === null ? t("workflow_admin_not_provided") : selected.estimatedCost.toFixed(2)}</div></div><div className="rounded-[7px] bg-shell px-3 py-2.5"><span className="text-[10px] text-text-4">{t("workflow_admin_static_validation")}</span><div className={"mt-1 flex items-center gap-1 text-[12px] font-semibold " + (selected.staticValid ? "text-accent" : "text-warm-bright")}><Check className="h-3.5 w-3.5" aria-hidden="true" />{selected.staticValid ? t("workflow_admin_static_pass") : t("workflow_admin_static_fail")}</div></div></div>
              <div className="mt-5"><h3 className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-4">{t("workflow_admin_dependencies")}</h3><div className="mt-2 max-h-32 overflow-auto rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 text-[11px] text-text-3">{selected.nodes.length ? selected.nodes.map((node, index) => <div key={nodeLabel(node, String(index))} className="flex items-center gap-2 py-1"><Circle className="h-2 w-2 shrink-0 text-accent" aria-hidden="true" />{nodeLabel(node, t("workflow_admin_not_provided"))}</div>) : t("workflow_admin_not_provided")}</div></div>
              {selected.riskTags.length ? <div className="mt-4 flex flex-wrap gap-1.5">{selected.riskTags.map((tag) => <span key={tag} className="rounded-full border border-warm/25 bg-warm-tint px-2 py-1 font-mono text-[10px] text-warm-bright">{tag}</span>)}</div> : null}
              {selected.history.length ? <div className="mt-5 border-t border-hairline-soft pt-4"><h3 className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-4">{t("workflow_admin_history")}</h3><div className="mt-2 space-y-1.5">{selected.history.map((record, index) => <div key={readText(record.id) || String(index)} className="rounded-[7px] bg-shell px-3 py-2 text-[11px] text-text-3">{readText(record.decision, record.action, record.status) || t("workflow_admin_not_provided")}{readText(record.comment) ? " · " + readText(record.comment) : ""}</div>)}</div></div> : null}
              <div className="mt-5 border-t border-hairline-soft pt-4"><h3 className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-4">{t("workflow_admin_decision")}</h3><div className="mt-3 space-y-3"><select data-testid="workflow-review-decision" aria-label={t("workflow_admin_decision")} className="w-full rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 text-[12px] text-text outline-none focus:border-accent" value={decision} onChange={(event) => setDecision(event.target.value as ReviewDecision)} disabled={submitting}><option value="start">{t("workflow_admin_start_review")}</option><option value="approve">{t("workflow_admin_approve")}</option><option value="changes_requested">{t("workflow_admin_request_changes")}</option><option value="reject">{t("workflow_admin_reject")}</option></select><textarea data-testid="workflow-review-comment" aria-label={t("workflow_admin_comment")} className="min-h-24 w-full resize-y rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 text-[12px] text-text outline-none placeholder:text-text-4 focus:border-accent" value={comment} onChange={(event) => setComment(event.target.value)} placeholder={t("workflow_admin_comment_placeholder")} disabled={submitting} /><button data-testid="workflow-review-submit" type="button" className="inline-flex w-full items-center justify-center gap-2 rounded-[7px] bg-accent px-3 py-2 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50" onClick={() => void submitReview()} disabled={submitting || !comment.trim()}>{submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}{submitting ? t("workflow_admin_submitting") : t("workflow_admin_submit")}</button></div></div>
            </article> : null}
          </div>
        )}
      </div>
    </section>
  );
}
