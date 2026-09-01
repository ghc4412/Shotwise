import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PromptPreview, type PromptPreviewModel } from "./PromptPreview";

function makePreview(overrides: Partial<PromptPreviewModel> = {}): PromptPreviewModel {
  return {
    source: "current_draft",
    requests: [
      {
        id: "video",
        label: "视频",
        originalPrompt: "角色在雨中奔跑",
        effectivePrompt: null,
        shape: "structured",
        provider: "example-provider",
        model: "example-model",
        references: [
          { kind: "character", label: "角色", value: "林雨" },
          { kind: "scene", label: "场景", value: "雨夜街道" },
        ],
        durationSeconds: 8,
        resolution: "1080p",
        capabilityAdjustments: ["时长已限制为 8 秒"],
        warnings: ["供应商会忽略环境音"],
        requestSummary: {
          endpoint: "/v1/videos",
          authorization: "Bearer should-never-render",
          api_key: "should-never-render",
          key: "should-never-render",
          nested: {
            Cookie: "session=should-never-render",
            "X-API-Key": "should-never-render",
            keep: "visible-value",
          },
        },
      },
    ],
    ...overrides,
  };
}

describe("PromptPreview", () => {
  it("renders a read-only fallback preview with generation context", () => {
    render(<PromptPreview preview={makePreview()} />);

    expect(screen.getByText("提示词预览")).toBeInTheDocument();
    expect(screen.getAllByText("角色在雨中奔跑")).toHaveLength(2);
    expect(screen.getByText("当前没有可用的实际入队快照；这里显示原始提示词。"))
      .toBeInTheDocument();
    expect(screen.getByText("structured")).toBeInTheDocument();
    expect(screen.getByText("example-provider / example-model")).toBeInTheDocument();
    expect(screen.getByText("角色: 林雨", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("8 秒 · 1080p")).toBeInTheDocument();
    expect(screen.getByText("8 秒 · 1080p")).toBeInTheDocument();
    expect(screen.getByText("时长已限制为 8 秒")).toBeInTheDocument();
    expect(screen.getByText("供应商会忽略环境音")).toBeInTheDocument();
  });

  it("redacts secret fields in the default and expanded request summary", () => {
    render(<PromptPreview preview={makePreview()} />);

    expect(screen.queryByText(/should-never-render/)).not.toBeInTheDocument();
    expect(screen.getAllByText("[已脱敏]").length).toBeGreaterThanOrEqual(4);

    fireEvent.click(screen.getByRole("button", { name: "高级详情" }));
    expect(screen.getByText("visible-value")).toBeInTheDocument();
    expect(screen.queryByText(/should-never-render/)).not.toBeInTheDocument();
  });

  it("copies only the redacted summary", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<PromptPreview preview={makePreview()} />);

    fireEvent.click(screen.getByRole("button", { name: "复制摘要" }));

    await vi.waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain("[已脱敏]");
    expect(copied).not.toContain("should-never-render");
  });
});
