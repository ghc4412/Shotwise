import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { GitBranch, Loader2, Lock, Maximize2, Minimize2, Network, PanelRightClose, PanelRightOpen, Plus, RefreshCw, Save, Search, Trash2, Unlock, UserRound, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { GlassModal } from "@/components/ui/GlassModal";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";
import type { Character, CharacterRelationEdge, CharacterRelationType, CharacterRelationsData } from "@/types";
import {
  connectionHandles,
  layoutCharacterRelations,
  type CharacterRelationsLayout,
} from "./character-relations-layout";

interface Props {
  projectName: string;
  characters: Record<string, Character>;
  readOnly?: boolean;
  onClose: () => void;
}

type RelationNodeData = { name: string };

const RELATION_TYPES: CharacterRelationType[] = [
  "family", "romance", "marriage", "friend", "ally", "enemy", "mentor", "subordinate", "rival", "interest", "custom",
];

function uid() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `relation-${Date.now()}-${Math.random()}`;
}

function characterInitial(name: string): string {
  return Array.from(name.trim())[0] ?? "";
}

function RelationNode({ data }: NodeProps<Node<RelationNodeData>>) {
  return (
    <div className="relative min-w-[150px] cursor-pointer rounded-lg border px-3 py-2 shadow-lg" style={{ background: "var(--panel-card-bg)", borderColor: "var(--color-accent-soft)" }}>
      <Handle id="target-left" type="target" position={Position.Left} className="!h-2 !w-2" />
      <Handle id="target-right" type="target" position={Position.Right} className="!h-2 !w-2" />
      <Handle id="target-top" type="target" position={Position.Top} className="!h-2 !w-2" />
      <Handle id="target-bottom" type="target" position={Position.Bottom} className="!h-2 !w-2" />
      <div className="flex items-center gap-2">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold" style={{ background: "var(--color-accent-dim)", color: "var(--color-text-2)" }}>
          {characterInitial(data.name) || <GitBranch className="h-4 w-4" />}
        </div>
        <span className="max-w-[92px] truncate text-xs font-medium" style={{ color: "var(--color-text)" }}>{data.name}</span>
      </div>
      <Handle id="source-left" type="source" position={Position.Left} className="!h-2 !w-2" />
      <Handle id="source-right" type="source" position={Position.Right} className="!h-2 !w-2" />
      <Handle id="source-top" type="source" position={Position.Top} className="!h-2 !w-2" />
      <Handle id="source-bottom" type="source" position={Position.Bottom} className="!h-2 !w-2" />
    </div>
  );
}

interface CharacterDetailsPanelProps {
  name: string;
  character: Character;
  relations: CharacterRelationEdge[];
  onSelectRelation: (id: string) => void;
}

function CharacterDetailsPanel({ name, character, relations, onSelectRelation }: CharacterDetailsPanelProps) {
  const { t } = useTranslation("dashboard");
  return (
    <div>
      <h3 className="mb-3 text-xs font-semibold" style={{ color: "var(--color-text)" }}>{t("character_relations_character_details")}</h3>
      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-md text-xl font-semibold" style={{ background: "var(--color-accent-dim)", color: "var(--color-text-2)" }}>
          {characterInitial(name) || <UserRound className="h-6 w-6" />}
        </div>
        <div className="min-w-0"><div className="truncate text-sm font-semibold" style={{ color: "var(--color-text)" }}>{name}</div><div className="mt-0.5 text-[11px]" style={{ color: "var(--color-text-3)" }}>{t("character_relations_relation_count", { count: relations.length })}</div></div>
      </div>
      <div className="space-y-3 text-xs">
        <div><div className="mb-1 font-medium" style={{ color: "var(--color-text-2)" }}>{t("description")}</div><div className="whitespace-pre-wrap leading-5" style={{ color: "var(--color-text-3)" }}>{character.description || t("character_relations_no_details")}</div></div>
        {character.voice_style && <div><div className="mb-1 font-medium" style={{ color: "var(--color-text-2)" }}>{t("voice_style")}</div><div className="whitespace-pre-wrap leading-5" style={{ color: "var(--color-text-3)" }}>{character.voice_style}</div></div>}
        <div><div className="mb-1 font-medium" style={{ color: "var(--color-text-2)" }}>{t("character_relations_related")}</div>{relations.length > 0 ? <div className="grid gap-1.5">{relations.map((relation) => { const other = relation.source === name ? relation.target : relation.source; return <button key={relation.id} type="button" onClick={() => onSelectRelation(relation.id)} className="flex items-center justify-between gap-2 rounded-md border px-2 py-1.5 text-left" style={{ borderColor: "var(--color-hairline-soft)", color: "var(--color-text-2)" }}><span className="truncate">{other}</span><span className="shrink-0 text-[11px]" style={{ color: "var(--color-text-3)" }}>{relation.label || t(`character_relation_type_${relation.type}`, { defaultValue: relation.type })}</span></button>; })}</div> : <div style={{ color: "var(--color-text-3)" }}>{t("character_relations_no_related")}</div>}</div>
      </div>
    </div>
  );
}

function CharacterRelationsCanvas(props: Props) {
  const { t } = useTranslation("dashboard");
  const { projectName, characters, readOnly = false, onClose } = props;
  const { fitView } = useReactFlow();
  const [graph, setGraph] = useState<CharacterRelationsData | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<RelationNodeData>>([]);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<CharacterRelationType | "all">("all");
  const [hideIsolated, setHideIsolated] = useState(false);
  const [layoutMode, setLayoutMode] = useState<CharacterRelationsLayout>("hierarchy");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedCharacterName, setSelectedCharacterName] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [layoutLocked, setLayoutLocked] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hydratedPositions = useRef(false);

  const load = useCallback(async () => {
    hydratedPositions.current = false;
    setNodes([]);
    setLoading(true);
    try { setGraph(await API.getCharacterRelations(projectName)); setError(null); }
    catch (err) { setError(errMsg(err)); }
    finally { setLoading(false); }
  }, [projectName, setNodes]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- modal hydration follows the server graph
    void load();
  }, [load]);

  const relationTypes = useMemo(() => RELATION_TYPES.map((type) => ({ type, label: t(`character_relation_type_${type}`, { defaultValue: type }) })), [t]);
  const selected = graph?.edges.find((edge) => edge.id === selectedId) ?? null;
  const selectedCharacter = selectedCharacterName ? characters[selectedCharacterName] : null;
  const selectedCharacterRelations = useMemo(
    () => graph?.edges.filter((edge) => edge.source === selectedCharacterName || edge.target === selectedCharacterName) ?? [],
    [graph, selectedCharacterName],
  );
  const visibleNames = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const matching = new Set(Object.keys(characters).filter((name) => !normalizedQuery || name.toLocaleLowerCase().includes(normalizedQuery)));
    if (hideIsolated && graph) {
      const connected = new Set(graph.edges.flatMap((edge) => [edge.source, edge.target]));
      for (const name of Object.keys(characters)) if (!connected.has(name)) matching.delete(name);
    }
    return matching;
  }, [characters, graph, hideIsolated, query]);
  const visibleEdges = useMemo(() => (graph?.edges ?? []).filter((edge) => visibleNames.has(edge.source) && visibleNames.has(edge.target) && (typeFilter === "all" || edge.type === typeFilter)), [graph, typeFilter, visibleNames]);
  const nodeDefinitions = useMemo<Node<RelationNodeData>[]>(() => {
    const names = [...visibleNames].sort();
    const positions = layoutCharacterRelations(names, visibleEdges, layoutMode);
    const savedPositions = graph?.node_positions ?? {};
    return names.map((name) => {
      return {
        id: name,
        type: "character",
        position: savedPositions[name] ?? positions[name] ?? { x: 0, y: 0 },
        data: { name },
      };
    });
  }, [graph, layoutMode, visibleEdges, visibleNames]);

  useEffect(() => {
    if (!graph) return;
    setNodes((currentNodes) => {
      const currentPositions = new Map(currentNodes.map((node) => [node.id, node.position]));
      const useSavedPositions = !hydratedPositions.current;
      hydratedPositions.current = true;
      return nodeDefinitions.map((node) => ({
        ...node,
        position: useSavedPositions
          ? graph.node_positions[node.id] ?? node.position
          : currentPositions.get(node.id) ?? node.position,
      }));
    });
  }, [graph, nodeDefinitions, setNodes]);

  const nodePositions = useMemo(
    () => new Map(nodes.map((node) => [node.id, node.position])),
    [nodes],
  );
  const edges = useMemo<Edge[]>(() => visibleEdges.map((relation) => ({
    ...connectionHandles(
      nodePositions.get(relation.source) ?? { x: 0, y: 0 },
      nodePositions.get(relation.target) ?? { x: 0, y: 0 },
    ),
    id: relation.id,
    source: relation.source,
    target: relation.target,
    label: relation.label || t(`character_relation_type_${relation.type}`, { defaultValue: relation.type }),
    animated: relation.origin === "ai",
    type: layoutMode === "hierarchy" ? "smoothstep" : "default",
    markerEnd: relation.directed ? { type: MarkerType.ArrowClosed } : undefined,
    zIndex: selectedId === relation.id ? 2 : 0,
    style: { stroke: relation.origin === "manual" ? "var(--color-accent-2)" : "var(--color-text-3)", strokeWidth: selectedId === relation.id ? 3 : 1.5 },
    labelStyle: { fill: "var(--color-text)", fontSize: 11 },
    // SVG fill cannot consume the panel gradient token; use the theme's solid surface color
    // so edge labels stay readable in both light and dark modes.
    labelBgStyle: { fill: "var(--color-surface-2)", fillOpacity: 0.96 },
    labelBgPadding: [4, 2],
    labelBgBorderRadius: 3,
  })), [layoutMode, nodePositions, selectedId, t, visibleEdges]);

  const arrange = () => {
    const positions = layoutCharacterRelations([...visibleNames], visibleEdges, layoutMode);
    setNodes((currentNodes) => currentNodes.map((node) => ({
      ...node,
      position: positions[node.id] ?? node.position,
    })));
    requestAnimationFrame(() => void fitView({ padding: 0.15, duration: 350 }));
  };

  const updateSelected = (patch: Partial<CharacterRelationEdge>) => {
    if (!selectedId || !graph) return;
    setGraph({ ...graph, edges: graph.edges.map((edge) => edge.id === selectedId ? { ...edge, ...patch } : edge) });
  };

  const addRelation = (source: string, target: string) => {
    if (!graph || !source || !target || source === target) return;
    const relation: CharacterRelationEdge = { id: uid(), source, target, type: "custom", label: "", directed: false, description: "", origin: "manual", manual_override: true, confidence: null, evidence: [] };
    setGraph({ ...graph, edges: [...graph.edges, relation] });
    setSelectedId(relation.id);
    setSelectedCharacterName(null);
  };

  const save = async () => {
    if (!graph || readOnly) return;
    setSaving(true);
    const nodePositions = {
      ...(graph.node_positions ?? {}),
      ...Object.fromEntries(nodes.map((node) => [node.id, node.position])),
    };
    try {
      const saved = await API.saveCharacterRelations(projectName, graph.revision, graph.edges, nodePositions);
      setGraph(saved);
      useAppStore.getState().pushToast(t("character_relations_saved"), "success");
    }
    catch (err) { const message = errMsg(err); setError(message); useAppStore.getState().pushToast(message, "error"); }
    finally { setSaving(false); }
  };

  const analyze = async () => {
    setAnalyzing(true);
    setError(null);
    try { setGraph(await API.analyzeCharacterRelations(projectName)); setError(null); useAppStore.getState().pushToast(t("character_relations_analysis_complete"), "success"); }
    catch (err) { const message = errMsg(err); setError(message); useAppStore.getState().pushToast(message, "error"); }
    finally { setAnalyzing(false); }
  };

  const sidebarToggle = (
    <button
      type="button"
      onClick={() => setSidebarOpen((open) => !open)}
      className="grid h-7 w-7 place-items-center rounded-md border shadow-sm focus-ring"
      aria-controls="character-relations-sidebar"
      aria-expanded={sidebarOpen}
      aria-label={sidebarOpen ? t("sidebar_collapse") : t("sidebar_expand")}
      title={sidebarOpen ? t("sidebar_collapse") : t("sidebar_expand")}
      style={{ background: "var(--color-shell-btn)", borderColor: "var(--color-hairline)", color: "var(--color-text-2)" }}
    >
      {sidebarOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
    </button>
  );

  return (
    <GlassModal
      open
      onClose={onClose}
      ariaLabel={t("character_relations")}
      widthClassName={fullscreen ? "w-auto" : "w-[min(96vw,1280px)]"}
      panelClassName={fullscreen ? "fixed inset-0 h-full" : "h-[min(90vh,860px)]"}
      panelStyle={fullscreen ? { borderRadius: 0, inset: 0, maxWidth: "none", position: "fixed" } : undefined}
    >
      <div className="flex h-full min-h-0 flex-col" style={{ background: "var(--panel-card-bg)" }}>
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3" style={{ borderColor: "var(--color-hairline-soft)" }}>
          <h2 className="mr-2 text-sm font-semibold" style={{ color: "var(--color-text)" }}>{t("character_relations")}</h2>
          <div className="relative min-w-[170px] flex-1"><Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("character_relations_search")} className="w-full rounded-md border py-1 pl-7 pr-2 text-xs" style={{ background: "var(--color-shell-field)", borderColor: "var(--color-hairline)", color: "var(--color-text)" }} /></div>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as CharacterRelationType | "all")} className="rounded-md border px-2 py-1 text-xs" style={{ background: "var(--color-shell-field)", borderColor: "var(--color-hairline)", color: "var(--color-text)" }}><option value="all">{t("character_relations_all_types")}</option>{relationTypes.map(({ type, label }) => <option key={type} value={type}>{label}</option>)}</select>
          <label className="flex items-center gap-1 text-xs" style={{ color: "var(--color-text-2)" }}><input type="checkbox" checked={hideIsolated} onChange={(e) => setHideIsolated(e.target.checked)} />{t("character_relations_hide_isolated")}</label>
          <select value={layoutMode} onChange={(event) => setLayoutMode(event.target.value as CharacterRelationsLayout)} aria-label={t("character_relations_layout_mode")} className="rounded-md border px-2 py-1 text-xs" style={{ background: "var(--color-shell-field)", borderColor: "var(--color-hairline)", color: "var(--color-text)" }}><option value="hierarchy">{t("character_relations_layout_hierarchy")}</option><option value="radial">{t("character_relations_layout_radial")}</option></select>
          <button type="button" onClick={arrange} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs" style={{ color: "var(--color-text-2)", borderColor: "var(--color-hairline)" }}><Network className="h-3.5 w-3.5" />{t("character_relations_arrange")}</button>
          {!readOnly && <button type="button" onClick={() => void analyze()} disabled={analyzing || saving} className="inline-flex min-w-fit items-center gap-1 rounded-md border px-2 py-1 text-xs disabled:cursor-wait disabled:opacity-60" style={{ color: "var(--color-text-2)", borderColor: "var(--color-hairline)" }}>{analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}{analyzing ? t("character_relations_analyzing") : graph?.edges.length ? t("reanalyze_character_relations") : t("analyze_character_relations")}</button>}
          {!readOnly && <button type="button" onClick={() => void save()} disabled={analyzing || saving || !graph} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium disabled:opacity-60" style={{ background: "var(--color-accent)", color: "oklch(0.14 0 0)" }}>{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}{t("character_relations_save")}</button>}
          <button
            type="button"
            onClick={() => setFullscreen((value) => !value)}
            className="rounded-md p-1 focus-ring"
            aria-pressed={fullscreen}
            aria-label={fullscreen ? t("character_relations_exit_fullscreen") : t("character_relations_fullscreen")}
            title={fullscreen ? t("character_relations_exit_fullscreen") : t("character_relations_fullscreen")}
          >
            {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
          <button type="button" onClick={onClose} className="ml-auto rounded-md p-1" title={t("common:close")}><X className="h-4 w-4" /></button>
        </div>
        {error && <div className="border-b px-4 py-2 text-xs" style={{ color: "var(--color-danger, #f87171)", borderColor: "var(--color-hairline-soft)" }}>{error}</div>}
        <div className="flex min-h-0 flex-1">
          <div className="character-relations-flow relative min-w-0 flex-1">
            {loading ? <div className="flex h-full items-center justify-center gap-2 text-sm" style={{ color: "var(--color-text-2)" }}><Loader2 className="h-4 w-4 animate-spin" />{t("character_relations_loading")}</div> : (
              <>
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={{ character: RelationNode }}
                  fitView
                  minZoom={0.08}
                  onNodesChange={onNodesChange}
                  nodesDraggable={!readOnly && !layoutLocked}
                  onNodeClick={(_, node) => { setSelectedCharacterName(node.id); setSelectedId(null); }}
                  onEdgeClick={(_, edge) => { setSelectedId(edge.id); setSelectedCharacterName(null); }}
                  onPaneClick={() => { setSelectedId(null); setSelectedCharacterName(null); }}
                  onConnect={(connection: Connection) => { if (!readOnly && !layoutLocked && connection.source && connection.target) addRelation(connection.source, connection.target); }}
                  nodesConnectable={!readOnly && !layoutLocked}
                  connectionLineStyle={{ stroke: "var(--color-text)" }}
                >
                  <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
                  <Controls showFitView={false} showInteractive={false}>
                    <ControlButton
                      type="button"
                      onClick={() => setLayoutLocked((value) => !value)}
                      aria-pressed={layoutLocked}
                      aria-label={layoutLocked ? t("character_relations_unlock_layout") : t("character_relations_lock_layout")}
                      title={layoutLocked ? t("character_relations_unlock_layout") : t("character_relations_lock_layout")}
                    >
                      {layoutLocked ? <Lock className="h-4 w-4" /> : <Unlock className="h-4 w-4" />}
                    </ControlButton>
                  </Controls>
                  <MiniMap
                    pannable
                    bgColor="#ffffff"
                    maskColor="#9ca3af"
                    maskStrokeColor="#3f3f46"
                    maskStrokeWidth={2}
                    nodeColor="#6b7280"
                    nodeStrokeColor="#4b5563"
                    nodeStrokeWidth={1}
                    className="character-relations-minimap"
                  />
                </ReactFlow>
                {analyzing && <div className="pointer-events-none absolute left-1/2 top-4 flex -translate-x-1/2 items-center gap-2 rounded-md border px-3 py-2 text-xs shadow-lg" style={{ background: "var(--panel-card-bg)", borderColor: "var(--color-hairline)", color: "var(--color-text-2)" }}><Loader2 className="h-3.5 w-3.5 animate-spin" />{t("character_relations_analyzing")}</div>}
                {!analyzing && graph?.edges.length === 0 && <div className="absolute left-1/2 top-4 flex max-w-[360px] -translate-x-1/2 items-center gap-3 rounded-md border px-3 py-2 shadow-lg" style={{ background: "var(--panel-card-bg)", borderColor: "var(--color-hairline)" }}><div><div className="text-xs font-medium" style={{ color: "var(--color-text)" }}>{t("character_relations_empty")}</div><div className="mt-0.5 text-[11px]" style={{ color: "var(--color-text-3)" }}>{t("character_relations_empty_hint")}</div></div>{!readOnly && <button type="button" onClick={() => void analyze()} className="shrink-0 rounded-md px-2 py-1 text-xs font-medium" style={{ background: "var(--color-accent)", color: "oklch(0.14 0 0)" }}>{t("analyze_character_relations")}</button>}</div>}
              </>
            )}
          </div>
          <div className="relative h-full shrink-0 transition-[width] duration-200 ease-out" style={{ width: sidebarOpen ? 300 : 0 }}>
            <aside
              id="character-relations-sidebar"
              className={`absolute inset-y-0 right-0 w-[300px] overflow-y-auto border-l p-4 transition-opacity duration-150 ${sidebarOpen ? "opacity-100" : "pointer-events-none invisible opacity-0"}`}
              style={{ borderColor: "var(--color-hairline-soft)" }}
            >
              {!readOnly && <div className="mb-4"><div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold" style={{ color: "var(--color-text)" }}>{t("character_relations_add")}</h3><div className="flex items-center gap-1.5"><Plus className="h-3.5 w-3.5" />{sidebarToggle}</div></div><div className="grid gap-2"><select id="relation-source" className="rounded-md border px-2 py-1.5 text-xs" style={{ background: "var(--color-shell-field)", borderColor: "var(--color-hairline)", color: "var(--color-text)" }} defaultValue=""><option value="">{t("character_relations_source")}</option>{Object.keys(characters).map((name) => <option key={name}>{name}</option>)}</select><select id="relation-target" className="rounded-md border px-2 py-1.5 text-xs" style={{ background: "var(--color-shell-field)", borderColor: "var(--color-hairline)", color: "var(--color-text)" }} defaultValue=""><option value="">{t("character_relations_target")}</option>{Object.keys(characters).map((name) => <option key={name}>{name}</option>)}</select><button type="button" onClick={() => { const source = (document.getElementById("relation-source") as HTMLSelectElement)?.value; const target = (document.getElementById("relation-target") as HTMLSelectElement)?.value; addRelation(source, target); }} className="rounded-md border px-2 py-1 text-xs" style={{ borderColor: "var(--color-hairline)", color: "var(--color-text-2)" }}>{t("character_relations_add")}</button></div></div>}
              {readOnly && <div className="mb-4 flex justify-end">{sidebarToggle}</div>}
              {selectedCharacterName && selectedCharacter ? (
                <CharacterDetailsPanel
                  name={selectedCharacterName}
                  character={selectedCharacter}
                  relations={selectedCharacterRelations}
                  onSelectRelation={(id) => { setSelectedId(id); setSelectedCharacterName(null); }}
                />
              ) : selected ? (
                <div>
                  <div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold" style={{ color: "var(--color-text)" }}>{t("character_relations_details")}</h3>{!readOnly && <button type="button" onClick={() => { setGraph((value) => value ? { ...value, edges: value.edges.filter((edge) => edge.id !== selected.id) } : value); setSelectedId(null); }} title={t("character_relations_delete")}><Trash2 className="h-3.5 w-3.5" /></button>}</div>
                  <div className="grid gap-2 text-xs"><label style={{ color: "var(--color-text-2)" }}>{t("character_relations_type")}<select disabled={readOnly} value={selected.type} onChange={(e) => updateSelected({ type: e.target.value as CharacterRelationType })} className="mt-1 w-full rounded-md border px-2 py-1.5" style={{ background: "var(--color-shell-field)", borderColor: "var(--color-hairline)", color: "var(--color-text)" }}>{relationTypes.map(({ type, label }) => <option key={type} value={type}>{label}</option>)}</select></label><label style={{ color: "var(--color-text-2)" }}>{t("character_relations_label")}<input disabled={readOnly} value={selected.label} onChange={(e) => updateSelected({ label: e.target.value })} className="mt-1 w-full rounded-md border px-2 py-1.5" style={{ background: "var(--color-shell-field)", borderColor: "var(--color-hairline)", color: "var(--color-text)" }} /></label><label style={{ color: "var(--color-text-2)" }}>{t("character_relations_description")}<textarea disabled={readOnly} value={selected.description} onChange={(e) => updateSelected({ description: e.target.value })} rows={4} className="mt-1 w-full rounded-md border px-2 py-1.5" style={{ background: "var(--color-shell-field)", borderColor: "var(--color-hairline)", color: "var(--color-text)" }} /></label><label className="flex items-center gap-2" style={{ color: "var(--color-text-2)" }}><input disabled={readOnly} type="checkbox" checked={selected.directed} onChange={(e) => updateSelected({ directed: e.target.checked })} />{t("character_relations_directed")}</label><div style={{ color: "var(--color-text-3)" }}>{selected.origin === "manual" ? t("character_relations_manual") : t("character_relations_ai")}{selected.confidence != null ? ` · ${t("character_relations_confidence")}: ${Math.round(selected.confidence * 100)}%` : ""}</div>{selected.evidence.length > 0 && <div style={{ color: "var(--color-text-3)" }}>{t("character_relations_evidence")}: {selected.evidence.map((item) => item.excerpt).join("; ")}</div>}</div>
                </div>
              ) : <div className="text-xs" style={{ color: "var(--color-text-3)" }}>{t("character_relations_select_hint")}</div>}
            </aside>
            {!sidebarOpen && <div className="absolute -left-9 top-3 z-10">{sidebarToggle}</div>}
          </div>
        </div>
      </div>
    </GlassModal>
  );
}

export function CharacterRelationsModal(props: Props) {
  return <ReactFlowProvider><CharacterRelationsCanvas {...props} /></ReactFlowProvider>;
}
