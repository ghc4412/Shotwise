import { useRef } from "react";
import { ImagePlus, Loader2, X } from "lucide-react";
import type { BoardToolbarAction } from "./BoardSelectionOverlay";

export type ReferenceAsset = { id: string; name: string; previewUrl?: string; mimeType?: string };

export interface BoardImageToolPanelProps {
  action: BoardToolbarAction;
  preset?: string;
  title: string;
  imageUrl?: string;
  instruction: string;
  referenceMediaAssetId: string;
  referenceAssets: ReferenceAsset[];
  gridRows: number;
  gridCols: number;
  includeSplitLines: boolean;
  busy?: boolean;
  onClose: () => void;
  onInstructionChange: (value: string) => void;
  onReferenceChange: (value: string) => void;
  onGridRowsChange: (value: number) => void;
  onGridColsChange: (value: number) => void;
  onIncludeSplitLinesChange: (value: boolean) => void;
  onUploadReference: (file: File) => void | Promise<void>;
  onSubmit: () => void | Promise<void>;
  labels: {
    description: string;
    close: string;
    previewUnavailable: string;
    instructionPlaceholder: string;
    instructionLabel: string;
    referenceImage: string;
    upload: string;
    noReference: string;
    cancel: string;
    submitEdit: string;
    applyAdjustment: string;
    gridRows: string;
    gridCols: string;
    includeSplitLines: string;
  };
}

const needsInstruction = new Set<BoardToolbarAction>(["edit", "adjust", "portrait", "portrait-emotion", "panorama", "angles", "lighting", "hd", "layers", "symmetry"]);

export function BoardImageToolPanel({
  action,
  preset,
  title,
  imageUrl,
  instruction,
  referenceMediaAssetId,
  referenceAssets,
  gridRows,
  gridCols,
  includeSplitLines,
  busy = false,
  adjustmentOpen,
  onClose,
  onPreviewClick,
  onInstructionChange,
  onReferenceChange,
  onGridRowsChange,
  onGridColsChange,
  onIncludeSplitLinesChange,
  onUploadReference,
  onSubmit,
  labels,
}: BoardImageToolPanelProps & {
  adjustmentOpen: boolean;
  onPreviewClick: () => void;
}) {
  const uploadRef = useRef<HTMLInputElement>(null);
  const isGridAction = action === "grid" || action === "split";
  const acceptsReference = !isGridAction && action !== "layers" && action !== "symmetry";
  return (
    <div onPointerDown={(event) => event.stopPropagation()} className="pointer-events-auto absolute inset-x-3 bottom-3 z-50 flex max-h-[min(78vh,620px)] flex-col overflow-hidden rounded-2xl border border-[#d9d4fb] bg-white/98 shadow-[0_18px_55px_rgba(42,45,76,0.24)] backdrop-blur-sm" data-testid="creative-board-tool-panel" data-tool-preset={preset ?? ""}>
      <div className="flex shrink-0 items-center justify-between border-b border-[#edf0f4] px-4 py-2.5">
        <div className="min-w-0"><div className="truncate text-[12px] font-semibold text-[#334155]">{title}</div><div className="mt-0.5 text-[9px] text-[#8a96a7]">{labels.description}</div></div>
        <button type="button" onClick={onClose} className="focus-ring rounded-md p-1 text-[#64748b] hover:bg-[#f5f7fa]" aria-label={labels.close}><X className="h-4 w-4" aria-hidden /></button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3">
        <button type="button" onClick={onPreviewClick} className="flex min-h-40 w-full items-center justify-center overflow-hidden rounded-xl border border-[#e4e8ef] bg-[#f7f8fb] text-left" data-testid="creative-board-tool-preview" aria-label={title}>
          {imageUrl ? <img src={imageUrl} alt={title} className="max-h-[min(42vh,360px)] w-full object-contain" /> : <span className="px-5 text-center text-[10px] text-[#94a3b8]">{labels.previewUnavailable}</span>}
        </button>
        {adjustmentOpen ? <div className="mt-3 flex min-h-0 flex-col gap-3 border-t border-[#edf0f4] pt-3">
          {isGridAction ? <div className="grid grid-cols-2 gap-2 rounded-xl border border-[#e7eaf0] bg-[#fafbfe] p-2.5">
            <label className="flex flex-col gap-1 text-[10px] font-semibold text-[#475569]">{labels.gridRows}<input type="number" min={2} max={8} value={gridRows} onChange={(event) => onGridRowsChange(Math.min(8, Math.max(2, Math.round(Number(event.target.value) || 2))))} data-testid="creative-board-grid-rows" className="rounded-lg border border-[#dfe5ed] bg-white px-2 py-1.5 text-[11px] font-normal text-[#334155] outline-none focus:border-[#8f85e8]" /></label>
            <label className="flex flex-col gap-1 text-[10px] font-semibold text-[#475569]">{labels.gridCols}<input type="number" min={2} max={8} value={gridCols} onChange={(event) => onGridColsChange(Math.min(8, Math.max(2, Math.round(Number(event.target.value) || 2))))} data-testid="creative-board-grid-cols" className="rounded-lg border border-[#dfe5ed] bg-white px-2 py-1.5 text-[11px] font-normal text-[#334155] outline-none focus:border-[#8f85e8]" /></label>
            <label className="col-span-2 flex items-center gap-2 text-[10px] font-normal text-[#64748b]"><input type="checkbox" checked={includeSplitLines} onChange={(event) => onIncludeSplitLinesChange(event.target.checked)} data-testid="creative-board-grid-split-lines" />{labels.includeSplitLines}</label>
          </div> : <textarea value={instruction} onChange={(event) => onInstructionChange(event.target.value)} placeholder={labels.instructionPlaceholder} className="min-h-24 w-full resize-y rounded-xl border border-[#dfe5ed] bg-white px-3 py-2 text-[11px] text-[#334155] outline-none placeholder:text-[#a4adba] focus:border-[#8f85e8]" aria-label={labels.instructionLabel} />}
          {acceptsReference ? <div className="rounded-xl border border-[#e7eaf0] bg-[#fafbfe] p-2.5"><div className="mb-2 flex items-center justify-between text-[10px] font-semibold text-[#475569]"><span>{labels.referenceImage}</span><button type="button" onClick={() => uploadRef.current?.click()} className="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] text-[#6254d9] hover:bg-[#f0edff]"><ImagePlus className="h-3 w-3" aria-hidden />{labels.upload}</button><input ref={uploadRef} type="file" accept="image/*" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void onUploadReference(file); event.currentTarget.value = ""; }} /></div><select value={referenceMediaAssetId} onChange={(event) => onReferenceChange(event.target.value)} className="w-full rounded-lg border border-[#dfe5ed] bg-white px-2 py-1.5 text-[10px] text-[#64748b]" aria-label={labels.referenceImage}><option value="">{labels.noReference}</option>{referenceAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></div> : null}
          <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="focus-ring rounded-lg border border-[#dfe5ed] px-3 py-2 text-[10px] text-[#64748b] hover:bg-[#f7f8fb]">{labels.cancel}</button><button type="button" disabled={busy || (needsInstruction.has(action) && !isGridAction && !instruction.trim())} onClick={() => void onSubmit()} className="focus-ring inline-flex items-center gap-1.5 rounded-lg bg-[#6254d9] px-3 py-2 text-[10px] font-semibold text-white hover:bg-[#5548c5] disabled:cursor-not-allowed disabled:opacity-50">{busy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}{action === "edit" ? labels.submitEdit : labels.applyAdjustment}</button></div>
        </div> : null}
      </div>
    </div>
  );
}
