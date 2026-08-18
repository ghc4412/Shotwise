import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@/i18n";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { CreativeOutlineManager } from "./CreativeOutlineManager";

describe("CreativeOutlineManager", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.spyOn(API, "getSourceContent").mockRejectedValue(new Error("not found"));
    vi.spyOn(API, "saveSourceFile").mockResolvedValue({ success: true });
  });

  it("creates, edits, and persists detailed chapter outlines separately from the source draft", async () => {
    render(<CreativeOutlineManager projectName="demo" onSelectedChapterChange={() => {}} />);

    await screen.findByRole("button", { name: "新建卷" });
    fireEvent.click(screen.getByRole("button", { name: "新建卷" }));
    fireEvent.click(screen.getByRole("button", { name: "添加章节" }));
    fireEvent.change(screen.getByLabelText("章节标题"), { target: { value: "第一章 雨夜来信" } });
    fireEvent.change(screen.getByLabelText("本章细纲"), { target: { value: "主角收到一封没有署名的旧信。" } });
    fireEvent.change(screen.getByLabelText("本章尾钩子（可选）"), { target: { value: "信封里夹着失踪者的照片。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存细纲" }));

    await waitFor(() => {
      expect(API.saveSourceFile).toHaveBeenCalledWith(
        "demo",
        "_creative_outline.json",
        expect.stringContaining("第一章 雨夜来信"),
      );
    });
    const payload = JSON.parse(vi.mocked(API.saveSourceFile).mock.calls[0][2]);
    expect(payload.volumes[0].chapters[0]).toMatchObject({
      title: "第一章 雨夜来信",
      summary: "主角收到一封没有署名的旧信。",
      hook: "信封里夹着失踪者的照片。",
    });
  });

  it("imports an AI outline as editable chapters after an explicit user action", async () => {
    render(
      <CreativeOutlineManager
        projectName="demo"
        onSelectedChapterChange={() => {}}
        outlineSuggestion={"第一章 雨夜来信\n主角收到一封旧信。\n\n第二章 失踪照片\n照片指向十年前的案件。"}
      />,
    );

    await screen.findByRole("button", { name: "导入为细纲" });
    fireEvent.click(screen.getByRole("button", { name: "导入为细纲" }));

    expect(screen.getByText("第一章 雨夜来信")).toBeInTheDocument();
    expect(screen.getByText("第二章 失踪照片")).toBeInTheDocument();
    expect(screen.getByDisplayValue("主角收到一封旧信。")).toBeInTheDocument();
  });
});
