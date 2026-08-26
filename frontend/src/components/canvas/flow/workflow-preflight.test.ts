import { describe, expect, it } from "vitest";
import type { WorkflowEdgeInput, WorkflowNodeInput } from "@/types";
import { validateWorkflowGraph } from "./workflow-preflight";

function node(node_key: string, node_type: string): WorkflowNodeInput {
  return { node_key, node_type, config: {} };
}

function edge(edge_key: string, source_node_key: string, target_node_key: string): WorkflowEdgeInput {
  return { edge_key, source_node_key, target_node_key };
}

describe("validateWorkflowGraph", () => {
  it("accepts a complete production chain", () => {
    const result = validateWorkflowGraph(
      [node("source", "source_import"), node("script", "script_generate"), node("compose", "compose"), node("export", "export")],
      [edge("source-script", "source", "script"), edge("script-compose", "script", "compose"), edge("compose-export", "compose", "export")],
    );
    expect(result.canRun).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it("blocks reference-video flows that contain storyboard image generation", () => {
    const result = validateWorkflowGraph(
      [node("storyboard", "storyboard_generate"), node("video", "shot_video_generate"), node("export", "export")],
      [edge("storyboard-video", "storyboard", "video"), edge("video-export", "video", "export")],
      { generationMode: "reference_video" },
    );
    expect(result.canRun).toBe(false);
    expect(result.errors.some((item) => item.code === "generation_mode")).toBe(true);
  });

  it("blocks graphs without a compose or export endpoint", () => {
    const result = validateWorkflowGraph([node("script", "script_generate")], []);
    expect(result.canRun).toBe(false);
    expect(result.errors.some((item) => item.code === "no_output")).toBe(true);
  });

  it("blocks cyclic graphs", () => {
    const result = validateWorkflowGraph(
      [node("a", "script_generate"), node("b", "compose"), node("export", "export")],
      [edge("a-b", "a", "b"), edge("b-a", "b", "a"), edge("b-export", "b", "export")],
    );
    expect(result.canRun).toBe(false);
    expect(result.errors.some((item) => item.code === "cycle")).toBe(true);
  });
});
