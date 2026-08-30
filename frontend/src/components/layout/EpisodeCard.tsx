import { useEffect, useRef, useState } from "react";
import { Clapperboard, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { EpisodeMeta } from "@/types";
import { useCostStore } from "@/stores/cost-store";
import { totalBreakdown } from "@/utils/cost-format";

interface EpisodeCardProps {
  ep: EpisodeMeta;
  active: boolean;
  onClick: () => void;
  onDelete?: () => void;
  onEditNumber?: () => void;
  /** ad 项目隐藏集语义：徽标不显示 E{n}，改用场记板图标。 */
  showEpisodeBadge?: boolean;
  /** ep.title 为空时的兜底显示文本（ad 项目用项目标题）。 */
  fallbackTitle?: string;
}

const STATUS_COLOR: Record<string, string> = {
  completed: "oklch(0.74 0.08 155)",
  in_production: "var(--color-accent)",
  scripted: "oklch(0.60 0.02 250)",
  draft: "oklch(0.46 0.01 250)",
  missing: "oklch(0.46 0.01 250)",
};

const STATUS_LABEL_KEY: Record<string, string> = {
  completed: "dashboard:episode_status_done",
  in_production: "dashboard:episode_status_active",
  scripted: "dashboard:episode_status_draft",
  draft: "dashboard:episode_status_draft",
  missing: "dashboard:episode_status_idea",
};

/** 侧栏分集卡片：导航按钮与更多操作按钮并列，避免嵌套 button。 */
export function EpisodeCard({
  ep,
  active,
  onClick,
  onDelete,
  onEditNumber,
  showEpisodeBadge = true,
  fallbackTitle,
}: EpisodeCardProps) {
  const { t } = useTranslation(["dashboard"]);
  const [menuOpen, setMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const status = ep.status ?? "draft";
  const statusColor = STATUS_COLOR[status] ?? STATUS_COLOR.draft;
  const statusLabel = t(STATUS_LABEL_KEY[status] ?? STATUS_LABEL_KEY.draft);
  const isActive = status === "in_production";
  const displayEpisode = ep.display_episode ?? ep.episode;

  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  const totalShots = ep.scenes_count ?? ep.storyboards?.total ?? ep.units_count ?? 0;
  const completedShots = ep.videos?.completed ?? 0;
  const progress = totalShots > 0 ? Math.round((completedShots / totalShots) * 100) : 0;
  const showProgress = totalShots > 0 && (active || progress > 0);
  const episodeCost = useCostStore((s) => s.getEpisodeCost(ep.episode));
  const spentBreakdown = episodeCost ? totalBreakdown(episodeCost.totals.actual) : null;
  const spentEntries = spentBreakdown ? Object.entries(spentBreakdown).filter(([, value]) => value > 0) : [];
  const primaryCost = spentEntries.find(([currency]) => currency === "USD") ?? spentEntries[0];
  const costText = primaryCost
    ? `${primaryCost[0] === "CNY" ? "¥" : "$"}${primaryCost[1].toFixed(2)}`
    : null;
  const duration = ep.duration_seconds ?? 0;
  const durationLabel = duration > 0 ? `${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, "0")}` : null;

  return (
    <div
      className="relative w-full rounded-lg transition-colors"
      style={{
        marginBottom: 3,
        background: active
          ? "linear-gradient(180deg, var(--color-shell-card-a), var(--color-shell-card-b))"
          : "transparent",
        border: active ? "1px solid var(--color-accent-soft)" : "1px solid transparent",
        boxShadow: active
          ? "0 0 0 1px var(--color-accent-soft), 0 4px 12px -6px oklch(0 0 0 / 0.5), inset 0 1px 0 oklch(1 0 0 / 0.04)"
          : "none",
      }}
      onMouseEnter={(event) => {
        if (!active) event.currentTarget.style.background = "var(--color-shell-card-hover)";
      }}
      onMouseLeave={(event) => {
        if (!active) event.currentTarget.style.background = "transparent";
      }}
    >
      <button
        type="button"
        onClick={onClick}
        className="grid w-full items-center gap-2.5 rounded-lg p-2 text-left focus-ring"
        style={{ gridTemplateColumns: "auto 1fr auto", paddingRight: onDelete ? 38 : 8 }}
        aria-current={active ? "page" : undefined}
      >
        <div
          className="num grid h-[34px] w-[34px] shrink-0 place-items-center rounded-md text-[11px] font-bold leading-none"
          style={{
            background: active
              ? "linear-gradient(135deg, var(--color-accent) 0%, oklch(0.45 0.12 285) 100%)"
              : "linear-gradient(180deg, var(--color-shell-card-badge), var(--color-shell-card-b))",
            color: active ? "oklch(0.14 0 0)" : "var(--color-text-3)",
            boxShadow: active
              ? "inset 0 1px 0 oklch(1 0 0 / 0.25), 0 0 0 1px oklch(1 0 0 / 0.12), 0 2px 6px -2px var(--color-accent-glow)"
              : "inset 0 1px 0 oklch(1 0 0 / 0.04), inset 0 0 0 1px var(--color-hairline-soft)",
          }}
        >
          {showEpisodeBadge ? `E${displayEpisode}` : <Clapperboard className="h-4 w-4" aria-hidden />}
        </div>
        <div className="min-w-0">
          <div
            className="truncate text-[13px]"
            style={{ color: active ? "var(--color-text)" : "var(--color-text-2)", fontWeight: active ? 600 : 500 }}
          >
            {ep.title || fallbackTitle || ""}
          </div>
          <div className="mt-[3px] flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 text-[10.5px]" style={{ color: "var(--color-text-4)" }}>
              <span className={`h-[5px] w-[5px] rounded-full ${isActive ? "animate-shot-pulse" : ""}`} style={{ background: statusColor }} />
              {statusLabel}
            </span>
            {totalShots > 0 && (
              <>
                <span aria-hidden="true" className="h-px w-px rounded" style={{ background: "var(--color-hairline)", width: 2, height: 2 }} />
                <span className="num text-[10.5px]" style={{ color: "var(--color-text-4)" }}>
                  {totalShots}{durationLabel ? ` · ${durationLabel}` : ""}
                </span>
              </>
            )}
          </div>
          {showProgress && (
            <div className="mt-[5px] h-[2px] overflow-hidden rounded-[1px]" style={{ background: "var(--color-shell-track)" }}>
              <div className="h-full" style={{ width: `${progress}%`, background: "linear-gradient(90deg, var(--color-accent), var(--color-accent-2))", boxShadow: "0 0 6px var(--color-accent-glow)" }} />
            </div>
          )}
        </div>
        {costText && <span className="num self-start pt-0.5 text-[10.5px]" style={{ color: active ? "var(--color-accent-2)" : "var(--color-text-4)" }}>{costText}</span>}
      </button>

      {onDelete && (
        <div className="absolute right-1.5 top-1.5 z-[2]">
          <button
            ref={triggerRef}
            type="button"
            aria-label={`${t("more_actions")} — E${displayEpisode}`}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
            className="grid h-7 w-7 place-items-center rounded-md text-text-3 transition-colors hover:bg-[var(--color-shell-btn-2)] hover:text-text focus-ring"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
          {menuOpen && (
            <div ref={menuRef} className="absolute right-0 top-[calc(100%+4px)] min-w-[142px] overflow-hidden rounded-md border border-hairline bg-bg-grad-a/95 shadow-[0_18px_40px_-22px_oklch(0_0_0_/_0.7)] backdrop-blur">
              {onEditNumber && (
                <button type="button" onClick={() => { setMenuOpen(false); onEditNumber(); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-text-2 hover:bg-[var(--color-shell-hover)] focus-visible:outline-none">
                  <Pencil className="h-3.5 w-3.5" />{t("edit_episode_number")}
                </button>
              )}
              <button type="button" onClick={() => { setMenuOpen(false); onDelete(); }} aria-label={`${t("delete_episode")} — E${displayEpisode}`} className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-danger-2 hover:bg-danger-soft focus-visible:outline-none">
                <Trash2 className="h-3.5 w-3.5" />{t("delete_episode")}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
