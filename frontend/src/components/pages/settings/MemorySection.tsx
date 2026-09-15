import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Download, Loader2, Pencil, Plus, Save, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import type { MemoryCandidate, MemoryCategory, MemoryEntry } from "@/types/memory";
import { ACCENT_BTN_CLS, CARD_STYLE, GHOST_BTN_CLS, INPUT_CLS } from "@/components/ui/darkroom-tokens";

const CATEGORIES: MemoryCategory[] = ["preference", "style", "world", "terminology", "workflow", "other"];

type Draft = { category: MemoryCategory; content: string };

function emptyDraft(): Draft {
  return { category: "preference", content: "" };
}

function formatMemoryDate(value: string, locale: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale);
}

export function MemorySection() {
  const { t, i18n } = useTranslation("dashboard");
  const [userMemories, setUserMemories] = useState<MemoryEntry[]>([]);
  const [projectMemories, setProjectMemories] = useState<MemoryEntry[]>([]);
  const [candidates, setCandidates] = useState<MemoryCandidate[]>([]);
  const [projects, setProjects] = useState<Array<{ name: string; title?: string }>>([]);
  const [selectedProject, setSelectedProject] = useState("");
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [users, pending, projectList] = await Promise.all([
        API.listUserMemories(),
        API.listMemoryCandidates(),
        API.listProjects(),
      ]);
      setUserMemories(users.items);
      setCandidates(pending.items.filter((item) => item.status === "pending"));
      const normalized = projectList.projects.map((project) => ({ name: project.name, title: project.title }));
      setProjects(normalized);
      const project = selectedProject && normalized.some((item) => item.name === selectedProject)
        ? selectedProject
        : (normalized[0]?.name ?? "");
      setSelectedProject(project);
      if (project) {
        setProjectMemories((await API.listProjectMemories(project)).items);
      } else {
        setProjectMemories([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory_load_failed"));
    } finally {
      setLoading(false);
    }
  }, [selectedProject, t]);

  useEffect(() => {
    // Loading server-backed settings on mount is an intentional effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const reloadProject = useCallback(async (projectName: string) => {
    if (!projectName) {
      setProjectMemories([]);
      return;
    }
    try {
      setProjectMemories((await API.listProjectMemories(projectName)).items);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory_load_failed"));
    }
  }, [t]);

  const handleProjectChange = (projectName: string) => {
    setSelectedProject(projectName);
    void reloadProject(projectName);
  };

  const resetDraft = () => {
    setDraft(emptyDraft());
    setEditingId(null);
  };

  const startEdit = (memory: MemoryEntry) => {
    setEditingId(memory.id);
    setDraft({ category: memory.category, content: memory.content });
  };

  const saveMemory = async (scope: "user" | "project") => {
    if (!draft.content.trim() || (scope === "project" && !selectedProject)) return;
    setSaving(true);
    setError(null);
    try {
      if (editingId) {
        await API.updateMemory(editingId, draft);
      } else if (scope === "user") {
        await API.createUserMemory(draft);
      } else {
        await API.createProjectMemory(selectedProject, draft);
      }
      resetDraft();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory_save_failed"));
    } finally {
      setSaving(false);
    }
  };

  const removeMemory = async (memory: MemoryEntry) => {
    if (!window.confirm(t("memory_confirm_delete"))) return;
    try {
      await API.deleteMemory(memory.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory_delete_failed"));
    }
  };

  const clearScope = async (scope: "user" | "project") => {
    if (scope === "project" && !selectedProject) return;
    if (!window.confirm(t("memory_confirm_clear"))) return;
    try {
      if (scope === "user") await API.clearUserMemories();
      else await API.clearProjectMemories(selectedProject);
      resetDraft();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory_delete_failed"));
    }
  };

  const resolveCandidate = async (candidate: MemoryCandidate, accepted: boolean) => {
    try {
      if (accepted) await API.acceptMemoryCandidate(candidate.id);
      else await API.rejectMemoryCandidate(candidate.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory_candidate_failed"));
    }
  };

  const exportMemory = async () => {
    try {
      const payload = await API.exportMemories(selectedProject || undefined);
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "shotwise-agent-memory.json";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory_export_failed"));
    }
  };

  const importMemory = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setImporting(true);
    setError(null);
    try {
      const raw = JSON.parse(await file.text()) as unknown;
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error(t("memory_import_invalid"));
      const payload = raw as Record<string, unknown>;
      const userEntries = payload.user_memories;
      const projectEntries = payload.project_memories ?? payload.entries;
      if (
        (userEntries !== undefined && !Array.isArray(userEntries)) ||
        (projectEntries !== undefined && !Array.isArray(projectEntries)) ||
        (userEntries === undefined && projectEntries === undefined)
      ) {
        throw new Error(t("memory_import_invalid"));
      }
      if (Array.isArray(projectEntries) && projectEntries.length > 0 && !selectedProject) {
        throw new Error(t("memory_no_project"));
      }
      await API.importMemories(payload, selectedProject || undefined);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("memory_import_failed"));
    } finally {
      setImporting(false);
    }
  };

  const categoryLabel = useMemo(() => (category: MemoryCategory) => t(`memory_category_${category}`), [t]);

  const renderMemory = (memory: MemoryEntry) => (
    <div key={memory.id} className="rounded-[9px] border border-hairline-soft bg-bg-grad-a/35 p-3">
      {editingId === memory.id ? (
        <MemoryForm
          draft={draft}
          setDraft={setDraft}
          categories={CATEGORIES}
          categoryLabel={categoryLabel}
          saving={saving}
          onSave={() => void saveMemory(memory.scope)}
          onCancel={resetDraft}
          t={t}
        />
      ) : (
        <>
          <div className="mb-1 flex items-start justify-between gap-3">
            <span className="rounded-full border border-accent/30 px-2 py-0.5 font-mono text-[10px] text-accent-2">
              {categoryLabel(memory.category)}
            </span>
            <div className="flex items-center gap-1">
              <button type="button" className={GHOST_BTN_CLS} onClick={() => startEdit(memory)} aria-label={t("memory_edit")}>
                <Pencil className="h-3 w-3" />
              </button>
              <button type="button" className={GHOST_BTN_CLS} onClick={() => void removeMemory(memory)} aria-label={t("memory_delete")}>
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          </div>
          <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-text-2">{memory.content}</p>
          <p className="mt-2 text-[10.5px] text-text-4">{t("memory_updated_at", { date: formatMemoryDate(memory.updated_at, i18n.language) })}</p>
        </>
      )}
    </div>
  );

  if (loading) {
    return <div className="flex items-center gap-2 p-6 text-[12px] text-text-3"><Loader2 className="h-4 w-4 animate-spin" />{t("memory_loading")}</div>;
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="mb-2 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-accent-2">{t("memory_kicker")}</div>
          <h2 className="font-editorial text-3xl text-text">{t("memory_title")}</h2>
          <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-text-3">{t("memory_description")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={GHOST_BTN_CLS} onClick={() => void exportMemory()}><Download className="h-3.5 w-3.5" />{t("memory_export")}</button>
          <button type="button" className={GHOST_BTN_CLS} onClick={() => importInputRef.current?.click()} disabled={importing}>
            {importing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5 rotate-180" />}{t("memory_import")}
          </button>
          <input ref={importInputRef} type="file" accept=".json,application/json" className="hidden" onChange={(event) => void importMemory(event)} />
        </div>
      </div>
      {error && <div className="rounded-[8px] border border-warm/40 bg-warm/10 px-3 py-2 text-[12px] text-warm-bright">{error}</div>}
      <div className="rounded-[12px] border border-hairline p-5" style={CARD_STYLE}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div><h3 className="text-[15px] font-semibold text-text">{t("memory_user_title")}</h3><p className="mt-1 text-[12px] text-text-3">{t("memory_user_description")}</p></div>
          <button type="button" className={GHOST_BTN_CLS} onClick={() => void clearScope("user")} disabled={userMemories.length === 0}><Trash2 className="h-3.5 w-3.5" />{t("memory_clear")}</button>
        </div>
        <div className="mb-4 space-y-2">{userMemories.length ? userMemories.map(renderMemory) : <p className="text-[12px] text-text-4">{t("memory_empty")}</p>}</div>
        {!editingId && <MemoryForm draft={draft} setDraft={setDraft} categories={CATEGORIES} categoryLabel={categoryLabel} saving={saving} onSave={() => void saveMemory("user")} onCancel={resetDraft} t={t} />}
      </div>
      <div className="rounded-[12px] border border-hairline p-5" style={CARD_STYLE}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div><h3 className="text-[15px] font-semibold text-text">{t("memory_project_title")}</h3><p className="mt-1 text-[12px] text-text-3">{t("memory_project_description")}</p></div>
          <select className={INPUT_CLS + " max-w-[260px]"} value={selectedProject} onChange={(event) => handleProjectChange(event.target.value)} aria-label={t("memory_project_select")}>
            <option value="">{t("memory_project_select")}</option>
            {projects.map((project) => <option key={project.name} value={project.name}>{project.title || project.name}</option>)}
          </select>
        </div>
        {selectedProject ? <>
          <div className="mb-4 flex justify-end"><button type="button" className={GHOST_BTN_CLS} onClick={() => void clearScope("project")} disabled={projectMemories.length === 0}><Trash2 className="h-3.5 w-3.5" />{t("memory_clear")}</button></div>
          <div className="mb-4 space-y-2">{projectMemories.length ? projectMemories.map(renderMemory) : <p className="text-[12px] text-text-4">{t("memory_empty")}</p>}</div>
          {!editingId && <MemoryForm draft={draft} setDraft={setDraft} categories={CATEGORIES} categoryLabel={categoryLabel} saving={saving} onSave={() => void saveMemory("project")} onCancel={resetDraft} t={t} />}
        </> : <p className="text-[12px] text-text-4">{t("memory_no_project")}</p>}
      </div>
      <div className="rounded-[12px] border border-hairline p-5" style={CARD_STYLE}>
        <div className="mb-4"><h3 className="text-[15px] font-semibold text-text">{t("memory_candidates_title")}</h3><p className="mt-1 text-[12px] text-text-3">{t("memory_candidates_description")}</p></div>
        <div className="space-y-2">{candidates.length ? candidates.map((candidate) => <div key={candidate.id} className="flex flex-col gap-3 rounded-[9px] border border-hairline-soft bg-bg-grad-a/35 p-3 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="mb-1 text-[10px] text-accent-2">{candidate.scope === "project" ? candidate.project_name : t("memory_user_scope")}</div><p className="whitespace-pre-wrap text-[12.5px] text-text-2">{candidate.content}</p></div><div className="flex shrink-0 gap-2"><button type="button" className={ACCENT_BTN_CLS} onClick={() => void resolveCandidate(candidate, true)}><Check className="h-3.5 w-3.5" />{t("memory_accept")}</button><button type="button" className={GHOST_BTN_CLS} onClick={() => void resolveCandidate(candidate, false)}><X className="h-3.5 w-3.5" />{t("memory_reject")}</button></div></div>) : <p className="text-[12px] text-text-4">{t("memory_no_candidates")}</p>}</div>
      </div>
    </section>
  );
}

type MemoryFormProps = {
  draft: Draft;
  setDraft: (draft: Draft) => void;
  categories: MemoryCategory[];
  categoryLabel: (category: MemoryCategory) => string;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
  t: (key: string) => string;
};

function MemoryForm({ draft, setDraft, categories, categoryLabel, saving, onSave, onCancel, t }: MemoryFormProps) {
  return <div className="flex flex-col gap-2 rounded-[9px] border border-dashed border-hairline-soft p-3 sm:flex-row sm:items-end">
    <label className="text-[11px] text-text-3">{t("memory_category")}
      <select className={INPUT_CLS + " mt-1 min-w-[150px]"} value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value as MemoryCategory })}>
        {categories.map((category) => <option key={category} value={category}>{categoryLabel(category)}</option>)}
      </select>
    </label>
    <label className="min-w-0 flex-1 text-[11px] text-text-3">{t("memory_content")}
      <textarea className={INPUT_CLS + " mt-1 min-h-[74px] resize-y"} value={draft.content} maxLength={8000} onChange={(event) => setDraft({ ...draft, content: event.target.value })} placeholder={t("memory_content_placeholder")} />
    </label>
    <div className="flex gap-2"><button type="button" className={ACCENT_BTN_CLS} onClick={onSave} disabled={saving || !draft.content.trim()}>{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}{t("memory_save")}</button><button type="button" className={GHOST_BTN_CLS} onClick={onCancel} disabled={saving}><Plus className="h-3.5 w-3.5 rotate-45" />{t("memory_cancel")}</button></div>
  </div>;
}
