import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, Clock3, DollarSign, FileText, Layers3, Loader2, Search, ShieldCheck, Sparkles, WandSparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { API } from "@/api";

type Skill = { id: string; versionId: string; workflowRevisionId: string; version: string; title: string; summary: string; category: "story" | "video" | "asset"; modes: string[]; inputs: string[]; outputs: string[]; costHint: string | null; review: boolean; compatible: boolean };
type Resource = { id: string; label: string; type: string; source: string; selectionKey: string };
const asList = (value: unknown) => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
function normalize(row: Record<string, unknown>): Skill | null {
  if (typeof row.id !== "string" || typeof row.title !== "string" || typeof row.summary !== "string") return null;
  const compatibility = typeof row.compatibility === "object" && row.compatibility !== null ? row.compatibility as Record<string, unknown> : {};
  const categoryValue = typeof row.category === "string" ? row.category : "";
  const category = ["剧集", "解说", "广告"].includes(categoryValue) ? "story" : categoryValue === "视频" ? "video" : "asset";
  const versionId = typeof row.version_id === "string"
    ? row.version_id
    : typeof row.version === "number" || typeof row.version === "string"
      ? row.id + ":v" + row.version
      : row.id + ":v1";
  return { id: row.id, versionId, workflowRevisionId: typeof row.workflow_revision_id === "string" ? row.workflow_revision_id : "", version: typeof row.version === "number" ? "v" + row.version : typeof row.version === "string" ? row.version : "", title: row.title, summary: row.summary, category, modes: asList(compatibility.supported_generation_modes), inputs: asList(row.inputs), outputs: asList(row.outputs), costHint: typeof row.estimated_cost_hint === "string" ? row.estimated_cost_hint : null, review: row.review_required === true, compatible: compatibility.compatible !== false };
}

export function CreationSkillsPage({ projectName }: { projectName: string }) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [, navigate] = useLocation();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [category, setCategory] = useState<"all" | Skill["category"]>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Skill | null>(null);
  const [preview, setPreview] = useState<{ id?: string; cost: number; outputs: string[]; modes: string[] } | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [resourceIds, setResourceIds] = useState<string[]>([]);
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [resourceLoading, setResourceLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState(false);
 const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<{ id: string; version: string; title: string; status: string; frozenAt: string }>>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await API.listCreationSkills(projectName);
      setSkills(response.items.map(normalize).filter((skill): skill is Skill => skill !== null));
    } catch (error) {
      setSkills([]);
      setLoadError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, [projectName]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- load the remote official catalog when the page mounts
  useEffect(() => { void load(); }, [load]);
  const visible = useMemo(() => skills.filter((skill) => skill.compatible && (category === "all" || skill.category === category) && (!query.trim() || (skill.title + skill.summary).toLowerCase().includes(query.trim().toLowerCase()))), [category, query, skills]);
  const prepare = async (skill: Skill) => {
    setSelected(skill); setPreview(null); setStarted(false); setActionError(null); setResourceIds([]); setParameters({}); setResourceLoading(true);
    try {
      const [projectResources, mediaResources] = await Promise.all([
        API.listCreationResources(projectName),
        API.listMediaAssets(projectName),
      ]);
      const projectItems = Array.isArray(projectResources.items) ? projectResources.items : [];
      const mediaItems = Array.isArray(mediaResources.items) ? mediaResources.items : [];
      const normalizeResource = (item: Record<string, unknown>, fallbackType: string, fallbackSource: string): Resource | null => {
        if (typeof item.id !== "string" || !item.id.trim()) return null;
        const type = typeof item.type === "string" ? item.type : typeof item.media_type === "string" ? item.media_type : fallbackType; const source = typeof item.source === "string" ? item.source : fallbackSource; return { id: item.id, label: typeof item.label === "string" ? item.label : typeof item.name === "string" ? item.name : item.id, type, source, selectionKey: source + ":" + type + ":" + item.id };
      };
      const merged = [...projectItems.map((item) => normalizeResource(item, "project_entity", "project_entity")), ...mediaItems.map((item) => normalizeResource(item, "media_asset", "media_asset"))].filter((item): item is Resource => item !== null);
      setResources(Array.from(new Map(merged.map((item) => [item.selectionKey, item])).values()));
    } catch (error) { setResources([]); setActionError(error instanceof Error ? error.message : String(error)); }
    finally { setResourceLoading(false); }
  };
  const showHistory = async () => {
    if (!selected) return;
    setHistoryLoading(true);
    setActionError(null);
    try {
      const response = await API.listCreationSkillVersions(selected.id);
      const items = Array.isArray(response.items) ? response.items : [];
      setHistory(items.map((item) => ({
        id: typeof item.id === "string" ? item.id : "",
        version: typeof item.version === "string" ? item.version : "",
        title: typeof item.title === "string" ? item.title : "",
        status: typeof item.status === "string" ? item.status : "",
        frozenAt: typeof item.frozen_at === "string" ? item.frozen_at : "",
      })).filter((item) => item.id));
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setHistoryLoading(false);
    }
  };

  const createPreview = async () => {
    if (!selected) return;
    if (!resourceIds.length || !selected.workflowRevisionId) { setActionError(t("creation_skills_empty")); return; }
    const selectedResources = resources.filter((item) => resourceIds.includes(item.selectionKey));
    setBusy(true);
    try {
      const response = await API.previewCreationPlan(projectName, {
        workspace_id: "default",
        creation_skill_version_id: selected.versionId,
        resource_ids: selectedResources.map((item) => item.id),
        resource_types: Array.from(new Set(selectedResources.map((item) => item.type))),
        resource_mapping: selectedResources.map((item) => ({ id: item.id, type: item.type, source: item.source })),
        parameters,
        workflow_revision: selected.workflowRevisionId,
        estimated_cost: undefined,
        steps: undefined,
        review_points: undefined,
        idempotency_key: projectName + ":" + selected.versionId + ":" + resourceIds.slice().sort().join(",") + ":" + JSON.stringify(parameters),
      });
      const report = response.compatibility_report as { compatible?: boolean } | undefined;
      if (!report?.compatible || typeof response.plan_id !== "string") throw new Error(t("creation_skills_empty"));
      setPreview({ id: response.plan_id, cost: typeof response.estimated_cost === "number" ? response.estimated_cost : 0, outputs: Array.isArray(response.steps) ? response.steps.filter((item): item is string => typeof item === "string") : selected.outputs, modes: selected.modes });
    } catch (error: unknown) { setPreview(null); setActionError(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const start = async () => {
    if (!preview) return;
    setActionError(null);
    if (preview.id) {
      try {
        const response = await API.startCreationPlan(preview.id);
        if (typeof response.workflow_run_id !== "string") throw new Error(t("creation_skills_empty"));
      } catch (error: unknown) {
        setActionError(error instanceof Error ? error.message : String(error));
        return;
      }
    }
    setStarted(true);
  };
  return <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--color-shell)] text-[var(--color-text)]">
    {actionError ? <div role="alert" aria-live="polite" className="mx-auto mb-3 w-full max-w-[1320px] rounded-md border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 px-6 py-2 text-[11px] text-[var(--color-danger)]">{t("creation_skills_action_error", { message: actionError })}</div> : null}
    <header className="border-b border-[var(--color-hairline-soft)] bg-[var(--panel-card-bg)] px-6 py-5"><div className="mx-auto flex max-w-[1320px] items-start justify-between gap-5"><div><div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--color-accent-2)]"><Sparkles className="h-3.5 w-3.5" aria-hidden />{t("creation_skills_eyebrow")}</div><h1 className="display-serif text-[28px] font-semibold">{t("creation_skills_title")}</h1><p className="mt-2 max-w-2xl text-[13px] text-[var(--color-text-3)]">{t("creation_skills_subtitle")}</p></div><button type="button" onClick={() => navigate("/flow?advanced=1")} className="focus-ring inline-flex items-center gap-2 rounded-md border border-[var(--color-hairline)] px-3 py-2 text-[12px]"><ArrowRight className="h-3.5 w-3.5" aria-hidden />{t("creation_skills_open_advanced_flow")}</button><button type="button" onClick={() => navigate("/creative-board")} className="focus-ring inline-flex items-center gap-2 rounded-md border border-[var(--color-hairline)] px-3 py-2 text-[12px]"><Layers3 className="h-3.5 w-3.5" aria-hidden />{t("creation_skills_open_board")}</button></div></header>
    <div className="mx-auto flex min-h-0 w-full max-w-[1320px] flex-1 gap-5 overflow-hidden px-6 py-5"><main className="min-w-0 flex-1 overflow-y-auto"><div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap gap-1.5">{(["all", "story", "video", "asset"] as const).map((item) => <button key={item} type="button" aria-pressed={category === item} onClick={() => setCategory(item)} className="rounded-full border border-[var(--color-hairline)] px-3 py-1.5 text-[11px]">{t("creation_skills_category_" + item)}</button>)}</div><label className="flex h-8 w-60 items-center gap-2 rounded-md border border-[var(--color-hairline)] px-2.5"><Search className="h-3.5 w-3.5" aria-hidden /><span className="sr-only">{t("creation_skills_search")}</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("creation_skills_search")} className="min-w-0 flex-1 bg-transparent text-[12px] outline-none" /></label></div>{loading ? <div className="flex items-center gap-2 py-10 text-[12px]"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />{t("creation_skills_loading")}</div> : null}{loadError ? <div role="alert" className="mb-4 rounded-md border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 px-3 py-2 text-[11px] text-[var(--color-danger)]">{t("creation_skills_load_error", { message: loadError })}</div> : null}{!loading && !loadError && visible.length === 0 ? <div className="rounded-md border border-dashed border-[var(--color-hairline)] px-4 py-8 text-center text-[12px] text-[var(--color-text-3)]">{t("creation_skills_empty")}</div> : null}<div className="grid grid-cols-1 gap-3 xl:grid-cols-2">{visible.map((skill) => <article key={skill.id} className="rounded-lg border border-[var(--color-hairline-soft)] bg-[var(--panel-card-bg)] p-4"><div className="flex items-start gap-3"><div className="rounded-md bg-[var(--color-accent-2)]/10 p-2 text-[var(--color-accent-2)]"><WandSparkles className="h-4 w-4" aria-hidden /></div><div className="min-w-0 flex-1"><h2 className="text-[14px] font-semibold">{skill.title}</h2><p className="mt-1 text-[11px] leading-relaxed">{skill.summary}</p></div><span className="rounded-full bg-[var(--color-good)]/10 px-2 py-1 text-[9px] text-[var(--color-good)]">{t("creation_skills_official")}</span></div><div className="mt-4 flex flex-wrap gap-4 text-[10px]"><span className="inline-flex items-center gap-1"><DollarSign className="h-3 w-3" aria-hidden />{t("creation_skills_cost", { value: skill.costHint ?? "—" })}</span><span className="inline-flex items-center gap-1"><FileText className="h-3 w-3" aria-hidden />{t("creation_skills_inputs_count", { count: skill.inputs.length })}</span>{skill.review ? <span className="inline-flex items-center gap-1 text-[var(--color-warn)]"><ShieldCheck className="h-3 w-3" aria-hidden />{t("creation_skills_review_required")}</span> : null}</div><div className="mt-4 flex items-center justify-between border-t border-[var(--color-hairline-soft)] pt-3"><span className="font-mono text-[10px]">{skill.version}</span><button type="button" onClick={() => void prepare(skill)} className="focus-ring inline-flex items-center gap-1 rounded-md bg-[var(--color-accent)] px-3 py-1.5 text-[11px] font-semibold">{t("creation_skills_prepare")}<ArrowRight className="h-3 w-3" aria-hidden /></button></div></article>)}</div></main>
      <aside className="hidden w-[330px] shrink-0 overflow-y-auto rounded-lg border border-[var(--color-hairline-soft)] bg-[var(--panel-card-bg)] p-4 lg:block">{selected ? <><div className="flex items-start justify-between"><div><div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-accent-2)]">{t("creation_skills_prepare_eyebrow")}</div><h2 className="mt-1 text-[18px] font-semibold">{selected.title}</h2></div><button type="button" onClick={() => setSelected(null)} className="text-[11px]">{t("common:cancel")}</button></div><p className="mt-3 text-[12px] leading-relaxed">{selected.summary}</p><div className="mt-4 flex items-center gap-2"><button type="button" onClick={() => void showHistory()} disabled={historyLoading} className="focus-ring rounded-md border border-[var(--color-hairline)] px-2.5 py-1.5 text-[10px]">{historyLoading ? t("creation_skills_history_loading") : t("creation_skills_history")}</button>{history.length ? <span className="text-[10px] text-[var(--color-text-3)]">{t("creation_skills_history_title")}: {history.map((item) => item.version).join(", ")}</span> : null}</div><h3 className="mt-5 text-[11px] font-semibold">{t("creation_skills_inputs")}</h3><div className="mt-2 flex flex-wrap gap-1.5">{selected.inputs.map((item) => <span key={item} className="rounded bg-[var(--color-shell-field)] px-2 py-1 text-[10px]">{item}</span>)}</div><h3 className="mt-4 text-[11px] font-semibold">{t("creation_skills_inputs")}</h3>{resourceLoading ? <div className="mt-2 text-[10px]">{t("creation_skills_loading")}</div> : <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">{resources.length ? resources.map((item) => <label key={item.selectionKey} className="flex items-center gap-2 text-[10px]"><input type="checkbox" checked={resourceIds.includes(item.selectionKey)} onChange={() => setResourceIds((current) => current.includes(item.selectionKey) ? current.filter((id) => id !== item.selectionKey) : [...current, item.selectionKey])} /><span className="truncate">{item.label}</span><span className="ml-auto text-[9px] text-[var(--color-text-3)]">{item.type}</span></label>) : <div className="text-[10px] text-[var(--color-text-3)]">{t("creation_skills_empty")}</div>}</div>}<h3 className="mt-4 text-[11px] font-semibold">{t("creation_plan_duration")}</h3><input aria-label={t("creation_plan_duration")} type="number" min="1" max="120" value={typeof parameters.duration === "number" ? parameters.duration : ""} onChange={(event) => { const value = Number(event.target.value); setParameters(value > 0 ? { duration: value } : {}); }} className="mt-2 w-full rounded border border-[var(--color-hairline)] bg-transparent px-2 py-1.5 text-[11px]" /><h3 className="mt-4 text-[11px] font-semibold">{t("creation_skills_outputs")}</h3><div className="mt-2 flex flex-wrap gap-1.5">{selected.outputs.map((item) => <span key={item} className="rounded bg-[var(--color-shell-field)] px-2 py-1 text-[10px]">{item}</span>)}</div><div className="mt-5 rounded-md border border-[var(--color-warn)]/30 bg-[var(--color-warn)]/5 p-3 text-[11px] leading-relaxed"><ShieldCheck className="mb-1 h-4 w-4" aria-hidden />{t("creation_skills_generation_lock")}</div>{preview ? <div className="mt-5 rounded-lg border border-[var(--color-accent-2)]/30 p-3"><div className="flex items-center gap-2 text-[12px] font-semibold"><Check className="h-4 w-4" aria-hidden />{t("creation_plan_ready")}</div><div className="mt-3 space-y-2 text-[11px]"><div className="flex justify-between"><span>{t("creation_plan_cost")}</span><b>{preview.cost}</b></div><div className="flex justify-between"><span>{t("creation_plan_route_snapshot")}</span><b>{preview.modes.join(" / ")}</b></div>{preview.outputs.map((item, index) => <div key={item} className="flex gap-2"><span className="font-mono text-[9px]">0{index + 1}</span>{item}</div>)}<p className="border-t border-[var(--color-hairline-soft)] pt-2 text-[10px]">{t("creation_plan_compatible")}</p></div>{started ? <div className="mt-3 rounded bg-[var(--color-good)]/10 px-2.5 py-2 text-[10px]">{t("creation_plan_started")}</div> : <button type="button" onClick={() => void start()} disabled={busy} className="focus-ring mt-4 w-full rounded-md bg-[var(--color-accent)] px-3 py-2 text-[11px] font-semibold">{t("creation_plan_start")}</button>}</div> : <button type="button" onClick={() => void createPreview()} disabled={busy || resourceLoading || !resourceIds.length} className="focus-ring mt-5 flex w-full items-center justify-center gap-2 rounded-md bg-[var(--color-accent)] px-3 py-2.5 text-[12px] font-semibold">{busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Clock3 className="h-4 w-4" aria-hidden />}{busy ? t("creation_plan_generating") : t("creation_plan_preview")}</button>}</> : <div className="flex min-h-[300px] flex-col items-center justify-center text-center"><Sparkles className="h-7 w-7" aria-hidden /><h2 className="mt-3 text-[13px] font-semibold">{t("creation_skills_select_title")}</h2><p className="mt-1 text-[11px] leading-relaxed">{t("creation_skills_select_hint")}</p></div>}</aside></div>
    </div>
}
