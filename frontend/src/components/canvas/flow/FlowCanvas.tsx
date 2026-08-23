import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type EdgeChange,
  type FinalConnectionState,
  type NodeProps,
  type OnConnectStartParams,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Download, FileUp, FolderPlus, Play, Redo2, Save, Search, Star, Undo2, Workflow as WorkflowIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import type { WorkflowEdgeInput, WorkflowNodeInput, WorkflowNodeRun, WorkflowTemplate } from "@/types";
import { GroupNode, type GroupNodeData, WorkflowNodeCard } from "./WorkflowNodeCard";
import { NodeConfigPanel } from "./NodeConfigPanel";
import {
  NODE_CATEGORY_LABEL_KEYS,
  NODE_TYPE_DEFS,
  nextNodeKey,
  nodeTypeDef,
  nodeTypeLabelKey,
} from "./node-registry";
import {
  type GroupMeta,
  type WorkflowNodeData,
  fromReactFlow,
  parseWorkflow,
  serializeWorkflow,
  toReactFlow,
  topologicalOrder,
} from "./workflow-utils";

interface FlowCanvasProps {
  initialNodes: WorkflowNodeInput[];
  initialEdges: WorkflowEdgeInput[];
  initialGroups: GroupMeta[];
  runStatus: Record<string, WorkflowNodeRun> | null;
  running: boolean;
  defaultName: string;
  onSave: (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => Promise<boolean>;
  onSaveReady?: (save: (() => Promise<boolean>) | null) => void;
  onGraphChange?: (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => void;
  onImportWorkflow: (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => Promise<void>;
  onRun: (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => Promise<void>;
  onViewNodeLogs?: (nodeKey: string) => void;
  onRetryFromNode?: (nodeKey: string) => void;
  onPreviewOutputs?: (nodeKey: string) => void;
  canRun?: boolean;
  runDisabledReason?: string;
}

interface ContextMenuState {
  x: number;
  y: number;
  nodeId: string | null;
}

interface CanvasSnapshot {
  nodes: Node[];
  edges: Edge[];
  groups: GroupMeta[];
}

function FlowCanvasInner({
  initialNodes,
  initialEdges,
  initialGroups,
  runStatus,
  running,
  defaultName,
  onSave,
  onSaveReady,
  onGraphChange,
  onImportWorkflow,
  onRun,
  onViewNodeLogs,
  onRetryFromNode,
  onPreviewOutputs,
  canRun = true,
  runDisabledReason,
}: FlowCanvasProps) {
  const { t } = useTranslation("dashboard");
  const { screenToFlowPosition } = useReactFlow();
  const projectData = useProjectsStore((s) => s.currentProjectData);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [groups, setGroups] = useState<GroupMeta[]>([]);
  const [graphHydrated, setGraphHydrated] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const [saving, setSaving] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [favoriteNodes, setFavoriteNodes] = useState<string[]>(() => {
    try {
      return JSON.parse(window.localStorage.getItem("shotwise-flow-favorites") ?? "[]") as string[];
    } catch {
      return [];
    }
  });
  const [customTemplates, setCustomTemplates] = useState<WorkflowTemplate[]>(() => {
    try {
      return JSON.parse(window.localStorage.getItem("shotwise-flow-custom-templates") ?? "[]") as WorkflowTemplate[];
    } catch {
      return [];
    }
  });
  const [officialTemplates, setOfficialTemplates] = useState<WorkflowTemplate[]>([]);
  const [templateNotice, setTemplateNotice] = useState<string | null>(null);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  /** Project assets (characters / scenes / props with an image) usable as reference nodes. */
  const projectAssets = useMemo(() => {
    const items: { name: string; path: string; kind: "character" | "scene" | "prop" }[] = [];
    for (const [name, char] of Object.entries(projectData?.characters ?? {})) {
      if (char.reference_image) items.push({ name, path: char.reference_image, kind: "character" });
    }
    for (const [name, scene] of Object.entries(projectData?.scenes ?? {})) {
      if (scene.scene_sheet) items.push({ name, path: scene.scene_sheet, kind: "scene" });
    }
    for (const [name, prop] of Object.entries(projectData?.props ?? {})) {
      if (prop.prop_sheet) items.push({ name, path: prop.prop_sheet, kind: "prop" });
    }
    return items;
  }, [projectData]);
  const fileRef = useRef<HTMLInputElement>(null);
  const groupSeq = useRef(0);
  const historyRef = useRef<{ past: CanvasSnapshot[]; future: CanvasSnapshot[] }>({ past: [], future: [] });
  const dragStartRef = useRef<{ nodeId: string; handleId: string | null; handleType: "source" | "target" | null } | null>(null);
  const pendingConnectionRef = useRef<{ source: string | null; sourceHandle: string | null } | null>(null);

  /** Record the current canvas as an undo point before a mutating operation. */
  const commit = useCallback(() => {
    historyRef.current.past.push({ nodes, edges, groups });
    historyRef.current.future = [];
    setCanUndo(true);
    setCanRedo(false);
  }, [edges, groups, nodes]);

  const undo = useCallback(() => {
    const previous = historyRef.current.past.pop();
    if (!previous) return;
    historyRef.current.future.push({ nodes, edges, groups });
    setNodes(previous.nodes);
    setEdges(previous.edges);
    setGroups(previous.groups);
    setCanUndo(historyRef.current.past.length > 0);
    setCanRedo(true);
  }, [edges, groups, nodes]);

  const redo = useCallback(() => {
    const next = historyRef.current.future.pop();
    if (!next) return;
    historyRef.current.past.push({ nodes, edges, groups });
    setNodes(next.nodes);
    setEdges(next.edges);
    setGroups(next.groups);
    setCanUndo(true);
    setCanRedo(historyRef.current.future.length > 0);
  }, [edges, groups, nodes]);

  const renameGroup = useCallback(
    (groupId: string, label: string) => {
      commit();
      setGroups((gs) => gs.map((g) => (g.id === groupId ? { ...g, label } : g)));
      setNodes((nds) => nds.map((n) => (n.id === `group-${groupId}` ? { ...n, data: { ...n.data, label } } : n)));
    },
    [commit],
  );

  const nodeTypes = useMemo(
    () => ({
      workflow: WorkflowNodeCard,
      group: (props: NodeProps) => {
        const groupNode = props as NodeProps<Node<GroupNodeData>>;
        return <GroupNode {...groupNode} onRename={(label) => renameGroup(groupNode.id, label)} />;
      },
    }),
    [renameGroup],
  );

  // Hydrate from server graph when it changes (definition switch / migration).
  useEffect(() => {
    const statusMap: Record<string, { status: string; progress: number | null; attemptNo: number; phaseCode: string | null }> = {};
    if (runStatus) {
      for (const [key, node] of Object.entries(runStatus)) {
        statusMap[key] = { status: node.status, progress: node.progress, attemptNo: node.attempt_no, phaseCode: node.phase_code };
      }
    }
    const { nodes: rfNodes, edges: rfEdges } = toReactFlow(initialNodes, initialEdges, statusMap, initialGroups);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the canvas must re-seed from the server graph
    setNodes(rfNodes);
    setEdges(rfEdges);
    setGroups(initialGroups);
    setGraphHydrated(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate once per graph identity
  }, [initialNodes, initialEdges, initialGroups]);

  // Keep the host page's production check in sync with the live canvas graph.
  useEffect(() => {
    if (!graphHydrated) return;
    const { nodes: workflowNodes, edges: workflowEdges } = fromReactFlow(nodes, edges, groups);
    onGraphChange?.(workflowNodes, workflowEdges, groups);
  }, [edges, graphHydrated, groups, nodes, onGraphChange]);

  // Live status badges while a run is executing (polled by the page).
  useEffect(() => {
    if (!runStatus) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- react to external run status
    setNodes((nds) =>
      nds.map((node) => {
        if (node.type !== "workflow") return node;
        const info = runStatus[node.id];
        if (!info) return node;
        const data = node.data as WorkflowNodeData;
        return {
          ...node,
          data: { ...data, status: info.status, progress: info.progress, attemptNo: info.attempt_no, phaseCode: info.phase_code },
        };
      }),
    );
  }, [runStatus]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)),
    [],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      if (changes.some((change) => change.type === "remove")) commit();
      setEdges((eds) => applyEdgeChanges(changes, eds));
    },
    [commit],
  );

  const canConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || connection.source === connection.target) return false;
      if (edges.some((e) => e.source === connection.source && e.target === connection.target)) return false;
      try {
        topologicalOrder(
          nodes.filter((n) => n.type === "workflow").map((n) => ({ node_key: n.id })),
          [
            ...edges.map((e) => ({ source_node_key: e.source, target_node_key: e.target })),
            { source_node_key: connection.source, target_node_key: connection.target },
          ],
        );
        return true;
      } catch {
        return false;
      }
    },
    [edges, nodes],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      commit();
      setEdges((eds) => addEdge({ ...connection, type: "smoothstep" }, eds));
    },
    [commit],
  );

  const onConnectStart = useCallback(
    (_event: MouseEvent | TouchEvent, params: OnConnectStartParams) => {
      dragStartRef.current = { nodeId: params.nodeId ?? "", handleId: params.handleId, handleType: params.handleType };
    },
    [],
  );

  const onConnectEnd = useCallback(
    (_event: MouseEvent | TouchEvent, connectionState: FinalConnectionState) => {
      const from = connectionState.fromNode;
      const start = dragStartRef.current;
      dragStartRef.current = null;
      if (!from || connectionState.toNode !== null) return;
      if (start?.handleType !== "source") return;
      // Dragged from an output port without landing on a target: open the palette
      // and wire the next created node back to this source.
      pendingConnectionRef.current = { source: from.id, sourceHandle: start.handleId };
      setPaletteOpen(true);
    },
    [],
  );

  /** Drop a project asset onto the canvas -> image reference node. */
  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData("application/x-shotwise-asset");
      if (!raw) return;
      try {
        const asset = JSON.parse(raw) as { name: string; path: string; kind: string };
        if (!asset.path) return;
        commit();
        const key = nextNodeKey("image_input");
        const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
        setNodes((nds) => [
          ...nds,
          {
            id: key,
            type: "workflow",
            position,
            data: {
              nodeType: "image_input",
              label: asset.name,
              config: { path: asset.path, label: asset.name },
              disabled: false,
              status: null,
              progress: null,
              attemptNo: null,
              phaseCode: null,
              groupId: null,
            },
            style: { borderColor: nodeTypeDef("image_input").color },
          },
        ]);
        setSelectedId(key);
      } catch {
        // ignore malformed payload
      }
    },
    [commit, screenToFlowPosition],
  );

  const addNode = (nodeType: string): string => {
    commit();
    const key = nextNodeKey(nodeType);
    const def = nodeTypeDef(nodeType);
    const position = screenToFlowPosition({ x: window.innerWidth / 2 - 100, y: window.innerHeight / 2 - 60 });
    setNodes((nds) => [
      ...nds,
      {
        id: key,
        type: "workflow",
        position,
        data: {
          nodeType,
          label: key,
          config: { ...def.defaultConfig },
          disabled: false,
          status: null,
          progress: null,
          attemptNo: null,
          phaseCode: null,
          groupId: null,
        },
        style: { borderColor: def.color },
      },
    ]);
    setSelectedId(key);
    return key;
  };

  /** Create a node and auto-wire it from the pending source port (drag-to-create). */
  const addNodeFromPort = (nodeType: string) => {
    const pending = pendingConnectionRef.current;
    pendingConnectionRef.current = null;
    const key = addNode(nodeType);
    const source = pending?.source;
    if (source) {
      const def = nodeTypeDef(nodeType);
      const targetHandle = def.inputs[0]?.id ?? null;
      setEdges((eds) => [
        ...eds,
        {
          id: `${source}-${key}`,
          source,
          sourceHandle: pending?.sourceHandle ?? null,
          target: key,
          targetHandle,
          type: "smoothstep",
          markerEnd: { type: MarkerType.ArrowClosed },
        },
      ]);
    }
    setPaletteOpen(false);
  };

  /** Remove every edge touching a node (ComfyUI-style port disconnect). */
  const disconnectNode = (nodeId: string) => {
    commit();
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
  };

  const addGroup = () => {
    commit();
    groupSeq.current += 1;
    const id = `group_${groupSeq.current}`;
    const position = screenToFlowPosition({ x: window.innerWidth / 2 - 120, y: window.innerHeight / 2 - 80 });
    setGroups((gs) => [...gs, { id, label: t("flow_group_default_name"), color: "#94a3b8" }]);
    setNodes((nds) => [
      ...nds,
      {
        id: `group-${id}`,
        type: "group",
        position,
        data: { label: t("flow_group_default_name"), color: "#94a3b8" },
        style: { width: 260, height: 180 },
        zIndex: -1,
      },
    ]);
  };

  const deleteNode = useCallback(
    (nodeId: string) => {
      commit();
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedId((current) => (current === nodeId ? null : current));
    },
    [commit],
  );

  const duplicateNode = (nodeId: string) => {
    commit();
    const source = nodes.find((n) => n.id === nodeId);
    if (!source) return;
    const sourceData = source.data as WorkflowNodeData;
    const key = nextNodeKey(sourceData.nodeType);
    setNodes((nds) => [
      ...nds,
      {
        ...source,
        id: key,
        position: { x: source.position.x + 40, y: source.position.y + 40 },
        data: { ...sourceData, label: key, status: null, progress: null, groupId: null },
        selected: false,
      },
    ]);
  };

  const toggleDisabled = (nodeId: string) => {
    commit();
    setNodes((nds) =>
      nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, disabled: !n.data.disabled } } : n)),
    );
  };

  const moveNodeToGroup = (nodeId: string) => {
    if (groups.length === 0) return;
    commit();
    const target = groups[0];
    setNodes((nds) => nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, groupId: target.id } } : n)));
  };

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const { nodes: wNodes, edges: wEdges } = fromReactFlow(nodes, edges, groups);
      return await onSave(wNodes, wEdges, groups);
    } finally {
      setSaving(false);
    }
  }, [edges, groups, nodes, onSave]);

  useEffect(() => {
    onSaveReady?.(save);
    return () => onSaveReady?.(null);
  }, [onSaveReady, save]);

  useEffect(() => {
    window.localStorage.setItem("shotwise-flow-favorites", JSON.stringify(favoriteNodes));
  }, [favoriteNodes]);

  useEffect(() => {
    window.localStorage.setItem("shotwise-flow-custom-templates", JSON.stringify(customTemplates));
  }, [customTemplates]);

  useEffect(() => {
    let active = true;
    void API.listWorkflowTemplates()
      .then(({ items }) => {
        if (!active) return;
        setOfficialTemplates(
          items
            .filter((item) => item.scope === "official")
            .map((item) => ({
              id: item.id,
              nameKey: item.name_key,
              descriptionKey: item.description_key,
              nodes: item.nodes,
              edges: item.edges,
            })),
        );
      })
      .catch(() => {
        // The canvas remains usable when the optional template catalog is unavailable.
      });
    return () => {
      active = false;
    };
  }, []);

  /** Persist the current canvas as a local custom template. */
  const saveAsTemplate = useCallback(() => {
    const { nodes: wNodes, edges: wEdges } = fromReactFlow(nodes, edges, groups);
    if (wNodes.length === 0) return;
    const name = window.prompt(t("flow_save_template_prompt"), `${defaultName} · ${new Date().toLocaleDateString()}`);
    if (!name?.trim()) return;
    const template: WorkflowTemplate = {
      id: `custom-${Date.now().toString(36)}`,
      nameKey: "flow_template_custom",
      descriptionKey: "flow_template_custom_desc",
      customName: name.trim(),
      nodes: wNodes,
      edges: wEdges,
    };
    setCustomTemplates((current) => [...current, template]);
    setTemplateNotice(name.trim());
    window.setTimeout(() => setTemplateNotice(null), 2500);
  }, [defaultName, edges, groups, nodes, t]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (!running) void save();
      }
      const active = document.activeElement as HTMLElement | null;
      const typing = active?.tagName === "INPUT" || active?.tagName === "TEXTAREA" || active?.isContentEditable;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        if (typing) return;
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        if (typing) return;
        event.preventDefault();
        redo();
      }
      if (event.key === "Delete" && selectedId) {
        if (typing) return;
        deleteNode(selectedId);
      }
      if (event.key === "Escape") setPaletteOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deleteNode, favoriteNodes, redo, running, save, selectedId, undo]);

  const exportJson = () => {
    const blob = new Blob([serializeWorkflow(defaultName, nodes, edges, groups)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${defaultName}-workflow.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const importJson = async (file: File) => {
    const text = await file.text();
    const parsed = parseWorkflow(text);
    commit();
    const { nodes: rfNodes, edges: rfEdges } = toReactFlow(parsed.nodes, parsed.edges, {}, []);
    setNodes(rfNodes);
    setEdges(rfEdges);
    setGroups(parsed.groups);
    await onImportWorkflow(parsed.nodes, parsed.edges, parsed.groups);
  };

  const loadTemplate = (templateId: string) => {
    const template =
      officialTemplates.find((item) => item.id === templateId) ??
      customTemplates.find((item) => item.id === templateId);
    if (!template) return;
    commit();
    const { nodes: rfNodes, edges: rfEdges } = toReactFlow(template.nodes, template.edges, {}, []);
    setNodes(rfNodes);
    setEdges(rfEdges);
    setGroups([]);
    setSelectedId(null);
  };

  const onNodeContextMenu = (event: React.MouseEvent, node: Node) => {
    event.preventDefault();
    setMenu({ x: event.clientX, y: event.clientY, nodeId: node.id });
  };

  const onPaneContextMenu = (event: React.MouseEvent | MouseEvent) => {
    event.preventDefault();
    setMenu({ x: event.clientX, y: event.clientY, nodeId: null });
  };

  const selectedNode = nodes.find((n) => n.id === selectedId && n.type === "workflow");
  const updateNodeData = useCallback(
    (next: WorkflowNodeData) => {
      setNodes((nds) => nds.map((n) => (n.id === selectedId ? { ...n, data: next } : n)));
    },
    [selectedId],
  );

  const categoryOrder = useMemo(() => ["script", "assets", "video", "post", "logic", "input"], []);
  const nodeTypesByCategory = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const [nodeType] of Object.entries(NODE_TYPE_DEFS)) {
      const category = nodeTypeDef(nodeType).category;
      map.set(category, [...(map.get(category) ?? []), nodeType]);
    }
    return map;
  }, []);

  const filteredNodeTypes = useCallback(
    (types: string[]) => types.filter((nodeType) => {
      const label = t(nodeTypeLabelKey(nodeType)).toLowerCase();
      return !search.trim() || label.includes(search.trim().toLowerCase()) || nodeType.includes(search.trim().toLowerCase());
    }),
    [search, t],
  );

  const toggleFavorite = (nodeType: string) => {
    setFavoriteNodes((current) => current.includes(nodeType) ? current.filter((item) => item !== nodeType) : [...current, nodeType]);
  };

  const renderNodeButton = (nodeType: string) => {
    const def = nodeTypeDef(nodeType);
    const favorite = favoriteNodes.includes(nodeType);
    return (
      <div key={nodeType} className="group flex items-center gap-1">
        <button
          type="button"
          onClick={() => (pendingConnectionRef.current ? addNodeFromPort(nodeType) : addNode(nodeType))}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-hairline px-2 py-1.5 text-left text-[10px] text-text-2 transition-colors hover:bg-bg focus-ring"
        >
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: def.color }} aria-hidden />
          <span className="truncate">{t(nodeTypeLabelKey(nodeType))}</span>
        </button>
        <button
          type="button"
          onClick={() => toggleFavorite(nodeType)}
          className={`grid h-6 w-6 shrink-0 place-items-center rounded text-text-4 hover:bg-bg focus-ring ${favorite ? "text-accent-2" : "opacity-0 group-hover:opacity-100"}`}
          title={favorite ? t("flow_remove_favorite") : t("flow_add_favorite")}
          aria-label={favorite ? t("flow_remove_favorite") : t("flow_add_favorite")}
        >
          <Star aria-hidden className={`h-3 w-3 ${favorite ? "fill-current" : ""}`} />
        </button>
      </div>
    );
  };

  return (
    <div className="relative flex h-full min-w-0 flex-1 overflow-hidden">
      {/* left palette */}
      <aside className="flex w-[168px] shrink-0 flex-col border-r border-hairline bg-bg-raised">
        <div className="border-b border-hairline px-3 py-2">
          <div className="flex items-center gap-2 text-[11px] font-semibold text-text-2">
            <WorkflowIcon aria-hidden className="h-3.5 w-3.5 text-accent-2" />
            {t("flow_canvas_palette")}
          </div>
          <label className="mt-2 flex h-7 items-center gap-1.5 rounded border border-hairline bg-bg px-2 text-text-4">
            <Search aria-hidden className="h-3 w-3" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("flow_canvas_search")}
              className="min-w-0 flex-1 bg-transparent text-[10px] text-text outline-none placeholder:text-text-4"
              aria-label={t("flow_canvas_search")}
            />
          </label>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {favoriteNodes.length > 0 ? (
            <div className="mb-3">
              <div className="mb-1 flex items-center gap-1 px-1 text-[9px] font-semibold uppercase tracking-wide text-text-4">
                <Star aria-hidden className="h-3 w-3 text-accent-2" />
                {t("flow_category_favorites")}
              </div>
              <div className="space-y-1">{filteredNodeTypes(favoriteNodes).map(renderNodeButton)}</div>
            </div>
          ) : null}
          {categoryOrder.map((category) => {
            const types = filteredNodeTypes(nodeTypesByCategory.get(category) ?? []);
            if (types.length === 0) return null;
            return (
              <div key={category} className="mb-3">
                <div className="mb-1 px-1 text-[9px] font-semibold uppercase tracking-wide text-text-4">
                  {t(NODE_CATEGORY_LABEL_KEYS[category] ?? category)}
                </div>
                <div className="space-y-1">
                  {types.map(renderNodeButton)}
                </div>
              </div>
            );
          })}
          <button
            type="button"
            onClick={addGroup}
            className="flex w-full items-center gap-2 rounded-md border border-dashed border-hairline px-2 py-1.5 text-[10px] text-text-3 transition-colors hover:bg-bg focus-ring"
          >
            <FolderPlus aria-hidden className="h-3 w-3" />
            {t("flow_canvas_add_group")}
          </button>
          {projectAssets.length > 0 ? (
            <div className="mt-3 border-t border-hairline-soft pt-2">
              <div className="mb-1 px-1 text-[9px] font-semibold uppercase tracking-wide text-text-4">{t("flow_assets_library")}</div>
              <div className="space-y-1">
                {projectAssets.map((asset) => (
                  <div
                    key={`${asset.kind}-${asset.name}`}
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.setData("application/x-shotwise-asset", JSON.stringify(asset));
                      event.dataTransfer.effectAllowed = "copy";
                    }}
                    className="flex cursor-grab items-center gap-2 rounded-md border border-hairline px-2 py-1.5 text-[10px] text-text-2 transition-colors hover:bg-bg active:cursor-grabbing"
                    title={asset.path}
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: asset.kind === "character" ? "#ec4899" : asset.kind === "scene" ? "#10b981" : "#f59e0b" }}
                      aria-hidden
                    />
                    <span className="truncate">{asset.name}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </aside>

      {/* canvas */}
      <div className="relative min-w-0 flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onConnectStart={onConnectStart}
          onConnectEnd={onConnectEnd}
          isValidConnection={canConnect as never}
          nodeTypes={nodeTypes}
          onNodeContextMenu={onNodeContextMenu}
          onPaneContextMenu={onPaneContextMenu}
          onNodeDragStart={() => commit()}
          onDoubleClick={() => setPaletteOpen(true)}
          onDrop={onDrop}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
          }}
          onSelectionChange={({ nodes: selected }) => {
            const node = selected.find((item) => item.type === "workflow");
            setSelectedId(node?.id ?? null);
          }}
          minZoom={0.2}
          maxZoom={2.5}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
          <Controls position="bottom-left" />
          <MiniMap position="bottom-right" pannable zoomable nodeStrokeWidth={2} />
        </ReactFlow>

        {/* top toolbar */}
        <div className="absolute left-2 top-2 z-10 flex items-center gap-1.5 rounded-md border border-hairline bg-bg-raised/95 p-1 shadow-sm">
          <select
            defaultValue=""
            onChange={(event) => {
              if (event.target.value) void loadTemplate(event.target.value);
              event.target.value = "";
            }}
            className="h-7 rounded border border-hairline bg-bg px-1.5 text-[10px] text-text focus-ring"
            aria-label={t("flow_canvas_templates")}
          >
            <option value="" disabled>
              {t("flow_canvas_templates")}
            </option>
            <optgroup label={t("flow_template_group_official")}>
              {officialTemplates.map((template) => (
                <option key={template.id} value={template.id}>
                  {t(template.nameKey)}
                </option>
              ))}
            </optgroup>
            {customTemplates.length > 0 ? (
              <optgroup label={t("flow_template_group_custom")}>
                {customTemplates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.customName ?? template.id}
                  </option>
                ))}
              </optgroup>
            ) : null}
          </select>
          <button
            type="button"
            onClick={saveAsTemplate}
            className="inline-flex h-7 items-center gap-1 rounded border border-hairline px-1.5 text-[10px] font-semibold text-text-2 hover:bg-bg focus-ring"
            title={t("flow_save_template")}
          >
            <Star aria-hidden className="h-3 w-3 text-accent-2" />
          </button>
          <button
            type="button"
            onClick={addGroup}
            className="grid h-7 w-7 place-items-center rounded border border-hairline text-text-3 hover:bg-bg focus-ring"
            title={t("flow_canvas_add_group")}
            aria-label={t("flow_canvas_add_group")}
          >
            <FolderPlus aria-hidden className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={exportJson}
            className="grid h-7 w-7 place-items-center rounded border border-hairline text-text-3 hover:bg-bg focus-ring"
            title={t("flow_canvas_export")}
            aria-label={t("flow_canvas_export")}
          >
            <Download aria-hidden className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="grid h-7 w-7 place-items-center rounded border border-hairline text-text-3 hover:bg-bg focus-ring"
            title={t("flow_canvas_import")}
            aria-label={t("flow_canvas_import")}
          >
            <FileUp aria-hidden className="h-3.5 w-3.5" />
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importJson(file);
              event.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={undo}
            disabled={!canUndo}
            className="grid h-7 w-7 place-items-center rounded border border-hairline text-text-3 hover:bg-bg focus-ring disabled:opacity-40"
            title={t("flow_undo")}
            aria-label={t("flow_undo")}
          >
            <Undo2 aria-hidden className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={redo}
            disabled={!canRedo}
            className="grid h-7 w-7 place-items-center rounded border border-hairline text-text-3 hover:bg-bg focus-ring disabled:opacity-40"
            title={t("flow_redo")}
            aria-label={t("flow_redo")}
          >
            <Redo2 aria-hidden className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || running}
            className="inline-flex h-7 items-center gap-1 rounded border border-hairline px-2 text-[10px] font-semibold text-text-2 hover:bg-bg focus-ring disabled:opacity-40"
          >
            <Save aria-hidden className="h-3 w-3" />
            {saving ? "..." : t("flow_canvas_save")}
          </button>
          <button
            type="button"
            onClick={() => {
              const { nodes: wNodes, edges: wEdges } = fromReactFlow(nodes, edges, groups);
              void onRun(wNodes, wEdges, groups);
            }}
            disabled={running || !canRun}
            className="inline-flex h-7 items-center gap-1 rounded bg-accent px-2 text-[10px] font-semibold text-black focus-ring disabled:opacity-40"
            title={!canRun ? runDisabledReason : t("flow_start")}
            aria-label={!canRun ? runDisabledReason : t("flow_start")}
          >
            <Play aria-hidden className="h-3 w-3" />
            {t("flow_start")}
          </button>
        </div>

        {templateNotice ? (
          <div className="absolute left-1/2 top-2 z-20 -translate-x-1/2 rounded-md border border-good/40 bg-bg-raised px-3 py-1.5 text-[11px] font-semibold text-good shadow-md">
            {t("flow_saved_as_template", { name: templateNotice })}
          </div>
        ) : null}

        {paletteOpen ? (
          <div className="absolute left-2 top-12 z-20 w-[250px] rounded-md border border-hairline bg-bg-raised p-2 shadow-lg">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-[10px] font-semibold text-text-2">{t("flow_canvas_add_node")}</span>
              <button type="button" onClick={() => setPaletteOpen(false)} className="text-[10px] text-text-4 hover:text-text focus-ring">Esc</button>
            </div>
            <label className="mb-2 flex h-7 items-center gap-1.5 rounded border border-hairline bg-bg px-2 text-text-4">
              <Search aria-hidden className="h-3 w-3" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("flow_canvas_search")} className="min-w-0 flex-1 bg-transparent text-[10px] text-text outline-none" />
            </label>
            <div className="max-h-[260px] space-y-1 overflow-y-auto">
              {Object.keys(NODE_TYPE_DEFS).filter((nodeType) => filteredNodeTypes([nodeType]).length > 0).map((nodeType) => (
                <button key={nodeType} type="button" onClick={() => (pendingConnectionRef.current ? addNodeFromPort(nodeType) : addNode(nodeType))} className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[10px] text-text-2 hover:bg-bg focus-ring">
                  <span className="h-2 w-2 rounded-full" style={{ background: nodeTypeDef(nodeType).color }} aria-hidden />
                  {t(nodeTypeLabelKey(nodeType))}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {/* context menu */}
        {menu ? (
          <div
            className="absolute z-20 w-40 rounded-md border border-hairline bg-bg-raised py-1 shadow-md"
            style={{ left: menu.x, top: menu.y }}
            onMouseLeave={() => setMenu(null)}
          >
            {menu.nodeId ? (
              <>
                {runStatus?.[menu.nodeId]?.status === "failed" && onRetryFromNode ? (
                  <button
                    type="button"
                    onClick={() => {
                      onRetryFromNode(menu.nodeId!);
                      setMenu(null);
                    }}
                    className="block w-full px-3 py-1.5 text-left text-[11px] font-semibold text-accent-2 hover:bg-bg focus-ring"
                  >
                    {t("flow_retry_from_node")}
                  </button>
                ) : null}
                {Object.keys(runStatus?.[menu.nodeId]?.output_refs ?? {}).length > 0 && onPreviewOutputs ? (
                  <button
                    type="button"
                    onClick={() => {
                      onPreviewOutputs(menu.nodeId!);
                      setMenu(null);
                    }}
                    className="block w-full px-3 py-1.5 text-left text-[11px] text-text-2 hover:bg-bg focus-ring"
                  >
                    {t("flow_view_outputs")}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    duplicateNode(menu.nodeId!);
                    setMenu(null);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-[11px] text-text-2 hover:bg-bg focus-ring"
                >
                  {t("flow_node_duplicate")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    toggleDisabled(menu.nodeId!);
                    setMenu(null);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-[11px] text-text-2 hover:bg-bg focus-ring"
                >
                  {t("flow_node_toggle_disabled")}
                </button>
                {onViewNodeLogs ? (
                  <button
                    type="button"
                    onClick={() => {
                      onViewNodeLogs(menu.nodeId!);
                      setMenu(null);
                    }}
                    className="block w-full px-3 py-1.5 text-left text-[11px] text-text-2 hover:bg-bg focus-ring"
                  >
                    {t("flow_node_view_logs")}
                  </button>
                ) : null}
                {groups.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => {
                      moveNodeToGroup(menu.nodeId!);
                      setMenu(null);
                    }}
                    className="block w-full px-3 py-1.5 text-left text-[11px] text-text-2 hover:bg-bg focus-ring"
                  >
                    {t("flow_node_add_to_group")}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    disconnectNode(menu.nodeId!);
                    setMenu(null);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-[11px] text-text-2 hover:bg-bg focus-ring"
                >
                  {t("flow_node_disconnect")}
                </button>
                <div className="my-1 border-t border-hairline-soft" />
                <button
                  type="button"
                  onClick={() => {
                    deleteNode(menu.nodeId!);
                    setMenu(null);
                  }}
                  className="block w-full px-3 py-1.5 text-left text-[11px] text-danger hover:bg-danger/10 focus-ring"
                >
                  {t("flow_node_delete")}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => {
                  addGroup();
                  setMenu(null);
                }}
                className="block w-full px-3 py-1.5 text-left text-[11px] text-text-2 hover:bg-bg focus-ring"
              >
                {t("flow_canvas_add_group")}
              </button>
            )}
          </div>
        ) : null}
      </div>

      {/* right config panel */}
      {selectedNode ? (
        <NodeConfigPanel
          nodeId={selectedNode.id}
          data={selectedNode.data as WorkflowNodeData}
          onChange={updateNodeData}
          onDelete={deleteNode}
          onAddToGroup={(nodeId) => {
            moveNodeToGroup(nodeId);
          }}
        />
      ) : null}
    </div>
  );
}

export function FlowCanvas(props: FlowCanvasProps) {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

export { WorkflowIcon };


