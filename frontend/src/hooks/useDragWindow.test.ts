import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useDragWindow } from "./useDragWindow";

/** dispatch a mouse event on window (blur 用 Event 类型）。 */
function fireWindow(type: string, opts: { clientX?: number; clientY?: number; buttons?: number } = {}) {
  window.dispatchEvent(
    new MouseEvent(type, {
      clientX: opts.clientX ?? 0,
      clientY: opts.clientY ?? 0,
      buttons: opts.buttons ?? 0,
    }),
  );
}

function fireBlur() {
  window.dispatchEvent(new Event("blur"));
}

describe("useDragWindow", () => {
  it("tracks drag and commits the final clamped position on mouseup", () => {
    const onCommit = vi.fn();
    const clamp = (p: { x: number; y: number }) => ({ x: Math.max(0, p.x), y: Math.max(0, p.y) });
    const { result } = renderHook(() =>
      useDragWindow({ getStart: () => ({ x: 100, y: 50 }), clamp, onCommit }),
    );

    expect(result.current.isDragging).toBe(false);
    expect(result.current.draftPos).toBeNull();

    // mousedown 于 (10, 20)，基准位置 (100, 50)
    act(() => {
      result.current.dragHandleProps.onMouseDown({
        button: 0,
        clientX: 10,
        clientY: 20,
        preventDefault: vi.fn(),
      } as never);
    });
    expect(result.current.isDragging).toBe(true);
    expect(result.current.draftPos).toEqual({ x: 100, y: 50 });

    // 移动 delta (30, 40) → 新位置 (130, 90)
    act(() => {
      fireWindow("mousemove", { clientX: 40, clientY: 60, buttons: 1 });
    });
    expect(result.current.draftPos).toEqual({ x: 130, y: 90 });

    // 松手提交
    act(() => {
      fireWindow("mouseup");
    });
    expect(result.current.isDragging).toBe(false);
    expect(result.current.draftPos).toBeNull();
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({ x: 130, y: 90 });
  });

  it("does not commit on a plain click (no movement)", () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() =>
      useDragWindow({ getStart: () => ({ x: 0, y: 0 }), onCommit }),
    );
    act(() => {
      result.current.dragHandleProps.onMouseDown({
        button: 0,
        clientX: 5,
        clientY: 5,
        preventDefault: vi.fn(),
      } as never);
    });
    act(() => {
      fireWindow("mouseup");
    });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("treats sub-threshold jitter as a click when minMoveDistance is raised", () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() =>
      useDragWindow({
        getStart: () => ({ x: 0, y: 0 }),
        onCommit,
        minMoveDistance: 5,
      }),
    );
    act(() => {
      result.current.dragHandleProps.onMouseDown({
        button: 0,
        clientX: 0,
        clientY: 0,
        preventDefault: vi.fn(),
      } as never);
    });
    // 移动 4px（低于阈值 5）：仍视为点击，不提交
    act(() => {
      fireWindow("mousemove", { clientX: 4, clientY: 0, buttons: 1 });
    });
    act(() => {
      fireWindow("mouseup");
    });
    expect(onCommit).not.toHaveBeenCalled();
    expect(result.current.isDragging).toBe(false);
  });

  it("still commits when the movement reaches the raised threshold", () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() =>
      useDragWindow({
        getStart: () => ({ x: 0, y: 0 }),
        onCommit,
        minMoveDistance: 5,
      }),
    );
    act(() => {
      result.current.dragHandleProps.onMouseDown({
        button: 0,
        clientX: 0,
        clientY: 0,
        preventDefault: vi.fn(),
      } as never);
    });
    act(() => {
      fireWindow("mousemove", { clientX: 5, clientY: 0, buttons: 1 });
    });
    act(() => {
      fireWindow("mouseup");
    });
    expect(onCommit).toHaveBeenCalledWith({ x: 5, y: 0 });
  });

  it("commits on window blur (mouse released outside window)", () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() =>
      useDragWindow({ getStart: () => ({ x: 10, y: 10 }), onCommit }),
    );
    act(() => {
      result.current.dragHandleProps.onMouseDown({
        button: 0,
        clientX: 0,
        clientY: 0,
        preventDefault: vi.fn(),
      } as never);
    });
    act(() => {
      fireWindow("mousemove", { clientX: 50, clientY: 30, buttons: 1 });
    });
    act(() => {
      fireBlur();
    });
    expect(onCommit).toHaveBeenCalledWith({ x: 60, y: 40 });
  });

  it("ignores non-primary buttons and when disabled", () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() =>
      useDragWindow({ getStart: () => ({ x: 0, y: 0 }), onCommit, disabled: true }),
    );
    act(() => {
      result.current.dragHandleProps.onMouseDown({
        button: 0,
        clientX: 0,
        clientY: 0,
        preventDefault: vi.fn(),
      } as never);
    });
    expect(result.current.isDragging).toBe(false);
    expect(onCommit).not.toHaveBeenCalled();
  });
});
