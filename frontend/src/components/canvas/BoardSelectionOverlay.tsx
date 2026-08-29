import { ChevronDown, Copy, Download, Expand, Grid3X3, Layers3, Maximize2, Pencil, Scan, SlidersHorizontal, Sparkles, SunMedium, Trash2, UserRound } from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";

type ResizeCorner = "nw" | "ne" | "sw" | "se";
export type BoardToolbarAction =
  | "portrait"
  | "portrait-emotion"
  | "panorama"
  | "angles"
  | "lighting"
  | "grid"
  | "hd"
  | "outpaint"
  | "redraw"
  | "erase"
  | "cutout"
  | "crop"
  | "edit"
  | "layers"
  | "split"
  | "adjust"
  | "symmetry"
  | "download"
  | "expand";

export type BoardToolbarSelection = {
  action: BoardToolbarAction;
  preset?: string;
  label?: string;
};

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
  onToolbarAction?: (selection: BoardToolbarSelection) => void;
  showTools?: boolean;
  labels: {
    openTools: string;
    duplicate: string;
    delete: string;
    resize: (corner: ResizeCorner) => string;
    toolbar: {
      portrait: string;
      panorama: string;
      angles: string;
      lighting: string;
      grid: string;
      hd: string;
      outpaint?: string;
      redraw?: string;
      erase?: string;
      cutout?: string;
      crop?: string;
      edit: string;
      layers: string;
      split: string;
      adjust: string;
      symmetry: string;
      download: string;
      expand: string;
      portraitEmotion?: string;
      gridPending?: string;
      hd2k?: string;
      hd4k?: string;
      split2x2?: string;
      split3x3?: string;
      split4x4?: string;
    };
  };
}

const stop = (event: ReactPointerEvent<HTMLElement>) => event.stopPropagation();

type ToolbarMenu = "portrait" | "grid" | "hd" | "split";

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
  onToolbarAction,
  showTools = true,
  labels,
}: BoardSelectionOverlayProps) {
  const handleSize = Math.max(7 / zoom, Math.min(11 / zoom, 9 / zoom));
  const toolbar = labels.toolbar;

  return (
    <div
      className="pointer-events-none absolute z-20"
      data-board-selection-overlay
      style={{ left: position.x, top: position.y, width: size.width, height: size.height }}
      aria-label={name}
    >
      <div className="pointer-events-none absolute -inset-[2px] rounded-[11px] border-2 border-[#6758dc] shadow-[0_0_0_1px_rgba(255,255,255,0.9),0_4px_14px_rgba(98,84,217,0.18)]" />
      {!multiSelected ? (
        <>
          {showTools ? (
            <div
              data-testid="creative-board-image-tools"
              className="pointer-events-auto absolute -top-[68px] left-1/2 flex max-w-[calc(100vw-32px)] -translate-x-1/2 items-center gap-0.5 overflow-visible rounded-[10px] border border-[#dfe4eb] bg-white px-2 py-1.5 text-[#4b5563] shadow-[0_8px_22px_rgba(45,56,73,0.16)]"
              onPointerDown={stop}
            >
              <ToolbarButton icon={UserRound} label={toolbar.portrait} badge="NEW" dropdown menu="portrait" onAction={onToolbarAction} items={[{ action: "portrait", preset: "quality", label: toolbar.portrait }, { action: "portrait-emotion", preset: "emotion", label: toolbar.portraitEmotion ?? toolbar.portrait }]} />
              <ToolbarButton icon={Maximize2} label={toolbar.panorama} onAction={onToolbarAction} action="panorama" />
              <ToolbarButton icon={Layers3} label={toolbar.angles} onAction={onToolbarAction} action="angles" />
              <ToolbarButton icon={SunMedium} label={toolbar.lighting} onAction={onToolbarAction} action="lighting" />
              <ToolbarButton icon={Grid3X3} label={toolbar.grid} dropdown menu="grid" onAction={onToolbarAction} items={[{ action: "grid", preset: "nine-grid", label: toolbar.gridPending ?? toolbar.grid }]} />
              <ToolbarButton text="HD" label={toolbar.hd} dropdown menu="hd" onAction={onToolbarAction} items={[{ action: "hd", label: toolbar.hd }, { action: "outpaint", label: toolbar.outpaint ?? "扩图" }, { action: "redraw", label: toolbar.redraw ?? "重绘" }, { action: "erase", label: toolbar.erase ?? "擦除" }, { action: "cutout", label: toolbar.cutout ?? "抠图" }, { action: "crop", label: toolbar.crop ?? "裁剪" }]} />
              <ToolbarButton icon={Pencil} label={toolbar.edit} onAction={onToolbarAction} action="edit" />
              <ToolbarButton icon={Layers3} label={toolbar.layers} onAction={onToolbarAction} action="layers" />
              <ToolbarButton icon={Grid3X3} label={toolbar.split} dropdown menu="split" onAction={onToolbarAction} items={[{ action: "split", preset: "2x2", label: toolbar.split2x2 ?? toolbar.split }, { action: "split", preset: "3x3", label: toolbar.split3x3 ?? toolbar.split }, { action: "split", preset: "4x4", label: toolbar.split4x4 ?? toolbar.split }]} />
              <span className="mx-1 h-5 w-px shrink-0 bg-[#e2e6ec]" aria-hidden />
              <ToolbarButton icon={SlidersHorizontal} label={toolbar.adjust} onAction={onToolbarAction} action="adjust" />
              <ToolbarButton icon={Scan} label={toolbar.symmetry} onAction={onToolbarAction} action="symmetry" />
              <ToolbarButton icon={Download} label={toolbar.download} onAction={onToolbarAction} action="download" />
              <ToolbarButton icon={Expand} label={toolbar.expand} onAction={onToolbarAction} action="expand" />
            </div>
          ) : null}
          <div className="pointer-events-none absolute inset-0">
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
                  left: corner.includes("w") ? -handleSize / 2 : size.width - handleSize / 2,
                  top: corner.includes("n") ? -handleSize / 2 : size.height - handleSize / 2,
                  cursor: `${corner}-resize`,
                }}
                aria-label={labels.resize(corner)}
              />
            ))}
          </div>
          <div className="pointer-events-auto absolute -bottom-9 left-1/2 flex -translate-x-1/2 items-center gap-0.5 rounded-lg border border-[#d9d4fb] bg-white/95 p-1 shadow-[0_5px_16px_rgba(69,57,145,0.18)] backdrop-blur-sm" onPointerDown={stop}>
            <button type="button" onPointerDown={stop} onClick={onOpenSkills} className="focus-ring rounded-md p-1 text-[#6254d9] hover:bg-[#f1efff]" aria-label={labels.openTools} title={labels.openTools}><Sparkles className="h-3.5 w-3.5" aria-hidden /></button>
            <button type="button" onPointerDown={stop} onClick={onDuplicate} className="focus-ring rounded-md p-1 text-[#64748b] hover:bg-[#f4f6fa]" aria-label={labels.duplicate} title={labels.duplicate}><Copy className="h-3.5 w-3.5" aria-hidden /></button>
            <button type="button" onPointerDown={stop} onClick={onDelete} className="focus-ring rounded-md p-1 text-[#b85d68] hover:bg-[#fff1f2]" aria-label={labels.delete} title={labels.delete}><Trash2 className="h-3.5 w-3.5" aria-hidden /></button>
          </div>
        </>
      ) : null}
    </div>
  );
}

function ToolbarButton({
  icon: Icon,
  text,
  label,
  badge,
  dropdown,
  menu,
  action,
  items,
  onAction,
}: {
  icon?: typeof UserRound;
  text?: string;
  label: string;
  badge?: string;
  dropdown?: boolean;
  menu?: ToolbarMenu;
  action?: BoardToolbarAction;
  items?: Array<{ action: BoardToolbarAction; preset?: string; label: string }>;
  onAction?: (selection: BoardToolbarSelection) => void;
}) {
  return (
    <div className="group/toolbar relative shrink-0" onMouseEnter={() => undefined}>
      <button type="button" onClick={() => action && onAction?.({ action })} className="focus-ring flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-[#4b5563] hover:bg-[#f4f6fa]" aria-label={label} title={label}>
        {Icon ? <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden /> : <span className="text-[10px] font-semibold leading-none">{text}</span>}
        <span className="whitespace-nowrap">{label}</span>
        {badge ? <span className="rounded bg-[#e7f8fb] px-1 py-0.5 text-[8px] font-bold leading-none text-[#1598ad]">{badge}</span> : null}
        {dropdown ? <ChevronDown className="h-3 w-3 shrink-0 text-[#8a96a7]" aria-hidden /> : null}
      </button>
      {menu && items?.length ? (
        <div role="menu" className="pointer-events-none invisible absolute left-1/2 top-[calc(100%+4px)] z-50 min-w-36 -translate-x-1/2 rounded-lg border border-[#dce3ec] bg-white p-1 opacity-0 shadow-[0_10px_24px_rgba(50,63,82,0.16)] transition-opacity group-hover/toolbar:pointer-events-auto group-hover/toolbar:visible group-hover/toolbar:opacity-100">
          {items.map((item, index) => <button key={item.label + index} type="button" role="menuitem" onClick={() => onAction?.({ action: item.action, preset: item.preset, label: item.label })} className="block w-full rounded-md px-2 py-1.5 text-left text-[10px] text-[#475569] hover:bg-[#f5f7fa]">{item.label}</button>)}
        </div>
      ) : null}
    </div>
  );
}

export type { ResizeCorner };
