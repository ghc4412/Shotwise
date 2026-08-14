import { Bot, Flame, Leaf, Sparkles, Wand2, Waves, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * 智能体角标（缩角角标 + 助手头部图标）的轻量皮肤系统。
 *
 * 参考 codex 宠物「皮肤包」的思路，但按 Web 端 44px 角标的体量落地为纯预设集合：
 * 皮肤 = 图标 + 渐变配色，即选即用、无美术资产。若未来要升级为精灵表动画宠物，
 * 只需把这里替换成动画渲染器，调用方（角标 / 头部图标）不感知。
 */
export interface AssistantSkin {
  id: string;
  /** i18n 名称 key（dashboard 命名空间）。 */
  labelKey: string;
  icon: LucideIcon;
  /** 135deg 渐变起始 / 结束色。 */
  from: string;
  to: string;
}

export const DEFAULT_ASSISTANT_SKIN_ID = "bot";

export const ASSISTANT_SKINS: readonly AssistantSkin[] = [
  {
    id: "bot",
    labelKey: "skin_bot",
    icon: Bot,
    from: "var(--color-accent)",
    to: "var(--color-violet)",
  },
  {
    id: "spark",
    labelKey: "skin_spark",
    icon: Sparkles,
    from: "oklch(0.85 0.10 85)",
    to: "oklch(0.68 0.14 55)",
  },
  {
    id: "wizard",
    labelKey: "skin_wizard",
    icon: Wand2,
    from: "oklch(0.74 0.12 305)",
    to: "oklch(0.56 0.16 265)",
  },
  {
    id: "ocean",
    labelKey: "skin_ocean",
    icon: Waves,
    from: "oklch(0.72 0.10 225)",
    to: "oklch(0.55 0.12 205)",
  },
  {
    id: "ember",
    labelKey: "skin_ember",
    icon: Flame,
    from: "oklch(0.78 0.14 45)",
    to: "oklch(0.60 0.18 25)",
  },
  {
    id: "leaf",
    labelKey: "skin_leaf",
    icon: Leaf,
    from: "oklch(0.82 0.13 150)",
    to: "oklch(0.60 0.14 165)",
  },
  {
    id: "bolt",
    labelKey: "skin_bolt",
    icon: Zap,
    from: "oklch(0.85 0.16 120)",
    to: "oklch(0.60 0.15 150)",
  },
];

const SKIN_BY_ID = new Map(ASSISTANT_SKINS.map((skin) => [skin.id, skin]));

export function isAssistantSkinId(value: unknown): value is string {
  return typeof value === "string" && SKIN_BY_ID.has(value);
}

export function getAssistantSkin(id: string): AssistantSkin {
  return SKIN_BY_ID.get(id) ?? SKIN_BY_ID.get(DEFAULT_ASSISTANT_SKIN_ID)!;
}
