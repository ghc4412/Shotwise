/* eslint-disable jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions -- board cards expose drag, double-click navigation, and selection as a canvas interaction surface. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ExternalLink, Grid3X3, Image as ImageIcon, Link2, Loader2, Plus, Sparkles, Trash2, Video, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { API } from "@/api";

type BoardItem = { id: string; item_type: string; resource_type: string; resource_id: string; position: { x: number; y: number }; size: { width: number; height: number } };
type BoardEdge = { id: string; source_item_id: string; target_item_id: string; relation: string };
type Board = { id: string; project_id: string; name: string; viewport: { x?: number; y?: number; zoom?: number }; items: BoardItem[]; edges: BoardEdge[] };
type Media = { id: string; original_name: string; kind: string };
const ITEM_TYPES = ["document", "character", "scene", "prop", "product", "media", "episode", "shot", "skill_action", "review", "final"] as const;

function itemIcon(type: string) {
  return type === "video" ? Video : type === "skill_action" ? Sparkles : type === "document" ? Link2 : ImageIcon;
}

function parseBoard(value: Record<string, unknown>): Board {
  return value as unknown as Board;
}

export function CreativeBoardPage({ projectName }: { projectName: string }) {
  const { t } = useTranslation("dashboard");
  const [, navigate] = useLocation();
  const [board, setBoard] = useState<Board | null>(null);
  const [media, setMedia] = useState<Media[]>([]);
  const [name, setName] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [itemType, setItemType] = useState<(typeof ITEM_TYPES)[number]>("media");
  const [resourceId, setResourceId] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [boards, mediaResponse] = await Promise.all([API.listCreativeBoards(projectName), API.listMediaAssets(projectName)]);
      const next = boards.items[0] && typeof boards.items[0].id === "string" ? parseBoard(await API.getCreativeBoard(boards.items[0].id)) : parseBoard(await API.createCreativeBoard(projectName, { name: t("creative_board_default_name"), viewport: { x: 0, y: 0, zoom: 1 } }));
      setBoard(next);
      setName(next.name);
      setMedia(mediaResponse.items.filter((item) => typeof item.id === "string" && typeof item.original_name === "string").map((item) => ({ id: String(item.id), original_name: String(item.original_name), kind: typeof item.kind === "string" ? item.kind : "image" })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("creative_board_load_error"));
    } finally {
      setLoading(false);
    }
  }, [projectName, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load the project board when the page mounts
    void load();
  }, [load]);

  const names = useMemo(() => new Map(media.map((item) => [item.id, item.original_name])), [media]);
  const zoom = Math.min(1.5, Math.max(0.6, typeof board?.viewport.zoom === "number" ? board.viewport.zoom : 1));
  const refresh = async () => {
    if (board) setBoard(parseBoard(await API.getCreativeBoard(board.id)));
  };
  const addCard = async () => {
    if (!board) return;
    const id = resourceId.trim() || (itemType === "media" ? media.find((item) => !board.items.some((candidate) => candidate.resource_id === item.id))?.id : "");
    if (!id) return;
    setSaving(true);
    try {
      await API.addCreativeBoardItem(board.id, { item_type: itemType, resource_type: itemType === "media" ? "media_asset" : itemType, resource_id: id, position: { x: 40 + board.items.length * 28, y: 40 + board.items.length * 28 }, size: { width: 240, height: 170 } });
      setResourceId("");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("creative_board_save_error"));
    } finally {
      setSaving(false);
    }
  };
  const saveName = async () => {
    if (!board || !name.trim() || name.trim() === board.name) return;
    try {
      const next = parseBoard(await API.updateCreativeBoard(board.id, { name: name.trim() }));
      setBoard(next);
      setName(next.name);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("creative_board_save_error"));
    }
  };
  const removeItem = async (item: BoardItem) => {
    if (!board) return;
    setSaving(true);
    try {
      await API.deleteCreativeBoardItem(board.id, item.id);
      setSelectedIds((current) => current.filter((id) => id !== item.id));
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("creative_board_save_error"));
    } finally {
      setSaving(false);
    }
  };
  const moveItem = async (item: BoardItem, x: number, y: number) => {
    if (!board) return;
    try {
      await API.updateCreativeBoardItem(board.id, item.id, { item_type: item.item_type, resource_type: item.resource_type, resource_id: item.resource_id, position: { x: Math.max(0, Math.round(x)), y: Math.max(0, Math.round(y)) }, size: item.size });
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("creative_board_save_error"));
    }
  };
  const relate = async () => {
    if (!board || selectedIds.length !== 2) return;
    try {
      await API.addCreativeBoardEdge(board.id, { source_item_id: selectedIds[0], target_item_id: selectedIds[1], relation: "reference" });
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("creative_board_edge_error"));
    }
  };
  const updateZoom = async (delta: number) => {
    if (!board) return;
    try {
      setBoard(parseBoard(await API.updateCreativeBoard(board.id, { viewport: { ...board.viewport, zoom: Math.min(1.5, Math.max(0.6, zoom + delta)) } })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("creative_board_save_error"));
    }
  };
  const removeEdge = async (edgeId: string) => {
    if (!board) return;
    try {
      await API.deleteCreativeBoardEdge(board.id, edgeId);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("creative_board_edge_error"));
    }
  };

  return <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[var(--color-shell)] text-[var(--color-text)]"><header className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--color-hairline-soft)] bg-[var(--panel-card-bg)] px-5 py-3"><div className="flex min-w-0 items-center gap-3"><button type="button" onClick={() => navigate("/skills")} className="focus-ring rounded-md p-1.5" aria-label={t("creative_board_back_to_skills")}><ArrowLeft className="h-4 w-4" aria-hidden /></button><Grid3X3 className="h-4 w-4 text-[var(--color-accent-2)]" aria-hidden /><div className="min-w-0"><div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-accent-2)]">{t("creative_board_eyebrow")}</div><input value={name} onChange={(event) => setName(event.target.value)} onBlur={() => void saveName()} placeholder={t("creative_board_default_name")} className="w-56 bg-transparent text-[16px] font-semibold outline-none" /></div></div><div className="flex flex-wrap justify-end gap-2"><select value={itemType} onChange={(event) => setItemType(event.target.value as (typeof ITEM_TYPES)[number])} className="rounded border border-[var(--color-hairline)] bg-transparent px-2 py-1.5 text-[11px]">{ITEM_TYPES.map((type) => <option key={type} value={type}>{t("creative_board_type_" + type, { defaultValue: type })}</option>)}</select>{itemType === "media" ? <select value={resourceId} onChange={(event) => setResourceId(event.target.value)} className="w-44 rounded border border-[var(--color-hairline)] bg-transparent px-2 py-1.5 text-[11px]"><option value="">{t("creative_board_resource_id")}</option>{media.map((item) => <option key={item.id} value={item.id}>{item.original_name}</option>)}</select> : <input value={resourceId} onChange={(event) => setResourceId(event.target.value)} placeholder={t("creative_board_resource_id")} className="w-36 rounded border border-[var(--color-hairline)] bg-transparent px-2 py-1.5 text-[11px]" />}<button type="button" disabled={saving} onClick={() => void addCard()} className="focus-ring inline-flex items-center gap-1.5 rounded-md border border-[var(--color-hairline)] px-3 py-1.5 text-[11px] disabled:opacity-50"><Plus className="h-3 w-3" aria-hidden />{t("creative_board_add_card")}</button><button type="button" onClick={() => navigate("/media")} className="focus-ring inline-flex items-center gap-1.5 rounded-md border border-[var(--color-hairline)] px-3 py-1.5 text-[11px]"><ExternalLink className="h-3 w-3" aria-hidden />{t("creative_board_open_media")}</button><button type="button" onClick={() => navigate("/flow")} className="focus-ring inline-flex items-center gap-1.5 rounded-md border border-[var(--color-hairline)] px-3 py-1.5 text-[11px]"><ExternalLink className="h-3 w-3" aria-hidden />{t("creative_board_open_advanced")}</button></div></header><div className="flex items-center justify-between border-b border-[var(--color-hairline-soft)] bg-[var(--panel-card-bg)] px-5 py-3"><div><p className="text-[12px] text-[var(--color-text-3)]">{t("creative_board_subtitle")}</p><p className="mt-1 text-[10px] text-[var(--color-text-4)]">{t("creative_board_semantic_hint")}</p></div><div className="flex items-center gap-2"><button type="button" onClick={() => void updateZoom(-0.1)} className="rounded border px-2 py-1 text-[11px]">−</button><span className="w-10 text-center text-[10px]">{Math.round(zoom * 100)}%</span><button type="button" onClick={() => void updateZoom(0.1)} className="rounded border px-2 py-1 text-[11px]">+</button>{selectedIds.length === 2 ? <button type="button" onClick={() => void relate()} className="rounded bg-[var(--color-accent)] px-2 py-1 text-[10px] text-white">{t("creative_board_relate")}</button> : null}</div></div>{error ? <div className="flex items-center justify-between border-b border-[var(--color-danger)]/30 px-5 py-2 text-[12px]"><span>{error}</span><button type="button" onClick={() => void load()}>{t("creative_board_retry")}</button></div> : null}<main className="relative min-h-0 flex-1 overflow-auto p-6" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); const item = board?.items.find((candidate) => candidate.id === event.dataTransfer.getData("text/board-item")); const rect = event.currentTarget.getBoundingClientRect(); if (item) void moveItem(item, event.clientX - rect.left, event.clientY - rect.top); }} style={{ backgroundImage: "linear-gradient(var(--color-hairline-soft) 1px, transparent 1px), linear-gradient(90deg, var(--color-hairline-soft) 1px, transparent 1px)", backgroundSize: "28px 28px" }}>{loading ? <div className="flex h-full items-center justify-center text-[12px] text-[var(--color-text-3)]"><Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />{t("creative_board_loading")}</div> : board && board.items.length === 0 ? <div className="flex h-full min-h-[360px] items-center justify-center text-center text-[12px] text-[var(--color-text-3)]"><div><p>{t("creative_board_empty")}</p><button type="button" disabled={media.length === 0} onClick={() => void addCard()} className="mt-3 rounded bg-[var(--color-accent)] px-3 py-2 text-[11px] text-white disabled:opacity-50">{t("creative_board_add_first_media")}</button></div></div> : board ? <div className="relative min-h-[760px] min-w-[1100px]" style={{ transform: "translate(" + (board.viewport.x || 0) + "px, " + (board.viewport.y || 0) + "px) scale(" + zoom + ")", transformOrigin: "top left" }}>{board.items.map((item) => { const Icon = itemIcon(item.item_type); const selected = selectedIds.includes(item.id); return <article key={item.id} draggable onDragStart={(event) => event.dataTransfer.setData("text/board-item", item.id)} onClick={() => setSelectedIds((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : current.length >= 2 ? [current[1], item.id] : current.concat(item.id))} onDoubleClick={() => item.resource_type === "media_asset" ? navigate("/media?asset=" + encodeURIComponent(item.resource_id)) : navigate("/timeline")} className={"absolute cursor-grab rounded-lg border bg-[var(--panel-card-bg)] p-3 shadow-lg " + (selected ? "border-[var(--color-accent)] ring-2 ring-[var(--color-accent)]/20" : "border-[var(--color-hairline)]")} style={{ left: item.position.x, top: item.position.y, width: item.size.width, minHeight: item.size.height }}><div className="flex items-start gap-2"><div className="rounded bg-[var(--color-shell-field)] p-1.5"><Icon className="h-3.5 w-3.5" aria-hidden /></div><div className="min-w-0 flex-1"><div className="text-[9px] uppercase text-[var(--color-text-4)]">{t("creative_board_type_" + item.item_type, { defaultValue: item.item_type })}</div><h2 className="mt-1 truncate text-[12px] font-semibold">{names.get(item.resource_id) || item.resource_id}</h2></div><button type="button" onClick={(event) => { event.stopPropagation(); void removeItem(item); }} aria-label={t("creative_board_delete_item")}><Trash2 className="h-3.5 w-3.5 text-[var(--color-text-4)]" aria-hidden /></button></div><div className="mt-3 border-t border-[var(--color-hairline-soft)] pt-2 text-[9px] text-[var(--color-text-4)]">{item.resource_type} · {item.resource_id}</div></article>; })}</div> : null}</main>{board && board.edges.length ? <aside className="border-t border-[var(--color-hairline-soft)] bg-[var(--panel-card-bg)] px-5 py-2"><div className="flex flex-wrap gap-2">{board.edges.map((edge) => <span key={edge.id} className="inline-flex items-center gap-1 rounded-full border border-[var(--color-hairline)] px-2 py-1 text-[10px]">{edge.relation}<button type="button" onClick={() => void removeEdge(edge.id)} aria-label={t("creative_board_delete_edge")}><X className="h-3 w-3" aria-hidden /></button></span>)}</div></aside> : null}</div>;
}
