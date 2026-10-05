import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, ImagePlus, Network, Package, Plus, RefreshCw } from "lucide-react";
import { Popover } from "@/components/ui/Popover";

export type GenerateDesignsMode = "missing" | "all";

interface Props {
  title: string;
  count: number;
  /** 未提供时隐藏「新增」入口（如只读展示的引导演示项目）。 */
  onAdd?: () => void;
  /** 未提供时隐藏「从资产库选择」入口（如不入全局资产的类型）。 */
  onPickFromLibrary?: () => void;
  /** 一键提交当前集合的设计图生成任务。 */
  onGenerateDesigns?: (mode: GenerateDesignsMode) => void;
  generateDesignsDisabled?: boolean;
  /** 提供时启用缺失/全量二选一菜单；未提供时保持旧的直接生成行为。 */
  pendingDesignCount?: number;
  onViewRelations?: () => void;
}

/**
 * GalleryToolbar — v3 视觉：玻璃栏 + display-serif 标题 + accent CTA。
 */
export function GalleryToolbar({
  title,
  count,
  onAdd,
  onPickFromLibrary,
  onGenerateDesigns,
  generateDesignsDisabled = false,
  pendingDesignCount,
  onViewRelations,
}: Props) {
  const { t } = useTranslation(["dashboard", "assets"]);
  const [generateMenuOpen, setGenerateMenuOpen] = useState(false);
  const generateButtonRef = useRef<HTMLButtonElement>(null);
  const hasGenerateChoice = pendingDesignCount !== undefined;
  const pendingCount = pendingDesignCount ?? 0;

  const runGenerate = (mode: GenerateDesignsMode) => {
    setGenerateMenuOpen(false);
    onGenerateDesigns?.(mode);
  };

  const handleGenerateClick = () => {
    if (!hasGenerateChoice) {
      runGenerate("all");
      return;
    }
    setGenerateMenuOpen((open) => !open);
  };

  return (
    <div
      className="sticky top-0 z-10 flex items-center gap-3 px-5 py-3"
      style={{
        background:
          "var(--panel-card-bg)",
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        borderBottom: "1px solid var(--color-hairline-soft)",
      }}
    >
      {/* Tiny accent dash before the title — establishes editorial rhythm */}
      <span
        aria-hidden
        className="h-3 w-[3px] rounded-full"
        style={{
          background:
            "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
          boxShadow: "0 0 8px var(--color-accent-glow)",
        }}
      />
      <h2
        className="display-serif text-[15px] font-semibold tracking-tight"
        style={{ color: "var(--color-text)" }}
      >
        {title}
      </h2>
      <span
        className="num inline-flex items-center justify-center rounded-md px-1.5 py-[2px] text-[10.5px]"
        style={{
          color: "var(--color-text-3)",
          background: "var(--color-accent-dim)",
          border: "1px solid var(--color-accent-soft)",
          minWidth: 22,
        }}
      >
        {String(count).padStart(2, "0")}
      </span>
      <div className="flex-1" />
      {onGenerateDesigns && (
        <button
          ref={generateButtonRef}
          type="button"
          onClick={handleGenerateClick}
          disabled={generateDesignsDisabled}
          aria-haspopup={hasGenerateChoice ? "menu" : undefined}
          aria-expanded={hasGenerateChoice ? generateMenuOpen && !generateDesignsDisabled : undefined}
          className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          style={{ color: "var(--color-text-2)", border: "1px solid var(--color-accent-soft)", background: "var(--color-accent-dim)" }}
          title={t("dashboard:generate_design_image")}
          aria-label={t("dashboard:generate_design_image")}
        >
          <ImagePlus className="h-3.5 w-3.5" />
          {t("dashboard:generate_design_image")}
          {hasGenerateChoice && (
            <ChevronDown aria-hidden className={`h-3 w-3 transition-transform ${generateMenuOpen ? "rotate-180" : ""}`} />
          )}
        </button>
      )}
      {hasGenerateChoice && (
        <Popover
          open={generateMenuOpen && !generateDesignsDisabled}
          onClose={() => setGenerateMenuOpen(false)}
          anchorRef={generateButtonRef}
          align="end"
          sideOffset={6}
          width="w-[340px]"
          className="max-w-[calc(100vw-24px)] overflow-hidden rounded-xl shadow-[0_18px_48px_-16px_oklch(0_0_0/0.65)]"
          style={{
            background: "var(--panel-dropdown-bg)",
            border: "1px solid var(--color-hairline)",
            backdropFilter: "blur(14px)",
            WebkitBackdropFilter: "blur(14px)",
          }}
        >
          <div
            className="border-b px-3.5 py-3"
            style={{ borderColor: "var(--color-hairline-soft)" }}
          >
            <div className="text-[12px] font-semibold" style={{ color: "var(--color-text)" }}>
              {t("dashboard:generate_designs_menu_title")}
            </div>
            <div className="mt-0.5 text-[10.5px] leading-4" style={{ color: "var(--color-text-4)" }}>
              {t("dashboard:generate_designs_menu_hint")}
            </div>
          </div>

          <div role="menu" aria-label={t("dashboard:generate_designs_menu_title")} className="p-1.5">
            <button
              type="button"
              role="menuitem"
              disabled={pendingCount === 0}
              onClick={() => runGenerate("missing")}
              className="flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45"
              style={{ background: pendingCount > 0 ? "var(--color-accent-dim)" : "transparent" }}
            >
              <span
                aria-hidden
                className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md"
                style={{
                  color: "var(--color-accent-2)",
                  background: "var(--color-accent-dim)",
                  border: "1px solid var(--color-accent-soft)",
                }}
              >
                {pendingCount === 0 ? <Check className="h-3.5 w-3.5" /> : <ImagePlus className="h-3.5 w-3.5" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="text-[12px] font-medium" style={{ color: "var(--color-text)" }}>
                    {t("dashboard:generate_designs_missing_title")}
                  </span>
                  <span
                    className="rounded-full px-1.5 py-0.5 text-[9.5px] font-medium"
                    style={{
                      color: pendingCount > 0 ? "var(--color-accent-2)" : "var(--color-text-4)",
                      background: pendingCount > 0 ? "var(--color-accent-dim)" : "var(--color-shell-field)",
                    }}
                  >
                    {pendingCount > 0
                      ? t("dashboard:generate_designs_missing_count", { count: pendingCount })
                      : t("dashboard:generate_designs_missing_complete")}
                  </span>
                </span>
                <span className="mt-0.5 block text-[10.5px] leading-4" style={{ color: "var(--color-text-3)" }}>
                  {t("dashboard:generate_designs_missing_desc")}
                </span>
              </span>
            </button>

            <button
              type="button"
              role="menuitem"
              disabled={count === 0}
              onClick={() => runGenerate("all")}
              className="mt-1 flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2.5 text-left transition-colors hover:bg-[oklch(1_0_0_/_0.04)] disabled:cursor-not-allowed disabled:opacity-45"
            >
              <span
                aria-hidden
                className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md"
                style={{
                  color: "var(--color-danger-2)",
                  background: "var(--color-danger-soft)",
                  border: "1px solid var(--color-danger-ring)",
                }}
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="text-[12px] font-medium" style={{ color: "var(--color-text)" }}>
                    {t("dashboard:generate_designs_all_title")}
                  </span>
                  <span
                    className="rounded-full px-1.5 py-0.5 text-[9.5px] font-medium"
                    style={{ color: "var(--color-danger-2)", background: "var(--color-danger-soft)" }}
                  >
                    {t("dashboard:generate_designs_all_count", { count })}
                  </span>
                </span>
                <span className="mt-0.5 block text-[10.5px] leading-4" style={{ color: "var(--color-text-3)" }}>
                  {t("dashboard:generate_designs_all_desc")}
                </span>
              </span>
            </button>
          </div>
        </Popover>
      )}
      {onViewRelations && (
        <button
          type="button"
          onClick={onViewRelations}
          className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] transition-colors"
          style={{ color: "var(--color-text-2)", border: "1px solid var(--color-hairline)", background: "var(--color-shell-btn)" }}
          title={t("dashboard:view_character_relations")}
        >
          <Network className="h-3.5 w-3.5" />
          {t("dashboard:view_character_relations")}
        </button>
      )}
      {onPickFromLibrary && (
      <button
        type="button"
        onClick={onPickFromLibrary}
        className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] transition-colors"
        style={{
          color: "var(--color-text-2)",
          border: "1px solid var(--color-hairline)",
          background: "var(--color-shell-btn)",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "oklch(0.26 0.013 265 / 0.7)";
          e.currentTarget.style.color = "var(--color-text)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "var(--color-shell-btn)";
          e.currentTarget.style.color = "var(--color-text-2)";
        }}
      >
        <Package className="h-3.5 w-3.5" />
        {t("assets:from_library")}
      </button>
      )}
      {onAdd && (
      <button
        type="button"
        onClick={onAdd}
        className="focus-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-[11.5px] font-medium transition-transform"
        style={{
          color: "oklch(0.14 0 0)",
          background:
            "linear-gradient(135deg, var(--color-accent-2), var(--color-accent))",
          boxShadow:
            "inset 0 1px 0 oklch(1 0 0 / 0.35), 0 6px 18px -4px var(--color-accent-glow), 0 0 0 1px var(--color-accent-soft)",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.transform = "translateY(-1px)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = "translateY(0)";
        }}
      >
        <Plus className="h-3.5 w-3.5" />
        {title}
      </button>
      )}
    </div>
  );
}
