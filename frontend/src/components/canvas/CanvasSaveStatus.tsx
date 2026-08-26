import { RefreshCw, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { CanvasPersistenceStatus } from "./canvasPersistence";

interface CanvasSaveStatusProps {
  status: CanvasPersistenceStatus;
  onSave: () => Promise<boolean>;
  onRetry: () => Promise<boolean>;
  conflict?: boolean;
}

export function CanvasSaveStatus({ status, onSave, onRetry, conflict = false }: CanvasSaveStatusProps) {
  const { t } = useTranslation("dashboard");
  const isSaving = status === "saving";
  const failed = status === "error" || conflict;
  const label = isSaving ? t("canvas.saveStatus.saving") : failed ? t("canvas.saveStatus.retry") : t("canvas.saveStatus.saveNow");

  return (
    <>
      <button
        type="button"
        className={"focus-ring inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[10px] font-medium transition-colors disabled:cursor-wait disabled:opacity-60 " + (failed ? "border-[#f2b8b5] bg-[#fff7f6] text-[#b42318] hover:bg-[#fff0ee]" : "border-[#dfe5ed] bg-white text-[#596579] hover:border-[#c8c1ff] hover:bg-[#faf9ff]")}
        disabled={isSaving}
        onClick={() => void (failed ? onRetry() : onSave())}
        aria-label={label}
        title={t("canvas.saveStatus.shortcutHint")}>
        {failed ? <RefreshCw className="h-3.5 w-3.5" aria-hidden /> : <Save className={"h-3.5 w-3.5 " + (isSaving ? "animate-pulse" : "")} aria-hidden />}
        <span>{label}</span>
      </button>
      <span className="sr-only" aria-live="polite" role="status" aria-atomic="true">
        {isSaving ? t("canvas.saveStatus.saving") : failed ? t("canvas.saveStatus.failed") : ""}
      </span>
    </>
  );
}
