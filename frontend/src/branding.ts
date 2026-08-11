// Brand configuration — single source of truth for product naming.
// Override at build time via Vite env vars
// (VITE_BRAND_NAME / VITE_BRAND_TAGLINE / VITE_BRAND_DESCRIPTION).
//
// Source code references BRAND.name (or the [[brand]] placeholder in i18n
// resources) so the displayed product name is not hardcoded across files.
// Downstream distributions can override these defaults via frontend/.env.

const env = import.meta.env as Record<string, string | undefined>;

function fallback(value: string | undefined, defaultValue: string): string {
  // Trim + empty check so VITE_BRAND_NAME="" (or whitespace) falls back to the
  // default, matching the documented "Empty = upstream defaults" contract.
  if (typeof value !== "string") return defaultValue;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : defaultValue;
}

export const BRAND = {
  name: fallback(env.VITE_BRAND_NAME, "Shotwise"),
  // 中文品牌名：与 name（英文/可配置）解耦，供界面中需要中文品牌展示的位置使用
  nameZh: "逐镜",
  tagline: fallback(env.VITE_BRAND_TAGLINE, "AI 漫剧生产平台"),
  description: fallback(
    env.VITE_BRAND_DESCRIPTION,
    "逐镜 AI 漫剧生产平台，统一管理剧本、生产流程、分镜、渲染资产与智能体协作。",
  ),
} as const;

export const BRAND_DOCUMENT_TITLE = `${BRAND.name} · ${BRAND.tagline}`;

