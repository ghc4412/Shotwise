import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "@/stores/app-store";
import { AssistantPeekTab } from "./AssistantPeekTab";

function setViewport(width: number, height: number) {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width });
  Object.defineProperty(window, "innerHeight", { writable: true, configurable: true, value: height });
}

describe("AssistantPeekTab", () => {
  beforeEach(() => {
    setViewport(1440, 900);
    useAppStore.setState(useAppStore.getInitialState(), true);
  });

  it("does not render while the assistant panel is open", () => {
    useAppStore.getState().setAssistantPanelOpen(true);
    render(<AssistantPeekTab />);
    expect(screen.queryByTestId("assistant-peek-tab")).not.toBeInTheDocument();
  });

  it("renders when the panel is collapsed and expands the panel on click", () => {
    useAppStore.getState().setAssistantPanelOpen(false);
    const { rerender } = render(<AssistantPeekTab />);
    const tab = screen.getByTestId("assistant-peek-tab");
    expect(tab).toBeInTheDocument();

    fireEvent.click(tab);
    rerender(<AssistantPeekTab />);
    expect(useAppStore.getState().assistantPanelOpen).toBe(true);
    expect(screen.queryByTestId("assistant-peek-tab")).not.toBeInTheDocument();
  });

  it("snaps to the nearest edge when dragged and does not expand the panel", () => {
    useAppStore.getState().setAssistantPanelOpen(false);
    // 固定锚点：右侧中部（默认右下会受视口影响，先显式设一个）
    useAppStore.getState().setAssistantPeekAnchor({ edge: "right", offset: 450 });
    render(<AssistantPeekTab />);
    const tab = screen.getByTestId("assistant-peek-tab");

    // 从右侧中部拖到视口左侧：mousemove 增量 (-1200, 0)
    fireEvent.mouseDown(tab, { button: 0, clientX: 600, clientY: 450 });
    act(() => {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: -600, clientY: 450, buttons: 1 }));
    });
    act(() => {
      window.dispatchEvent(new MouseEvent("mouseup"));
    });

    const anchor = useAppStore.getState().assistantPeekAnchor;
    expect(anchor?.edge).toBe("left");
    // 拖拽松手不应误展开面板；紧随其后的 click 同样被抑制
    expect(useAppStore.getState().assistantPanelOpen).toBe(false);
    fireEvent.click(tab);
    expect(useAppStore.getState().assistantPanelOpen).toBe(false);
  });

  it("opens the panel on a fresh click after a drag (stale suppression flag is cleared)", () => {
    useAppStore.getState().setAssistantPanelOpen(false);
    useAppStore.getState().setAssistantPeekAnchor({ edge: "right", offset: 450 });
    const { rerender } = render(<AssistantPeekTab />);
    const tab = screen.getByTestId("assistant-peek-tab");

    // 先拖一次：松手吸附到左边缘，同序列 click 被抑制
    fireEvent.mouseDown(tab, { button: 0, clientX: 600, clientY: 450 });
    act(() => {
      window.dispatchEvent(new MouseEvent("mousemove", { clientX: -600, clientY: 450, buttons: 1 }));
    });
    act(() => {
      window.dispatchEvent(new MouseEvent("mouseup"));
    });
    fireEvent.click(tab);
    expect(useAppStore.getState().assistantPanelOpen).toBe(false);

    // 新一轮交互：mousedown 重置抑制标记后，单击应正常展开面板
    fireEvent.mouseDown(tab, { button: 0, clientX: 100, clientY: 200 });
    fireEvent.click(tab);
    rerender(<AssistantPeekTab />);
    expect(useAppStore.getState().assistantPanelOpen).toBe(true);
  });

  it("renders the selected skin icon", () => {
    useAppStore.getState().setAssistantPanelOpen(false);
    useAppStore.getState().setAssistantSkin("ember");
    const { rerender } = render(<AssistantPeekTab />);
    expect(screen.getByTestId("assistant-peek-tab")).toBeInTheDocument();
    // lucide 按图标名生成 class：skin=ember → Flame
    expect(document.querySelector(".lucide-flame")).toBeInTheDocument();

    useAppStore.getState().setAssistantSkin("ocean");
    rerender(<AssistantPeekTab />);
    expect(document.querySelector(".lucide-waves-horizontal")).toBeInTheDocument();
    expect(document.querySelector(".lucide-flame")).not.toBeInTheDocument();
  });
});
