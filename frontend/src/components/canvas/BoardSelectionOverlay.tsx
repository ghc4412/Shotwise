import { Copy, Sparkles, Trash2 } from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";

type ResizeCorner = "nw" | "ne" | "sw" | "se";

interface BoardSelectionOverlayProps {
  name: string;
  position: { x: number; y: number };
  size: { width: number; height: number };
  zoom: number;
  multiSelected?: boolean;
  onResizeStart: (event: ReactPointerEvent<HTMLButtonElement>, corner: ResizeCorner) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onOpenSkills: () => void;
  labels: {
    openTools: string;
    duplicate: string;
    delete: string;
    resize: (corner: ResizeCorner) => string;
  };
}

const stop = (event: ReactPointerEvent<HTMLElement>) => event.stopPropagation();

export function BoardSelectionOverlay({
  name,
  position,
  size,
  zoom,
  multiSelected = false,
  onResizeStart,
  onDuplicate,
  onDelete,
  onOpenSkills,
  labels,
}: BoardSelectionOverlayProps) {
  // The overlay lives inside the transformed canvas world. Keep its geometry in
  // world coordinates and counter-scale handles so they remain easy to grab.
  const scaledWidth = size.width;
  const scaledHeight = size.height;
  const handleSize = Math.max(7 / zoom, Math.min(11 / zoom, 9 / zoom));

  return (
    <div
      className="pointer-events-none absolute z-20"
      data-board-selection-overlay
      style={{
        left: position.x,
        top: position.y,
        width: scaledWidth,
        height: scaledHeight,
      }}
      aria-label={name}
    >
      <div className="pointer-events-none absolute -inset-[2px] rounded-[11px] border-2 border-[#6758dc] shadow-[0_0_0_1px_rgba(255,255,255,0.9),0_4px_14px_rgba(98,84,217,0.18)]" />
      {!multiSelected ? (
        <>
          <div className="pointer-events-auto absolute -top-9 left-1/2 flex -translate-x-1/2 items-center gap-0.5 rounded-lg border border-[#d9d4fb] bg-white/95 p-1 shadow-[0_5px_16px_rgba(69,57,145,0.18)] backdrop-blur-sm" onPointerDown={stop}>
            <button type="button" onPointerDown={stop} onClick={onOpenSkills} className="focus-ring rounded-md p-1 text-[#6254d9] hover:bg-[#f1efff]" aria-label={labels.openTools} title={labels.openTools}>
              <Sparkles className="h-3.5 w-3.5" aria-hidden />
            </button>
            <button type="button" onPointerDown={stop} onClick={onDuplicate} className="focus-ring rounded-md p-1 text-[#64748b] hover:bg-[#f4f6fa]" aria-label={labels.duplicate} title={labels.duplicate}>
              <Copy className="h-3.5 w-3.5" aria-hidden />
            </button>
            <button type="button" onPointerDown={stop} onClick={onDelete} className="focus-ring rounded-md p-1 text-[#b85d68] hover:bg-[#fff1f2]" aria-label={labels.delete} title={labels.delete}>
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
          {(["nw", "ne", "sw", "se"] as ResizeCorner[]).map((corner) => (
            <button
              key={corner}
              type="button"
              data-resize-corner={corner}
              onPointerDown={(event) => onResizeStart(event, corner)}
              className="focus-ring pointer-events-auto absolute rounded-sm border border-white bg-[#6758dc] shadow-[0_1px_4px_rgba(40,35,107,0.32)]"
              style={{
                width: handleSize,
                height: handleSize,
                left: corner.includes("w") ? -handleSize / 2 : scaledWidth - handleSize / 2,
                top: corner.includes("n") ? -handleSize / 2 : scaledHeight - handleSize / 2,
                cursor: `${corner}-resize`,
              }}
              aria-label={labels.resize(corner)}
            />
          ))}
        </>
      ) : null}
    </div>
  );
}

export type { ResizeCorner };
