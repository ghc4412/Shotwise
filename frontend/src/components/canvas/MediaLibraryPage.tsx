/* eslint-disable jsx-a11y/media-has-caption -- the library previews user-provided media; caption tracks are not available at upload time. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioLines, Film, Grid2X2, Image as ImageIcon, Loader2, Search, Upload, WandSparkles, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { API } from "@/api";

type MediaKind = "image" | "video" | "audio";
type MediaOrigin = "upload" | "generated" | "edited" | "extracted" | "imported";
type Filter = "all" | MediaKind | MediaOrigin | "archived";
type BindingKind = "project" | "character" | "scene" | "prop" | "product" | "shot" | "style" | "final";
type MediaBinding = { id: string; binding_kind: string; target_id: string | null; purpose: string };
type MediaAsset = {
  id: string;
  kind: MediaKind;
  original_name: string;
  physical_path: string;
  size_bytes: number;
  origin: MediaOrigin;
  archived: boolean;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  bindings: MediaBinding[];
};
type Resource = { id: string; label: string; type: string; selectionKey: string };

const FILTERS: Filter[] = ["all", "image", "video", "audio", "upload", "generated", "edited", "extracted", "imported", "archived"];
const BINDING_KINDS: BindingKind[] = ["project", "character", "scene", "prop", "product", "shot", "style", "final"];

function mediaIcon(kind: MediaKind) {
  return kind === "video" ? Film : kind === "audio" ? AudioLines : ImageIcon;
}

function parseAsset(value: Record<string, unknown>): MediaAsset | null {
  if (typeof value.id !== "string" || !["image", "video", "audio"].includes(String(value.kind))) return null;
  const bindings = Array.isArray(value.bindings) ? value.bindings : [];
  return {
    id: value.id,
    kind: value.kind as MediaKind,
    original_name: typeof value.original_name === "string" ? value.original_name : value.id,
    physical_path: typeof value.physical_path === "string" ? value.physical_path : "",
    size_bytes: typeof value.size_bytes === "number" ? value.size_bytes : 0,
    origin: ["upload", "generated", "edited", "extracted"].includes(String(value.origin)) ? value.origin as MediaOrigin : "imported",
    archived: value.archived === true,
    width: typeof value.width === "number" ? value.width : null,
    height: typeof value.height === "number" ? value.height : null,
    duration_seconds: typeof value.duration_seconds === "number" ? value.duration_seconds : null,
    bindings: bindings.filter((item): item is MediaBinding => typeof item === "object" && item !== null && typeof (item as MediaBinding).id === "string"),
  };
}

function parseResource(value: Record<string, unknown>): Resource | null {
  if (typeof value.id !== "string") return null;
  const type = typeof value.type === "string" ? value.type : typeof value.resource_type === "string" ? value.resource_type : "resource";
  const label = typeof value.label === "string" ? value.label : typeof value.name === "string" ? value.name : value.id;
  return { id: value.id, label, type, selectionKey: typeof value.selection_key === "string" ? value.selection_key : type + ":" + value.id };
}

export function MediaLibraryPage({ projectName }: { projectName: string }) {
  const { t } = useTranslation("dashboard");
  const [, navigate] = useLocation();
  const fileInput = useRef<HTMLInputElement>(null);
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [resources, setResources] = useState<Resource[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [bindingFilter, setBindingFilter] = useState("");
  const [targetFilter, setTargetFilter] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<MediaAsset | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [binding, setBinding] = useState(false);
  const [bindingKind, setBindingKind] = useState<BindingKind>("project");
  const [targetId, setTargetId] = useState("");
  const [purpose, setPurpose] = useState("reference");

  const requestFilter = useMemo(() => ({
    kind: ["image", "video", "audio"].includes(filter) ? filter as MediaKind : undefined,
    origin: ["upload", "generated", "edited", "extracted", "imported"].includes(filter) ? filter as MediaOrigin : undefined,
    archived: filter === "archived" ? true : filter === "all" ? undefined : false,
    binding_kind: bindingFilter || undefined,
    target_id: targetFilter || undefined,
  }), [bindingFilter, filter, targetFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [response, resourceResponse] = await Promise.all([
        API.listMediaAssets(projectName, requestFilter),
        API.listCreationResources(projectName).catch(() => ({ items: [] as Array<Record<string, unknown>> })),
      ]);
      setAssets(response.items.map(parseAsset).filter((item): item is MediaAsset => item !== null));
      setResources(resourceResponse.items.map(parseResource).filter((item): item is Resource => item !== null));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("media_library_load_error"));
    } finally {
      setLoading(false);
    }
  }, [projectName, requestFilter, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load the project media index when the page mounts or filters change
    void load();
  }, [load]);

  const targetOptions = useMemo(() => resources.filter((resource) => resource.type === bindingKind || resource.selectionKey.startsWith(bindingKind + ":")), [bindingKind, resources]);
  const resourceLabels = useMemo(() => new Map(resources.map((resource) => [resource.id, resource.label])), [resources]);
  const visible = useMemo(() => assets.filter((asset) => {
    const matchesFilter = filter === "all" || (filter === "archived" ? asset.archived : !asset.archived && (filter === asset.kind || filter === asset.origin));
    const matchesBinding = !bindingFilter || asset.bindings.some((binding) => binding.binding_kind === bindingFilter && (!targetFilter || binding.target_id === targetFilter));
    const needle = query.trim().toLowerCase();
    const searchable = [asset.original_name, asset.physical_path, asset.id, ...asset.bindings.map((binding) => resourceLabels.get(binding.target_id ?? "") ?? binding.target_id ?? "")].join(" ").toLowerCase();
    return matchesFilter && matchesBinding && (!needle || searchable.includes(needle));
  }), [assets, bindingFilter, filter, query, resourceLabels, targetFilter]);

  const upload = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      await API.uploadMediaAsset(projectName, file);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("media_library_upload_error"));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const bind = async () => {
    if (!selected || (bindingKind !== "project" && !targetId)) return;
    setBinding(true);
    setError(null);
    try {
      await API.bindMediaAsset(projectName, selected.id, { binding_kind: bindingKind, target_id: targetId || null, purpose });
      const updated = parseAsset(await API.getMediaAsset(projectName, selected.id));
      if (updated) {
        setSelected(updated);
        setAssets((current) => current.map((item) => item.id === updated.id ? updated : item));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("media_library_bind_error"));
    } finally {
      setBinding(false);
    }
  };

  const toggleArchive = async () => {
    if (!selected) return;
    try {
      await API.archiveMediaAsset(projectName, selected.id, !selected.archived);
      const archived = !selected.archived;
      setSelected({ ...selected, archived });
      setAssets((current) => current.map((item) => item.id === selected.id ? { ...item, archived } : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("media_library_archive_error"));
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--color-shell)] text-[var(--color-text)]">
      <header className="border-b border-[var(--color-hairline-soft)] bg-[var(--panel-card-bg)] px-6 py-5">
        <div className="mx-auto flex max-w-[1320px] items-start justify-between gap-5">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-[var(--color-accent-2)]"><Grid2X2 className="h-3.5 w-3.5" aria-hidden />{t("media_library_eyebrow")}</div>
            <h1 className="display-serif text-[28px] font-semibold">{t("media_library_title")}</h1>
            <p className="mt-2 text-[13px]">{t("media_library_subtitle")}</p>
          </div>
          <div className="flex gap-2">
            <input ref={fileInput} type="file" accept="image/*,video/*,audio/*" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} />
            <button type="button" disabled={uploading} onClick={() => fileInput.current?.click()} className="focus-ring inline-flex items-center gap-1.5 rounded-md bg-[var(--color-accent)] px-3 py-2 text-[12px] text-white disabled:opacity-60"><Upload className="h-3.5 w-3.5" aria-hidden />{uploading ? t("media_library_uploading") : t("media_library_upload")}</button>
            <button type="button" onClick={() => navigate("/creative-board")} className="focus-ring rounded-md border border-[var(--color-hairline)] px-3 py-2 text-[12px]">{t("media_library_open_board")}</button>
          </div>
        </div>
      </header>
      <div className="mx-auto min-h-0 w-full max-w-[1320px] flex-1 overflow-y-auto px-6 py-5">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-wrap gap-1.5">{FILTERS.map((item) => <button key={item} type="button" aria-pressed={filter === item} onClick={() => setFilter(item)} className="rounded-full border border-[var(--color-hairline)] px-3 py-1.5 text-[11px]">{t("media_library_filter_" + item)}</button>)}</div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="grid gap-1 text-[10px]"><span>{t("media_library_bind")}</span><select aria-label={t("media_library_bind")} value={bindingFilter} onChange={(event) => { setBindingFilter(event.target.value); setTargetFilter(""); }} className="h-8 rounded-md border border-[var(--color-hairline)] bg-transparent px-2 text-[11px]"><option value="">{t("media_library_filter_all")}</option>{BINDING_KINDS.map((kind) => <option key={kind} value={kind}>{t("media_library_binding_" + kind)}</option>)}</select></label>
            {bindingFilter ? <label className="grid gap-1 text-[10px]"><span>{t("media_library_target_id")}</span><select aria-label={t("media_library_target_id")} value={targetFilter} onChange={(event) => setTargetFilter(event.target.value)} className="h-8 max-w-48 rounded-md border border-[var(--color-hairline)] bg-transparent px-2 text-[11px]"><option value="">{t("media_library_filter_all")}</option>{resources.filter((resource) => resource.type === bindingFilter || resource.selectionKey.startsWith(bindingFilter + ":")).map((resource) => <option key={resource.id} value={resource.id}>{resource.label}</option>)}</select></label> : null}
            <label className="flex h-8 w-60 items-center gap-2 rounded-md border border-[var(--color-hairline)] px-2.5"><Search className="h-3.5 w-3.5" aria-hidden /><span className="sr-only">{t("media_library_search")}</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("media_library_search")} className="min-w-0 flex-1 bg-transparent text-[12px] outline-none" /></label>
          </div>
        </div>
        {error ? <div className="mb-4 flex items-center justify-between rounded-md border border-[var(--color-danger)]/30 px-3 py-2 text-[12px]"><span>{error}</span><button type="button" onClick={() => void load()}>{t("media_library_retry")}</button></div> : null}
        {loading ? <div className="flex items-center justify-center p-16 text-[12px] text-[var(--color-text-3)]"><Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />{t("media_library_loading")}</div> : <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">{visible.map((asset) => { const Icon = mediaIcon(asset.kind); const url = API.getMediaAssetContentUrl(projectName, asset.id); return <button type="button" key={asset.id} onClick={() => setSelected(asset)} className="overflow-hidden rounded-lg border border-[var(--color-hairline-soft)] bg-[var(--panel-card-bg)] text-left transition hover:border-[var(--color-accent-2)]"><div className="relative flex aspect-[1.35] items-center justify-center overflow-hidden bg-[var(--color-shell-field)] text-[var(--color-accent-2)]">{asset.kind === "image" ? <img src={url} alt={asset.original_name} loading="lazy" className="h-full w-full object-cover" /> : asset.kind === "video" ? <video src={url} preload="metadata" muted className="h-full w-full object-cover" /> : <AudioLines className="h-8 w-8" aria-hidden />}<Icon className="absolute bottom-2 left-2 h-4 w-4 rounded bg-black/40 p-0.5 text-white" aria-hidden /><span className="absolute right-2 top-2 rounded bg-black/45 px-1.5 py-0.5 text-[9px] text-white">{t("media_library_source_" + asset.origin)}</span></div><div className="p-3"><h2 className="truncate text-[12px] font-semibold">{asset.original_name}</h2><p className="mt-1 truncate font-mono text-[9px] text-[var(--color-text-4)]">{asset.physical_path}</p><div className="mt-3 flex justify-between text-[10px] text-[var(--color-text-3)]"><span>{asset.bindings.length ? t("media_library_in_use") : t("media_library_unbound")}</span>{asset.origin === "upload" ? <Upload className="h-3 w-3" aria-hidden /> : <WandSparkles className="h-3 w-3" aria-hidden />}</div></div></button>; })}</div>}
        {!loading && visible.length === 0 ? <div className="p-12 text-center text-[12px]">{t("media_library_empty")}</div> : null}
      </div>
      {selected ? <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/35 p-4 md:items-center" role="dialog" aria-modal="true" aria-label={t("media_library_detail")}><section className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-xl border border-[var(--color-hairline)] bg-[var(--panel-card-bg)] p-5 shadow-2xl"><div className="flex items-center justify-between"><div><h2 className="text-[16px] font-semibold">{selected.original_name}</h2><p className="mt-1 text-[10px] text-[var(--color-text-3)]">{selected.id}</p></div><button type="button" onClick={() => setSelected(null)} aria-label={t("media_library_close")}><X className="h-4 w-4" aria-hidden /></button></div><div className="mt-4 flex max-h-72 items-center justify-center overflow-hidden rounded-lg bg-[var(--color-shell-field)]">{selected.kind === "image" ? <img src={API.getMediaAssetContentUrl(projectName, selected.id)} alt={selected.original_name} className="max-h-72 max-w-full object-contain" /> : selected.kind === "video" ? <video src={API.getMediaAssetContentUrl(projectName, selected.id)} controls className="max-h-72 max-w-full" /> : <audio src={API.getMediaAssetContentUrl(projectName, selected.id)} controls className="w-full" />}</div><dl className="mt-4 grid grid-cols-2 gap-3 text-[11px]"><div><dt className="text-[var(--color-text-4)]">{t("media_library_source")}</dt><dd>{t("media_library_source_" + selected.origin)}</dd></div><div><dt className="text-[var(--color-text-4)]">{t("media_library_size")}</dt><dd>{selected.size_bytes.toLocaleString()} B</dd></div><div><dt className="text-[var(--color-text-4)]">{t("media_library_dimensions")}</dt><dd>{selected.width && selected.height ? selected.width + " × " + selected.height : "—"}</dd></div><div><dt className="text-[var(--color-text-4)]">{t("media_library_duration")}</dt><dd>{selected.duration_seconds ? selected.duration_seconds + "s" : "—"}</dd></div></dl><div className="mt-5 border-t border-[var(--color-hairline-soft)] pt-4"><h3 className="text-[12px] font-semibold">{t("media_library_bind")}</h3><p className="mt-1 text-[10px] text-[var(--color-text-3)]">{t("media_library_subtitle")}</p><div className="mt-2 grid gap-2 md:grid-cols-3"><label className="grid gap-1 text-[10px]"><span>{t("media_library_bind")}</span><select aria-label={t("media_library_binding_kind")} value={bindingKind} onChange={(event) => { setBindingKind(event.target.value as BindingKind); setTargetId(""); }} className="rounded border border-[var(--color-hairline)] bg-transparent px-2 py-2 text-[11px]">{BINDING_KINDS.map((kind) => <option key={kind} value={kind}>{t("media_library_binding_" + kind)}</option>)}</select></label><label className="grid gap-1 text-[10px]"><span>{t("media_library_target_id")}</span><select aria-label={t("media_library_target_id")} value={targetId} onChange={(event) => setTargetId(event.target.value)} disabled={bindingKind === "project" || targetOptions.length === 0} className="rounded border border-[var(--color-hairline)] bg-transparent px-2 py-2 text-[11px]"><option value="">{bindingKind === "project" ? t("media_library_binding_project") : t("media_library_empty")}</option>{targetOptions.map((resource) => <option key={resource.id} value={resource.id}>{resource.label}</option>)}</select></label><label className="grid gap-1 text-[10px]"><span>{t("media_library_purpose")}</span><select aria-label={t("media_library_purpose")} value={purpose} onChange={(event) => setPurpose(event.target.value)} className="rounded border border-[var(--color-hairline)] bg-transparent px-2 py-2 text-[11px]"><option value="reference">{t("media_library_purpose")} · reference</option><option value="style">{t("media_library_purpose")} · style</option><option value="final">{t("media_library_purpose")} · final</option></select></label></div>{bindingKind !== "project" && targetOptions.length === 0 ? <p className="mt-2 text-[10px] text-[var(--color-text-3)]">{t("media_library_empty")}</p> : null}<div className="mt-2 flex gap-2"><button type="button" disabled={binding || (bindingKind !== "project" && !targetId)} onClick={() => void bind()} className="rounded bg-[var(--color-accent)] px-3 py-2 text-[11px] text-white disabled:opacity-60">{binding ? t("media_library_binding") : t("media_library_bind")}</button><button type="button" onClick={() => void toggleArchive()} className="rounded border border-[var(--color-hairline)] px-3 py-2 text-[11px]">{selected.archived ? t("media_library_unarchive") : t("media_library_archive")}</button></div></div><div className="mt-4 whitespace-pre-line text-[10px] text-[var(--color-text-3)]">{selected.bindings.map((item) => item.binding_kind + ":" + (resourceLabels.get(item.target_id ?? "") ?? item.target_id ?? "project") + " · " + item.purpose).join("\n") || t("media_library_no_bindings")}</div></section></div> : null}
    </div>
  );
}
