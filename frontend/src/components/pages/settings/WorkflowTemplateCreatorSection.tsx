import { AlertTriangle, CheckCircle2, Loader2, UploadCloud } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { API } from "@/api";
import type { WorkflowEdgeInput, WorkflowNodeInput } from "@/types/workflow";

type TemplateType = "manga" | "short_drama";

const emptyGraph = {
  nodes: [],
  edges: [],
};

type ReviewRecord = { id: string; decision?: string; comment?: string };
type CreatedTemplate = {
  id: string;
  status: string;
  name?: string;
  description?: string;
  template_type?: TemplateType;
  contract?: Record<string, unknown>;
  reviews?: ReviewRecord[];
};

export function WorkflowTemplateCreatorSection() {
  const { t } = useTranslation("dashboard");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateType, setTemplateType] = useState<TemplateType>("manga");
  const [contractText, setContractText] = useState(JSON.stringify(emptyGraph, null, 2));
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<CreatedTemplate | null>(null);
  const [templates, setTemplates] = useState<CreatedTemplate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selected = useMemo(
    () => templates.find((template) => template.id === selectedId) ?? null,
    [selectedId, templates],
  );
  const activeStatus = selected?.status ?? created?.status;
  const editable = !activeStatus || activeStatus === "draft" || activeStatus === "rejected";

  const loadTemplates = async () => {
    setLoading(true);
    try {
      const result = await API.listWorkflowCreatorTemplates();
      const items = result.items as CreatedTemplate[];
      setTemplates(items);
      if (selectedId) {
        const current = items.find((template) => template.id === selectedId);
        if (current) setCreated({ id: current.id, status: current.status });
      }
    } catch {
      setError(t("workflow_creator_load_error"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    void API.listWorkflowCreatorTemplates()
      .then((result) => {
        if (!cancelled) setTemplates(result.items as CreatedTemplate[]);
      })
      .catch(() => {
        if (!cancelled) setError(t("workflow_creator_load_error"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const selectTemplate = (template: CreatedTemplate) => {
    setSelectedId(template.id);
    setCreated({ id: template.id, status: template.status });
    setName(template.name ?? "");
    setDescription(template.description ?? "");
    setTemplateType(template.template_type === "short_drama" ? "short_drama" : "manga");
    setContractText(JSON.stringify(template.contract ?? emptyGraph, null, 2));
    setError(null);
    setNotice(null);
  };

  const createDraft = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const contract = JSON.parse(contractText) as Record<string, unknown>;
      const nodes = Array.isArray(contract.nodes) ? (contract.nodes as WorkflowNodeInput[]) : [];
      const edges = Array.isArray(contract.edges) ? (contract.edges as WorkflowEdgeInput[]) : [];
      const template = selectedId
        ? await API.updateWorkflowTemplateDraft(selectedId, {
            name: name.trim(),
            description: description.trim(),
            template_type: templateType,
            contract,
            nodes: nodes as unknown as Array<Record<string, unknown>>,
            edges: edges as unknown as Array<Record<string, unknown>>,
            content_mode: "drama",
            generation_mode: "storyboard",
          })
        : await API.createWorkflowTemplateDraft({
            name: name.trim(),
            description: description.trim(),
            template_type: templateType,
            contract,
            nodes,
            edges,
          });
      const templateId = template.id;
      const templateStatus = template.status;
      if (!templateId || !templateStatus) {
        throw new Error("workflow_template_id_missing");
      }
      setCreated({ id: templateId, status: templateStatus });
      setSelectedId(templateId);
      setNotice(t("workflow_creator_saved"));
      await loadTemplates();
    } catch (cause) {
      setError(cause instanceof SyntaxError ? t("workflow_creator_invalid_json") : t("workflow_creator_create_error"));
    } finally {
      setBusy(false);
    }
  };

  const submitDraft = async () => {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const submitted = await API.submitWorkflowTemplate(selectedId);
      setCreated({ id: selectedId, status: submitted.status });
      setTemplates((current) => current.map((template) => (template.id === selectedId ? { ...template, status: submitted.status } : template)));
      setNotice(t("workflow_creator_submitted"));
    } catch {
      setError(t("workflow_creator_submit_error"));
    } finally {
      setBusy(false);
    }
  };

  const withdrawDraft = async () => {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const withdrawn = await API.withdrawWorkflowTemplate(selectedId);
      setCreated({ id: selectedId, status: withdrawn.status });
      setTemplates((current) => current.map((template) => (template.id === selectedId ? { ...template, status: withdrawn.status } : template)));
      setNotice(t("workflow_creator_withdrawn"));
    } catch {
      setError(t("workflow_creator_withdraw_error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="min-h-full px-8 py-8" aria-labelledby="workflow-creator-title">
      <div className="mx-auto max-w-4xl">
        <div className="border-b border-hairline-soft pb-6">
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-accent">{t("workflow_creator_kicker")}</p>
          <h1 id="workflow-creator-title" className="mt-2 text-[28px] font-semibold tracking-[-0.02em] text-text">{t("workflow_creator_title")}</h1>
          <p className="mt-2 max-w-2xl text-[13px] leading-6 text-text-3">{t("workflow_creator_subtitle")}</p>
        </div>

        {error ? <div className="mt-5 flex items-start gap-2 rounded-[8px] border border-warm/35 bg-warm-tint px-4 py-3 text-[12px] text-warm-bright" role="alert"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{error}</div> : null}
        {created ? <div className="mt-5 flex items-center gap-2 rounded-[8px] border border-accent/35 bg-accent-dim px-4 py-3 text-[12px] text-text" role="status"><CheckCircle2 className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />{notice ?? t("workflow_creator_created", { status: created.status })}</div> : null}

        <div className="mt-6 space-y-4 rounded-[10px] border border-hairline-soft bg-shell-2 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3"><span className="font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-text-4">{t("workflow_creator_drafts")}</span><div className="flex gap-2"><button type="button" className="rounded-[7px] border border-accent/50 px-3 py-2 text-[12px] text-text" onClick={() => { setSelectedId(null); setCreated(null); setName(""); setDescription(""); setTemplateType("manga"); setContractText(JSON.stringify(emptyGraph, null, 2)); }}>{t("workflow_creator_new")}</button><button type="button" className="rounded-[7px] border border-hairline-soft px-3 py-2 text-[12px] text-text" onClick={() => void loadTemplates()} disabled={loading || busy}>{t("workflow_creator_refresh")}</button></div></div>
          {loading ? <p className="text-[12px] text-text-4">{t("workflow_creator_loading")}</p> : null}
          {templates.length ? <div className="grid gap-2 sm:grid-cols-2">{templates.map((template) => <button key={template.id} type="button" className="rounded-[7px] border border-hairline-soft px-3 py-2 text-left" onClick={() => selectTemplate(template)}><span className="block truncate text-[12px] text-text">{template.name ?? template.id}</span><span className="mt-1 block text-[10px] uppercase tracking-[0.1em] text-text-4">{template.status}</span></button>)}</div> : null}
          <label className="block text-[12px] text-text-2"><span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-text-4">{t("workflow_creator_name")}</span><input data-testid="workflow-creator-name" className="w-full rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 text-text outline-none focus:border-accent disabled:opacity-50" value={name} onChange={(event) => setName(event.target.value)} disabled={!editable || busy} /></label>
          <label className="block text-[12px] text-text-2"><span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-text-4">{t("workflow_creator_description")}</span><textarea className="min-h-20 w-full rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 text-text outline-none focus:border-accent disabled:opacity-50" value={description} onChange={(event) => setDescription(event.target.value)} disabled={!editable || busy} /></label>
          <label className="block text-[12px] text-text-2"><span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-text-4">{t("workflow_creator_type")}</span><select className="w-full rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 text-text outline-none focus:border-accent disabled:opacity-50" value={templateType} onChange={(event) => setTemplateType(event.target.value as TemplateType)} disabled={!editable || busy}><option value="manga">{t("workflow_admin_type_manga")}</option><option value="short_drama">{t("workflow_admin_type_short_drama")}</option></select></label>
          <label className="block text-[12px] text-text-2"><span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-text-4">{t("workflow_creator_contract")}</span><textarea data-testid="workflow-creator-contract" className="min-h-64 w-full rounded-[7px] border border-hairline-soft bg-shell px-3 py-2 font-mono text-[11px] text-text outline-none focus:border-accent disabled:opacity-50" value={contractText} onChange={(event) => setContractText(event.target.value)} disabled={!editable || busy} spellCheck={false} /></label>
          <div className="flex flex-wrap gap-2">
            <button data-testid="workflow-creator-save" type="button" className="inline-flex items-center gap-2 rounded-[7px] bg-accent px-3 py-2 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50" onClick={() => void createDraft()} disabled={busy || !editable || !name.trim()}>{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <UploadCloud className="h-3.5 w-3.5" aria-hidden="true" />}{busy ? t("workflow_creator_working") : t("workflow_creator_save")}</button>
            <button data-testid="workflow-creator-submit" type="button" className="inline-flex items-center gap-2 rounded-[7px] border border-hairline-soft px-3 py-2 text-[12px] font-semibold text-text transition-colors hover:border-accent/50 hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-50" onClick={() => void submitDraft()} disabled={busy || !selectedId || activeStatus !== "draft"}>{t("workflow_creator_submit")}</button>
            <button data-testid="workflow-creator-withdraw" type="button" className="inline-flex items-center gap-2 rounded-[7px] border border-hairline-soft px-3 py-2 text-[12px] font-semibold text-text transition-colors hover:border-accent/50 hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-50" onClick={() => void withdrawDraft()} disabled={busy || !selectedId || !["submitted", "under_review"].includes(activeStatus ?? "")}>{t("workflow_creator_withdraw")}</button>
          </div>
          {selected?.reviews?.length ? <div className="rounded-[8px] border border-hairline-soft p-3"><p className="font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-text-4">{t("workflow_creator_reviews")}</p><div className="mt-2 space-y-2">{selected.reviews.map((review) => <p key={review.id} className="text-[12px] text-text-3"><span className="font-medium text-text">{review.decision}</span>{review.comment ? " — " + review.comment : ""}</p>)}</div></div> : null}
          {!editable && selected ? <p className="text-[11px] text-text-4">{t("workflow_creator_not_editable")}</p> : null}
        </div>
      </div>
    </section>
  );
}
