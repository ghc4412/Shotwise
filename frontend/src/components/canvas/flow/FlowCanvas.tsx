import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
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
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Download, FileUp, FolderPlus, Play, Save, Workflow as WorkflowIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { WorkflowEdgeInput, WorkflowNodeInput } from "@/types";
import { GroupNode, WorkflowNodeCard } from "./WorkflowNodeCard";
import { NodeConfigPanel } from "./NodeConfigPanel";
import {
  NODE_CATEGORY_LABEL_KEYS,
  NODE_TYPE_DEFS,
  WORKFLOW_TEMPLATES,
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

const NODE_TYPES = {
  workflow: WorkflowNodeCard,
  group: GroupNode,
};

interface RunStatusInfo {
  status: string;
  progress: number | null;
  attemptNo: number;
  phaseCode: string | null;
}

interface FlowCanvasProps {
  initialNodes: WorkflowNodeInput[];
  initialEdges: WorkflowEdgeInput[];
  initialGroups: GroupMeta[];
  runStatus: Record<string, RunStatusInfo> | null;
  running: boolean;
  defaultName: string;
  onSave: (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => Promise<void>;
  onImportWorkflow: (nodes: WorkflowNodeInput[], edges: WorkflowEdgeInput[], groups: GroupMeta[]) => Promise<void>;
  onViewNodeLogs?: (nodeKey: string) => void;
}

interface ContextMenuState {
  x: number;
  y: number;
  nodeId: string | null;
}

interface FlowCanvasInnerProps extends FlowCanvasProps {
  onRun: () => void;
}

function FlowCanvasInner({
  initialNodes,
  initialEdges,
  initialGroups,
  runStatus,
  running,
  defaultName,
  onSave,
  onImportWorkflow,
  onRun,
  onViewNodeLogs,
}: FlowCanvasInnerProps) {
  const { t } = useTranslation("dashboard");
  const { screenToFlowPosition } = useReactFlow();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [groups, setGroups] = useState<GroupMeta[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const groupSeq = useRef(0);

  // Hydrate from server graph when it changes (definition switch / migration).
  useEffect(() => {
    const { nodes: rfNodes, edges: rfEdges } = toReactFlow(initialNodes, initialEdges, runStatus ?? {}, initialGroups);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the canvas must re-seed from the server graph
    setNodes(rfNodes);
    setEdges(rfEdges);
    setGroups(initialGroups);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- hydrate once per graph identity
  }, [initialNodes, initialEdges, initialGroups]);

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
          data: { ...data, status: info.status, progress: info.progress, attemptNo: info.attemptNo, phaseCode: info.phaseCode },
        };
      }),
    );
  }, [runStatus]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)),
    [],
  );
  const onEdgesChange = useCallback((changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)), []);

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
      setEdges((eds) => addEdge({ ...connection, type: "smoothstep" }, eds));
    },
    [],
  );

  const addNode = (nodeType: string) => {
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
  };

  const addGroup = () => {
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

  const deleteNode = (nodeId: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId));
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
    setSelectedId((current) => (current === nodeId ? null : current));
  };

  const duplicateNode = (nodeId: string) => {
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
    setNodes((nds) =>
      nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, disabled: !n.data.disabled } } : n)),
    );
  };

  const moveNodeToGroup = (nodeId: string) => {
    if (groups.length === 0) return;
    const target = groups[0];
    setNodes((nds) => nds.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, groupId: target.id } } : n)));
  };

  const save = async () => {
    setSaving(true);
    try {
      const { nodes: wNodes, edges: wEdges } = fromReactFlow(nodes, edges, groups);
      await onSave(wNodes, wEdges, groups);
    } finally {
      setSaving(false);
    }
  };

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
    const { nodes: rfNodes, edges: rfEdges } = toReactFlow(parsed.nodes, parsed.edges, {}, []);
    setNodes(rfNodes);
    setEdges(rfEdges);
    setGroups(parsed.groups);
    await onImportWorkflow(parsed.nodes, parsed.edges, parsed.groups);
  };

  const loadTemplate = (templateId: string) => {
    const template = WORKFLOW_TEMPLATES.find((item) => item.id === templateId);
    if (!template) return;
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

  const categoryOrder = useMemo(() => ["production", "business", "generic", "input"], []);
  const nodeTypesByCategory = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const [nodeType] of Object.entries(NODE_TYPE_DEFS)) {
      const category = nodeTypeDef(nodeType).category;
      map.set(category, [...(map.get(category) ?? []), nodeType]);
    }
    return map;
  }, []);

  return (
    <div className="relative flex h-full min-w-0 flex-1 overflow-hidden">
      {/* left palette */}
      <aside className="flex w-[168px] shrink-0 flex-col border-r border-hairline bg-bg-raised">
        <div className="border-b border-hairline px-3 py-2 text-[11px] font-semibold text-text-2">
          {t("flow_canvas_palette")}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {categoryOrder.map((category) => {
            const types = nodeTypesByCategory.get(category) ?? [];
            if (types.length === 0) return null;
            return (
              <div key={category} className="mb-3">
                <div className="mb-1 px-1 text-[9px] font-semibold uppercase tracking-wide text-text-4">
                  {t(NODE_CATEGORY_LABEL_KEYS[category] ?? category)}
                </div>
                <div className="space-y-1">
                  {types.map((nodeType) => {
                    const def = nodeTypeDef(nodeType);
                    return (
                      <button
                        key={nodeType}
                        type="button"
                        onClick={() => addNode(nodeType)}
                        className="flex w-full items-center gap-2 rounded-md border border-hairline px-2 py-1.5 text-left text-[10px] text-text-2 transition-colors hover:bg-bg focus-ring"
                      >
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: def.color }} aria-hidden />
                        <span className="truncate">{t(nodeTypeLabelKey(nodeType))}</span>
                      </button>
                    );
                  })}
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
          isValidConnection={canConnect as never}
          nodeTypes={NODE_TYPES}
          onNodeContextMenu={onNodeContextMenu}
          onPaneContextMenu={onPaneContextMenu}
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
            onChange={(event) => event.target.value && void loadTemplate(event.target.value)}
            className="h-7 rounded border border-hairline bg-bg px-1.5 text-[10px] text-text focus-ring"
            aria-label={t("flow_canvas_templates")}
          >
            <option value="" disabled>
              {t("flow_canvas_templates")}
            </option>
            {WORKFLOW_TEMPLATES.map((template) => (
              <option key={template.id} value={template.id}>
                {t(template.nameKey)}
              </option>
            ))}
          </select>
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
            onClick={() => void save()}
            disabled={saving || running}
            className="inline-flex h-7 items-center gap-1 rounded border border-hairline px-2 text-[10px] font-semibold text-text-2 hover:bg-bg focus-ring disabled:opacity-40"
          >
            <Save aria-hidden className="h-3 w-3" />
            {saving ? "..." : t("flow_canvas_save")}
          </button>
          <button
            type="button"
            onClick={onRun}
            disabled={running}
            className="inline-flex h-7 items-center gap-1 rounded bg-accent px-2 text-[10px] font-semibold text-black focus-ring disabled:opacity-40"
          >
            <Play aria-hidden className="h-3 w-3" />
            {t("flow_start")}
          </button>
        </div>

        {/* context menu */}
        {menu ? (
          <div
            className="absolute z-20 w-40 rounded-md border border-hairline bg-bg-raised py-1 shadow-md"
            style={{ left: menu.x, top: menu.y }}
            onMouseLeave={() => setMenu(null)}
          >
            {menu.nodeId ? (
              <>
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

export function FlowCanvas(props: FlowCanvasProps & { onRun: () => void }) {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

export { WorkflowIcon };


