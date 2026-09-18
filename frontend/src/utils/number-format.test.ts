import { describe, expect, it } from "vitest";
import {
  formatCompactDateTime,
  formatCount,
  formatDurationMs,
  formatSeconds,
  localeOf,
} from "./number-format";

describe("localeOf", () => {
  it("maps the three interface languages", () => {
    expect(localeOf("zh")).toBe("zh-CN");
    expect(localeOf("zh-CN")).toBe("zh-CN");
    expect(localeOf("en")).toBe("en-US");
    expect(localeOf("vi")).toBe("vi-VN");
  });

  it("falls back to en-US for unknown or missing languages", () => {
    expect(localeOf(undefined)).toBe("en-US");
    expect(localeOf("")).toBe("en-US");
    expect(localeOf("fr")).toBe("en-US");
  });
});

describe("formatCount", () => {
  it("groups digits per interface language", () => {
    expect(formatCount(1234, "en")).toBe("1,234");
    expect(formatCount(1234, "zh")).toBe("1,234");
    expect(formatCount(1234, "vi")).toBe("1.234");
  });

  it("renders small values unchanged and non-finite values as a placeholder", () => {
    expect(formatCount(0, "vi")).toBe("0");
    expect(formatCount(Number.NaN, "en")).toBe("—");
    expect(formatCount(Number.POSITIVE_INFINITY, "zh")).toBe("—");
  });
});

describe("formatSeconds / formatDurationMs", () => {
  it("uses the interface-language decimal separator and appends the unit", () => {
    expect(formatSeconds(1.5, "en")).toBe("1.5s");
    expect(formatSeconds(1.5, "zh")).toBe("1.5s");
    expect(formatSeconds(1.5, "vi")).toBe("1,5s");
  });

  it("honours the fraction-digit ceiling", () => {
    expect(formatSeconds(12, "vi", 0)).toBe("12s");
    expect(formatSeconds(12.34, "en", 0)).toBe("12s");
  });

  it("converts milliseconds and treats missing or non-positive values as no duration", () => {
    expect(formatDurationMs(1500, "en")).toBe("1.5s");
    expect(formatDurationMs(0, "en")).toBeNull();
    expect(formatDurationMs(-1, "en")).toBeNull();
    expect(formatDurationMs(null, "en")).toBeNull();
    expect(formatDurationMs(undefined, "vi")).toBeNull();
  });
});

describe("formatCompactDateTime", () => {
  it("is null-safe and unparsable-safe", () => {
    expect(formatCompactDateTime(null, "en")).toBeNull();
    expect(formatCompactDateTime(undefined, "zh")).toBeNull();
    expect(formatCompactDateTime("", "vi")).toBeNull();
    expect(formatCompactDateTime("not-a-date", "en")).toBeNull();
  });

  it("keeps the 24-hour form for zh/vi and the 12-hour form for en", () => {
    const iso = "2026-09-10T14:03:00Z";
    expect(formatCompactDateTime(iso, "zh")).not.toMatch(/AM|PM/);
    expect(formatCompactDateTime(iso, "vi")).not.toMatch(/AM|PM/);
    expect(formatCompactDateTime(iso, "en")).toMatch(/AM|PM/);
  });

  it("treats a timestamp without an explicit offset as UTC", () => {
    const naive = "2026-09-10T14:03:00";
    const rendered = formatCompactDateTime(naive, "vi");
    expect(rendered).not.toBeNull();
    expect(rendered).toBe(formatCompactDateTime(`${naive}Z`, "vi"));
  });
});
