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
  episode_id?: string | null;
  budget_limit?: number | null;
  spent_amount?: number;
  reserved_amount?: number;
  remaining_amount?: number | null;
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  workspace_id: string;
  project_id: string;
  input_fingerprint: string;
  episode_id?: string | null;
  budget_limit?: number | null;
  spent_amount?: number;
  reserved_amount?: number;
  remaining_amount?: number | null;
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
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  executor_id?: string;
  required_capabilities?: string[];
  estimated_cost?: number;
  cache_policy?: string;
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

export interface WorkflowRevisionDetail {
  id: string;
  revision_no: number;
  status: string;
  graph_hash: string;
  execution_hash: string;
  content_mode?: string;
  generation_mode?: string;
  input_schema?: Record<string, unknown>;
  template_lock: Record<string, unknown> | null;
  nodes: WorkflowNodeInput[];
  edges: WorkflowEdgeInput[];
}

export interface WorkflowDefinitionDetail {
  id: string;
  workspace_id: string;
  project_id: string;
  name: string;
  scope: string;
  active_revision_id: string | null;
  active_revision?: WorkflowRevisionDetail;
  draft_revision?: WorkflowRevisionDetail;
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
  content_mode?: string;
  generation_mode?: string;
}

export interface WorkflowTemplateCatalogItem {
  id: string;
  scope: "official" | "custom" | "marketplace";
  name_key: string;
  description_key: string;
  template_lock?: Record<string, unknown> | null;
  nodes: WorkflowNodeInput[];
  edges: WorkflowEdgeInput[];
  name?: string;
  description?: string;
  template_type?: "manga" | "short_drama";
  status?: string;
  published_revision_id?: string | null;
  contract?: Record<string, unknown>;
  stats?: WorkflowTemplateStats;
}

export interface WorkflowTemplateStats {
  views: number;
  derivations: number;
  run_count: number;
  successful_run_count: number;
  success_rate: number;
  average_cost: number;
  average_duration_seconds: number;
  rating: number | null;
}

export interface WorkflowPatchOperation {
  operation: "set_config" | "add_node" | "remove_node" | "add_edge" | "remove_edge";
  target_node?: string | null;
  path?: string | null;
  before?: unknown;
  after?: unknown;
  estimated_cost_delta?: number;
  requires_confirmation?: boolean;
}

export interface WorkflowPatch {
  base_revision_id: string;
  operations: WorkflowPatchOperation[];
  scope?: "shot" | "scene" | "episode";
  rerun?: boolean;
  reason?: string;
}

export interface WorkflowPatchPreview {
  valid: boolean;
  affected_nodes: string[];
  estimated_cost_delta: number;
  requires_confirmation: boolean;
}

export interface WorkflowPatchApplyResult {
  revision_id: string;
  status: string;
  parent_revision_id: string;
  affected_nodes: string[];
  estimated_cost_delta: number;
  published?: { id: string; status: string };
  run?: { id: string; status: string; version: number };
}

export interface WorkflowReviewItem extends WorkflowTemplateCatalogItem {
  risk_tags: string[];
  static_validation?: {
    valid: boolean;
    node_count: number;
    edge_count: number;
    missing_endpoints: Array<Record<string, unknown>>;
  };
  reviews: Array<{
    id: string;
    decision: string;
    comment: string;
    reviewer_id: string;
    created_at: string;
  }>;
}

export interface WorkflowExport {
  schema_version: number;
  name: string;
  nodes: WorkflowNodeInput[];
  edges: WorkflowEdgeInput[];
  template_lock: Record<string, unknown> | null;
  content_mode?: string;
  generation_mode?: string;
  input_schema?: Record<string, unknown>;
}

export interface WorkflowTemplateUpgradeChanges {
  added_nodes: string[];
  removed_nodes: string[];
  changed_nodes: string[];
  added_edges: string[];
  removed_edges: string[];
}

export interface WorkflowTemplateUpgrade {
  available: boolean;
  reason?: string;
  template_id?: string;
  current_revision_id?: string;
  current_source_revision_id?: string;
  latest_revision_id?: string;
  latest_revision_no?: number;
  compatible?: boolean;
  compatibility_reasons?: string[];
  estimated_cost_delta?: number;
  changes?: WorkflowTemplateUpgradeChanges;
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
