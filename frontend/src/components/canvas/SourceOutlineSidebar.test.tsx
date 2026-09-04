import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@/i18n";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { SourceOutlineSidebar } from "./SourceOutlineSidebar";

const sourceContent = "第241章 前一章\n旧内容\n\n第242章 思想落后的张羽（求月票）\n张羽迎来新的冲突。";
const savedOutline = JSON.stringify({
  version: 1,
  volumes: [{
    id: "volume-1",
    title: "demo.txt",
    chapters: [
      { id: "chapter-241", title: "第241章 前一章", summary: "前一章摘要", hook: "" },
      { id: "chapter-242", title: "第242章 一层巨变之始", summary: "旧缓存摘要", hook: "" },
    ],
  }],
});

function renderSidebar(content: string) {
  return render(
    <SourceOutlineSidebar
      projectName="demo"
      filename="demo.txt"
      content={content}
      onSelectItem={() => {}}
    />,
  );
}

describe("SourceOutlineSidebar", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.spyOn(API, "getSourceContent").mockImplementation(async (_projectName, filename) => {
      if (filename === "_creative_outline.json") return savedOutline;
      return sourceContent;
    });
  });

  it("normalizes saved AI titles to the exact titles in the source", async () => {
    renderSidebar(sourceContent);

    expect(await screen.findByText("思想落后的张羽（求月票）")).toBeInTheDocument();
    expect(screen.queryByText("一层巨变之始")).not.toBeInTheDocument();
  });

  it("reports segmented extraction progress in one workspace notification", async () => {
    const longContent = [
      "第1章 开始",
      "a".repeat(20_000),
      "第2章 继续",
      "b".repeat(20_000),
    ].join("\n");
    vi.spyOn(API, "generateCreativeDraft").mockResolvedValue({
      operation: "outline",
      content: JSON.stringify([{ chapter: 1, title: "开始", summary: "摘要" }]),
      provider: "test",
      model: "test",
    });
    vi.spyOn(API, "saveSourceFile").mockResolvedValue({ success: true });

    renderSidebar(longContent);
    fireEvent.click(await screen.findByRole("button", { name: "AI提取细纲" }));

    await waitFor(() => {
      expect(useAppStore.getState().workspaceNotifications).toHaveLength(1);
      expect(useAppStore.getState().workspaceNotifications[0]).toEqual(
        expect.objectContaining({
          text: "「demo.txt」的细纲提取已完成",
          tone: "success",
        }),
      );
    });
    expect(API.generateCreativeDraft).toHaveBeenCalledTimes(2);
  });

  it("keeps a failed extraction visible in workspace notifications", async () => {
    vi.spyOn(API, "generateCreativeDraft").mockRejectedValue(new Error("AI unavailable"));

    renderSidebar(sourceContent);
    fireEvent.click(await screen.findByRole("button", { name: "AI提取细纲" }));

    await waitFor(() => {
      expect(useAppStore.getState().workspaceNotifications).toHaveLength(1);
      expect(useAppStore.getState().workspaceNotifications[0]).toEqual(
        expect.objectContaining({
          text: "「demo.txt」的细纲提取失败",
          tone: "error",
        }),
      );
    });
  });

  it("re-normalizes the saved outline when the source content arrives or changes", async () => {
    const { rerender } = renderSidebar("");
    expect(await screen.findByText("一层巨变之始")).toBeInTheDocument();

    rerender(
      <SourceOutlineSidebar
        projectName="demo"
        filename="demo.txt"
        content={sourceContent}
        onSelectItem={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("思想落后的张羽（求月票）")).toBeInTheDocument();
      expect(screen.queryByText("一层巨变之始")).not.toBeInTheDocument();
    });
  });
});
