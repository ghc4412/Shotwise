import type { WorkflowEdgeInput, WorkflowNodeInput } from "@/types";
import { NODE_TYPE_DEFS } from "./node-registry";
import { topologicalOrder } from "./workflow-utils";

export type WorkflowPreflightSeverity = "error" | "warning";

export interface WorkflowPreflightIssue {
  severity: WorkflowPreflightSeverity;
  code: string;
  messageKey: string;
  params?: Record<string, string | number>;
}

export interface WorkflowPreflightResult {
  canRun: boolean;
  errors: WorkflowPreflightIssue[];
  warnings: WorkflowPreflightIssue[];
}

export interface WorkflowPreflightContext {
  contentMode?: string;
  generationMode?: string;
}

const INPUT_NODE_TYPES = new Set(["source_import", "image_input", "video_input"]);
const TERMINAL_NODE_TYPES = new Set(["compose", "export"]);
const REFERENCE_VIDEO_INCOMPATIBLE = new Set(["storyboard_generate", "storyboard_review", "shot_image_generate"]);

function makeIssue(
  severity: WorkflowPreflightSeverity,
  code: string,
  messageKey: string,
  params?: Record<string, string | number>,
): WorkflowPreflightIssue {
  return { severity, code, messageKey, params };
}

export function validateWorkflowGraph(
  nodes: WorkflowNodeInput[],
  edges: WorkflowEdgeInput[],
  context: WorkflowPreflightContext = {},
): WorkflowPreflightResult {
  const errors: WorkflowPreflightIssue[] = [];
  const warnings: WorkflowPreflightIssue[] = [];

  if (nodes.length === 0) {
    errors.push(makeIssue("error", "empty_graph", "flow_preflight_no_nodes"));
    return { canRun: false, errors, warnings };
  }

  const nodeKeys = new Set<string>();
  for (const node of nodes) {
    if (nodeKeys.has(node.node_key)) {
      errors.push(makeIssue("error", "duplicate_node", "flow_preflight_duplicate_node", { node: node.node_key }));
    }
    nodeKeys.add(node.node_key);

    if (!NODE_TYPE_DEFS[node.node_type]) {
      errors.push(makeIssue("error", "unknown_node", "flow_preflight_unknown_node", { node: node.node_type }));
    }

    if (context.generationMode === "reference_video" && REFERENCE_VIDEO_INCOMPATIBLE.has(node.node_type)) {
      errors.push(makeIssue("error", "generation_mode", "flow_preflight_reference_incompatible", { node: node.node_type }));
    }
  }

  for (const edge of edges) {
    if (!nodeKeys.has(edge.source_node_key) || !nodeKeys.has(edge.target_node_key)) {
      errors.push(makeIssue("error", "missing_endpoint", "flow_preflight_missing_endpoint", { edge: edge.edge_key }));
    }
  }

  try {
    topologicalOrder(
      nodes.map((node) => ({ node_key: node.node_key })),
      edges.map((edge) => ({ source_node_key: edge.source_node_key, target_node_key: edge.target_node_key })),
    );
  } catch {
    errors.push(makeIssue("error", "cycle", "flow_preflight_cycle"));
  }

  if (!nodes.some((node) => TERMINAL_NODE_TYPES.has(node.node_type))) {
    errors.push(makeIssue("error", "no_output", "flow_preflight_no_output"));
  }

  const incoming = new Set(edges.map((edge) => edge.target_node_key));
  const outgoing = new Set(edges.map((edge) => edge.source_node_key));
  for (const node of nodes) {
    if (!INPUT_NODE_TYPES.has(node.node_type) && !incoming.has(node.node_key)) {
      warnings.push(makeIssue("warning", "missing_input", "flow_preflight_missing_input", { node: node.node_key }));
    }
    if (!TERMINAL_NODE_TYPES.has(node.node_type) && !outgoing.has(node.node_key)) {
      warnings.push(makeIssue("warning", "dead_end", "flow_preflight_dead_end", { node: node.node_key }));
    }
  }

  return { canRun: errors.length === 0, errors, warnings };
}
