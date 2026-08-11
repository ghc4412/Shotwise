import { useEffect, useRef, useState } from "react";
import { Check, Palette } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  ACCENT_THEME_IDS,
  useAppStore,
  type AccentThemeId,
} from "@/stores/app-store";

/** 6 套 accent 主题的展示元数据：i18n 名称 key + 色板色（与 index.css 的 dark 值保持一致） */
export const ACCENT_THEME_META: Record<AccentThemeId, { labelKey: string; swatch: string }> = {
  aurora: { labelKey: "accent_aurora", swatch: "oklch(0.83 0.14 200)" },
  jade: { labelKey: "accent_jade", swatch: "oklch(0.80 0.15 165)" },
  violet: { labelKey: "accent_violet", swatch: "oklch(0.80 0.15 285)" },
  crimson: { labelKey: "accent_crimson", swatch: "oklch(0.80 0.16 355)" },
  amber: { labelKey: "accent_amber", swatch: "oklch(0.82 0.15 75)" },
  ocean: { labelKey: "accent_ocean", swatch: "oklch(0.80 0.13 230)" },
};

export function ThemeAccentPicker() {
  const { t } = useTranslation("common");
  const accentTheme = useAppStore((s) => s.accentTheme);
  const setAccentTheme = useAppStore((s) => s.setAccentTheme);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // 点击面板外或 Esc 关闭
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const current = ACCENT_THEME_META[accentTheme];

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="theme-toggle theme-toggle-compact"
        aria-label={t("accent_theme")}
        title={t("accent_theme")}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="theme-toggle-icon" aria-hidden="true">
          <Palette className="h-3.5 w-3.5" />
        </span>
        <span
          aria-hidden
          className="absolute right-[5px] top-[5px] h-1.5 w-1.5 rounded-full"
          style={{
            background: current.swatch,
            boxShadow: `0 0 6px ${current.swatch}`,
          }}
        />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={t("accent_theme")}
          className="absolute right-0 top-[calc(100%+6px)] z-50 w-[172px] rounded-lg border p-1.5"
          style={{
            borderColor: "var(--color-hairline-strong)",
            background: "color-mix(in oklab, var(--color-surface-2) 92%, transparent)",
            boxShadow:
              "0 18px 44px -18px oklch(0 0 0 / 0.7), inset 0 1px 0 oklch(1 0 0 / 0.06)",
            backdropFilter: "blur(14px)",
          }}
        >
          {ACCENT_THEME_IDS.map((id) => {
            const meta = ACCENT_THEME_META[id];
            const selected = id === accentTheme;
            return (
              <button
                key={id}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  setAccentTheme(id);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[12px] transition-colors hover:bg-[oklch(1_0_0_/_0.06)]"
                style={{ color: "var(--color-text-2)" }}
              >
                <span
                  aria-hidden
                  className="grid h-4 w-4 shrink-0 place-items-center rounded-full"
                  style={{
                    background: `linear-gradient(135deg, ${meta.swatch}, color-mix(in oklab, ${meta.swatch} 55%, white))`,
                    boxShadow: selected
                      ? `0 0 0 2px var(--color-surface-2), 0 0 0 3.5px ${meta.swatch}`
                      : "inset 0 1px 0 oklch(1 0 0 / 0.25)",
                  }}
                />
                <span className="flex-1 truncate">{t(meta.labelKey)}</span>
                {selected && (
                  <Check
                    className="h-3.5 w-3.5"
                    style={{ color: "var(--color-accent-2)" }}
                    aria-hidden
                  />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
