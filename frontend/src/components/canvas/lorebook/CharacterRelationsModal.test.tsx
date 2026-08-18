import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import { CharacterRelationsModal } from "./CharacterRelationsModal";

vi.mock("@xyflow/react", () => ({
  Background: () => null,
  BackgroundVariant: { Dots: "dots" },
  ControlButton: ({ children, ...props }: { children: ReactNode } & Record<string, unknown>) => <button {...props}>{children}</button>,
  Controls: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Handle: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
  MiniMap: ({
    pannable,
    bgColor,
    maskColor,
    maskStrokeColor,
    maskStrokeWidth,
  }: {
    pannable?: boolean;
    bgColor?: string;
    maskColor?: string;
    maskStrokeColor?: string;
    maskStrokeWidth?: number;
  }) => (
    <div
      data-testid="mock-mini-map"
      data-pannable={String(pannable)}
      data-bg-color={bgColor}
      data-mask-color={maskColor}
      data-mask-stroke-color={maskStrokeColor}
      data-mask-stroke-width={String(maskStrokeWidth)}
    />
  ),
  Position: { Bottom: "bottom", Left: "left", Right: "right", Top: "top" },
  ReactFlow: ({ children, nodesDraggable, nodesConnectable }: { children: ReactNode; nodesDraggable?: boolean; nodesConnectable?: boolean }) => (
    <div data-testid="mock-react-flow" data-nodes-draggable={String(nodesDraggable)} data-nodes-connectable={String(nodesConnectable)}>{children}</div>
  ),
  ReactFlowProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useNodesState: () => [[], vi.fn(), vi.fn()],
  useReactFlow: () => ({ fitView: vi.fn() }),
}));

vi.mock("@/api", () => ({
  API: {
    getCharacterRelations: vi.fn().mockResolvedValue({ revision: 1, edges: [], node_positions: {} }),
  },
}));

describe("CharacterRelationsModal fullscreen control", () => {
  it("allows dragging the minimap viewport with a distinct gray mask", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <CharacterRelationsModal projectName="demo" characters={{}} onClose={vi.fn()} />
      </I18nextProvider>,
    );

    const minimap = await screen.findByTestId("mock-mini-map");

    expect(minimap).toHaveAttribute("data-pannable", "true");
    expect(minimap).toHaveAttribute("data-bg-color", "#ffffff");
    expect(minimap).toHaveAttribute("data-mask-color", "#9ca3af");
    expect(minimap).toHaveAttribute("data-mask-stroke-color", "#3f3f46");
    expect(minimap).toHaveAttribute("data-mask-stroke-width", "2");
  });

  it("expands and restores the graph dialog", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <CharacterRelationsModal projectName="demo" characters={{}} onClose={vi.fn()} />
      </I18nextProvider>,
    );

    const fullscreenButton = screen.getByRole("button", { name: /全屏展开|enter full screen|mở toàn màn hình/i });
    const dialog = screen.getByRole("dialog");

    fireEvent.click(fullscreenButton);

    expect(fullscreenButton).toHaveAccessibleName(/退出全屏|exit full screen|thoát toàn màn hình/i);
    expect(fullscreenButton).toHaveAttribute("aria-pressed", "true");
    expect(dialog).toHaveClass("fixed", "inset-0");
    expect(dialog).toHaveStyle({ borderRadius: "0", inset: "0", maxWidth: "none", position: "fixed" });

    fireEvent.click(fullscreenButton);

    expect(fullscreenButton).toHaveAccessibleName(/全屏展开|enter full screen|mở toàn màn hình/i);
    expect(fullscreenButton).toHaveAttribute("aria-pressed", "false");
    expect(dialog).not.toHaveClass("fixed", "inset-0");
  });

  it("locks layout editing without disabling graph inspection", async () => {
    render(
      <I18nextProvider i18n={i18n}>
        <CharacterRelationsModal projectName="demo" characters={{}} onClose={vi.fn()} />
      </I18nextProvider>,
    );

    const lockButton = await screen.findByRole("button", { name: /锁定布局|lock layout|khóa bố cục/i });
    const flow = screen.getByTestId("mock-react-flow");

    expect(flow).toHaveAttribute("data-nodes-draggable", "true");
    expect(flow).toHaveAttribute("data-nodes-connectable", "true");

    fireEvent.click(lockButton);

    const unlockButton = await screen.findByRole("button", { name: /解除布局锁定|unlock layout|mở khóa bố cục/i });
    expect(unlockButton).toHaveAttribute("aria-pressed", "true");
    expect(flow).toHaveAttribute("data-nodes-draggable", "false");
    expect(flow).toHaveAttribute("data-nodes-connectable", "false");

    fireEvent.click(unlockButton);

    const relockButton = await screen.findByRole("button", { name: /锁定布局|lock layout|khóa bố cục/i });
    await waitFor(() => expect(relockButton).toHaveAttribute("aria-pressed", "false"));
    const unlockedFlow = screen.getByTestId("mock-react-flow");
    expect(unlockedFlow).toHaveAttribute("data-nodes-draggable", "true");
    expect(unlockedFlow).toHaveAttribute("data-nodes-connectable", "true");
  });
});
