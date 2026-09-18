/**
 * 用量界面数字 / 时长 / 紧凑时间的本地化格式化。
 *
 * 界面语言决定千分位与小数分隔符（zh-CN 为 `1,234.5`，vi-VN 为 `1.234,5`），
 * 因此不能依赖浏览器默认 locale——`toLocaleString()` 无参会跟随浏览器而非界面语言。
 * 金额不在此处：货币符号与精度另有口径，走 `cost-format`。
 */

const LOCALE_BY_LANGUAGE: Record<string, string> = {
  zh: "zh-CN",
  en: "en-US",
  vi: "vi-VN",
};

/** 界面语言 → BCP-47 locale；未登记语言回落到 en-US。 */
export function localeOf(language: string | undefined): string {
  const lang = (language ?? "").split("-")[0];
  return LOCALE_BY_LANGUAGE[lang] ?? "en-US";
}

const numberFormatters = new Map<string, Intl.NumberFormat>();

function getNumberFormatter(locale: string, maximumFractionDigits: number | undefined): Intl.NumberFormat {
  const key = `${locale}|${maximumFractionDigits ?? ""}`;
  let fmt = numberFormatters.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat(
      locale,
      maximumFractionDigits === undefined ? undefined : { maximumFractionDigits },
    );
    numberFormatters.set(key, fmt);
  }
  return fmt;
}

/** 按界面语言格式化计数：zh `1,234` / vi `1.234`。 */
export function formatCount(value: number, language: string | undefined): string {
  if (!Number.isFinite(value)) return "—";
  return getNumberFormatter(localeOf(language), undefined).format(value);
}

/** 按界面语言格式化秒数并补 `s` 后缀：zh `1.5s` / vi `1,5s`。 */
export function formatSeconds(value: number, language: string | undefined, maximumFractionDigits = 1): string {
  if (!Number.isFinite(value)) return "—";
  return `${getNumberFormatter(localeOf(language), maximumFractionDigits).format(value)}s`;
}

/**
 * 毫秒 → 秒字符串；null / 非法值 / 非正数一律返回 null。
 *
 * `duration_ms` 为 0 与缺失同义（都表示这次调用没有可显示的时长），调用点据此决定
 * 是否渲染该片段，不做 `0s` 展示。
 */
export function formatDurationMs(
  milliseconds: number | null | undefined,
  language: string | undefined,
): string | null {
  if (milliseconds === null || milliseconds === undefined || !Number.isFinite(milliseconds)) return null;
  if (milliseconds <= 0) return null;
  return formatSeconds(milliseconds / 1000, language);
}

const compactDateTimeFormatters = new Map<string, Intl.DateTimeFormat>();

const COMPACT_DATE_TIME_OPTIONS: Intl.DateTimeFormatOptions = {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
};

function getCompactFormatter(locale: string): Intl.DateTimeFormat {
  let fmt = compactDateTimeFormatters.get(locale);
  if (!fmt) {
    try {
      fmt = new Intl.DateTimeFormat(locale, COMPACT_DATE_TIME_OPTIONS);
    } catch {
      fmt = new Intl.DateTimeFormat("en-US", COMPACT_DATE_TIME_OPTIONS);
    }
    compactDateTimeFormatters.set(locale, fmt);
  }
  return fmt;
}

function parseTimestamp(value: string): Date {
  // 无显式时区后缀的 ISO 串按 UTC 处理，避免浏览器各自解释
  const hasTz = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/.test(value);
  return new Date(hasTz ? value : `${value}Z`);
}

/** 按界面语言格式化紧凑时间；解析失败返回 null 由调用方兜底。 */
export function formatCompactDateTime(
  value: string | null | undefined,
  language: string | undefined,
): string | null {
  if (!value) return null;
  const date = parseTimestamp(value);
  if (Number.isNaN(date.getTime())) return null;
  return getCompactFormatter(localeOf(language)).format(date);
}
