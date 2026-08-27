import { useEffect, useRef, useState } from "react";
import { Check, Minus, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";

interface AvatarCropDialogProps {
  imageUrl: string;
  name: string;
  onClose: () => void;
  onSave: (file: File) => Promise<boolean>;
}

const OUTPUT_SIZE = 512;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function AvatarCropDialog({ imageUrl, name, onClose, onSave }: AvatarCropDialogProps) {
  const { t } = useTranslation(["dashboard", "assets"]);
  const viewportRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const dragRef = useRef<{ x: number; y: number; offsetX: number; offsetY: number } | null>(null);
  const [viewportSize, setViewportSize] = useState(520);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [saving, setSaving] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const baseScale = imageSize.width && imageSize.height
    ? Math.max(viewportSize / imageSize.width, viewportSize / imageSize.height)
    : 1;
  const renderedScale = baseScale * zoom;
  const renderedWidth = imageSize.width * renderedScale;
  const renderedHeight = imageSize.height * renderedScale;

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const updateSize = () => {
      const nextSize = viewport.getBoundingClientRect().width;
      if (nextSize > 0) setViewportSize(nextSize);
    };
    updateSize();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(updateSize);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!imageSize.width || !imageSize.height) return;
    // Keep the current crop while the responsive viewport changes; zoom updates
    // are handled independently so they do not reset the user's focal point.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOffset((current) => ({
      x: clamp(current.x, Math.min(0, viewportSize - renderedWidth), 0),
      y: clamp(current.y, Math.min(0, viewportSize - renderedHeight), 0),
    }));
  }, [imageSize.height, imageSize.width, renderedHeight, renderedWidth, viewportSize]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const zoomAroundPoint = (nextZoom: number, pointX = viewportSize / 2, pointY = viewportSize / 2) => {
    const clampedZoom = clamp(nextZoom, 1, 3);
    if (clampedZoom === zoom || !renderedScale) return;
    const nextScale = baseScale * clampedZoom;
    const imageX = (pointX - offset.x) / renderedScale;
    const imageY = (pointY - offset.y) / renderedScale;
    const nextWidth = imageSize.width * nextScale;
    const nextHeight = imageSize.height * nextScale;
    setZoom(clampedZoom);
    setOffset({
      x: clamp(pointX - imageX * nextScale, Math.min(0, viewportSize - nextWidth), 0),
      y: clamp(pointY - imageY * nextScale, Math.min(0, viewportSize - nextHeight), 0),
    });
  };

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (saving) return;
    event.preventDefault();
    const delta = event.deltaY < 0 ? 0.1 : -0.1;
    const bounds = event.currentTarget.getBoundingClientRect();
    zoomAroundPoint(
      Number((zoom + delta).toFixed(2)),
      event.clientX - bounds.left,
      event.clientY - bounds.top,
    );
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { x: event.clientX, y: event.clientY, offsetX: offset.x, offsetY: offset.y };
    setIsDragging(true);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const minX = Math.min(0, viewportSize - renderedWidth);
    const minY = Math.min(0, viewportSize - renderedHeight);
    setOffset({
      x: clamp(drag.offsetX + event.clientX - drag.x, minX, 0),
      y: clamp(drag.offsetY + event.clientY - drag.y, minY, 0),
    });
  };

  const handlePointerUp = () => {
    dragRef.current = null;
    setIsDragging(false);
  };

  const exportAvatar = async () => {
    const image = imageRef.current;
    if (!image || !image.naturalWidth || !image.naturalHeight || !renderedScale) {
      setError(t("assets:avatar_export_failed"));
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = OUTPUT_SIZE;
    canvas.height = OUTPUT_SIZE;
    const context = canvas.getContext("2d");
    if (!context) {
      setError(t("assets:avatar_export_failed"));
      return;
    }
    const sourceSize = Math.min(viewportSize / renderedScale, image.naturalWidth, image.naturalHeight);
    const sourceX = clamp(-offset.x / renderedScale, 0, image.naturalWidth - sourceSize);
    const sourceY = clamp(-offset.y / renderedScale, 0, image.naturalHeight - sourceSize);
    context.imageSmoothingQuality = "high";
    context.drawImage(image, sourceX, sourceY, sourceSize, sourceSize, 0, 0, OUTPUT_SIZE, OUTPUT_SIZE);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) {
      setError(t("assets:avatar_export_failed"));
      return;
    }
    setError(null);
    setSaving(true);
    try {
      if (await onSave(new File([blob], name + "_avatar.png", { type: "image/png" }))) onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={t("assets:edit_avatar")}
    >
      <div
        className="w-full max-w-2xl overflow-hidden rounded-2xl"
        style={{ background: "var(--panel-card-bg)", border: "1px solid var(--color-hairline)" }}
      >
        <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--color-hairline)" }}>
          <div>
            <h2 className="text-sm font-semibold" style={{ color: "var(--color-text)" }}>{t("assets:edit_avatar")}</h2>
            <p className="mt-1 text-xs" style={{ color: "var(--color-text-3)" }}>{t("assets:avatar_crop_hint")}</p>
          </div>
          <button type="button" onClick={onClose} className="focus-ring rounded-md p-1.5" aria-label={t("common:close")}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex flex-col items-center gap-4 p-5 sm:flex-row sm:items-end">
          <div
            ref={viewportRef}
            className="relative aspect-square w-[min(80vw,520px)] touch-none overflow-hidden rounded-xl bg-black"
            style={{ cursor: isDragging ? "grabbing" : "grab" }}
            onWheel={handleWheel}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
          >
            <img
              ref={imageRef}
              src={imageUrl}
              alt={name}
              draggable={false}
              onLoad={(event) => {
                const { naturalWidth, naturalHeight } = event.currentTarget;
                const scale = Math.max(viewportSize / naturalWidth, viewportSize / naturalHeight);
                setImageSize({ width: naturalWidth, height: naturalHeight });
                setOffset({
                  x: (viewportSize - naturalWidth * scale) / 2,
                  y: (viewportSize - naturalHeight * scale) / 2,
                });
                setError(null);
              }}
              onError={() => setError(t("assets:avatar_image_load_failed"))}
              className="pointer-events-none absolute max-w-none select-none"
              style={{ width: renderedWidth, height: renderedHeight, left: offset.x, top: offset.y }}
            />
            <div className="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-white/80" />
           {error && <p role="alert" className="absolute bottom-2 left-2 right-2 rounded bg-black/70 px-2 py-1 text-xs text-red-200">{error}</p>}
          </div>
          <div className="flex w-full items-center justify-center gap-2 sm:w-auto sm:flex-col">
            <button type="button" onClick={() => zoomAroundPoint(zoom - 0.1)} disabled={zoom <= 1 || saving} className="focus-ring rounded-lg p-2 disabled:opacity-40" aria-label={t("assets:zoom_out")}>
              <Minus className="h-4 w-4" />
            </button>
            <input aria-label={t("assets:avatar_zoom")} type="range" min="1" max="3" step="0.05" value={zoom} onChange={(event) => zoomAroundPoint(Number(event.target.value))} disabled={saving} className="w-36 sm:h-36 sm:w-2 sm:[writing-mode:vertical-lr]" />
            <button type="button" onClick={() => zoomAroundPoint(zoom + 0.1)} disabled={zoom >= 3 || saving} className="focus-ring rounded-lg p-2 disabled:opacity-40" aria-label={t("assets:zoom_in")}>
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t px-5 py-4" style={{ borderColor: "var(--color-hairline)" }}>
          <button type="button" onClick={onClose} disabled={saving} className="focus-ring rounded-lg px-3 py-2 text-xs" style={{ color: "var(--color-text-2)" }}>{t("common:cancel")}</button>
          <button type="button" onClick={() => void exportAvatar()} disabled={saving || !imageSize.width} className="focus-ring inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium disabled:opacity-50" style={{ background: "var(--color-accent)", color: "white" }}>
            <Check className="h-3.5 w-3.5" />{saving ? t("common:saving") : t("common:save")}
          </button>
        </div>
      </div>
    </div>
  );
}
