import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { WorkflowEdgeInput, WorkflowNodeInput } from "@/types";
import { nodeTypeDef, nextNodeKey } from "./node-registry";

/** ReactFlow node data attached to every canvas node. */
export interface WorkflowNodeData extends Record<string, unknown> {
  nodeType: string;
  label: string;
  config: Record<string, unknown>;
  disabled: boolean;
  status: string | null;
  progress: number | null;
  attemptNo: number | null;
  phaseCode: string | null;
  groupId: string | null;
}

export interface GroupMeta {
  id: string;
  label: string;
  color: string;
}

/** Convert persisted workflow nodes/edges into ReactFlow state. */
export function toReactFlow(
  nodes: WorkflowNodeInput[],
  edges: WorkflowEdgeInput[],
  statusMap: Record<string, { status: string; progress: number | null; attemptNo: number; phaseCode: string | null }>,
  groups: GroupMeta[],
): { nodes: Node[]; edges: Edge[] } {
  const rfNodes: Node[] = nodes.map((node) => {
    const ui = node.ui_position ?? { x: 0, y: 0 };
    const groupId = typeof ui.group === "string" ? ui.group : null;
    const status = statusMap[node.node_key] ?? null;
    const def = nodeTypeDef(node.node_type);
    return {
      id: node.node_key,
      type: "workflow",
      position: { x: ui.x ?? 0, y: ui.y ?? 0 },
      data: {
        nodeType: node.node_type,
        label: node.node_key,
        config: node.config ?? {},
        disabled: Boolean((node.config ?? {}).disabled ?? node.disabled),
        status: status?.status ?? null,
        progress: status?.progress ?? null,
        attemptNo: status?.attemptNo ?? null,
        phaseCode: status?.phaseCode ?? null,
        groupId,
      },
      style: { borderColor: def.color },
    } satisfies Node;
  });
  const rfEdges: Edge[] = edges.map((edge) => ({
    id: edge.edge_key,
    source: edge.source_node_key,
    target: edge.target_node_key,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed },
  }));
  for (const group of groups) {
    const children = rfNodes.filter((node) => node.data.groupId === group.id);
    if (children.length === 0) continue;
    const minX = Math.min(...children.map((n) => n.position.x));
    const minY = Math.min(...children.map((n) => n.position.y));
    const maxX = Math.max(...children.map((n) => n.position.x + 200));
    const maxY = Math.max(...children.map((n) => n.position.y + 120));
    rfNodes.push({
      id: `group-${group.id}`,
      type: "group",
      position: { x: minX - 20, y: minY - 36 },
      data: { label: group.label, color: group.color },
      style: { width: maxX - minX + 40, height: maxY - minY + 56 },
      zIndex: -1,
    });
  }
  return { nodes: rfNodes, edges: rfEdges };
}

/** Convert ReactFlow state back into persisted workflow nodes/edges. */
export function fromReactFlow(
  nodes: Node[],
  edges: Edge[],
  groups: GroupMeta[],
): { nodes: WorkflowNodeInput[]; edges: WorkflowEdgeInput[] } {
  const groupOf = new Map(groups.map((g) => [g.id, g.id]));
  const workflowNodes: WorkflowNodeInput[] = nodes
    .filter((node) => node.type === "workflow")
    .map((node) => {
      const data = node.data as WorkflowNodeData;
      const groupId = data.groupId && groupOf.has(data.groupId) ? data.groupId : null;
      return {
        node_key: node.id,
        node_type: data.nodeType,
        node_type_version: "1",
        config_schema_version: "1",
        config: { ...data.config, disabled: data.disabled },
        ui_position: {
          x: Math.round(node.position.x),
          y: Math.round(node.position.y),
          ...(groupId ? { group: groupId } : {}),
        },
        weight: 1,
        disabled: data.disabled,
      };
    });
  const workflowEdges: WorkflowEdgeInput[] = edges
    .filter((edge) => edge.source !== edge.target)
    .map((edge) => ({
      edge_key: edge.id,
      source_node_key: edge.source,
      target_node_key: edge.target,
      on_failure: "stop",
      priority: 0,
    }));
  return { nodes: workflowNodes, edges: workflowEdges };
}

/** Kahn topological order (roots first); throws on cycles. */
export function topologicalOrder(
  nodes: { node_key: string }[],
  edges: { source_node_key: string; target_node_key: string }[],
): string[] {
  const incoming = new Map<string, string[]>(nodes.map((n) => [n.node_key, []]));
  for (const edge of edges) {
    incoming.get(edge.target_node_key)?.push(edge.source_node_key);
  }
  const queue = [...incoming.entries()].filter(([, sources]) => sources.length === 0).map(([key]) => key);
  const order: string[] = [];
  const removed = new Set<string>();
  while (queue.length > 0) {
    const key = queue.shift()!;
    order.push(key);
    removed.add(key);
    for (const edge of edges) {
      if (edge.source_node_key !== key) continue;
      const remaining = (incoming.get(edge.target_node_key) ?? []).filter((s) => !removed.has(s));
      incoming.set(edge.target_node_key, remaining);
      if (remaining.length === 0 && !removed.has(edge.target_node_key)) queue.push(edge.target_node_key);
    }
  }
  if (order.length !== nodes.length) {
    throw new Error("workflow_cycle_detected");
  }
  return order;
}

/** Serialize the canvas to an exportable workflow JSON document. */
export function serializeWorkflow(
  name: string,
  nodes: Node[],
  edges: Edge[],
  groups: GroupMeta[],
): string {
  const { nodes: wNodes, edges: wEdges } = fromReactFlow(nodes, edges, groups);
  return JSON.stringify(
    {
      schema_version: 1,
      name,
      nodes: wNodes,
      edges: wEdges,
      template_lock: null,
      groups: groups.map((g) => ({ id: g.id, label: g.label, color: g.color })),
    },
    null,
    2,
  );
}

/** Parse an imported workflow JSON document into canvas-friendly data. */
export function parseWorkflow(json: string): {
  name: string;
  nodes: WorkflowNodeInput[];
  edges: WorkflowEdgeInput[];
  groups: GroupMeta[];
} {
  const parsed: unknown = JSON.parse(json);
  if (typeof parsed !== "object" || parsed === null) throw new Error("invalid_workflow_json");
  const doc = parsed as {
    name?: unknown;
    nodes?: unknown;
    edges?: unknown;
    groups?: unknown;
  };
  const nodes = Array.isArray(doc.nodes) ? (doc.nodes as WorkflowNodeInput[]) : [];
  const edges = Array.isArray(doc.edges) ? (doc.edges as WorkflowEdgeInput[]) : [];
  if (nodes.length === 0) throw new Error("workflow_has_no_nodes");
  const groups: GroupMeta[] = Array.isArray(doc.groups)
    ? (doc.groups as GroupMeta[])
    : [];
  // Normalize: every node needs a unique node_key and known config shape.
  const seen = new Set<string>();
  const normalized = nodes.map((node) => {
    const key = typeof node.node_key === "string" && node.node_key ? node.node_key : nextNodeKey(String(node.node_type ?? "node"));
    if (seen.has(key)) throw new Error("workflow_duplicate_node_key");
    seen.add(key);
    return {
      ...node,
      node_key: key,
      node_type: String(node.node_type ?? "export"),
      config: typeof node.config === "object" && node.config !== null ? node.config : {},
      ui_position: node.ui_position ?? { x: 0, y: 0 },
    };
  });
  const validKeys = new Set(normalized.map((n) => n.node_key));
  const normalizedEdges = edges
    .filter((e) => validKeys.has(e.source_node_key) && validKeys.has(e.target_node_key))
    .map((e, index) => ({ ...e, edge_key: e.edge_key || `edge_${index}` }));
  return { name: typeof doc.name === "string" ? doc.name : "imported workflow", nodes: normalized, edges: normalizedEdges, groups };
}

/** Status tone mapping shared by node cards and status badges. */
export const NODE_STATUS_ORDER = [
  "running",
  "queued",
  "waiting_review",
  "paused",
  "retry_wait",
  "failed",
  "succeeded",
  "skipped",
  "blocked",
  "cancelled",
] as const;
