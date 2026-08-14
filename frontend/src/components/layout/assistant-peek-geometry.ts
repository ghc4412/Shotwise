/**
 * 缩角角标几何纯函数 —— 不碰 store / DOM，便于单测。
 * 所有坐标均为 viewport 像素。
 *
 * 语义约定：锚点 (AssistantPeekAnchor) 的 offset 是角标中心沿该边缘的像素位置，
 * 解析时按边缘长度 clamp，保证角标不会滑出该边缘。
 */
import type { AssistantPeekAnchor, PeekEdge } from "@/stores/app-store";

export interface Size {
  width: number;
  height: number;
}

export interface Viewport {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

/** 默认锚点：右下角（未自定义位置时使用）。 */
export function defaultPeekAnchor(viewport: Viewport, tabSize: number): AssistantPeekAnchor {
  return { edge: "right", offset: viewport.height - tabSize / 2 };
}

/**
 * 把锚点解析为角标左上角坐标（隐藏态：沿边缘法线方向完全出屏，只露 inset px 在页内）。
 */
export function resolvePeekPosition(
  anchor: AssistantPeekAnchor,
  size: Size,
  viewport: Viewport,
  inset: number,
): Point {
  const alongEdge = anchor.edge === "top" || anchor.edge === "bottom";
  const edgeLen = alongEdge ? viewport.width : viewport.height;
  const tabLen = alongEdge ? size.width : size.height;
  const offset = Math.round(
    Math.min(Math.max(anchor.offset, tabLen / 2), edgeLen - tabLen / 2),
  );
  const along = Math.round(offset - tabLen / 2);
  switch (anchor.edge) {
    case "left":
      return { x: -size.width + inset, y: along };
    case "right":
      return { x: viewport.width - inset, y: along };
    case "top":
      return { x: along, y: -size.height + inset };
    case "bottom":
      return { x: along, y: viewport.height - inset };
  }
}

/** 拖拽中保证至少 `sliver` px 的角标仍在屏内（否则松手后无处可抓）。 */
export function clampPeekDrag(
  pos: Point,
  size: Size,
  viewport: Viewport,
  sliver: number,
): Point {
  const minX = -size.width + sliver;
  const maxX = viewport.width - sliver;
  const minY = -size.height + sliver;
  const maxY = viewport.height - sliver;
  return {
    x: Math.round(Math.min(Math.max(pos.x, minX), maxX)),
    y: Math.round(Math.min(Math.max(pos.y, minY), maxY)),
  };
}

/**
 * 松手吸附：按角标中心到四边的最小距离选最近边缘，offset 取中心沿该边缘的位置。
 */
export function snapPeekToEdge(
  pos: Point,
  size: Size,
  viewport: Viewport,
): AssistantPeekAnchor {
  const centerX = pos.x + size.width / 2;
  const centerY = pos.y + size.height / 2;
  const distLeft = centerX;
  const distRight = viewport.width - centerX;
  const distTop = centerY;
  const distBottom = viewport.height - centerY;
  const nearestHorizontal = Math.min(distLeft, distRight);
  const nearestVertical = Math.min(distTop, distBottom);
  if (nearestHorizontal <= nearestVertical) {
    return {
      edge: distLeft <= distRight ? "left" : "right",
      offset: Math.round(centerY),
    };
  }
  return {
    edge: distTop <= distBottom ? "top" : "bottom",
    offset: Math.round(centerX),
  };
}

/**
 * hover / focus 时把角标沿法线方向滑出所需位移：滑出完整尺寸后，角标与页面边界
 * 之间保留 inset 间距（隐藏态贴边露 inset，hover 态距离边界 inset）。
 */
export function peekSlideDistance(size: Size, edge: PeekEdge): number {
  return edge === "left" || edge === "right" ? size.width : size.height;
}
