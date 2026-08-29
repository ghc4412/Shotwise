import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CanvasImageEditorOverlay, type CanvasEditorOperation } from "./CanvasImageEditorOverlay";

const baseLabels = {
  close: "close",
  run: "run",
  running: "running",
  instructionPlaceholder: "hint",
  instructionLabel: "instruction",
  regionHint: "region",
  ratio: "ratio",
  ratioOriginal: "original",
  ratio116: "1:1",
  ratio34: "3:4",
  ratio169: "16:9",
  resolution: "res",
  resolution2k: "2K",
  resolution4k: "4K",
  count: "count",
  multiplier: "multiplier",
  multiplier2: "2×",
  multiplier4: "4×",
  multiplier6: "6×",
};

function renderEditor(operation: CanvasEditorOperation, onSubmit = vi.fn()) {
  render(
    <CanvasImageEditorOverlay operation={operation} title={operation} imageUrl="/img.png" onSubmit={onSubmit} onClose={vi.fn()} labels={baseLabels} />,
  );
  return { onSubmit };
}

describe("CanvasImageEditorOverlay", () => {
  it("submits an HD operation with instruction and multiplier", () => {
    const { onSubmit } = renderEditor("hd");
    const config = screen.getByTestId("canvas-image-editor-config");
    fireEvent.change(within(config).getByLabelText("instruction"), { target: { value: "enhance detail" } });
    fireEvent.click(screen.getByTestId("canvas-image-editor-run"));
    expect(onSubmit).toHaveBeenCalledWith({ instruction: "enhance detail", count: 1, aspectRatio: undefined, quality: "2K", multiplier: 2 });
  });

  it("shows a region box for region-based operations and submits it", () => {
    const { onSubmit } = renderEditor("redraw");
    const canvas = screen.getByTestId("canvas-image-editor-canvas");
    expect(canvas.querySelector("[data-region-box]")).toBeTruthy();
    fireEvent.click(screen.getByTestId("canvas-image-editor-run"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const args = onSubmit.mock.calls[0][0] as { region: unknown };
    expect(args.region).toEqual({ x: 0.1, y: 0.1, width: 0.8, height: 0.8 });
  });

  it("does not show a region box for whole-image operations", () => {
    renderEditor("cutout");
    const canvas = screen.getByTestId("canvas-image-editor-canvas");
    expect(canvas.querySelector("[data-region-box]")).toBeNull();
  });
});
