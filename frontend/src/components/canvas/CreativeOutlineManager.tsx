import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, FileText, Plus, Save, Trash2 } from "lucide-react";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { errMsg, voidPromise } from "@/utils/async";

export const CREATIVE_OUTLINE_FILENAME = "_creative_outline.json";

export type CreativeOutlineChapter = {
  id: string;
  title: string;
  summary: string;
  hook: string;
};

type CreativeOutlineVolume = {
  id: string;
  title: string;
  chapters: CreativeOutlineChapter[];
};

type CreativeOutlineDocument = {
  version: 1;
  volumes: CreativeOutlineVolume[];
};

function newId(prefix: string): string {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
}

function parseOutline(content: string): CreativeOutlineDocument | null {
  try {
    const parsed: unknown = JSON.parse(content);
    if (!parsed || typeof parsed !== "object" || !Array.isArray((parsed as { volumes?: unknown }).volumes)) {
      return null;
    }
    const volumes = (parsed as { volumes: unknown[] }).volumes.flatMap((volume): CreativeOutlineVolume[] => {
      if (!volume || typeof volume !== "object" || !Array.isArray((volume as { chapters?: unknown }).chapters)) {
        return [];
      }
      const data = volume as { id?: unknown; title?: unknown; chapters: unknown[] };
      return [
        {
          id: typeof data.id === "string" ? data.id : newId("volume"),
          title: typeof data.title === "string" ? data.title : "",
          chapters: data.chapters.flatMap((chapter): CreativeOutlineChapter[] => {
            if (!chapter || typeof chapter !== "object") return [];
            const entry = chapter as Record<string, unknown>;
            return [
              {
                id: typeof entry.id === "string" ? entry.id : newId("chapter"),
                title: typeof entry.title === "string" ? entry.title : "",
                summary: typeof entry.summary === "string" ? entry.summary : "",
                hook: typeof entry.hook === "string" ? entry.hook : "",
              },
            ];
          }),
        },
      ];
    });
    return { version: 1, volumes };
  } catch {
    return null;
  }
}

function findChapter(document: CreativeOutlineDocument, id: string | null): CreativeOutlineChapter | null {
  if (!id) return null;
  for (const volume of document.volumes) {
    const chapter = volume.chapters.find((entry) => entry.id === id);
    if (chapter) return chapter;
  }
  return null;
}

function chaptersFromSuggestion(content: string, fallbackTitle: string): CreativeOutlineChapter[] {
  const lines = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const heading = /^(?:#{1,3}\s*)?(?:第[0-9０-９一二三四五六七八九十百千万零]+\s*[章节回]|\d+[.、])/;
  const headings = lines
    .map((line, index) => ({ line, index }))
    .filter(({ line }) => heading.test(line));
  if (headings.length === 0) {
    return content.trim()
      ? [{ id: newId("chapter"), title: fallbackTitle, summary: content.trim(), hook: "" }]
      : [];
  }
  return headings.map(({ line, index }, headingIndex) => ({
    id: newId("chapter"),
    title: line.replace(/^#{1,3}\s*/, ""),
    summary: lines.slice(index + 1, headings[headingIndex + 1]?.index ?? lines.length).join(" "),
    hook: "",
  }));
}

function updateChapter(
  document: CreativeOutlineDocument,
  chapterId: string,
  update: Partial<CreativeOutlineChapter>,
): CreativeOutlineDocument {
  return {
    ...document,
    volumes: document.volumes.map((volume) => ({
      ...volume,
      chapters: volume.chapters.map((chapter) => (chapter.id === chapterId ? { ...chapter, ...update } : chapter)),
    })),
  };
}

export function CreativeOutlineManager({
  projectName,
  onSelectedChapterChange,
  outlineSuggestion,
  onOutlineSuggestionConsumed,
}: {
  projectName: string;
  onSelectedChapterChange: (chapter: CreativeOutlineChapter | null) => void;
  outlineSuggestion?: string | null;
  onOutlineSuggestionConsumed?: () => void;
}) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [outline, setOutline] = useState<CreativeOutlineDocument>({ version: 1, volumes: [] });
  const [savedOutline, setSavedOutline] = useState<CreativeOutlineDocument>({ version: 1, volumes: [] });
  const [selectedChapterId, setSelectedChapterId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const selectedChapter = useMemo(() => findChapter(outline, selectedChapterId), [outline, selectedChapterId]);
  const dirty = JSON.stringify(outline) !== JSON.stringify(savedOutline);

  useEffect(() => {
    onSelectedChapterChange(selectedChapter);
  }, [onSelectedChapterChange, selectedChapter]);

  useEffect(() => {
    let disposed = false;
    // Switching projects must enter a loading state before the new outline arrives.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    void API.getSourceContent(projectName, CREATIVE_OUTLINE_FILENAME)
      .then((content) => parseOutline(content))
      .then((saved) => {
        if (disposed) return;
        const next = saved ?? { version: 1, volumes: [] };
        setOutline(next);
        setSavedOutline(next);
        setSelectedChapterId(next.volumes[0]?.chapters[0]?.id ?? null);
      })
      .catch(() => {
        if (disposed) return;
        setOutline({ version: 1, volumes: [] });
        setSavedOutline({ version: 1, volumes: [] });
        setSelectedChapterId(null);
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [projectName]);

  const saveOutline = useCallback(async () => {
    setSaving(true);
    try {
      await API.saveSourceFile(projectName, CREATIVE_OUTLINE_FILENAME, JSON.stringify(outline, null, 2));
      setSavedOutline(outline);
      useAppStore.getState().invalidateSourceFiles();
      useAppStore.getState().pushToast(t("dashboard:creative_outline_saved"), "success");
    } catch (error) {
      useAppStore
        .getState()
        .pushToast(t("dashboard:creative_outline_save_failed", { message: errMsg(error) }), "error");
    } finally {
      setSaving(false);
    }
  }, [outline, projectName, t]);

  const addVolume = useCallback(() => {
    const volume: CreativeOutlineVolume = {
      id: newId("volume"),
      title: t("dashboard:creative_outline_new_volume"),
      chapters: [],
    };
    setOutline((current) => ({ ...current, volumes: [...current.volumes, volume] }));
  }, [t]);

  const addChapter = useCallback(
    (volumeId: string) => {
      const chapter: CreativeOutlineChapter = {
        id: newId("chapter"),
        title: t("dashboard:creative_outline_new_chapter"),
        summary: "",
        hook: "",
      };
      setOutline((current) => ({
        ...current,
        volumes: current.volumes.map((volume) =>
          volume.id === volumeId ? { ...volume, chapters: [...volume.chapters, chapter] } : volume,
        ),
      }));
      setSelectedChapterId(chapter.id);
    },
    [t],
  );

  const importSuggestion = useCallback(() => {
    const chapters = chaptersFromSuggestion(
      outlineSuggestion ?? "",
      t("dashboard:creative_outline_new_chapter"),
    );
    if (chapters.length === 0) {
      useAppStore.getState().pushToast(t("dashboard:creative_outline_import_failed"), "error");
      return;
    }
    setOutline((current) => {
      const target = current.volumes[0] ?? {
        id: newId("volume"),
        title: t("dashboard:creative_outline_new_volume"),
        chapters: [],
      };
      const hasTarget = current.volumes.some((volume) => volume.id === target.id);
      return {
        ...current,
        volumes: hasTarget
          ? current.volumes.map((volume) =>
              volume.id === target.id ? { ...volume, chapters: [...volume.chapters, ...chapters] } : volume,
            )
          : [...current.volumes, { ...target, chapters }],
      };
    });
    setSelectedChapterId(chapters[0].id);
    onOutlineSuggestionConsumed?.();
    useAppStore.getState().pushToast(t("dashboard:creative_outline_imported"), "success");
  }, [onOutlineSuggestionConsumed, outlineSuggestion, t]);

  const removeChapter = useCallback(
    (chapterId: string) => {
      if (!confirm(t("dashboard:creative_outline_confirm_delete_chapter"))) return;
      setOutline((current) => ({
        ...current,
        volumes: current.volumes.map((volume) => ({
          ...volume,
          chapters: volume.chapters.filter((chapter) => chapter.id !== chapterId),
        })),
      }));
      if (selectedChapterId === chapterId) setSelectedChapterId(null);
    },
    [selectedChapterId, t],
  );

  const removeVolume = useCallback(
    (volumeId: string) => {
      if (!confirm(t("dashboard:creative_outline_confirm_delete_volume"))) return;
      setOutline((current) => ({ ...current, volumes: current.volumes.filter((volume) => volume.id !== volumeId) }));
      if (outline.volumes.find((volume) => volume.id === volumeId)?.chapters.some((chapter) => chapter.id === selectedChapterId)) {
        setSelectedChapterId(null);
      }
    },
    [outline.volumes, selectedChapterId, t],
  );

  if (loading) {
    return (
      <aside className="min-h-0 overflow-y-auto rounded-lg p-3" style={{ border: "1px solid var(--color-hairline-soft)", background: "var(--panel-card-bg)" }}>
        <span className="text-[11px]" style={{ color: "var(--color-text-4)" }}>
          {t("dashboard:creative_outline_loading")}
        </span>
      </aside>
    );
  }

  return (
    <aside className="min-h-0 overflow-y-auto rounded-lg p-3" style={{ border: "1px solid var(--color-hairline-soft)", background: "var(--panel-card-bg)" }}>
      <header className="flex items-center gap-2 border-b pb-2.5" style={{ borderColor: "var(--color-hairline-soft)" }}>
        <FileText className="h-3.5 w-3.5" style={{ color: "var(--color-accent-2)" }} aria-hidden />
        <h3 className="flex-1 text-[12px] font-semibold" style={{ color: "var(--color-text)" }}>
          {t("dashboard:creative_outline_title")}
        </h3>
        <button
          type="button"
          onClick={voidPromise(saveOutline)}
          disabled={saving || !dirty}
          aria-label={t("dashboard:creative_outline_save")}
          className="focus-ring grid h-7 w-7 place-items-center rounded-md disabled:opacity-50"
          style={{ color: "var(--color-text-3)", border: "1px solid var(--color-hairline-soft)" }}
        >
          <Save className="h-3.5 w-3.5" aria-hidden />
        </button>
      </header>

      <button
        type="button"
        onClick={addVolume}
        className="focus-ring mt-3 inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[11px]"
        style={{ color: "var(--color-text-2)", border: "1px solid var(--color-hairline-soft)", background: "var(--color-shell-btn)" }}
      >
        <Plus className="h-3.5 w-3.5" aria-hidden />
        {t("dashboard:creative_outline_add_volume")}
      </button>

      {outlineSuggestion ? (
        <button
          type="button"
          onClick={importSuggestion}
          className="focus-ring mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-[11px]"
          style={{ color: "var(--color-accent-2)", border: "1px solid var(--color-accent-soft)", background: "var(--color-accent-dim)" }}
        >
          <FileText className="h-3.5 w-3.5" aria-hidden />
          {t("dashboard:creative_outline_import")}
        </button>
      ) : null}

      <div className="mt-3 space-y-2.5">
        {outline.volumes.map((volume) => (
          <section key={volume.id} className="border-b pb-2.5" style={{ borderColor: "var(--color-hairline-soft)" }}>
            <div className="flex items-center gap-1">
              <ChevronDown className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--color-text-4)" }} aria-hidden />
              <input
                value={volume.title}
                onChange={(event) =>
                  setOutline((current) => ({
                    ...current,
                    volumes: current.volumes.map((entry) =>
                      entry.id === volume.id ? { ...entry, title: event.target.value } : entry,
                    ),
                  }))
                }
                aria-label={t("dashboard:creative_outline_volume_title")}
                className="focus-ring min-w-0 flex-1 bg-transparent px-1 py-1 text-[11px] font-semibold outline-none"
                style={{ color: "var(--color-text-2)" }}
              />
              <button
                type="button"
                onClick={() => addChapter(volume.id)}
                aria-label={t("dashboard:creative_outline_add_chapter")}
                className="focus-ring grid h-6 w-6 place-items-center rounded"
                style={{ color: "var(--color-text-4)" }}
              >
                <Plus className="h-3.5 w-3.5" aria-hidden />
              </button>
              <button
                type="button"
                onClick={() => removeVolume(volume.id)}
                aria-label={t("dashboard:creative_outline_delete_volume")}
                className="focus-ring grid h-6 w-6 place-items-center rounded"
                style={{ color: "var(--color-text-4)" }}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
            <div className="mt-1 space-y-0.5 pl-4">
              {volume.chapters.map((chapter, index) => {
                const active = chapter.id === selectedChapterId;
                return (
                  <button
                    key={chapter.id}
                    type="button"
                    onClick={() => setSelectedChapterId(chapter.id)}
                    className="focus-ring flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11px]"
                    style={{
                      color: active ? "var(--color-accent-2)" : "var(--color-text-3)",
                      background: active ? "var(--color-accent-dim)" : "transparent",
                    }}
                  >
                    <span className="num shrink-0 text-[10px]">{index + 1}</span>
                    <span className="truncate">{chapter.title || t("dashboard:creative_outline_untitled_chapter")}</span>
                  </button>
                );
              })}
              {volume.chapters.length === 0 ? (
                <span className="block px-2 py-1 text-[10.5px]" style={{ color: "var(--color-text-4)" }}>
                  {t("dashboard:creative_outline_empty_volume")}
                </span>
              ) : null}
            </div>
          </section>
        ))}
      </div>

      {outline.volumes.length === 0 ? (
        <p className="mt-5 text-[11px] leading-5" style={{ color: "var(--color-text-4)" }}>
          {t("dashboard:creative_outline_empty")}
        </p>
      ) : null}

      {selectedChapter ? (
        <section className="mt-4 space-y-2.5 border-t pt-3" style={{ borderColor: "var(--color-hairline-soft)" }}>
          <input
            value={selectedChapter.title}
            onChange={(event) => setOutline((current) => updateChapter(current, selectedChapter.id, { title: event.target.value }))}
            aria-label={t("dashboard:creative_outline_chapter_title")}
            placeholder={t("dashboard:creative_outline_chapter_title")}
            className="focus-ring w-full rounded-md px-2.5 py-2 text-[11.5px] outline-none"
            style={{ color: "var(--color-text)", background: "var(--color-shell-field)", border: "1px solid var(--color-hairline-soft)" }}
          />
          <textarea
            value={selectedChapter.summary}
            onChange={(event) => setOutline((current) => updateChapter(current, selectedChapter.id, { summary: event.target.value }))}
            aria-label={t("dashboard:creative_outline_chapter_summary")}
            placeholder={t("dashboard:creative_outline_chapter_summary_placeholder")}
            className="focus-ring min-h-24 w-full resize-y rounded-md px-2.5 py-2 text-[11.5px] leading-5 outline-none"
            style={{ color: "var(--color-text)", background: "var(--color-shell-field)", border: "1px solid var(--color-hairline-soft)" }}
          />
          <input
            value={selectedChapter.hook}
            onChange={(event) => setOutline((current) => updateChapter(current, selectedChapter.id, { hook: event.target.value }))}
            aria-label={t("dashboard:creative_outline_chapter_hook")}
            placeholder={t("dashboard:creative_outline_chapter_hook")}
            className="focus-ring w-full rounded-md px-2.5 py-2 text-[11.5px] outline-none"
            style={{ color: "var(--color-text)", background: "var(--color-shell-field)", border: "1px solid var(--color-hairline-soft)" }}
          />
          <button
            type="button"
            onClick={() => removeChapter(selectedChapter.id)}
            className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[10.5px]"
            style={{ color: "var(--color-text-4)" }}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden />
            {t("dashboard:creative_outline_delete_chapter")}
          </button>
        </section>
      ) : null}
    </aside>
  );
}
