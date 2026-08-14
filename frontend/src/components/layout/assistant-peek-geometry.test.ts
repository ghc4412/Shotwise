import { describe, expect, it } from "vitest";
import {
  clampPeekDrag,
  defaultPeekAnchor,
  peekSlideDistance,
  resolvePeekPosition,
  snapPeekToEdge,
} from "./assistant-peek-geometry";

const viewport = { width: 1200, height: 800 };
const size = { width: 44, height: 44 };
const inset = 12;

describe("defaultPeekAnchor", () => {
  it("points to the bottom-right edge", () => {
    expect(defaultPeekAnchor(viewport, 44)).toEqual({ edge: "right", offset: 778 });
  });
});

describe("resolvePeekPosition", () => {
  it("hides the tab off the right edge leaving only the inset strip", () => {
    const pos = resolvePeekPosition({ edge: "right", offset: 778 }, size, viewport, inset);
    expect(pos).toEqual({ x: 1200 - inset, y: 778 - 22 });
  });

  it("hides the tab off the left / top / bottom edges", () => {
    expect(resolvePeekPosition({ edge: "left", offset: 100 }, size, viewport, inset)).toEqual({
      x: -44 + 12,
      y: 100 - 22,
    });
    expect(resolvePeekPosition({ edge: "top", offset: 300 }, size, viewport, inset)).toEqual({
      x: 300 - 22,
      y: -44 + 12,
    });
    expect(resolvePeekPosition({ edge: "bottom", offset: 600 }, size, viewport, inset)).toEqual({
      x: 600 - 22,
      y: 800 - 12,
    });
  });

  it("clamps the offset so the tab never slides past the edge", () => {
    expect(resolvePeekPosition({ edge: "right", offset: 99999 }, size, viewport, inset).y).toBe(
      800 - 44,
    );
    expect(resolvePeekPosition({ edge: "right", offset: -100 }, size, viewport, inset).y).toBe(0);
    expect(resolvePeekPosition({ edge: "bottom", offset: 99999 }, size, viewport, inset).x).toBe(
      1200 - 44,
    );
  });
});

describe("clampPeekDrag", () => {
  const sliver = 20;
  it("keeps at least sliver px of the tab on screen", () => {
    expect(clampPeekDrag({ x: -1000, y: 0 }, size, viewport, sliver).x).toBe(-44 + 20);
    expect(clampPeekDrag({ x: 2000, y: 0 }, size, viewport, sliver).x).toBe(1200 - 20);
    expect(clampPeekDrag({ x: 0, y: -1000 }, size, viewport, sliver).y).toBe(-44 + 20);
    expect(clampPeekDrag({ x: 0, y: 2000 }, size, viewport, sliver).y).toBe(800 - 20);
  });

  it("leaves in-viewport positions unchanged", () => {
    expect(clampPeekDrag({ x: 300, y: 100 }, size, viewport, sliver)).toEqual({
      x: 300,
      y: 100,
    });
  });
});

describe("snapPeekToEdge", () => {
  it("snaps to the nearest edge with the center offset", () => {
    // 偏左：角标中心 (10, 400) → 左缘
    expect(snapPeekToEdge({ x: 10 - 22, y: 400 - 22 }, size, viewport)).toEqual({
      edge: "left",
      offset: 400,
    });
    // 偏右：中心 (1190, 400) → 右缘
    expect(snapPeekToEdge({ x: 1190 - 22, y: 400 - 22 }, size, viewport)).toEqual({
      edge: "right",
      offset: 400,
    });
    // 偏上：中心 (600, 10) → 上缘
    expect(snapPeekToEdge({ x: 600 - 22, y: 10 - 22 }, size, viewport)).toEqual({
      edge: "top",
      offset: 600,
    });
    // 偏下：中心 (600, 790) → 下缘
    expect(snapPeekToEdge({ x: 600 - 22, y: 790 - 22 }, size, viewport)).toEqual({
      edge: "bottom",
      offset: 600,
    });
  });

  it("picks the nearest edge by distance", () => {
    // 中心 (600, 400)：到水平边缘 600px、到垂直边缘 400px → 垂直更近
    expect(snapPeekToEdge({ x: 600 - 22, y: 400 - 22 }, size, viewport)).toEqual({
      edge: "top",
      offset: 600,
    });
  });

  it("prefers the horizontal edge when distances tie", () => {
    // 方形视口中心 (400, 400)：到四边等距 → 取水平（left，因 distLeft <= distRight）
    const square = { width: 800, height: 800 };
    expect(snapPeekToEdge({ x: 400 - 22, y: 400 - 22 }, size, square)).toEqual({
      edge: "left",
      offset: 400,
    });
  });
});

describe("peekSlideDistance", () => {
  it("slides the full tab size so the hovered tab keeps an inset gap from the edge", () => {
    expect(peekSlideDistance(size, "left")).toBe(44);
    expect(peekSlideDistance(size, "right")).toBe(44);
    expect(peekSlideDistance(size, "top")).toBe(44);
    expect(peekSlideDistance(size, "bottom")).toBe(44);
  });
});
