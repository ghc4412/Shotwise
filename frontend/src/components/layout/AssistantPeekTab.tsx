/**
 * 缩角角标：助手面板收起后常驻的可拖动图标。
 *
 * - 拖动：头部可直接抓取，松手时吸附到最近边缘，隐藏进页面边缘只留一角（inset）。
 * - hover / focus：沿法线方向滑出完整图标，便于看清与点击。
 * - 点击（未拖动）：重新展开右侧停靠面板；面板展开时角标不渲染。
 * - 外观由 assistant-skins 皮肤驱动，与助手头部图标统一换肤。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDragWindow } from "@/hooks/useDragWindow";
import { ASSISTANT_PEEK_INSET, useAppStore } from "@/stores/app-store";
import { getAssistantSkin } from "@/utils/assistant-skins";
import { UI_LAYERS } from "@/utils/ui-layers";
import {
  clampPeekDrag,
  defaultPeekAnchor,
  peekSlideDistance,
  resolvePeekPosition,
  snapPeekToEdge,
} from "./assistant-peek-geometry";

const PEEK_TAB_SIZE = 44;
const PEEK_DRAG_SLIVER = 20;

export function AssistantPeekTab() {
  const { t } = useTranslation("dashboard");
  const assistantPanelOpen = useAppStore((s) => s.assistantPanelOpen);
  const assistantPeekAnchor = useAppStore((s) => s.assistantPeekAnchor);
  const setAssistantPeekAnchor = useAppStore((s) => s.setAssistantPeekAnchor);
  const persistAssistantPeekAnchor = useAppStore((s) => s.persistAssistantPeekAnchor);
  const assistantSkin = useAppStore((s) => s.assistantSkin);
  const setAssistantPanelOpen = useAppStore((s) => s.setAssistantPanelOpen);

  // viewport 尺寸（仅 client；fixed 定位必须拿实时视口）
  const [viewport, setViewport] = useState(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
  }));
  useEffect(() => {
    const onResize = () =>
      setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const size = useMemo(() => ({ width: PEEK_TAB_SIZE, height: PEEK_TAB_SIZE }), []);
  const anchor = assistantPeekAnchor ?? defaultPeekAnchor(viewport, PEEK_TAB_SIZE);

  const [hovered, setHovered] = useState(false);

  // 拖拽后刚吸附过（useDragWindow 仅在真正移动过时触发 onCommit），
  // 抑制紧随其后的 click，避免「拖到新位置松手」误展开面板。
  // 每次 mousedown 重置，防止上次拖拽的标记残留吞掉后续的正常单击。
  const justDraggedRef = useRef(false);

  const { isDragging, draftPos, dragHandleProps } = useDragWindow({
    // 拖动基准取当前可见位置：hover 滑出后按下，从滑出位置跟手拖动，避免跳回隐藏位置
    getStart: () => {
      const base = resolvePeekPosition(anchor, size, viewport, ASSISTANT_PEEK_INSET);
      if (!hovered) return base;
      const slide = peekSlideDistance(size, anchor.edge);
      return {
        x: base.x + (anchor.edge === "left" ? slide : anchor.edge === "right" ? -slide : 0),
        y: base.y + (anchor.edge === "top" ? slide : anchor.edge === "bottom" ? -slide : 0),
      };
    },
    clamp: (pos) => clampPeekDrag(pos, size, viewport, PEEK_DRAG_SLIVER),
    // 角标只有 44px，单击时的手部微动不该被当成拖动；阈值放大到 5px
    minMoveDistance: 5,
    onCommit: (pos) => {
      justDraggedRef.current = true;
      const next = snapPeekToEdge(pos, size, viewport);
      setAssistantPeekAnchor(next);
      persistAssistantPeekAnchor();
    },
  });

  // 面板展开时不渲染角标
  if (assistantPanelOpen) return null;

  const rest = resolvePeekPosition(anchor, size, viewport, ASSISTANT_PEEK_INSET);
  const pos = isDragging && draftPos ? draftPos : rest;

  // hover 沿法线方向滑出完整图标并留出 inset 间距；拖动中禁用（跟手优先）
  const slide = peekSlideDistance(size, anchor.edge);
  const transform =
    !isDragging && hovered
      ? anchor.edge === "left"
        ? `translateX(${slide}px)`
        : anchor.edge === "right"
          ? `translateX(-${slide}px)`
          : anchor.edge === "top"
            ? `translateY(${slide}px)`
            : `translateY(-${slide}px)`
      : "none";

  const skin = getAssistantSkin(assistantSkin);
  const SkinIcon = skin.icon;

  return (
    <button
      type="button"
      data-testid="assistant-peek-tab"
      onMouseDown={(e) => {
        // 新一轮交互开始：清掉拖拽抑制标记，避免上次拖拽残留吞掉本次单击
        justDraggedRef.current = false;
        dragHandleProps.onMouseDown(e);
      }}
      onClick={() => {
        if (justDraggedRef.current) {
          justDraggedRef.current = false;
          return;
        }
        setAssistantPanelOpen(true);
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
      aria-label={t("open_assistant_panel")}
      title={t("open_assistant_panel")}
      className={`fixed grid place-items-center rounded-xl ${UI_LAYERS.workspaceFloating} ${
        isDragging
          ? "cursor-grabbing"
          : "cursor-grab motion-safe:transition-transform motion-safe:duration-200"
      }`}
      style={{
        left: pos.x,
        top: pos.y,
        width: PEEK_TAB_SIZE,
        height: PEEK_TAB_SIZE,
        transform,
        background: `linear-gradient(135deg, ${skin.from}, ${skin.to})`,
        color: "oklch(0.12 0 0)",
        boxShadow:
          "0 0 0 1px oklch(1 0 0 / 0.1), 0 6px 20px -6px var(--color-accent-glow)",
        touchAction: "none",
        userSelect: "none",
      }}
    >
      <SkinIcon className="h-5 w-5" />
    </button>
  );
}
