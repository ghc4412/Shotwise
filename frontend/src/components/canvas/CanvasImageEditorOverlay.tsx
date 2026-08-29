import { useCallback, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { Loader2, X } from "lucide-react";

export type CanvasEditorOperation = "hd" | "outpaint" | "redraw" | "erase" | "cutout" | "crop";

export type CanvasEditorSubmission = {
  instruction: string;
  region?: { x: number; y: number; width: number; height: number };
  count?: number;
  aspectRatio?: string;
  quality?: string;
  multiplier?: number;
};

type DragMode = "move" | "nw" | "ne" | "sw" | "se";

const REGION_NEEDS_BOX = new Set<CanvasEditorOperation>(["redraw", "erase", "crop", "outpaint"]);
const MIN_REGION = 0.08;

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

export function CanvasImageEditorOverlay({
  operation,
  title,
  imageUrl,
  busy = false,
  onClose,
  onSubmit,
  labels,
}: {
  operation: CanvasEditorOperation;
  title: string;
  imageUrl?: string;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (submission: CanvasEditorSubmission) => void | Promise<void>;
  labels: {
    close: string;
    run: string;
    running: string;
    instructionPlaceholder: string;
    instructionLabel: string;
    regionHint: string;
    ratio: string;
    ratioOriginal: string;
    ratio116: string;
    ratio34: string;
    ratio169: string;
    resolution: string;
    resolution2k: string;
    resolution4k: string;
    count: string;
    multiplier: string;
    multiplier2: string;
    multiplier4: string;
    multiplier6: string;
  };
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);
  const [region, setRegion] = useState({ x: 0.1, y: 0.1, width: 0.8, height: 0.8 });
  const [instruction, setInstruction] = useState("");
  const [ratio, setRatio] = useState("original");
  const [resolution, setResolution] = useState("2k");
  const [count, setCount] = useState(1);
  const [multiplier, setMultiplier] = useState(2);
  const dragRef = useRef<{ mode: DragMode; startX: number; startY: number; start: typeof region } | null>(null);

  const needsRegion = REGION_NEEDS_BOX.has(operation);

  const displayed = useCallback(() => {
    const width = naturalSize?.width ?? 800;
    const height = naturalSize?.height ?? 600;
    const maxWidth = Math.min(window.innerWidth * 0.6, 1100);
    const maxHeight = Math.min(window.innerHeight * 0.52, 620);
    const scale = Math.min(maxWidth / width, maxHeight / height);
    return { width: Math.round(width * scale), height: Math.round(height * scale) };
  }, [naturalSize]);

  const box = displayed();
  const regionPx = {
    left: region.x * box.width,
    top: region.y * box.height,
    width: region.width * box.width,
    height: region.height * box.height,
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLElement>, mode: DragMode) => {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { mode, startX: event.clientX, startY: event.clientY, start: { ...region } };
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    event.preventDefault();
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const dx = (event.clientX - drag.startX) / rect.width;
    const dy = (event.clientY - drag.startY) / rect.height;
    let { x, y, width, height } = drag.start;
    if (drag.mode === "move") {
      x = Math.min(clamp01(drag.start.x + dx), 1 - width);
      y = Math.min(clamp01(drag.start.y + dy), 1 - height);
    } else if (drag.mode === "se") {
      width = drag.start.width + dx;
      height = drag.start.height + dy;
    } else if (drag.mode === "sw") {
      width = drag.start.width - dx;
      x = drag.start.x + dx;
      height = drag.start.height + dy;
    } else if (drag.mode === "ne") {
      height = drag.start.height - dy;
      y = drag.start.y + dy;
      width = drag.start.width + dx;
    } else if (drag.mode === "nw") {
      width = drag.start.width - dx;
      x = drag.start.x + dx;
      height = drag.start.height - dy;
      y = drag.start.y + dy;
    }
    setRegion({ x: clamp01(x), y: clamp01(y), width: Math.max(MIN_REGION, width), height: Math.max(MIN_REGION, height) });
  };

  const onPointerUp = () => {
    dragRef.current = null;
  };

  const run = () => {
    const submission: CanvasEditorSubmission = {
      instruction: instruction.trim(),
      count: operation === "cutout" ? 1 : count,
      aspectRatio: ratio === "original" ? undefined : ratio,
      quality: operation === "crop" ? undefined : resolution.toUpperCase(),
      multiplier: operation === "hd" ? multiplier : undefined,
    };
    if (needsRegion) submission.region = region;
    void onSubmit(submission);
  };

  return createPortal(
    <div className="fixed inset-0 z-[120] flex flex-col bg-[#10131a]/55 backdrop-blur-[2px]" role="dialog" aria-modal="true" aria-label={title} onWheel={(event) => event.stopPropagation()}>
      <div className="flex items-center justify-between border-b border-[#e4e9f0] bg-white px-4 py-2.5">
        <div className="min-w-0"><div className="truncate text-[13px] font-semibold text-[#334155]">{title}</div></div>
        <button type="button" onClick={onClose} className="focus-ring rounded-md p-1 text-[#64748b] hover:bg-[#f5f7fa]" aria-label={labels.close}><X className="h-4 w-4" aria-hidden /></button>
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col items-center justify-center gap-4 overflow-hidden p-4">
        <div ref={containerRef} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} className="relative overflow-hidden rounded-lg border border-white/60 bg-[#0d1117] shadow-[0_20px_60px_rgba(0,0,0,0.35)]" style={{ width: box.width, height: box.height }} data-testid="canvas-image-editor-canvas">
          {imageUrl ? <img src={imageUrl} alt={title} draggable={false} className="pointer-events-none h-full w-full select-none object-fill" onLoad={(event) => { const img = event.currentTarget; if (img.naturalWidth && img.naturalHeight) setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight }); }} /> : <span className="flex h-full items-center justify-center text-[12px] text-white/80">—</span>}
          {needsRegion && !busy ? (
            <div className="absolute cursor-move border-2 border-[#63e1ff] shadow-[0_0_0_1px_rgba(255,255,255,0.8)]" style={{ left: regionPx.left, top: regionPx.top, width: regionPx.width, height: regionPx.height }} data-region-box onPointerDown={(event) => onPointerDown(event, "move")}>
              <span className="absolute -top-6 left-0 whitespace-nowrap text-[10px] font-medium text-white/85">{labels.regionHint}</span>
              {(["nw", "ne", "sw", "se"] as const).map((corner) => (
                <button key={corner} type="button" aria-label={corner} onPointerDown={(event) => onPointerDown(event, corner)} className="absolute h-3 w-3 rounded-sm border border-white bg-[#63e1ff] shadow" style={{ left: corner.includes("w") ? -6 : regionPx.width - 6, top: corner.includes("n") ? -6 : regionPx.height - 6, cursor: `${corner}-resize` }} />
              ))}
            </div>
          ) : null}
        </div>

        <div className="pointer-events-auto w-full max-w-xl rounded-2xl border border-[#d9d4fb] bg-white/98 p-3 shadow-[0_18px_55px_rgba(42,45,76,0.24)] backdrop-blur-sm" data-testid="canvas-image-editor-config" onWheel={(event) => event.stopPropagation()}>
          <div className="flex min-h-0 flex-col gap-3">
            <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder={labels.instructionPlaceholder} className="min-h-16 w-full resize-y rounded-lg border border-[#dfe5ed] bg-white px-3 py-2 text-[11px] text-[#334155] outline-none placeholder:text-[#a4adba] focus:border-[#8f85e8]" aria-label={labels.instructionLabel} />
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-[10px] font-semibold text-[#475569]">{labels.ratio}<select value={ratio} onChange={(event) => setRatio(event.target.value)} className="rounded-lg border border-[#dfe5ed] bg-white px-2 py-1.5 text-[11px] text-[#334155]" aria-label={labels.ratio}><option value="original">{labels.ratioOriginal}</option><option value="1:1">{labels.ratio116}</option><option value="3:4">{labels.ratio34}</option><option value="16:9">{labels.ratio169}</option></select></label>
              {operation !== "crop" ? <label className="flex flex-col gap-1 text-[10px] font-semibold text-[#475569]">{labels.resolution}<select value={resolution} onChange={(event) => setResolution(event.target.value)} className="rounded-lg border border-[#dfe5ed] bg-white px-2 py-1.5 text-[11px] text-[#334155]" aria-label={labels.resolution}><option value="2k">{labels.resolution2k}</option><option value="4k">{labels.resolution4k}</option></select></label> : null}
              {operation === "hd" ? <label className="flex flex-col gap-1 text-[10px] font-semibold text-[#475569]">{labels.multiplier}<select value={multiplier} onChange={(event) => setMultiplier(Number(event.target.value))} className="rounded-lg border border-[#dfe5ed] bg-white px-2 py-1.5 text-[11px] text-[#334155]" aria-label={labels.multiplier}><option value={2}>{labels.multiplier2}</option><option value={4}>{labels.multiplier4}</option><option value={6}>{labels.multiplier6}</option></select></label> : null}
              {operation === "redraw" || operation === "outpaint" ? <label className="flex flex-col gap-1 text-[10px] font-semibold text-[#475569]">{labels.count}<input type="number" min={1} max={4} value={count} onChange={(event) => setCount(Math.min(4, Math.max(1, Math.round(Number(event.target.value) || 1))))} className="w-16 rounded-lg border border-[#dfe5ed] bg-white px-2 py-1.5 text-[11px] text-[#334155] outline-none" aria-label={labels.count} /></label> : null}
            </div>
            {needsRegion ? <p className="text-[10px] text-[#94a3b8]">{labels.regionHint}</p> : null}
          </div>
        </div>
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-[#e4e9f0] bg-white px-4 py-2.5">
        <button type="button" onClick={onClose} className="focus-ring rounded-lg border border-[#dfe5ed] px-3 py-2 text-[11px] text-[#64748b] hover:bg-[#f7f8fb]">{labels.close}</button>
        <button type="button" disabled={busy || !imageUrl} onClick={run} className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-[#6254d9] px-4 py-2 text-[11px] font-semibold text-white hover:bg-[#5548c5] disabled:cursor-not-allowed disabled:opacity-50" data-testid="canvas-image-editor-run">{busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}{busy ? labels.running : labels.run}</button>
      </div>
    </div>,
    document.body,
  );
}
