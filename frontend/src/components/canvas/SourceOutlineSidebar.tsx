import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight, Eye, EyeOff, ListTree, Loader2, RefreshCw, Save, Sparkles } from "lucide-react";
import { API } from "@/api";
import { errMsg } from "@/utils/async";
import { useAppStore } from "@/stores/app-store";
import {
  buildCreativeOutlineDocument,
  CREATIVE_OUTLINE_FILENAME,
  mergeOutlineItems,
  mergeOutlineWithSourceChapters,
  parseOutline,
  parseSavedCreativeOutline,
  parseSourceChapters,
  splitSourceIntoChunks,
  type OutlineItem,
} from "./source-outline";

interface SourceOutlineSidebarProps {
  projectName: string;
  filename: string;
  content: string;
  onSelectItem: (item: OutlineItem) => void;
}

async function requestOutline(
  projectName: string,
  filename: string,
  content: string,
  batchNumber: number,
  totalBatches: number,
) {
  return API.generateCreativeDraft(projectName, {
    operation: "outline",
    content,
    instruction: [
      "请阅读源文件「" + filename + "」的当前片段，提取当前片段中出现的所有章节大纲。",
      "这是第 " + batchNumber + "/" + totalBatches + " 个片段；只处理当前片段，不要臆测片段外的章节内容。",
      "请只输出 JSON 数组，不要使用 Markdown，格式为 [{\"chapter\":1,\"title\":\"章节标题\",\"summary\":\"本章核心事件\"}]。",
      "原文已有章节必须逐字复制章节标题（包括括号、标点和副标题），不得改写、概括或替换标题；同时保留原文章节编号和顺序。",
      "如果没有明确章节，才按自然剧情段落划分并给出简短标题。",
      "如果当前片段是同一章节的延续，请继续使用原章节编号，后续系统会自动合并摘要。",
    ].join("\n"),
  });
}

export function SourceOutlineSidebar({ projectName, filename, content, onSelectItem }: SourceOutlineSidebarProps) {
  const { t } = useTranslation("dashboard");
  const [expanded, setExpanded] = useState(true);
  const [showSummaries, setShowSummaries] = useState(true);
  const [items, setItems] = useState<OutlineItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [hasAttempted, setHasAttempted] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    let disposed = false;

    void API.getSourceContent(projectName, CREATIVE_OUTLINE_FILENAME)
      .then((savedContent) => {
        if (disposed) return;
        const savedItems = parseSavedCreativeOutline(savedContent);
        const sourceChapters = parseSourceChapters(content);
        const normalizedItems = mergeOutlineWithSourceChapters(sourceChapters, savedItems);
        setItems(normalizedItems);
        setHasAttempted(normalizedItems.length > 0);
        setError(false);
      })
      .catch(() => {
        if (disposed) return;
        setItems([]);
        setHasAttempted(false);
        setError(false);
      });

    return () => {
      disposed = true;
    };
  }, [content, projectName]);

  const saveItems = useCallback(
    async (outlineItems: OutlineItem[]) => {
      if (outlineItems.length === 0 || saving) return false;
      setSaving(true);
      try {
        const document = buildCreativeOutlineDocument(outlineItems, filename);
        await API.saveSourceFile(projectName, CREATIVE_OUTLINE_FILENAME, JSON.stringify(document, null, 2));
        useAppStore.getState().invalidateSourceFiles();
        useAppStore.getState().pushToast(t("creative_outline_saved"), "success");
        return true;
      } catch (saveError) {
        useAppStore
          .getState()
          .pushToast(t("creative_outline_save_failed", { message: errMsg(saveError) }), "error");
        return false;
      } finally {
        setSaving(false);
      }
    },
    [filename, projectName, saving, t],
  );

  const handleExtract = useCallback(async () => {
    const notificationId = useAppStore.getState().pushWorkspaceNotification({
      text: t("creative_outline_extract_started", { filename }),
      tone: "info",
    });
    setLoading(true);
    setHasAttempted(true);
    setError(false);
    try {
      const chunks = splitSourceIntoChunks(content);
      if (chunks.length === 0) {
        setError(true);
        useAppStore.getState().updateWorkspaceNotification(notificationId, {
          text: t("creative_outline_extract_failed", { filename }),
          tone: "error",
        });
        return;
      }

      const sourceChapters = parseSourceChapters(content);
      const batches: OutlineItem[][] = [];
      for (let index = 0; index < chunks.length; index += 1) {
        const result = await requestOutline(projectName, filename, chunks[index], index + 1, chunks.length);
        batches.push(parseOutline(result.content));
        setItems(mergeOutlineWithSourceChapters(sourceChapters, mergeOutlineItems(batches)));
        useAppStore.getState().updateWorkspaceNotification(notificationId, {
          text: t("creative_outline_extract_progress", {
            filename,
            current: index + 1,
            total: chunks.length,
          }),
        });
      }
      const extractedItems = mergeOutlineWithSourceChapters(sourceChapters, mergeOutlineItems(batches));
      if (extractedItems.length === 0) {
        setError(true);
        useAppStore.getState().updateWorkspaceNotification(notificationId, {
          text: t("creative_outline_extract_failed", { filename }),
          tone: "error",
        });
        return;
      }
      setItems(extractedItems);
      const saved = await saveItems(extractedItems);
      useAppStore.getState().updateWorkspaceNotification(notificationId, {
        text: saved
          ? t("creative_outline_extract_completed", { filename })
          : t("creative_outline_extract_failed", { filename }),
        tone: saved ? "success" : "error",
      });
    } catch {
      setError(true);
      useAppStore.getState().updateWorkspaceNotification(notificationId, {
        text: t("creative_outline_extract_failed", { filename }),
        tone: "error",
      });
    } finally {
      setLoading(false);
    }
  }, [content, filename, projectName, saveItems, t]);

  const handleSave = useCallback(async () => {
    if (items.length === 0 || saving) return;
    await saveItems(items);
  }, [items, saveItems, saving]);

  return (
    <aside
      className={
        expanded
          ? "flex w-[276px] shrink-0 flex-col border-r border-hairline-soft bg-bg-grad-a/35"
          : "flex w-11 shrink-0 flex-col items-center border-r border-hairline-soft bg-bg-grad-a/35"
      }
      aria-label={t("creative_outline_title")}
    >
      <div
        className={
          expanded
            ? "flex items-center gap-2 border-b border-hairline-soft px-3 py-3"
            : "flex flex-col items-center gap-2 py-3"
        }
      >
        <ListTree className="h-4 w-4 shrink-0 text-accent-2" aria-hidden="true" />
        {expanded && (
          <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-text">
            {t("creative_outline_title")}
          </span>
        )}
        {expanded && (
          <button
            type="button"
            onClick={() => setShowSummaries((value) => !value)}
            aria-pressed={showSummaries}
            aria-label={t(showSummaries ? "creative_outline_hide_summaries" : "creative_outline_show_summaries")}
            title={t(showSummaries ? "creative_outline_hide_summaries" : "creative_outline_show_summaries")}
            className="rounded-md p-1.5 text-text-4 transition-colors hover:bg-bg-grad-a hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            {showSummaries ? <Eye className="h-3.5 w-3.5" aria-hidden /> : <EyeOff className="h-3.5 w-3.5" aria-hidden />}
          </button>
        )}
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="rounded-md p-1.5 text-text-4 transition-colors hover:bg-bg-grad-a hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-label={t(expanded ? "creative_outline_collapse" : "creative_outline_expand")}
          title={t(expanded ? "creative_outline_collapse" : "creative_outline_expand")}
        >
          {expanded ? <ChevronLeft className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </button>
      </div>

      {expanded && (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="grid grid-cols-2 border-b border-hairline-soft p-3">
            <button
              type="button"
              onClick={() => void handleExtract()}
              disabled={loading || !content.trim()}
              className="focus-ring flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-2 text-[11.5px] font-semibold text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : hasAttempted ? (
                <RefreshCw className="h-3.5 w-3.5" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              <span>{t("creative_outline_ai_extract")}</span>
            </button>
            {items.length > 0 && (
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={loading || saving}
                className="focus-ring flex w-full items-center justify-center gap-2 rounded-md border border-hairline-soft px-3 py-2 text-[11.5px] font-semibold text-text-2 transition-colors hover:bg-bg-grad-a disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                <span>{t("creative_outline_save")}</span>
              </button>
            )}
          </div>

          <div
            className="source-file-scroll min-h-0 flex-1 overflow-y-scroll px-3 py-3"
            style={{
              scrollbarWidth: "auto",
              scrollbarColor: "var(--color-text-4) var(--color-bg-2)",
            }}
          >
            {loading ? (
              <div className="flex items-center gap-2 py-5 text-[11.5px] text-text-4">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>{t("creative_outline_loading")}</span>
              </div>
            ) : error && items.length === 0 ? (
              <p className="rounded-md border border-warm-ring/40 bg-warm-ring/10 px-3 py-2 text-[11px] leading-5 text-warm-bright">
                {t("creative_outline_ai_error")}
              </p>
            ) : items.length > 0 ? (
              <ol className="space-y-1">
                {items.map((item, index) => (
                  <li key={item.title + "-" + index}>
                    <button
                      type="button"
                      onClick={() => onSelectItem(item)}
                      className="focus-ring w-full rounded-md px-2.5 py-2 text-left transition-colors hover:bg-bg-grad-a"
                      title={item.title}
                    >
                      <div className="flex gap-2 text-[12px] leading-5 text-text-2">
                        <span className="shrink-0 font-mono text-[10px] text-accent-2">
                          {String(item.chapter ?? index + 1).padStart(2, "0")}
                        </span>
                        <span className="min-w-0 font-medium">{item.title}</span>
                      </div>
                      {showSummaries && item.summary && (
                        <p className="mt-1 pl-7 text-[10.5px] leading-5 text-text-4">{item.summary}</p>
                      )}
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="flex flex-col items-center px-3 py-8 text-center">
                <Sparkles className="h-5 w-5 text-accent-2/70" />
                <p className="mt-3 text-[11px] leading-5 text-text-4">
                  {t(hasAttempted ? "creative_outline_ai_empty" : "creative_outline_ai_hint")}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
