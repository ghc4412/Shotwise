import { useCallback, useRef, useState } from "react";
import { Copy, Download, History, Loader2, MoreHorizontal, RotateCcw, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API, type CreativeBoardVersionRecord } from "@/api";
import type { CreativeBoardSnapshot } from "./CreativeBoardWorkspace";
import type { CanvasPersistenceStatus } from "./canvasPersistence";

interface CreativeBoardActionsProps {
  boardId: string;
  projectName: string;
  snapshot: CreativeBoardSnapshot;
  saveStatus: CanvasPersistenceStatus;
  ensureSaved: () => Promise<boolean>;
  onRestored: () => Promise<void>;
  onCopied: (boardId: string) => void;
  onError: (message: string) => void;
}

function downloadFile(filename: string, content: BlobPart, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function escapeSvg(value: string) {
  const entities: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&apos;" };
  return value.replace(/[&<>"']/g, (character) => entities[character] ?? character);
}

function snapshotSvg(snapshot: CreativeBoardSnapshot) {
  const edges = snapshot.edges.map((edge) => {
    const source = snapshot.items.find((item) => item.id === edge.source_item_id);
    const target = snapshot.items.find((item) => item.id === edge.target_item_id);
    if (!source || !target) return "";
    const x1 = source.position.x + source.size.width / 2;
    const y1 = source.position.y + source.size.height / 2;
    const x2 = target.position.x + target.size.width / 2;
    const y2 = target.position.y + target.size.height / 2;
    return "<path d=\"M" + x1 + " " + y1 + " L" + x2 + " " + y2 + "\" stroke=\"#a8b3c3\" stroke-width=\"3\" fill=\"none\"/>";
  }).join("");
  const items = snapshot.items.map((item) => "<g><rect x=\"" + item.position.x + "\" y=\"" + item.position.y + "\" width=\"" + item.size.width + "\" height=\"" + item.size.height + "\" rx=\"14\" fill=\"#ffffff\" stroke=\"#d9e0ea\"/><text x=\"" + (item.position.x + 16) + "\" y=\"" + (item.position.y + 28) + "\" font-family=\"sans-serif\" font-size=\"16\" fill=\"#334155\">" + escapeSvg(item.resource_id) + "</text></g>").join("");
  return "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"5000\" height=\"3500\" viewBox=\"0 0 5000 3500\"><rect width=\"100%\" height=\"100%\" fill=\"#f5f8fc\"/>" + edges + items + "</svg>";
}

export function CreativeBoardActions({ boardId, snapshot, saveStatus, ensureSaved, onRestored, onCopied, onError }: CreativeBoardActionsProps) {
  const { t } = useTranslation("dashboard");
  const [open, setOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<CreativeBoardVersionRecord[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<CreativeBoardVersionRecord | null>(null);
  const [versionName, setVersionName] = useState("");
  const [copyName, setCopyName] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [retryAvailable, setRetryAvailable] = useState(false);
  const retryRef = useRef<(() => Promise<void>) | null>(null);
  const snapshotRevision = snapshot.revision;

  const guarded = useCallback(async () => {
    const saved = await ensureSaved();
    if (!saved) {
      const message = t("creative_board_action_save_failed");
      setNotice(message);
      setRetryAvailable(true);
      onError(message);
      retryRef.current = async () => {
        if (await ensureSaved()) {
          setRetryAvailable(false);
          setNotice(null);
        }
      };
      return false;
    }
    setRetryAvailable(false);
    return true;
  }, [ensureSaved, onError, t]);

  const loadVersions = useCallback(async () => {
    if (!(await guarded())) return;
    setBusy(true);
    try {
      const result = await API.listCreativeBoardVersions(boardId);
      const enriched = await Promise.all(result.items.map(async (version) => {
        const detail = await API.getCreativeBoardVersion(boardId, version.id);
        const detailSnapshot = detail.snapshot;
        return { ...version, items_count: detailSnapshot?.items.length ?? 0, edges_count: detailSnapshot?.edges.length ?? 0 };
      }));
      setVersions(enriched);
      setVersionsOpen(true);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("creative_board_version_load_error");
      setNotice(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  }, [boardId, guarded, onError, t]);

  const saveVersion = useCallback(async () => {
    const trimmedName = versionName.trim();
    if (!trimmedName || !(await guarded())) return;
    setBusy(true);
    try {
      await API.createCreativeBoardVersion(boardId, { version_name: trimmedName, expected_revision: snapshot.revision });
      setVersionName("");
      setNotice(t("creative_board_version_saved"));
      if (versionsOpen) await loadVersions();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("creative_board_version_error");
      setNotice(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  }, [boardId, guarded, loadVersions, onError, snapshot, t, versionName, versionsOpen]);

  const restoreVersion = useCallback(async () => {
    if (!selectedVersion || !(await guarded())) return;
    setBusy(true);
    try {
      await API.restoreCreativeBoardVersion(boardId, selectedVersion.id, snapshotRevision);
      await onRestored();
      setSelectedVersion(null);
      setNotice(t("creative_board_version_restore_success"));
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("creative_board_version_restore_error");
      setNotice(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  }, [boardId, guarded, onError, onRestored, selectedVersion, snapshotRevision, t]);

  const copyBoard = useCallback(async () => {
    const trimmedName = copyName.trim();
    if (!trimmedName || !(await guarded())) return;
    setBusy(true);
    try {
      const result = await API.duplicateCreativeBoard(boardId, { name: trimmedName });
      onCopied(result.id);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("creative_board_copy_error");
      setNotice(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  }, [boardId, copyName, guarded, onCopied, onError, t]);

  const exportJson = useCallback(async () => {
    if (!(await guarded())) return;
    try {
      downloadFile((snapshot.name || "creative-board") + ".json", JSON.stringify(snapshot, null, 2), "application/json");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("creative_board_export_error");
      setNotice(message);
      onError(message);
    }
  }, [guarded, onError, snapshot, t]);

  const exportImage = useCallback(async () => {
    if (!(await guarded())) return;
    try {
      downloadFile((snapshot.name || "creative-board") + ".svg", snapshotSvg(snapshot), "image/svg+xml");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("creative_board_export_error");
      setNotice(message);
      onError(message);
    }
  }, [guarded, onError, snapshot, t]);

  const actionDisabled = busy || saveStatus === "saving";
  return <div className="relative flex items-center gap-1">
    <button type="button" disabled={actionDisabled} onClick={() => setOpen((value) => !value)} className="focus-ring inline-flex items-center gap-1 rounded-md border border-[#dfe5ed] bg-white px-2 py-1.5 text-[10px] font-medium text-[#64748b] disabled:opacity-50" aria-expanded={open} aria-label={t("creative_board_actions")}><MoreHorizontal className="h-3.5 w-3.5" aria-hidden />{t("creative_board_actions")}</button>
    {open ? <div className="absolute right-0 top-9 z-50 w-72 rounded-lg border border-[#dfe5ed] bg-white p-3 shadow-[0_12px_30px_rgba(53,68,91,0.16)]"><div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8a96a7]">{t("creative_board_actions")}</div><div className="space-y-2"><div className="flex gap-1.5"><input value={versionName} onChange={(event) => setVersionName(event.target.value)} placeholder={t("creative_board_version_name_placeholder")} aria-label={t("creative_board_version_name")} className="min-w-0 flex-1 rounded-md border border-[#dfe5ed] px-2 py-1.5 text-[10px] outline-none focus:border-[#9b92ed]" /><button type="button" disabled={actionDisabled || !versionName.trim()} onClick={() => void saveVersion()} className="focus-ring inline-flex items-center gap-1 rounded-md bg-[#6254d9] px-2 py-1.5 text-[10px] font-semibold text-white disabled:opacity-50"><Save className="h-3 w-3" aria-hidden />{t("creative_board_save_version")}</button></div><button type="button" disabled={actionDisabled} onClick={() => void loadVersions()} className="focus-ring flex w-full items-center gap-2 rounded-md border border-[#dfe5ed] px-2 py-1.5 text-left text-[10px] text-[#64748b] disabled:opacity-50"><History className="h-3.5 w-3.5 text-[#6254d9]" aria-hidden />{t("creative_board_version_list")}</button><div className="flex gap-1.5"><input value={copyName} onChange={(event) => setCopyName(event.target.value)} placeholder={t("creative_board_copy_name_placeholder")} aria-label={t("creative_board_copy_name")} className="min-w-0 flex-1 rounded-md border border-[#dfe5ed] px-2 py-1.5 text-[10px] outline-none focus:border-[#9b92ed]" /><button type="button" disabled={actionDisabled || !copyName.trim()} onClick={() => void copyBoard()} className="focus-ring inline-flex items-center gap-1 rounded-md border border-[#dfe5ed] px-2 py-1.5 text-[10px] text-[#64748b] disabled:opacity-50"><Copy className="h-3 w-3" aria-hidden />{t("creative_board_copy")}</button></div><div className="flex gap-1.5"><button type="button" disabled={actionDisabled} onClick={() => void exportJson()} className="focus-ring inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-[#dfe5ed] px-2 py-1.5 text-[10px] text-[#64748b] disabled:opacity-50"><Download className="h-3 w-3" aria-hidden />{t("creative_board_export_json")}</button><button type="button" disabled={actionDisabled} onClick={() => void exportImage()} className="focus-ring inline-flex flex-1 items-center justify-center gap-1 rounded-md border border-[#dfe5ed] px-2 py-1.5 text-[10px] text-[#64748b] disabled:opacity-50"><Download className="h-3 w-3" aria-hidden />{t("creative_board_export_image")}</button></div></div>{notice ? <div className="mt-2 rounded-md bg-[#fff8f8] px-2 py-1.5 text-[10px] text-[#a34a4a]" role="alert">{notice}{retryAvailable ? <button type="button" className="ml-2 underline" onClick={() => void retryRef.current?.()}>{t("creative_board_action_retry")}</button> : null}</div> : null}</div> : null}
    {versionsOpen ? <div className="absolute right-0 top-9 z-[51] w-80 rounded-lg border border-[#dfe5ed] bg-white shadow-[0_12px_30px_rgba(53,68,91,0.16)]"><div className="flex items-center justify-between border-b border-[#edf0f4] px-3 py-2"><span className="text-[11px] font-semibold text-[#334155]">{t("creative_board_version_list")}</span><button type="button" onClick={() => setVersionsOpen(false)} aria-label={t("creative_board_action_cancel")} className="text-[#8a96a7]">×</button></div><div className="max-h-72 overflow-y-auto p-2">{versions.length === 0 ? <div className="p-4 text-center text-[10px] text-[#8a96a7]">{t("creative_board_version_empty")}</div> : versions.map((version) => <button type="button" key={version.id} onClick={() => setSelectedVersion(version)} className="mb-1.5 block w-full rounded-md border border-[#edf0f4] px-2.5 py-2 text-left hover:border-[#c8c1ff]"><div className="flex items-center justify-between text-[10px] font-semibold text-[#334155]"><span>{t("creative_board_version_number", { version: version.version_number })} · {version.version_name}</span><span className="text-[#8a96a7]">{new Date(version.created_at).toLocaleString()}</span></div><div className="mt-1 text-[9px] text-[#8a96a7]">{t("creative_board_version_nodes", { count: version.items_count ?? 0 })} · {t("creative_board_version_edges", { count: version.edges_count ?? 0 })}</div></button>)}</div></div> : null}
    {selectedVersion ? <div className="absolute right-0 top-9 z-[52] w-80 rounded-lg border border-[#dfe5ed] bg-white p-3 shadow-[0_12px_30px_rgba(53,68,91,0.16)]" role="dialog" aria-modal="true"><div className="flex items-center gap-2 text-[11px] font-semibold text-[#334155]"><RotateCcw className="h-3.5 w-3.5 text-[#6254d9]" aria-hidden />{t("creative_board_version_restore_title")}</div><p className="mt-2 text-[10px] leading-relaxed text-[#64748b]">{t("creative_board_version_restore_summary", { version: selectedVersion.version_number, name: selectedVersion.version_name })}</p><div className="mt-2 rounded-md bg-[#fafbfe] px-2 py-1.5 text-[10px] text-[#64748b]">{t("creative_board_version_diff", { nodes: (selectedVersion.items_count ?? 0) - snapshot.items.length, edges: (selectedVersion.edges_count ?? 0) - snapshot.edges.length })}</div><div className="mt-3 flex justify-end gap-1.5"><button type="button" onClick={() => setSelectedVersion(null)} className="focus-ring rounded-md border border-[#dfe5ed] px-2.5 py-1.5 text-[10px] text-[#64748b]">{t("creative_board_action_cancel")}</button><button type="button" disabled={busy} onClick={() => void restoreVersion()} className="focus-ring inline-flex items-center gap-1 rounded-md bg-[#6254d9] px-2.5 py-1.5 text-[10px] font-semibold text-white disabled:opacity-50">{busy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}{t("creative_board_version_restore")}</button></div></div> : null}
  </div>;
}
