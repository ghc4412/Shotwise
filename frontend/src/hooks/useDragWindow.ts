/**
 * 通用浮窗拖拽 hook —— 泛化 StudioLayout resize 的「mousedown 记 ref → window
 * mousemove/mouseup/blur → draft 状态 → mouseup 提交」范式。
 *
 * 拖拽期间用本地 draft 状态即时反馈（不写 store），mouseup/blur 才提交最终位置，
 * 避免每帧触发 zustand 订阅链路。吸附/缩角判定由调用方的 onCommit 决定。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";

export interface DragPoint {
  x: number;
  y: number;
}

interface UseDragWindowOptions {
  disabled?: boolean;
  /** 拖拽开始时的基准位置（已提交值）。 */
  getStart: () => DragPoint;
  /** 每帧 clamp（默认恒等）。 */
  clamp?: (pos: DragPoint) => DragPoint;
  /**
   * 判定为「拖动」所需的最小位移（px）。过小会把微小的手部抖动当成拖动，
   * 导致点击被误判。默认 2，交互目标较小时调用方可调大（如角标用 5）。
   */
  minMoveDistance?: number;
  /** mouseup/blur 提交最终位置（仅当真正移动过）。 */
  onCommit: (pos: DragPoint) => void;
}

interface UseDragWindowResult {
  isDragging: boolean;
  /** 拖拽中的即时位置，非拖拽时为 null。 */
  draftPos: DragPoint | null;
  dragHandleProps: {
    onMouseDown: (e: ReactMouseEvent<HTMLElement>) => void;
  };
}

/** 小于该位移视为点击而非拖拽，不提交。 */
const DEFAULT_MIN_MOVE_DISTANCE = 2;

export function useDragWindow(options: UseDragWindowOptions): UseDragWindowResult {
  const { disabled = false } = options;
  const [isDragging, setIsDragging] = useState(false);
  const [draftPos, setDraftPos] = useState<DragPoint | null>(null);

  const dragStateRef = useRef<{
    startMouse: DragPoint;
    startPos: DragPoint;
  } | null>(null);
  const lastPosRef = useRef<DragPoint | null>(null);
  const movedRef = useRef(false);
  const restoreBodyStyleRef = useRef<{ cursor: string; userSelect: string } | null>(
    null,
  );

  // refs 持有回调供 window 监听器读取最新值（闭包过期防护），
  // 与 AgentCopilot 的 tRef 同属稳定 event-handler ref 模式
  const getStartRef = useRef(options.getStart);
  // eslint-disable-next-line react-hooks/refs
  getStartRef.current = options.getStart;
  const clampRef = useRef(options.clamp);
  // eslint-disable-next-line react-hooks/refs
  clampRef.current = options.clamp;
  const minMoveDistanceRef = useRef(
    options.minMoveDistance ?? DEFAULT_MIN_MOVE_DISTANCE,
  );
  // eslint-disable-next-line react-hooks/refs
  minMoveDistanceRef.current = options.minMoveDistance ?? DEFAULT_MIN_MOVE_DISTANCE;
  const onCommitRef = useRef(options.onCommit);
  // eslint-disable-next-line react-hooks/refs
  onCommitRef.current = options.onCommit;

  const restoreBody = useCallback(() => {
    const saved = restoreBodyStyleRef.current;
    if (saved) {
      document.body.style.cursor = saved.cursor;
      document.body.style.userSelect = saved.userSelect;
      restoreBodyStyleRef.current = null;
    }
  }, []);

  const finishDrag = useCallback(() => {
    const drag = dragStateRef.current;
    if (!drag) return;
    dragStateRef.current = null;
    restoreBody();
    const final = lastPosRef.current;
    lastPosRef.current = null;
    const moved = movedRef.current;
    movedRef.current = false;
    setIsDragging(false);
    setDraftPos(null);
    // 无位移的「点击」不提交，避免误触发吸附/缩角
    if (final && moved) onCommitRef.current(final);
  }, [restoreBody]);

  useEffect(() => {
    if (disabled || !isDragging) return;

    const onMouseMove = (e: MouseEvent) => {
      // 主键已在中途松开（如焦点切走时）→ 主动收尾
      if ((e.buttons & 1) === 0) {
        finishDrag();
        return;
      }
      const drag = dragStateRef.current;
      if (!drag) return;
      const clamp = clampRef.current ?? ((p: DragPoint) => p);
      const threshold = minMoveDistanceRef.current;
      const next = clamp({
        x: drag.startPos.x + (e.clientX - drag.startMouse.x),
        y: drag.startPos.y + (e.clientY - drag.startMouse.y),
      });
      if (
        Math.abs(next.x - drag.startPos.x) >= threshold ||
        Math.abs(next.y - drag.startPos.y) >= threshold
      ) {
        movedRef.current = true;
      }
      lastPosRef.current = next;
      setDraftPos(next);
    };
    const onMouseUp = () => finishDrag();

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    // 鼠标在窗外松开时 mouseup 可能不触发，blur 兜底防止卡死
    window.addEventListener("blur", finishDrag);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("blur", finishDrag);
      // 组件意外卸载时兜底清理 body 样式
      restoreBody();
    };
  }, [disabled, isDragging, finishDrag, restoreBody]);

  const handleMouseDown = useCallback(
    (e: ReactMouseEvent<HTMLElement>) => {
      if (disabled) return;
      // 仅响应主键，避免右键/中键意外进入拖拽态
      if (e.button !== 0) return;
      e.preventDefault();
      dragStateRef.current = {
        startMouse: { x: e.clientX, y: e.clientY },
        startPos: getStartRef.current(),
      };
      restoreBodyStyleRef.current = {
        cursor: document.body.style.cursor,
        userSelect: document.body.style.userSelect,
      };
      document.body.style.cursor = "grabbing";
      document.body.style.userSelect = "none";
      movedRef.current = false;
      const start = dragStateRef.current.startPos;
      const clamp = clampRef.current ?? ((p: DragPoint) => p);
      const initial = clamp(start);
      lastPosRef.current = initial;
      setIsDragging(true);
      setDraftPos(initial);
    },
    [disabled],
  );

  return {
    isDragging,
    draftPos,
    dragHandleProps: { onMouseDown: handleMouseDown },
  };
}
