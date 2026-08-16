import type { WorkflowEdgeInput, WorkflowNodeInput, WorkflowNodeTypeDef, WorkflowPortDef, WorkflowTemplate } from "@/types";

/** Port kinds that carry project asset references. */
const IN: WorkflowPortDef[] = [{ id: "in", label: "in", kind: "params", multiple: true }];
const OUT: WorkflowPortDef[] = [{ id: "out", label: "out", kind: "params", multiple: true }];
const NONE: WorkflowPortDef[] = [];

/**
 * Registry of canvas node types. The node_type strings must match the backend
 * adapter registry in server/services/workflow_adapters.py exactly.
 */
export const NODE_TYPE_DEFS: Record<string, WorkflowNodeTypeDef> = {
  // ---- production chain ----
  source_import: { node_type: "source_import", color: "#8b5cf6", category: "production", inputs: NONE, outputs: [{ id: "source", label: "source", kind: "source" }], defaultConfig: {} },
  script_generate: { node_type: "script_generate", color: "#3b82f6", category: "production", inputs: IN, outputs: [{ id: "script", label: "script", kind: "script" }], defaultConfig: { episode: 1 } },
  script_review: { node_type: "script_review", color: "#f59e0b", category: "production", inputs: IN, outputs: [{ id: "script", label: "script", kind: "script" }], defaultConfig: {} },
  character_reference: { node_type: "character_reference", color: "#ec4899", category: "business", inputs: IN, outputs: [{ id: "characters", label: "characters", kind: "asset" }], defaultConfig: {} },
  storyboard_generate: { node_type: "storyboard_generate", color: "#06b6d4", category: "production", inputs: IN, outputs: [{ id: "plan", label: "plan", kind: "plan" }], defaultConfig: {} },
  storyboard_review: { node_type: "storyboard_review", color: "#f59e0b", category: "production", inputs: IN, outputs: [{ id: "image", label: "image", kind: "image" }], defaultConfig: {} },
  shot_image_generate: { node_type: "shot_image_generate", color: "#10b981", category: "production", inputs: IN, outputs: [{ id: "image", label: "image", kind: "image" }], defaultConfig: { only_missing: false } },
  shot_video_generate: { node_type: "shot_video_generate", color: "#ef4444", category: "production", inputs: IN, outputs: [{ id: "video", label: "video", kind: "video" }], defaultConfig: {} },
  voice_generate: { node_type: "voice_generate", color: "#14b8a6", category: "production", inputs: IN, outputs: [{ id: "plan", label: "plan", kind: "plan" }], defaultConfig: {} },
  subtitle_generate: { node_type: "subtitle_generate", color: "#a855f7", category: "production", inputs: IN, outputs: [{ id: "plan", label: "plan", kind: "plan" }], defaultConfig: {} },
  compose: { node_type: "compose", color: "#6366f1", category: "business", inputs: IN, outputs: [{ id: "draft", label: "draft", kind: "file" }], defaultConfig: { episode: 1 } },
  quality_check: { node_type: "quality_check", color: "#f59e0b", category: "business", inputs: IN, outputs: [], defaultConfig: {} },
  export: { node_type: "export", color: "#22c55e", category: "business", inputs: IN, outputs: [{ id: "exported", label: "exported", kind: "file" }], defaultConfig: {} },
  // ---- generic wiring ----
  image_input: { node_type: "image_input", color: "#64748b", category: "input", inputs: NONE, outputs: [{ id: "image", label: "image", kind: "image" }], defaultConfig: {} },
  video_input: { node_type: "video_input", color: "#64748b", category: "input", inputs: NONE, outputs: [{ id: "video", label: "video", kind: "video" }], defaultConfig: {} },
  loop: { node_type: "loop", color: "#0ea5e9", category: "generic", inputs: IN, outputs: [{ id: "items", label: "items", kind: "params" }], defaultConfig: { items: [] } },
  branch: { node_type: "branch", color: "#f97316", category: "generic", inputs: IN, outputs: [{ id: "true", label: "true", kind: "params" }, { id: "false", label: "false", kind: "params" }], defaultConfig: { condition: { field: "", equals: "" } } },
  param_adjust: { node_type: "param_adjust", color: "#eab308", category: "generic", inputs: IN, outputs: [{ id: "params", label: "params", kind: "params" }], defaultConfig: { overrides: {} } },
};

/** Human-readable title of a node type (i18n key = flow_node_<node_type>). */
export function nodeTypeLabelKey(nodeType: string): string {
  return `flow_node_${nodeType.replaceAll("-", "_")}`;
}

export const NODE_CATEGORY_LABEL_KEYS: Record<string, string> = {
  production: "flow_category_production",
  business: "flow_category_business",
  generic: "flow_category_generic",
  input: "flow_category_input",
};

export function nodeTypeDef(nodeType: string): WorkflowNodeTypeDef {
  return (
    NODE_TYPE_DEFS[nodeType] ?? {
      node_type: nodeType,
      color: "#94a3b8",
      category: "generic",
      inputs: IN,
      outputs: OUT,
      defaultConfig: {},
    }
  );
}

let sequence = 0;
/** Fresh node_key for a new canvas node. */
export function nextNodeKey(nodeType: string): string {
  sequence += 1;
  return `${nodeType}_${Date.now().toString(36)}${sequence}`;
}

// ---------------------------------------------------------------------------
// Built-in templates
// ---------------------------------------------------------------------------

const T = (
  nodeType: string,
  extra: Record<string, unknown> = {},
): Pick<WorkflowNodeInput, "node_type" | "config"> => ({
  node_type: nodeType,
  config: { ...nodeTypeDef(nodeType).defaultConfig, ...extra },
});

const chain = (
  types: string[],
): { nodes: WorkflowNodeInput[]; edges: WorkflowEdgeInput[] } => {
  const nodes: WorkflowNodeInput[] = types.map((nodeType, index) => ({
    ...T(nodeType),
    node_key: nodeType,
    ui_position: { x: index * 260, y: (index % 4) * 40 },
  }));
  const edges: WorkflowEdgeInput[] = types.slice(1).map((target, index) => ({
    edge_key: `${types[index]}-${target}`,
    source_node_key: types[index],
    target_node_key: target,
    on_failure: "stop",
  }));
  return { nodes, edges };
};

/** Template A: storyboard-driven image-to-video production pipeline. */
export const TEMPLATE_STORYBOARD: WorkflowTemplate = {
  id: "storyboard-to-video",
  nameKey: "flow_template_storyboard",
  descriptionKey: "flow_template_storyboard_desc",
  ...chain([
    "script_generate",
    "script_review",
    "character_reference",
    "storyboard_generate",
    "quality_check",
    "shot_image_generate",
    "shot_video_generate",
    "compose",
    "export",
  ]),
};

/** Template B: reference-image-driven video pipeline. */
export const TEMPLATE_REFERENCE: WorkflowTemplate = {
  id: "reference-to-video",
  nameKey: "flow_template_reference",
  descriptionKey: "flow_template_reference_desc",
  ...chain(["image_input", "character_reference", "quality_check", "shot_video_generate", "param_adjust", "export"]),
};

export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [TEMPLATE_STORYBOARD, TEMPLATE_REFERENCE];
