import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { CARD_STYLE } from "@/components/ui/darkroom-tokens";
import { useAppStore } from "@/stores/app-store";
import { ASSISTANT_SKINS } from "@/utils/assistant-skins";

/**
 * 外观设置：智能体角标（缩角角标 + 助手头部图标）皮肤选择。
 * 皮肤为纯预设集合（图标 + 渐变配色），选择即时生效并持久化。
 */
export function AppearanceSection() {
  const { t } = useTranslation("dashboard");
  const assistantSkin = useAppStore((s) => s.assistantSkin);
  const setAssistantSkin = useAppStore((s) => s.setAssistantSkin);
  const persistAssistantSkin = useAppStore((s) => s.persistAssistantSkin);

  return (
    <section className="space-y-6">
      <div className="rounded-[12px] border border-hairline p-6" style={CARD_STYLE}>
        <div className="mb-3 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-accent-2">
          {t("appearance_agent_skin_title")}
        </div>
        <p className="mb-5 max-w-[520px] text-[12.5px] leading-relaxed text-text-2">
          {t("appearance_agent_skin_desc")}
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {ASSISTANT_SKINS.map((skin) => {
            const selected = skin.id === assistantSkin;
            const Icon = skin.icon;
            return (
              <button
                key={skin.id}
                type="button"
                onClick={() => {
                  setAssistantSkin(skin.id);
                  persistAssistantSkin();
                }}
                aria-pressed={selected}
                className={`group relative flex flex-col items-center gap-2.5 rounded-[10px] border p-4 transition-colors focus-ring ${
                  selected
                    ? "border-accent-soft bg-accent-dim/40"
                    : "border-hairline hover:border-hairline-strong"
                }`}
                style={
                  selected
                    ? { boxShadow: "0 0 0 1px var(--color-accent-soft)" }
                    : undefined
                }
              >
                <span
                  className="grid h-10 w-10 place-items-center rounded-xl"
                  style={{
                    background: `linear-gradient(135deg, ${skin.from}, ${skin.to})`,
                    color: "oklch(0.12 0 0)",
                  }}
                >
                  <Icon className="h-5 w-5" />
                </span>
                <span className="text-[12px] text-text-2">{t(skin.labelKey)}</span>
                {selected && (
                  <span
                    className="absolute right-2 top-2 grid h-4 w-4 place-items-center rounded-full"
                    style={{
                      background: "var(--color-accent)",
                      color: "oklch(0.12 0 0)",
                    }}
                  >
                    <Check className="h-3 w-3" strokeWidth={3} />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
