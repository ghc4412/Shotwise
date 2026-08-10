import { Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppStore } from "@/stores/app-store";

interface ThemeToggleProps {
  compact?: boolean;
}

export function ThemeToggle({ compact = false }: ThemeToggleProps) {
  const { t } = useTranslation("common");
  const theme = useAppStore((state) => state.theme);
  const toggleTheme = useAppStore((state) => state.toggleTheme);
  const isLight = theme === "light";
  const label = isLight ? t("theme_dark") : t("theme_light");

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className={`theme-toggle ${compact ? "theme-toggle-compact" : ""}`}
      aria-label={label}
      title={label}
      aria-pressed={isLight}
    >
      <span className="theme-toggle-icon" aria-hidden="true">
        {isLight ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
      </span>
      {!compact ? <span className="hidden xl:inline">{label}</span> : null}
    </button>
  );
}
