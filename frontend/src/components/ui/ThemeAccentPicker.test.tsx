import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeAccentPicker } from "@/components/ui/ThemeAccentPicker";
import { ACCENT_THEME_IDS, useAppStore } from "@/stores/app-store";

// 与 ThemeAccentPicker 的 i18n 文案保持一致（测试 setup 默认 zh）
const LABELS: Record<string, string> = {
  aurora: "霓虹青",
  jade: "翡翠绿",
  violet: "星夜紫",
  crimson: "绯红",
  amber: "琥珀金",
  ocean: "深海蓝",
};

describe("ThemeAccentPicker", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    document.documentElement.className = "";
    window.localStorage.clear();
  });

  it("renders a compact trigger with an accent-aria label", () => {
    render(<ThemeAccentPicker />);
    expect(screen.getByRole("button", { name: "主题颜色" })).toBeInTheDocument();
  });

  it("lists all 6 preset accents when opened", () => {
    render(<ThemeAccentPicker />);
    fireEvent.click(screen.getByRole("button", { name: "主题颜色" }));
    for (const id of ACCENT_THEME_IDS) {
      expect(screen.getByRole("option", { name: LABELS[id] })).toBeInTheDocument();
    }
  });

  it("switches the document class, store state, and persists the choice", () => {
    render(<ThemeAccentPicker />);
    fireEvent.click(screen.getByRole("button", { name: "主题颜色" }));
    fireEvent.click(screen.getByRole("option", { name: "翡翠绿" }));

    expect(document.documentElement.classList.contains("accent-jade")).toBe(true);
    expect(document.documentElement.classList.contains("accent-aurora")).toBe(false);
    expect(useAppStore.getState().accentTheme).toBe("jade");
    expect(window.localStorage.getItem("shotwise-accent-theme")).toBe("jade");
  });

  it("marks the current accent as selected", () => {
    useAppStore.getState().setAccentTheme("amber");
    render(<ThemeAccentPicker />);
    fireEvent.click(screen.getByRole("button", { name: "主题颜色" }));
    expect(screen.getByRole("option", { name: "琥珀金" })).toHaveAttribute("aria-selected", "true");
  });
});
