export type WorkflowRunStatus =
  | "planned"
  | "running"
  | "paused"
  | "waiting_review"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface WorkflowNodeRun {
  id: string;
  node_key: string;
  attempt_no: number;
  status: string;
  progress: number | null;
  progress_source: string | null;
  phase_code: string | null;
  error_code: string | null;
  /** Machine-readable error details, e.g. validation field + value. */
  error_params?: Record<string, unknown>;
  /** Node outputs as asset references: port id -> asset refs. */
  output_refs?: Record<string, WorkflowAssetRef[]>;
  fencing_token: number;
}

/** A node output: a typed reference into the project asset tree. */
export interface WorkflowAssetRef {
  kind: string;
  path?: string | null;
  count?: number | null;
  label?: string;
}

export interface WorkflowRunSummary {
  id: string;
  workflow_revision_id: string;
  status: WorkflowRunStatus;
  mode: "auto" | "manual" | "hybrid";
  progress: number | null;
  version: number;
  control_generation: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  workspace_id: string;
  project_id: string;
  input_fingerprint: string;
  nodes: WorkflowNodeRun[];
}

export interface WorkflowEvent {
  seq: number;
  event_id: string;
  aggregate_type: string;
  aggregate_id: string;
  aggregate_version: number;
  event_type: string;
  event_version: number;
  payload: Record<string, unknown>;
  trace_id: string | null;
  created_at: string;
}

// ---------- canvas workflow (ComfyUI-style DAG) ----------

export type WorkflowNodeConfig = Record<string, unknown>;

export interface WorkflowNodeInput {
  node_key: string;
  node_type: string;
  node_type_version?: string;
  config_schema_version?: string;
  config: WorkflowNodeConfig;
  ui_position?: { x: number; y: number; group?: string } | null;
  weight?: number;
  disabled?: boolean;
}

export interface WorkflowEdgeInput {
  edge_key: string;
  source_node_key: string;
  target_node_key: string;
  on_failure?: "stop" | "skip" | "fallback";
  priority?: number;
}

export interface WorkflowDefinitionSummary {
  id: string;
  name: string;
  scope: string;
  active_revision_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowDefinitionDetail {
  id: string;
  workspace_id: string;
  project_id: string;
  name: string;
  scope: string;
  active_revision_id: string | null;
  active_revision?: {
    id: string;
    revision_no: number;
    status: string;
    graph_hash: string;
    execution_hash: string;
    template_lock: Record<string, unknown> | null;
    nodes: WorkflowNodeInput[];
    edges: WorkflowEdgeInput[];
  };
}

export interface WorkflowRevisionSummary {
  id: string;
  revision_no: number;
  status: string;
  graph_hash: string;
  execution_hash: string;
  is_active: boolean;
  created_by: string;
  created_at: string;
}

export interface WorkflowTemplateCatalogItem {
  id: string;
  scope: "official" | "custom";
  name_key: string;
  description_key: string;
  template_lock: Record<string, unknown> | null;
  nodes: WorkflowNodeInput[];
  edges: WorkflowEdgeInput[];
}

export interface WorkflowExport {
  schema_version: number;
  name: string;
  nodes: WorkflowNodeInput[];
  edges: WorkflowEdgeInput[];
  template_lock: Record<string, unknown> | null;
}

export interface WorkflowNodeLogEntry {
  seq: number;
  level: string;
  line: string;
  created_at: string;
}

/** Ports of a canvas node type: what it can consume and produce. */
export interface WorkflowPortDef {
  id: string;
  label: string;
  kind: "image" | "video" | "script" | "audio" | "asset" | "params" | "plan" | "file" | "source";
  multiple?: boolean;
}

export interface WorkflowNodeTypeDef {
  node_type: string;
  color: string;
  category: "script" | "assets" | "video" | "post" | "logic" | "input";
  inputs: WorkflowPortDef[];
  outputs: WorkflowPortDef[];
  defaultConfig: WorkflowNodeConfig;
}

/** Built-in template loaded onto the canvas. */
export interface WorkflowTemplate {
  id: string;
  nameKey: string;
  descriptionKey: string;
  /** User-facing name for locally saved custom templates. */
  customName?: string;
  nodes: WorkflowNodeInput[];
  edges: WorkflowEdgeInput[];
}
