import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Box, Check, ChevronDown, ChevronLeft, ChevronRight, ListTree, PenLine, Save, Scissors, Sparkles, WandSparkles } from "lucide-react";
import { API, type CreativeDraftOperation } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useAssistantStore } from "@/stores/assistant-store";
import { useProjectsStore } from "@/stores/projects-store";
import { errMsg, voidPromise } from "@/utils/async";
import { CreativeOutlineManager, type CreativeOutlineChapter } from "./CreativeOutlineManager";

const DRAFT_FILENAME = "creative_draft.md";

type CreativeDraftEditorProps = {
  projectName: string;
  contentMode: "narration" | "drama";
  sourceKind?: "novel" | "screenplay";
  initialGenerate?: boolean;
};

type DraftSelection = {
  start: number;
  end: number;
  text: string;
};

type NovelProfile = {
  genre: string;
  audience: string;
  perspective: string;
  length: string;
  tone: string;
};

const NOVEL_PROFILE_OPTIONS = {
  genre: ["romance", "modern", "suspense", "thriller", "scifi", "wuxia", "fantasy", "xianxia", "historical"],
  audience: ["male", "female", "general"],
  perspective: ["first", "third"],
  length: ["short", "long"],
  tone: ["warm", "tense", "dark", "humorous"],
} as const;

const OPERATIONS: Array<{
  operation: CreativeDraftOperation;
  icon: typeof Sparkles;
  label: string;
  requiresContent: boolean;
}> = [
  { operation: "generate", icon: Sparkles, label: "creative_draft_generate", requiresContent: false },
  { operation: "continue", icon: PenLine, label: "creative_draft_continue", requiresContent: true },
  { operation: "expand", icon: WandSparkles, label: "creative_draft_expand", requiresContent: true },
  { operation: "rewrite", icon: WandSparkles, label: "creative_draft_rewrite", requiresContent: true },
  { operation: "polish", icon: Check, label: "creative_draft_polish", requiresContent: true },
  { operation: "outline", icon: ListTree, label: "creative_draft_outline", requiresContent: true },
  { operation: "split", icon: Scissors, label: "creative_draft_split", requiresContent: true },
];

function NovelProfileOptionGroup({
  label,
  group,
  value,
  onChange,
}: {
  label: string;
  group: keyof typeof NOVEL_PROFILE_OPTIONS;
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  return (
    <div className="space-y-1.5">
      <span className="block text-[10.5px] font-semibold" style={{ color: "var(--color-text-4)" }}>
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {NOVEL_PROFILE_OPTIONS[group].map((option) => {
          const active = value === option;
          return (
            <button
              key={option}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(active ? "" : option)}
              className="focus-ring rounded-md px-2 py-1 text-[10.5px] transition-colors"
              style={{
                color: active ? "var(--color-accent-2)" : "var(--color-text-3)",
                background: active ? "var(--color-accent-dim)" : "var(--color-shell-btn)",
                border: `1px solid ${active ? "var(--color-accent-soft)" : "var(--color-hairline-soft)"}`,
              }}
            >
              {t(`creative_draft_${group}_${option}`)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function CreativeDraftEditor({
  projectName,
  contentMode,
  sourceKind,
  initialGenerate = false,
}: CreativeDraftEditorProps) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [draft, setDraft] = useState("");
  const [savedDraft, setSavedDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [runningOperation, setRunningOperation] = useState<CreativeDraftOperation | null>(null);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [suggestionOperation, setSuggestionOperation] = useState<CreativeDraftOperation | null>(null);
  const [suggestionSelection, setSuggestionSelection] = useState<DraftSelection | null>(null);
  const [selection, setSelection] = useState<DraftSelection | null>(null);
  const [selectedOutlineChapter, setSelectedOutlineChapter] = useState<CreativeOutlineChapter | null>(null);
  const [outlineCollapsed, setOutlineCollapsed] = useState(false);
  const [novelProfileCollapsed, setNovelProfileCollapsed] = useState(false);
  const [instructionCollapsed, setInstructionCollapsed] = useState(false);
  const [novelProfile, setNovelProfile] = useState<NovelProfile>({
    genre: "",
    audience: "",
    perspective: "",
    length: "",
    tone: "",
  });
  const instructionRef = useRef<HTMLTextAreaElement>(null);

  const dirty = draft !== savedDraft;
  const characterCount = Array.from(draft).length;
  const showNovelProfile = contentMode === "drama" && sourceKind !== "screenplay";

  const handleSelectedOutlineChapterChange = useCallback((chapter: CreativeOutlineChapter | null) => {
    setSelectedOutlineChapter(chapter);
  }, []);

  const updateSelection = useCallback((target: HTMLTextAreaElement) => {
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const text = target.value.slice(start, end);
    setSelection(text.trim() ? { start, end, text } : null);
  }, []);

  useEffect(() => {
    let disposed = false;
    // Switching projects must enter a loading state before the new draft arrives.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setSuggestion(null);
    void API.getSourceContent(projectName, DRAFT_FILENAME)
      .then((text) => {
        if (disposed) return;
        setDraft(text);
        setSavedDraft(text);
      })
      .catch(() => {
        if (disposed) return;
        setDraft("");
        setSavedDraft("");
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [projectName]);

  useEffect(() => {
    if (initialGenerate && !loading) instructionRef.current?.focus();
  }, [initialGenerate, loading]);

  const saveDraft = useCallback(
    async (showSuccess = true) => {
      setSaving(true);
      try {
        await API.saveSourceFile(projectName, DRAFT_FILENAME, draft);
        setSavedDraft(draft);
        useAppStore.getState().invalidateSourceFiles();
        if (showSuccess) useAppStore.getState().pushToast(t("dashboard:creative_draft_saved"), "success");
        return true;
      } catch (error) {
        useAppStore
          .getState()
          .pushToast(t("dashboard:creative_draft_save_failed", { message: errMsg(error) }), "error");
        return false;
      } finally {
        setSaving(false);
      }
    },
    [draft, projectName, t],
  );

  const runOperation = useCallback(
    async (operation: CreativeDraftOperation) => {
      const meta = OPERATIONS.find((item) => item.operation === operation);
      if (!meta) return;
      if (meta.requiresContent && !draft.trim()) {
        useAppStore.getState().pushToast(t("dashboard:creative_draft_content_required"), "error");
        return;
      }
      if (operation === "generate" && !instruction.trim()) {
        useAppStore.getState().pushToast(t("dashboard:creative_draft_generate_required"), "error");
        instructionRef.current?.focus();
        return;
      }

      const useSelection =
        selection !== null && ["expand", "rewrite", "polish"].includes(operation);
      const content = useSelection ? selection.text : draft;
      const profileInstruction = showNovelProfile
        ? (Object.entries(novelProfile) as Array<[keyof NovelProfile, string]>)
            .filter(([, value]) => Boolean(value))
            .map(([key, value]) => `${t(`dashboard:creative_draft_${key}`)}：${t(`dashboard:creative_draft_${key}_${value}`)}`)
            .join("；")
        : "";
      const outlineInstruction = selectedOutlineChapter
        ? [
            `${t("dashboard:creative_outline_ai_context")}：${selectedOutlineChapter.title}`,
            selectedOutlineChapter.summary,
            selectedOutlineChapter.hook
              ? `${t("dashboard:creative_outline_chapter_hook")}：${selectedOutlineChapter.hook}`
              : "",
          ]
            .filter(Boolean)
            .join("\n")
        : "";
      const generationInstruction = [profileInstruction, outlineInstruction, instruction.trim()]
        .filter(Boolean)
        .join("\n");

      setRunningOperation(operation);
      try {
        const result = await API.generateCreativeDraft(projectName, {
          operation,
          content,
          instruction: generationInstruction,
        });
        setSuggestion(result.content);
        setSuggestionOperation(operation);
        setSuggestionSelection(useSelection ? selection : null);
      } catch (error) {
        useAppStore
          .getState()
          .pushToast(t("dashboard:creative_draft_generation_failed", { message: errMsg(error) }), "error");
      } finally {
        setRunningOperation(null);
      }
    },
    [
      draft,
      instruction,
      novelProfile,
      projectName,
      selectedOutlineChapter,
      selection,
      showNovelProfile,
      t,
    ],
  );

  const handleOperationClick = useCallback(
    (operation: CreativeDraftOperation) => {
      void runOperation(operation);
    },
    [runOperation],
  );

  const applySuggestionAsReplacement = useCallback(() => {
    if (!suggestion) return;
    if (!suggestionSelection) {
      setDraft(suggestion);
      return;
    }

    const selectedNow = draft.slice(suggestionSelection.start, suggestionSelection.end);
    if (selectedNow !== suggestionSelection.text) {
      useAppStore.getState().pushToast(t("dashboard:creative_draft_selection_changed"), "error");
      return;
    }
    setDraft(
      `${draft.slice(0, suggestionSelection.start)}${suggestion}${draft.slice(suggestionSelection.end)}`,
    );
    setSelection(null);
  }, [draft, suggestion, suggestionSelection, t]);

  const handoffToAssistant = useCallback(
    (kind: "assets" | "production") => {
      const promptKey =
        kind === "assets"
          ? "creative_draft_assets_prompt"
          : contentMode === "narration"
            ? "creative_draft_confirm_narration_prompt"
            : sourceKind === "screenplay"
              ? "creative_draft_confirm_screenplay_prompt"
              : "creative_draft_confirm_novel_prompt";
      useAssistantStore.getState().setInput(t(`dashboard:${promptKey}`, { filename: DRAFT_FILENAME }));
      useAppStore.getState().setAssistantPanelOpen(true);
    },
    [contentMode, sourceKind, t],
  );

  const handleExtractAssets = useCallback(async () => {
    if (!draft.trim()) {
      useAppStore.getState().pushToast(t("dashboard:creative_draft_content_required"), "error");
      return;
    }
    const saved = await saveDraft(false);
    if (!saved) return;
    handoffToAssistant("assets");
  }, [draft, handoffToAssistant, saveDraft, t]);

  const handleConfirmSource = useCallback(async () => {
    if (!draft.trim()) {
      useAppStore.getState().pushToast(t("dashboard:creative_draft_content_required"), "error");
      return;
    }
    setConfirming(true);
    try {
      const saved = dirty ? await saveDraft(false) : true;
      if (!saved) return;
      await API.generateOverview(projectName);
      await useProjectsStore.getState().refreshProject(projectName);
      handoffToAssistant("production");
      useAppStore.getState().pushToast(t("dashboard:creative_draft_confirmed"), "success");
    } catch (error) {
      useAppStore
        .getState()
        .pushToast(t("dashboard:creative_draft_confirm_failed", { message: errMsg(error) }), "error");
    } finally {
      setConfirming(false);
    }
  }, [dirty, draft, handoffToAssistant, projectName, saveDraft, t]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-[12px]" style={{ color: "var(--color-text-4)" }}>
        {t("dashboard:creative_draft_loading")}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        className="flex flex-wrap items-center gap-2 border-b px-5 py-2.5"
        style={{ borderColor: "var(--color-hairline-soft)", background: "var(--panel-card-bg)" }}
      >
        <span className="text-[11px]" style={{ color: dirty ? "var(--color-warm)" : "var(--color-text-4)" }}>
          {dirty ? t("dashboard:creative_draft_unsaved") : DRAFT_FILENAME}
        </span>
        {showNovelProfile ? (
          <button
            type="button"
            onClick={() => setOutlineCollapsed((collapsed) => !collapsed)}
            aria-label={t(outlineCollapsed ? "dashboard:creative_outline_expand" : "dashboard:creative_outline_collapse")}
            title={t(outlineCollapsed ? "dashboard:creative_outline_expand" : "dashboard:creative_outline_collapse")}
            className="focus-ring grid h-7 w-7 place-items-center rounded-md"
            style={{ color: "var(--color-text-3)", border: "1px solid var(--color-hairline-soft)", background: "var(--color-shell-btn)" }}
          >
            {outlineCollapsed ? <ChevronRight className="h-3.5 w-3.5" aria-hidden /> : <ChevronLeft className="h-3.5 w-3.5" aria-hidden />}
          </button>
        ) : null}
        <div className="flex-1" />
          <button
          type="button"
          onClick={voidPromise(() => saveDraft())}
          disabled={saving || !dirty}
          className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-medium disabled:opacity-50"
          style={{ color: "var(--color-text-2)", border: "1px solid var(--color-hairline)", background: "var(--color-shell-btn)" }}
          >
            <Save className="h-3.5 w-3.5" aria-hidden />
            {saving ? t("common:saving") : t("dashboard:creative_draft_save")}
        </button>
        <button
          type="button"
          onClick={voidPromise(handleConfirmSource)}
          disabled={confirming || saving}
          className="focus-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-[11.5px] font-medium disabled:opacity-50"
          style={{ color: "oklch(0.14 0 0)", background: "linear-gradient(135deg, var(--color-accent-2), var(--color-accent))" }}
        >
          <Check className="h-3.5 w-3.5" aria-hidden />
          {confirming ? t("dashboard:creative_draft_confirming") : t("dashboard:creative_draft_confirm_source")}
        </button>
      </div>

      <div
        className={`grid min-h-0 flex-1 gap-4 overflow-hidden p-5 ${
          showNovelProfile
            && !outlineCollapsed
            ? "lg:grid-cols-[13rem_minmax(0,1fr)_19rem]"
            : "lg:grid-cols-[minmax(0,1fr)_19rem]"
        }`}
      >
        {showNovelProfile && !outlineCollapsed ? (
          <CreativeOutlineManager
            projectName={projectName}
            onSelectedChapterChange={handleSelectedOutlineChapterChange}
            outlineSuggestion={suggestionOperation === "outline" ? suggestion : null}
            onOutlineSuggestionConsumed={() => {
              setSuggestion(null);
              setSuggestionOperation(null);
            }}
          />
        ) : null}
        <section className="flex min-h-0 flex-col overflow-hidden rounded-lg" style={{ border: "1px solid var(--color-hairline-soft)", background: "var(--color-shell-field)" }}>
          <label htmlFor="creative-draft-content" className="sr-only">
            {t("dashboard:creative_draft_title")}
          </label>
          <textarea
            id="creative-draft-content"
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
              updateSelection(event.target);
            }}
            onSelect={(event) => updateSelection(event.currentTarget)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
                event.preventDefault();
                if (!saving && dirty) void saveDraft();
              }
            }}
            placeholder={t("dashboard:creative_draft_empty")}
            className="focus-ring min-h-[28rem] flex-1 resize-none bg-transparent px-5 py-4 text-[14px] leading-7 outline-none"
            style={{ color: "var(--color-text)" }}
          />
          <div className="flex items-center gap-2 border-t px-4 py-2 text-[10.5px]" style={{ borderColor: "var(--color-hairline-soft)", color: "var(--color-text-4)" }}>
            <span className="num">{t("dashboard:creative_draft_character_count", { count: characterCount })}</span>
            {selection ? <span className="num">{t("dashboard:creative_draft_selection_count", { count: Array.from(selection.text).length })}</span> : null}
            <span className="ml-auto">{t("dashboard:creative_draft_save_shortcut")}</span>
          </div>
        </section>

        <aside className="min-h-0 overflow-y-auto rounded-lg p-3" style={{ border: "1px solid var(--color-hairline-soft)", background: "var(--panel-card-bg)" }}>
          {showNovelProfile ? (
            <section className="mb-4 space-y-3 border-b pb-4" style={{ borderColor: "var(--color-hairline-soft)" }}>
              <button
                type="button"
                onClick={() => setNovelProfileCollapsed((collapsed) => !collapsed)}
                aria-expanded={!novelProfileCollapsed}
                aria-label={t(novelProfileCollapsed ? "dashboard:creative_draft_expand_novel_profile" : "dashboard:creative_draft_collapse_novel_profile")}
                className="focus-ring flex w-full items-center gap-1.5 rounded px-0.5 py-1 text-left"
                style={{ color: "var(--color-text-2)" }}
              >
                <ChevronDown className={`h-3.5 w-3.5 transition-transform ${novelProfileCollapsed ? "-rotate-90" : ""}`} aria-hidden />
                <span className="text-[11px] font-semibold">{t("dashboard:creative_draft_novel_profile")}</span>
              </button>
              {!novelProfileCollapsed ? (
                <div className="space-y-3">
                  <NovelProfileOptionGroup
                    label={t("dashboard:creative_draft_genre")}
                    group="genre"
                    value={novelProfile.genre}
                    onChange={(genre) => setNovelProfile((current) => ({ ...current, genre }))}
                  />
                  <NovelProfileOptionGroup
                    label={t("dashboard:creative_draft_audience")}
                    group="audience"
                    value={novelProfile.audience}
                    onChange={(audience) => setNovelProfile((current) => ({ ...current, audience }))}
                  />
                  <NovelProfileOptionGroup
                    label={t("dashboard:creative_draft_perspective")}
                    group="perspective"
                    value={novelProfile.perspective}
                    onChange={(perspective) => setNovelProfile((current) => ({ ...current, perspective }))}
                  />
                  <NovelProfileOptionGroup
                    label={t("dashboard:creative_draft_length")}
                    group="length"
                    value={novelProfile.length}
                    onChange={(length) => setNovelProfile((current) => ({ ...current, length }))}
                  />
                  <NovelProfileOptionGroup
                    label={t("dashboard:creative_draft_tone")}
                    group="tone"
                    value={novelProfile.tone}
                    onChange={(tone) => setNovelProfile((current) => ({ ...current, tone }))}
                  />
                </div>
              ) : null}
            </section>
          ) : null}
          <div className="mb-2 flex items-center gap-1.5">
            <label htmlFor="creative-draft-instruction" className="flex-1 text-[11px] font-semibold" style={{ color: "var(--color-text-3)" }}>
              {t("dashboard:creative_draft_instruction")}
            </label>
            <button
              type="button"
              onClick={() => setInstructionCollapsed((collapsed) => !collapsed)}
              aria-expanded={!instructionCollapsed}
              aria-label={t(instructionCollapsed ? "dashboard:creative_draft_expand_instruction" : "dashboard:creative_draft_collapse_instruction")}
              className="focus-ring grid h-6 w-6 place-items-center rounded"
              style={{ color: "var(--color-text-4)" }}
            >
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${instructionCollapsed ? "-rotate-90" : ""}`} aria-hidden />
            </button>
          </div>
          {!instructionCollapsed ? (
            <textarea
              id="creative-draft-instruction"
              ref={instructionRef}
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              placeholder={t("dashboard:creative_draft_instruction_placeholder")}
              className="focus-ring min-h-24 w-full resize-y rounded-md p-2.5 text-[12px] leading-5 outline-none"
              style={{ color: "var(--color-text)", background: "var(--color-shell-field)", border: "1px solid var(--color-hairline-soft)" }}
            />
          ) : null}
          <div className="mt-3 grid grid-cols-2 gap-1.5">
            {OPERATIONS.map(({ operation, icon: Icon, label }) => (
              <button
                key={operation}
                type="button"
                onClick={() => handleOperationClick(operation)}
                disabled={runningOperation !== null}
                className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2.5 py-2 text-left text-[11px] disabled:opacity-50"
                style={{ color: "var(--color-text-2)", border: "1px solid var(--color-hairline)", background: "var(--color-shell-btn)" }}
              >
                <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                {runningOperation === operation ? t("dashboard:creative_draft_generating") : t(`dashboard:${label}`)}
              </button>
            ))}
          </div>

          {selection ? (
            <p className="mt-2 text-[10.5px] leading-4" style={{ color: "var(--color-text-4)" }}>
              {t("dashboard:creative_draft_selection_hint")}
            </p>
          ) : null}

          {suggestion ? (
            <section className="mt-4 border-t pt-3" style={{ borderColor: "var(--color-hairline-soft)" }}>
              <h3 className="text-[11px] font-semibold" style={{ color: "var(--color-text-3)" }}>
                {t("dashboard:creative_draft_suggestion")}
              </h3>
              <pre className="mt-2 max-h-52 overflow-y-auto whitespace-pre-wrap rounded-md p-2.5 text-[11.5px] leading-5" style={{ color: "var(--color-text-2)", background: "var(--color-shell-field)" }}>
                {suggestion}
              </pre>
              <div className="mt-2 grid grid-cols-2 gap-1.5">
                <button type="button" onClick={applySuggestionAsReplacement} className="focus-ring rounded-md px-2 py-1.5 text-[11px]" style={{ color: "var(--color-text-2)", border: "1px solid var(--color-hairline)" }}>
                  {t("dashboard:creative_draft_replace")}
                </button>
                <button type="button" onClick={() => setDraft((current) => `${current.trimEnd()}${current.trim() ? "\n\n" : ""}${suggestion}`)} className="focus-ring rounded-md px-2 py-1.5 text-[11px]" style={{ color: "var(--color-text-2)", border: "1px solid var(--color-hairline)" }}>
                  {t("dashboard:creative_draft_append")}
                </button>
              </div>
            </section>
          ) : null}

          <section className="mt-4 border-t pt-3" style={{ borderColor: "var(--color-hairline-soft)" }}>
            <button type="button" onClick={voidPromise(handleExtractAssets)} disabled={saving} className="focus-ring flex w-full items-center gap-1.5 rounded-md px-2.5 py-2 text-left text-[11px] disabled:opacity-50" style={{ color: "var(--color-text-2)", border: "1px solid var(--color-hairline)", background: "var(--color-shell-btn)" }}>
              <Box className="h-3.5 w-3.5 shrink-0" aria-hidden />
              {t("dashboard:creative_draft_extract_assets")}
            </button>
          </section>
        </aside>
      </div>
    </div>
  );
}
