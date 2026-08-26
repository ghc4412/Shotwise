import { useEffect, useMemo, useRef, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { Box, Check, CircleCheck, Clock3, FilePlus2, Hand, Heart, Images, Loader2, Plus, Search, Send, ShieldCheck, Upload, WandSparkles, X } from "lucide-react";
import { API } from "../../api";
import { useProjectsStore } from "../../stores/projects-store";
import { useAppStore } from "../../stores/app-store";
import { PRESET_SKILLS, type SkillPreset } from "../../stores/skillPresets";

type Skill = {
  id: string;
  versionId: string;
  workflowRevisionId: string;
  version: string;
  title: string;
  summary: string;
  category: string;
  modes: string[];
  inputs: string[];
  outputs: string[];
  costHint: string | null;
  review: boolean;
  compatible: boolean;
  preset: SkillPreset;
  source: "official" | "preset";
};

type Resource = { selectionKey: string; label: string; type: string };
type PromptAttachment = { name: string; source: "local" | "library"; id?: string };
type PromptLibraryAsset = { id: string; label: string; type: string };
type PreparationPreview = { planId: string; cost: string; outputs: string[]; modes: string[] };
type CategoryId = "recommended" | "film" | "commerce" | "shortDrama" | "anime" | "music" | "creator" | "universal" | "discover";
type Category = { id: CategoryId; labelKey: string };

const CATEGORIES: Category[] = [
  { id: "recommended", labelKey: "creation_skills_market_category_recommended" },
  { id: "film", labelKey: "creation_skills_market_category_film" },
  { id: "commerce", labelKey: "creation_skills_market_category_commerce" },
  { id: "shortDrama", labelKey: "creation_skills_market_category_shortDrama" },
  { id: "anime", labelKey: "creation_skills_market_category_anime" },
  { id: "music", labelKey: "creation_skills_market_category_music" },
  { id: "creator", labelKey: "creation_skills_market_category_creator" },
  { id: "universal", labelKey: "creation_skills_market_category_universal" },
  { id: "discover", labelKey: "creation_skills_market_category_discover" },
];

const SKILLS_PER_PAGE = 12;
const SAVED_SKILLS_STORAGE_KEY = "shotwise-creation-skills-saved";

function readSavedSkillIds(projectName: string): string[] {
  try {
    const raw = window.localStorage.getItem(SAVED_SKILLS_STORAGE_KEY + ":" + projectName);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

const PRESET_MARKET_CATEGORY: Record<SkillPreset["category"], CategoryId> = {
  recommended: "recommended",
  "professional-film": "film",
  "commercial-ad": "commerce",
  "short-drama": "shortDrama",
  "anime-game": "anime",
  "music-mv": "music",
  "self-media": "creator",
  general: "universal",
  discover: "discover",
};

const asList = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
const asString = (value: unknown): string => typeof value === "string" ? value : "";
const displayCost = (response: Record<string, unknown>, fallback: string | null): string => {
  const estimated = response.estimated_cost;
  if (typeof estimated === "string" || typeof estimated === "number") return String(estimated);
  const cost = response.cost;
  if (typeof cost === "string" || typeof cost === "number") return String(cost);
  return fallback ?? "—";
};

const SKILL_IMAGE_HINTS: ReadonlyArray<readonly [RegExp, string]> = [
  [/(anime|animation|manga|game|二次元|动漫|游戏)/i, "/style-thumbnails/anim_arcane.png"],
  [/(music|mv|concert|performance|neon|音乐|演出|霓虹)/i, "/style-thumbnails/live_cyberpunk.png"],
  [/(product|brand|commercial|commerce|ad|advert|产品|品牌|广告|电商)/i, "/style-thumbnails/live_premium_drama.png"],
  [/(character|continuity|actor|casting|角色|连续性|演员|选角)/i, "/style-thumbnails/live_kdrama.png"],
  [/(vlog|creator|knowledge|short|social|自媒体|知识|短剧|竖屏)/i, "/style-thumbnails/live_anderson.png"],
  [/(storyboard|cinematic|film|drama|novel|shot|镜头|分镜|电影|剧集|故事)/i, "/style-thumbnails/live_cinema.png"],
];

function presetForId(id: string, hint = id): SkillPreset {
  const exact = PRESET_SKILLS.find((preset) => preset.id === id);
  if (exact) return exact;
  const index = Array.from(id).reduce((sum, character) => sum + character.charCodeAt(0), 0) % PRESET_SKILLS.length;
  const fallback = PRESET_SKILLS[index] ?? PRESET_SKILLS[0];
  const image = SKILL_IMAGE_HINTS.find(([pattern]) => pattern.test(hint))?.[1];
  return image && fallback ? { ...fallback, image } : fallback;
}

function presetSkill(preset: SkillPreset): Skill {
  return { id: preset.id, versionId: preset.id + ":preset", workflowRevisionId: "", version: "preset", title: preset.title, summary: preset.description, category: preset.category, modes: [], inputs: [], outputs: [], costHint: null, review: preset.type === "official", compatible: true, preset, source: "preset" };
}

const LOCAL_SKILLS = PRESET_SKILLS.map(presetSkill);

function normalize(row: Record<string, unknown>): Skill | null {
  const compatibility = typeof row.compatibility === "object" && row.compatibility !== null ? row.compatibility as Record<string, unknown> : {};
  const id = typeof row.skill_id === "string" ? row.skill_id : typeof row.id === "string" ? row.id : "";
  const versionId = typeof row.skill_version_id === "string" ? row.skill_version_id : typeof row.version_id === "string" ? row.version_id : id + (typeof row.version === "number" || typeof row.version === "string" ? ":v" + row.version : "");
  const title = asString(row.title);
  if (!id || !title) return null;
  return {
    id,
    versionId,
    workflowRevisionId: asString(row.workflow_revision_id),
    version: typeof row.version === "number" ? "v" + row.version : asString(row.version),
    title,
    summary: asString(row.summary) || asString(row.description),
    category: asString(row.category) || "通用技能",
    modes: asList(compatibility.supported_generation_modes),
    inputs: asList(row.inputs),
    outputs: asList(row.outputs),
    costHint: asString(row.estimated_cost_hint) || null,
    review: row.review_required === true,
    compatible: compatibility.compatible !== false,
    preset: presetForId(id, [id, title, asString(row.description), asString(row.summary)].join(" ")),
    source: "official",
  };
}

function skillMarketCategory(skill: Skill): CategoryId {
  if (skill.source === "preset") return PRESET_MARKET_CATEGORY[skill.preset.category];
  if (["广告", "商业广告"].includes(skill.category)) return "commerce";
  if (["剧集", "短剧爽剧"].includes(skill.category)) return "shortDrama";
  if (skill.category === "动漫游戏") return "anime";
  if (skill.category === "音乐MV") return "music";
  if (skill.category === "自媒体创作") return "creator";
  if (skill.category === "通用技能") return "universal";
  if (["视频", "专业影视", "电影"].includes(skill.category)) return "film";
  return "discover";
}

export function CreationSkillsPage({ projectName }: { projectName?: string } = {}) {
  const { t } = useTranslation("dashboard");
  const currentProjectName = useProjectsStore((state) => state.currentProjectName);
  const pushToast = useAppStore((state) => state.pushToast);
  const projectNameForApi = projectName ?? currentProjectName ?? "";
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selected, setSelected] = useState<Skill | null>(null);
  const [activeTab, setActiveTab] = useState<"skills" | "saved" | "mine">("skills");
  const [category, setCategory] = useState<CategoryId>("recommended");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [prompt, setPrompt] = useState("");
  const [promptMenu, setPromptMenu] = useState<"add" | "library" | "model" | "skill" | "mode" | null>(null);
  const [promptModelTab, setPromptModelTab] = useState<"image" | "video">("image");
  const [promptModel, setPromptModel] = useState("lib-image");
  const [promptMode, setPromptMode] = useState<"manual" | "auto">("auto");
  const [promptAttachment, setPromptAttachment] = useState<PromptAttachment | null>(null);
  const [promptLibraryAssets, setPromptLibraryAssets] = useState<PromptLibraryAsset[]>([]);
  const [promptLibraryLoading, setPromptLibraryLoading] = useState(false);
  const [promptLibraryLoaded, setPromptLibraryLoaded] = useState(false);
  const promptFileInputRef = useRef<HTMLInputElement>(null);
  const [savedIdsByProject, setSavedIdsByProject] = useState<Record<string, string[]>>({});
  const savedIds = savedIdsByProject[projectNameForApi] ?? readSavedSkillIds(projectNameForApi);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);
  const [resourceIds, setResourceIds] = useState<string[]>([]);
  const [resourceLoading, setResourceLoading] = useState(false);
  const [parameters, setParameters] = useState<Record<string, unknown>>({});
  const [preview, setPreview] = useState<PreparationPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState(false);
  const [actionError, setActionError] = useState("");
  const [history, setHistory] = useState<Array<{ version: string; status: string }>>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    window.localStorage.setItem(SAVED_SKILLS_STORAGE_KEY + ":" + projectNameForApi, JSON.stringify(savedIds));
  }, [projectNameForApi, savedIds]);

  useEffect(() => {
    let cancelled = false;
    void API.listCreationSkills(projectNameForApi).then((response) => {
      if (cancelled) return;
      setLoadError("");
      const official = response.items.map((row) => normalize(row)).filter((skill): skill is Skill => skill !== null && skill.compatible);
      const officialIds = new Set(official.map((skill) => skill.id));
      setSkills([...official, ...LOCAL_SKILLS.filter((skill) => !officialIds.has(skill.id))]);
    }).catch((error: unknown) => {
      if (cancelled) return;
      setLoadError(error instanceof Error ? error.message : String(error));
      setSkills(LOCAL_SKILLS);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [projectNameForApi]);

  const categories = CATEGORIES.map((item) => ({ ...item, label: t(item.labelKey) }));
  const allVisible = useMemo(() => skills.filter((skill) => {
    if (activeTab === "saved" && !savedIds.includes(skill.id)) return false;
    if (activeTab === "mine" && skill.source !== "preset") return false;
    const needle = query.trim().toLowerCase();
    return (category === "recommended" || category === "discover" || skillMarketCategory(skill) === category) && (!needle || [skill.title, skill.summary, skill.category, skill.preset.author].join(" ").toLowerCase().includes(needle));
  }), [activeTab, category, query, savedIds, skills]);

  const totalPages = Math.max(1, Math.ceil(allVisible.length / SKILLS_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const visible = useMemo(() => allVisible.slice((currentPage - 1) * SKILLS_PER_PAGE, currentPage * SKILLS_PER_PAGE), [allVisible, currentPage]);

  const prepare = async (skill: Skill) => {
    setSelected(skill);
    setPreview(null);
    setStarted(false);
    setActionError("");
    setResourceIds([]);
    const params = new URLSearchParams(window.location.search);
    const episode = Number(params.get("episode"));
    setParameters(Number.isFinite(episode) && episode > 0 ? { episode } : {});
    setResourceLoading(true);
    try {
      const response = await API.listCreationResources(projectNameForApi);
      const nextResources = response.items.map((row) => {
        const selectionKey = asString(row.selection_key) || asString(row.selectionKey) || asString(row.id);
        return { selectionKey, label: asString(row.label) || asString(row.name) || selectionKey, type: asString(row.type) || "resource" };
      }).filter((resource) => resource.selectionKey);
      setResources(nextResources);
      const requestedResource = params.get("resource_id");
      if (requestedResource && nextResources.some((resource) => resource.selectionKey === requestedResource)) setResourceIds([requestedResource]);
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : String(error));
      setResources([]);
    } finally {
      setResourceLoading(false);
    }
  };

  const toggleSaved = (skillId: string) => setSavedIdsByProject((current) => {
    const savedForProject = current[projectNameForApi] ?? readSavedSkillIds(projectNameForApi);
    const next = savedForProject.includes(skillId)
      ? savedForProject.filter((id) => id !== skillId)
      : [...savedForProject, skillId];
    return { ...current, [projectNameForApi]: next };
  });
  const toggleResource = (id: string) => setResourceIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);

  const showHistory = async () => {
    if (!selected) return;
    setHistoryLoading(true);
    try {
      const response = await API.listCreationSkillVersions(selected.id);
      setHistory(response.items.map((row) => ({ version: asString(row.version), status: asString(row.status) })));
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setHistoryLoading(false);
    }
  };

  const createPreview = async () => {
    if (!selected || !resourceIds.length || !selected.workflowRevisionId) {
      setActionError(t("creation_skills_empty"));
      return;
    }
    setBusy(true);
    setActionError("");
    try {
      const result = await API.previewCreationPlan(projectNameForApi, { creation_skill_version_id: selected.versionId, workflow_revision: selected.workflowRevisionId, workflow_revision_id: selected.workflowRevisionId, resource_ids: resourceIds, parameters });
      const response = result;
      const report = typeof response.compatibility_report === "object" && response.compatibility_report !== null ? response.compatibility_report as Record<string, unknown> : typeof response.report === "object" && response.report !== null ? response.report as Record<string, unknown> : {};
      const planId = asString(response.plan_id);
      if (!planId || report.compatible === false) throw new Error(t("creation_skills_empty"));
      const outputs = asList(response.steps).length ? asList(response.steps) : asList(response.outputs);
      setPreview({ planId, cost: displayCost(response, selected.costHint), outputs: outputs.length ? outputs : selected.outputs, modes: selected.modes });
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!preview) return;
    setBusy(true);
    setActionError("");
    try {
      const response = await API.startCreationPlan(preview.planId);
      if (!asString(response.workflow_run_id)) throw new Error(t("creation_skills_empty"));
      setStarted(true);
      pushToast(t("creation_plan_started") );
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const submitPrompt = () => {
    if (!prompt.trim()) return;
    setQuery(prompt.trim());
    setCategory("discover");
    setPromptMenu(null);
  };

  const openPromptLibrary = async () => {
    setPromptMenu("library");
    if (promptLibraryLoaded || promptLibraryLoading) return;
    setPromptLibraryLoading(true);
    try {
      const response = await API.listMediaAssets(projectNameForApi);
      const items = Array.isArray(response.items) ? response.items : [];
      setPromptLibraryAssets(items.map((item) => {
        const id = asString(item.id) || asString(item.asset_id) || asString(item.media_id);
        const label = asString(item.name) || asString(item.file_name) || asString(item.filename) || id;
        return { id, label, type: asString(item.media_type) || asString(item.type) || "media" };
      }).filter((item) => item.id && item.label));
      setPromptLibraryLoaded(true);
    } catch {
      setPromptLibraryAssets([]);
    } finally {
      setPromptLibraryLoading(false);
    }
  };

 return <div className="flex h-full min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden bg-[#f7f8fb] text-slate-900">
    {started ? <div role="status" aria-live="polite" className="mx-auto mt-3 w-full max-w-[1440px] rounded-xl bg-emerald-500/10 px-6 py-2 text-[11px] text-emerald-700">{t("creation_plan_started")} · {t("task_hud_title")}</div> : null}
    {actionError ? <div role="alert" aria-live="polite" className="mx-auto mt-3 w-full max-w-[1440px] rounded-xl border border-rose-200 bg-rose-50 px-6 py-2 text-[11px] text-rose-700">{t("creation_skills_action_error", { message: actionError })}</div> : null}
<main data-testid="creation-skills-scroll" className="skills-page-scrollbar min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto w-full max-w-none px-11 pb-10 pt-10 sm:px-16 lg:px-32">
      <section className="mx-auto max-w-3xl text-center">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-[11px] font-semibold text-indigo-600"><WandSparkles className="h-3.5 w-3.5" aria-hidden />{t("creation_skills_eyebrow")}</div>
        <h1 className="text-balance text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-4xl">{t("creation_skills_market_title")}</h1>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-slate-500">{t("creation_skills_market_subtitle")}</p>
        <form className="relative mt-7 overflow-visible rounded-2xl border border-slate-200 bg-white p-2 text-left shadow-[0_16px_50px_rgba(42,47,70,0.09)] focus-within:border-indigo-300 focus-within:ring-4 focus-within:ring-indigo-100" onSubmit={(event) => { event.preventDefault(); submitPrompt(); }}>
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submitPrompt(); }} rows={4} placeholder={t("creation_skills_market_prompt_placeholder")} aria-label={t("creation_skills_market_prompt_label")} className="min-h-24 w-full resize-none bg-transparent px-4 pt-3 text-base leading-7 outline-none placeholder:text-slate-400" />
          {promptAttachment ? <div className="mx-2 mt-1 inline-flex max-w-[calc(100%-1rem)] items-center gap-1.5 rounded-md bg-indigo-50 px-2 py-1 text-[11px] text-indigo-700"><span className="max-w-[240px] truncate">{t("creation_prompt_selected_file", { name: promptAttachment.name })}</span><button type="button" onClick={() => setPromptAttachment(null)} aria-label={t("creation_prompt_remove_file")} className="rounded p-0.5 transition hover:bg-indigo-100">×</button></div> : null}
          <div className="flex items-center justify-between gap-4 px-3 pb-2 pt-3">
            <div className="flex items-center gap-2 text-slate-400">
              <div className="relative">
                <button type="button" aria-label={t("creation_prompt_add")} title={t("creation_prompt_add")} aria-haspopup="menu" aria-expanded={promptMenu === "add"} onClick={() => setPromptMenu((menu) => menu === "add" ? null : "add")} className={promptMenu === "add" ? "rounded-lg bg-slate-100 p-2 text-indigo-600" : "rounded-lg p-2 transition hover:bg-slate-100 hover:text-indigo-600"}><Plus className="h-4 w-4" aria-hidden /></button>
                {promptMenu === "add" ? <div role="menu" className="absolute bottom-[calc(100%+8px)] left-0 z-30 min-w-44 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
                  <button type="button" role="menuitem" onClick={() => { setPromptMenu(null); promptFileInputRef.current?.click(); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-slate-700 transition hover:bg-slate-50"><Upload className="h-4 w-4" aria-hidden />{t("creation_prompt_local_upload")}</button>
                  <button type="button" role="menuitem" onClick={() => void openPromptLibrary()} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-slate-700 transition hover:bg-slate-50"><Images className="h-4 w-4" aria-hidden />{t("creation_prompt_library_add")}</button>
                </div> : null}
                {promptMenu === "library" ? <div role="dialog" aria-label={t("creation_prompt_library_add")} className="absolute bottom-[calc(100%+8px)] left-0 z-30 w-72 rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
                  <div className="mb-2 flex items-center justify-between"><span className="text-xs font-semibold text-slate-800">{t("creation_prompt_library_select")}</span><button type="button" onClick={() => setPromptMenu(null)} aria-label={t("creation_prompt_close")} className="rounded p-1 text-slate-400 hover:bg-slate-100">×</button></div>
                  {promptLibraryLoading ? <div className="py-5 text-center text-xs text-slate-400">{t("creation_prompt_library_loading")}</div> : promptLibraryAssets.length ? <div className="max-h-48 space-y-1 overflow-y-auto">{promptLibraryAssets.map((asset) => <button key={asset.id} type="button" onClick={() => { setPromptAttachment({ name: asset.label, source: "library", id: asset.id }); setPromptMenu(null); }} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition hover:bg-slate-50"><Images className="h-4 w-4 shrink-0 text-slate-400" aria-hidden /><span className="min-w-0 flex-1 truncate text-xs text-slate-700">{asset.label}</span><span className="text-[10px] text-slate-400">{asset.type}</span></button>)}</div> : <div className="py-5 text-center text-xs text-slate-400">{t("creation_prompt_no_media")}</div>}
                </div> : null}
              </div>
              <div className="relative">
                <button type="button" aria-label={t("creation_prompt_model")} title={t("creation_prompt_model")} aria-haspopup="dialog" aria-expanded={promptMenu === "model"} onClick={() => setPromptMenu((menu) => menu === "model" ? null : "model")} className={promptMenu === "model" ? "rounded-lg bg-slate-100 p-2 text-indigo-600" : "rounded-lg p-2 transition hover:bg-slate-100 hover:text-indigo-600"}><Box className="h-4 w-4" aria-hidden /></button>
                {promptMenu === "model" ? <div role="dialog" aria-label={t("creation_prompt_model")} className="absolute bottom-[calc(100%+8px)] left-1/2 z-30 w-80 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-xl">
                  <div className="mb-3 text-sm font-semibold text-slate-800">{t("creation_prompt_model")}</div>
                  <div className="mb-3 grid grid-cols-2 rounded-lg bg-slate-100 p-0.5">{(["image", "video"] as const).map((tab) => <button key={tab} type="button" onClick={() => setPromptModelTab(tab)} className={promptModelTab === tab ? "rounded-md bg-white px-3 py-1.5 text-xs font-medium text-slate-800 shadow-sm" : "rounded-md px-3 py-1.5 text-xs text-slate-400"}>{t(tab === "image" ? "creation_prompt_image" : "creation_prompt_video")}</button>)}</div>
                  <div className="max-h-56 space-y-1 overflow-y-auto">{(promptModelTab === "image" ? [{ id: "lib-image", label: "Lib Image" }, { id: "general-image-pro", label: "General image Pro" }, { id: "general-image-v2", label: "General image V2" }, { id: "seedream-5-pro", label: "Seedream 5.0 Pro" }] : [{ id: "veo-3.1", label: "Veo 3.1" }, { id: "kling-2.6", label: "Kling 2.6" }, { id: "seedance-1.5", label: "Seedance 1.5" }]).map((model) => <button key={model.id} type="button" onClick={() => { setPromptModel(model.id); setPromptMenu(null); }} className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left transition hover:bg-slate-50"><span className="min-w-0"><span className="block truncate text-xs font-medium text-slate-700">{model.label}</span><span className="mt-0.5 block text-[10px] text-slate-400">{t("creation_prompt_model_desc")}</span></span>{promptModel === model.id ? <Check className="h-3.5 w-3.5 shrink-0 text-indigo-600" aria-hidden /> : <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-slate-300" />}</button>)}</div>
                </div> : null}
              </div>
              <div className="relative">
                <button type="button" aria-label={t("creation_prompt_skill")} title={t("creation_prompt_skill")} aria-haspopup="dialog" aria-expanded={promptMenu === "skill"} onClick={() => setPromptMenu((menu) => menu === "skill" ? null : "skill")} className={promptMenu === "skill" ? "rounded-lg bg-slate-100 p-2 text-indigo-600" : "rounded-lg p-2 transition hover:bg-slate-100 hover:text-indigo-600"}><FilePlus2 className="h-4 w-4" aria-hidden /></button>
                {promptMenu === "skill" ? <div role="dialog" aria-label={t("creation_prompt_skill")} className="absolute bottom-[calc(100%+8px)] left-1/2 z-30 w-80 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-xl">
                  <div className="mb-2 text-sm font-semibold text-slate-800">{t("creation_prompt_skill")}</div>
                  <div className="max-h-56 space-y-1 overflow-y-auto">{skills.length ? skills.slice(0, 10).map((skill) => <button key={skill.id + skill.versionId} type="button" onClick={() => { setPrompt((current) => current + (current ? " " : "") + "/" + skill.id + " "); setPromptMenu(null); }} className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition hover:bg-slate-50"><FilePlus2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden /><span className="min-w-0"><span className="block truncate text-xs font-medium text-slate-700">/{skill.id}</span><span className="mt-0.5 block truncate text-[10px] text-slate-400">{skill.summary || skill.title}</span></span></button>) : <div className="py-5 text-center text-xs text-slate-400">{t("creation_prompt_no_skills")}</div>}</div>
                </div> : null}
              </div>
              <div className="relative">
                <button type="button" aria-label={t("creation_prompt_mode")} title={t("creation_prompt_mode")} aria-haspopup="menu" aria-expanded={promptMenu === "mode"} onClick={() => setPromptMenu((menu) => menu === "mode" ? null : "mode")} className={promptMenu === "mode" ? "rounded-lg bg-slate-100 p-2 text-indigo-600" : "rounded-lg p-2 transition hover:bg-slate-100 hover:text-indigo-600"}>{promptMode === "auto" ? <CircleCheck className="h-4 w-4" aria-hidden /> : <Hand className="h-4 w-4" aria-hidden />}</button>
                {promptMenu === "mode" ? <div role="menu" className="absolute bottom-[calc(100%+8px)] right-0 z-30 w-64 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
                  <button type="button" role="menuitemradio" aria-checked={promptMode === "manual"} onClick={() => { setPromptMode("manual"); setPromptMenu(null); }} className="flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left transition hover:bg-slate-50"><Hand className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden /><span className="flex-1"><span className="block text-xs font-medium text-slate-700">{t("creation_prompt_manual_mode")}</span><span className="mt-0.5 block text-[10px] text-slate-400">{t("creation_prompt_manual_mode_hint")}</span></span>{promptMode === "manual" ? <Check className="h-3.5 w-3.5 text-indigo-600" aria-hidden /> : null}</button>
                  <button type="button" role="menuitemradio" aria-checked={promptMode === "auto"} onClick={() => { setPromptMode("auto"); setPromptMenu(null); }} className="flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left transition hover:bg-slate-50"><CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden /><span className="flex-1"><span className="block text-xs font-medium text-slate-700">{t("creation_prompt_auto_mode")}</span><span className="mt-0.5 block text-[10px] text-slate-400">{t("creation_prompt_auto_mode_hint")}</span></span>{promptMode === "auto" ? <Check className="h-3.5 w-3.5 text-indigo-600" aria-hidden /> : null}</button>
                </div> : null}
              </div>
            </div>
            <button type="submit" aria-label={t("creation_skills_market_send")} className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-slate-950 text-white transition hover:bg-indigo-600"><Send className="h-4 w-4" aria-hidden /></button>
          </div>
          <input ref={promptFileInputRef} type="file" accept="image/*,video/*,.pdf,.txt,.doc,.docx" className="hidden" aria-label={t("creation_prompt_local_upload")} onChange={(event) => { const file = event.target.files?.[0]; if (file) setPromptAttachment({ name: file.name, source: "local" }); event.target.value = ""; }} />
        </form>
      </section>
      <div className="mt-6 flex flex-col gap-4 border-b border-slate-200 pb-3 lg:flex-row lg:items-center lg:justify-between"><div className="flex w-fit items-center gap-5">{([['skills', t('creation_skills_market_tab_skills')], ['saved', t('creation_skills_market_tab_saved')], ['mine', t('creation_skills_market_tab_mine')]] as const).map(([id, label]) => <button key={id} type="button" onClick={() => { setActiveTab(id); setPage(1); }} aria-pressed={activeTab === id} className={activeTab === id ? "text-xs font-semibold text-slate-900" : "text-xs font-medium text-slate-500 transition hover:text-slate-900"}>{label}</button>)}</div><label className="flex h-8 w-full max-w-xs items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-slate-400 focus-within:border-slate-300 focus-within:ring-2 focus-within:ring-slate-100"><Search className="h-3.5 w-3.5" aria-hidden /><span className="sr-only">{t("creation_skills_market_search")}</span><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t("creation_skills_market_search")} className="min-w-0 flex-1 bg-transparent text-xs text-slate-700 outline-none placeholder:text-slate-400" /></label></div>
       <nav aria-label={t("creation_skills_market_categories_label")} className="mt-4 flex items-center gap-2 overflow-x-auto pb-1"><div className="flex min-w-max gap-2">{categories.map(({ id, label }) => <button key={id} type="button" onClick={() => { setCategory(id); setPage(1); }} aria-pressed={category === id} className={category === id ? "shrink-0 rounded-full border border-slate-300 bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-800" : "shrink-0 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:border-slate-300 hover:text-slate-800"}>{label}</button>)}</div><span className="shrink-0 text-xs font-medium text-slate-400">{allVisible.length} {t("creation_skills_market_results")}</span></nav>
      <div className="skills-market-section mt-5"><section aria-label={t("creation_skills_market_grid_label")} className="min-w-0"><div className="mb-3 flex items-center justify-between"><h2 className="sr-only">{t("creation_skills_market_section_title")}</h2></div>{loading ? <div className="flex items-center gap-2 py-12 text-xs text-slate-500"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />{t("creation_skills_loading")}</div> : null}{loadError ? <div role="alert" className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">{t("creation_skills_load_error", { message: loadError })}</div> : null}{!loading && visible.length === 0 ? <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center text-sm text-slate-500">{t("creation_skills_empty")}</div> : null}<div className="skills-market-grid grid grid-cols-1 gap-x-2.5 gap-y-2.5 sm:grid-cols-2 xl:grid-cols-3">{visible.map((skill) => { const saved = savedIds.includes(skill.id); const label = categories.find((item) => item.id === skillMarketCategory(skill))?.label ?? skill.category; return <article key={skill.id + skill.versionId} className="skills-market-card group relative overflow-hidden rounded-xl border border-slate-200 bg-white text-left transition duration-200 hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-[0_10px_22px_rgba(42,47,70,0.09)]"><button type="button" aria-label={t("creation_skills_prepare")} title={t("creation_skills_market_use")} onClick={() => void prepare(skill)} className="flex min-h-[128px] w-full items-center gap-3 p-2.5 pr-9 text-left"><div className="relative h-[112px] w-[118px] shrink-0 overflow-hidden rounded-lg bg-slate-900"><img src={skill.preset.image} alt="" loading="lazy" decoding="async" onError={(event) => { event.currentTarget.src = "/style-thumbnails/live_cinema.png"; }} className="h-full w-full object-cover transition duration-500 group-hover:scale-105" /><div className="absolute inset-0 bg-gradient-to-t from-slate-950/45 via-transparent to-transparent" /><div className="absolute right-1.5 top-1.5 rounded bg-slate-950/65 px-1.5 py-0.5 text-[9px] font-medium text-white">{skill.preset.tags[0] ?? label}</div></div><div className="flex min-w-0 flex-1 flex-col justify-center py-1"><h3 className="line-clamp-2 pr-1 text-[13px] font-semibold leading-5 text-slate-900">{skill.title}</h3><p className="mt-1 line-clamp-3 text-[12px] leading-[18px] text-slate-500">{skill.summary}</p><div className="mt-auto flex min-w-0 items-center gap-1.5 pt-3 text-[10px] text-slate-400"><span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 font-semibold text-indigo-700">{skill.preset.author.slice(0, 1)}</span><span className="min-w-0 truncate">{skill.preset.author}</span><span className="shrink-0">↗ {skill.preset.usage.toLocaleString()}</span></div></div></button><button type="button" aria-label={t("creation_skills_market_save")} onClick={() => toggleSaved(skill.id)} className={saved ? "absolute right-2 top-2 rounded-lg p-1 text-rose-500" : "absolute right-2 top-2 rounded-lg p-1 text-slate-300 transition hover:text-rose-400"}><Heart className="h-3.5 w-3.5" fill={saved ? "currentColor" : "none"} aria-hidden /></button></article>; })}</div></section></div>
      {!loading && allVisible.length > 0 ? <SkillPagination page={currentPage} totalPages={totalPages} onPrevious={() => setPage((pageNumber) => Math.max(1, pageNumber - 1))} onNext={() => setPage((pageNumber) => Math.min(totalPages, pageNumber + 1))} previousLabel={t("creation_skills_market_previous")} nextLabel={t("creation_skills_market_next")} pageLabel={t("creation_skills_market_page", { current: currentPage, total: totalPages })} ariaLabel={t("creation_skills_market_pagination")} /> : null}
      {selected ? <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/20 p-4 backdrop-blur-[1px]" role="dialog" aria-modal="true" aria-label={t("creation_skills_prepare_eyebrow")}><aside className="h-full w-full max-w-md overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl"><PreparationPanel selected={selected} resources={resources} resourceIds={resourceIds} resourceLoading={resourceLoading} parameters={parameters} setParameters={setParameters} preview={preview} busy={busy} started={started} history={history} historyLoading={historyLoading} onClose={() => setSelected(null)} onHistory={() => void showHistory()} onToggleResource={toggleResource} onPreview={() => void createPreview()} onStart={() => void start()} t={t} /></aside></div> : null}
    </main>
  </div>;
}

export default CreationSkillsPage;

type SkillPaginationProps = { page: number; totalPages: number; onPrevious: () => void; onNext: () => void; previousLabel: string; nextLabel: string; pageLabel: string; ariaLabel: string };

function SkillPagination({ page, totalPages, onPrevious, onNext, previousLabel, nextLabel, pageLabel, ariaLabel }: SkillPaginationProps) {
  if (totalPages <= 1) return null;
  return <nav aria-label={ariaLabel} className="mt-6 flex items-center justify-center gap-2"><button type="button" onClick={onPrevious} disabled={page === 1} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 transition hover:border-indigo-200 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-40">{previousLabel}</button><span className="min-w-20 text-center text-xs text-slate-500">{pageLabel}</span><button type="button" onClick={onNext} disabled={page === totalPages} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 transition hover:border-indigo-200 hover:text-indigo-600 disabled:cursor-not-allowed disabled:opacity-40">{nextLabel}</button></nav>;
}

type PreparationPanelProps = { selected: Skill; resources: Resource[]; resourceIds: string[]; resourceLoading: boolean; parameters: Record<string, unknown>; setParameters: (value: Record<string, unknown>) => void; preview: PreparationPreview | null; busy: boolean; started: boolean; history: Array<{ version: string; status: string }>; historyLoading: boolean; onClose: () => void; onHistory: () => void; onToggleResource: (id: string) => void; onPreview: () => void; onStart: () => void; t: TFunction };

function PreparationPanel({ selected, resources, resourceIds, resourceLoading, parameters, setParameters, preview, busy, started, history, historyLoading, onClose, onHistory, onToggleResource, onPreview, onStart, t }: PreparationPanelProps) {
  return <><div style={{ backgroundImage: "url(" + selected.preset.image + ")" }} className="relative mb-5 h-32 overflow-hidden rounded-xl bg-cover bg-center"><div className="absolute inset-0 bg-slate-950/25" /><span className="absolute bottom-4 left-4 rounded-md bg-white/85 px-2 py-1 text-xs font-bold text-slate-800 shadow-sm">{selected.preset.tags[0] ?? "Skill"}</span><button type="button" onClick={onClose} aria-label={t("creation_skills_market_close")} className="absolute right-3 top-3 rounded-lg bg-white/30 p-1.5 text-white backdrop-blur-sm"><X className="h-4 w-4" aria-hidden /></button></div><div className="flex items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-indigo-500">{t("creation_skills_prepare_eyebrow")}</p><h2 className="mt-1 text-lg font-semibold tracking-[-0.02em] text-slate-950">{selected.title}</h2></div><button type="button" onClick={onClose} className="text-[11px] text-slate-500 hover:text-slate-900">{t("common:cancel")}</button></div><p className="mt-3 text-sm leading-6 text-slate-500">{selected.summary}</p><div className="mt-4 flex items-center gap-2"><button type="button" onClick={onHistory} disabled={historyLoading} className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] text-slate-600">{historyLoading ? t("creation_skills_history_loading") : t("creation_skills_history")}</button>{history.length ? <span className="text-[10px] text-slate-400">{t("creation_skills_history_title")}: {history.map((item) => item.version).join(", ")}</span> : null}</div><h3 className="mt-5 text-[11px] font-semibold text-slate-700">{t("creation_skills_inputs")}</h3><div className="mt-2 flex flex-wrap gap-1.5">{selected.inputs.map((item) => <span key={item} className="rounded bg-slate-100 px-2 py-1 text-[10px] text-slate-500">{item}</span>)}</div><h3 className="mt-4 text-[11px] font-semibold text-slate-700">{t("creation_skills_inputs")}</h3>{resourceLoading ? <div className="mt-2 text-[10px] text-slate-500">{t("creation_skills_loading")}</div> : <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">{resources.length ? resources.map((item) => <label key={item.selectionKey} className="flex items-center gap-2 text-[10px] text-slate-600"><input type="checkbox" checked={resourceIds.includes(item.selectionKey)} onChange={() => onToggleResource(item.selectionKey)} /><span className="truncate">{item.label}</span><span className="ml-auto text-[9px] text-slate-400">{item.type}</span></label>) : <div className="text-[10px] text-slate-400">{t("creation_skills_empty")}</div>}</div>}<h3 className="mt-4 text-[11px] font-semibold text-slate-700">{t("creation_plan_duration")}</h3><input aria-label={t("creation_plan_duration")} type="number" min="1" max="120" value={typeof parameters.duration === "number" ? parameters.duration : ""} onChange={(event) => { const value = Number(event.target.value); setParameters(value > 0 ? { ...parameters, duration: value } : parameters.episode ? { episode: parameters.episode } : {}); }} className="mt-2 w-full rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-[11px]" /><h3 className="mt-4 text-[11px] font-semibold text-slate-700">{t("creation_skills_outputs")}</h3><div className="mt-2 flex flex-wrap gap-1.5">{selected.outputs.map((item) => <span key={item} className="rounded bg-slate-100 px-2 py-1 text-[10px] text-slate-500">{item}</span>)}</div><div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-[11px] leading-relaxed text-amber-800"><ShieldCheck className="mb-1 h-4 w-4" aria-hidden />{t("creation_skills_generation_lock")}</div>{preview ? <div className="mt-5 rounded-xl border border-indigo-100 bg-indigo-50/50 p-3"><div className="flex items-center gap-2 text-xs font-semibold text-indigo-900"><Check className="h-4 w-4" aria-hidden />{t("creation_plan_ready")}</div><div className="mt-3 space-y-2 text-[11px] text-slate-600"><div className="flex justify-between"><span>{t("creation_plan_cost")}</span><b>{preview.cost}</b></div><div className="flex justify-between"><span>{t("creation_plan_route_snapshot")}</span><b>{preview.modes.join(" / ")}</b></div>{preview.outputs.map((item, index) => <div key={item} className="flex gap-2"><span className="font-mono text-[9px]">0{index + 1}</span>{item}</div>)}<p className="border-t border-indigo-100 pt-2 text-[10px]">{t("creation_plan_compatible")}</p></div>{started ? <div className="mt-3 rounded-lg bg-emerald-500/10 px-2.5 py-2 text-[10px] text-emerald-700">{t("creation_plan_started")}</div> : <button type="button" aria-label={t("creation_plan_start")} onClick={onStart} disabled={busy} className="mt-4 w-full rounded-xl bg-slate-950 px-3 py-2.5 text-[11px] font-semibold text-white transition hover:bg-indigo-600">{t("creation_plan_start")}</button>}</div> : <button type="button" aria-label={t("creation_plan_preview")} onClick={onPreview} disabled={busy || resourceLoading || !resourceIds.length} className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-slate-950 px-3 py-2.5 text-[12px] font-semibold text-white transition hover:bg-indigo-600">{busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Clock3 className="h-4 w-4" aria-hidden />}{busy ? t("creation_plan_generating") : t("creation_plan_preview")}</button>}</>;
}
