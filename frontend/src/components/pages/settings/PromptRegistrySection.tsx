import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, FileText, Loader2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { StreamMarkdown } from "@/components/copilot/StreamMarkdown";
import { CARD_STYLE, INPUT_CLS } from "@/components/ui/darkroom-tokens";
import type {
  PromptTemplateDetailResponse,
  PromptTemplateGroup,
  PromptTemplateSummary,
} from "@/types/prompt-registry";

/** 分组展示顺序，与后端 PROMPT_TEMPLATE_GROUPS 一致。 */
const GROUP_ORDER: PromptTemplateGroup[] = ["system", "agent", "skill", "reference"];

const GROUP_LABEL_KEY: Record<PromptTemplateGroup, string> = {
  system: "prompt_registry_group_system",
  agent: "prompt_registry_group_agent",
  skill: "prompt_registry_group_skill",
  reference: "prompt_registry_group_reference",
};

const MODE_LABEL_KEY: Record<string, string> = {
  drama: "prompt_registry_mode_drama",
  narration: "prompt_registry_mode_narration",
  ad: "prompt_registry_mode_ad",
};

export function PromptRegistrySection() {
  const { t } = useTranslation("dashboard");
  const [templates, setTemplates] = useState<PromptTemplateSummary[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [detail, setDetail] = useState<PromptTemplateDetailResponse | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const { templates: items } = await API.getPromptRegistry();
        if (cancelled) return;
        setTemplates(items);
        setSelectedPath((current) => (current && items.some((item) => item.path === current) ? current : items[0]?.path ?? null));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : t("prompt_registry_load_failed"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    // Loading server-backed settings on mount is an intentional effect.
    void load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (!selectedPath) {
        setDetail(null);
        return;
      }
      setDetailLoading(true);
      try {
        const next = await API.getPromptTemplate(selectedPath);
        if (!cancelled) {
          setDetail(next);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setDetail(null);
          setError(err instanceof Error ? err.message : t("prompt_registry_load_failed"));
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    };
    // 选中项变化时重新拉取详情，属于数据加载而非派生状态。
    void load();
    return () => {
      cancelled = true;
    };
  }, [selectedPath, t]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return templates;
    return templates.filter((item) =>
      [item.title, item.path, item.description].some((value) => value.toLowerCase().includes(needle)),
    );
  }, [templates, query]);

  const groups = useMemo(
    () =>
      GROUP_ORDER.map((group) => ({
        group,
        items: filtered.filter((item) => item.group === group),
      })).filter((bucket) => bucket.items.length > 0),
    [filtered],
  );

  if (loading) {
    return (
      <div className="rounded-[10px] border border-hairline px-5 py-6" style={CARD_STYLE}>
        <div className="flex items-center gap-2 text-[12.5px] text-text-3">
          <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" />
          <span className="font-mono text-[10.5px] uppercase tracking-[0.14em]">
            {t("prompt_registry_loading")}
          </span>
        </div>
      </div>
    );
  }

  return (
    <section className="space-y-5">
      <div className="rounded-[10px] border border-hairline p-5" style={CARD_STYLE}>
        <div className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-accent-2">
          {t("prompt_registry_title")}
        </div>
        <p className="mt-2 text-[12.5px] leading-[1.6] text-text-3">{t("prompt_registry_desc")}</p>
      </div>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-1.5 rounded-[8px] border px-4 py-3 text-[12px]"
          style={{
            borderColor: "var(--color-warm-ring)",
            background: "var(--color-warm-tint)",
            color: "var(--color-warm-bright)",
          }}
        >
          <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {templates.length === 0 ? (
        <div className="rounded-[10px] border border-hairline px-5 py-6 text-[12.5px] text-text-3" style={CARD_STYLE}>
          {t("prompt_registry_empty")}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
          <div className="space-y-3">
            <label className="relative block">
              <span className="sr-only">{t("prompt_registry_search_placeholder")}</span>
              <Search
                aria-hidden
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-3"
              />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("prompt_registry_search_placeholder")}
                className={`${INPUT_CLS} pl-8`}
              />
            </label>

            <nav aria-label={t("prompt_registry_title")} className="space-y-4">
              {groups.map((bucket) => (
                <div key={bucket.group} className="space-y-1">
                  <div className="px-1 font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-text-3">
                    {t(GROUP_LABEL_KEY[bucket.group])}
                  </div>
                  <ul className="space-y-1">
                    {bucket.items.map((item) => {
                      const isActive = item.path === selectedPath;
                      return (
                        <li key={item.path}>
                          <button
                            type="button"
                            onClick={() => setSelectedPath(item.path)}
                            aria-current={isActive ? "true" : undefined}
                            className={
                              "w-full rounded-md border px-2.5 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent " +
                              (isActive
                                ? "border-accent/35 bg-accent-dim text-text"
                                : "border-transparent text-text-3 hover:border-hairline-soft hover:bg-bg-grad-a/55 hover:text-text")
                            }
                          >
                            <span className="flex items-center gap-2">
                              <FileText aria-hidden className="h-3.5 w-3.5 shrink-0" />
                              <span className="truncate text-[12.5px]">{item.title}</span>
                            </span>
                            {item.content_mode && (
                              <span className="mt-1 block font-mono text-[10px] uppercase tracking-[0.12em] text-text-3">
                                {t(MODE_LABEL_KEY[item.content_mode] ?? "prompt_registry_mode_drama")}
                              </span>
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
              {groups.length === 0 && (
                <p className="px-1 text-[12px] text-text-3">{t("prompt_registry_no_match")}</p>
              )}
            </nav>
          </div>

          <div className="min-w-0 rounded-[10px] border border-hairline p-5" style={CARD_STYLE}>
            {detailLoading && (
              <div className="flex items-center gap-2 text-[12.5px] text-text-3">
                <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" />
                <span className="font-mono text-[10.5px] uppercase tracking-[0.14em]">
                  {t("prompt_registry_loading")}
                </span>
              </div>
            )}

            {!detailLoading && !detail && (
              <p className="text-[12.5px] text-text-3">{t("prompt_registry_select_hint")}</p>
            )}

            {!detailLoading && detail && (
              <article className="space-y-3">
                <header className="space-y-1.5">
                  <h3 className="text-[14px] font-medium text-text">{detail.template.title}</h3>
                  <p className="break-all font-mono text-[10.5px] text-text-3">{detail.template.path}</p>
                  {detail.template.description && (
                    <p className="text-[12px] leading-[1.55] text-text-3">{detail.template.description}</p>
                  )}
                  <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-text-3">
                    {t("prompt_registry_size", { count: detail.template.char_count })}
                  </p>
                </header>
                <div className="markdown-body text-[13px] leading-[1.65] text-text-2">
                  <StreamMarkdown content={detail.content} />
                </div>
              </article>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
