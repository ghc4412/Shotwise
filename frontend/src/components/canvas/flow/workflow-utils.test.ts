import { describe, expect, it } from "vitest";
import type { Node } from "@xyflow/react";
import { fromReactFlow, parseWorkflow, serializeWorkflow, toReactFlow, topologicalOrder } from "./workflow-utils";
import type { WorkflowNodeData } from "./workflow-utils";

function rfNode(id: string, nodeType: string, x: number, y: number): Node<WorkflowNodeData> {
  return {
    id,
    type: "workflow",
    position: { x, y },
    data: {
      nodeType,
      label: id,
      config: {},
      disabled: false,
      status: null,
      progress: null,
      attemptNo: null,
      phaseCode: null,
      groupId: null,
    },
  };
}

describe("topologicalOrder", () => {
  it("orders a linear chain roots first", () => {
    const nodes = [{ node_key: "a" }, { node_key: "b" }, { node_key: "c" }];
    const edges = [
      { source_node_key: "a", target_node_key: "b" },
      { source_node_key: "b", target_node_key: "c" },
    ];
    expect(topologicalOrder(nodes, edges)).toEqual(["a", "b", "c"]);
  });

  it("orders a diamond keeping dependencies before dependents", () => {
    const nodes = [{ node_key: "a" }, { node_key: "b" }, { node_key: "c" }, { node_key: "d" }];
    const edges = [
      { source_node_key: "a", target_node_key: "b" },
      { source_node_key: "a", target_node_key: "c" },
      { source_node_key: "b", target_node_key: "d" },
      { source_node_key: "c", target_node_key: "d" },
    ];
    const order = topologicalOrder(nodes, edges);
    expect(order[0]).toBe("a");
    expect(order[order.length - 1]).toBe("d");
  });

  it("rejects cycles", () => {
    const nodes = [{ node_key: "a" }, { node_key: "b" }];
    const edges = [
      { source_node_key: "a", target_node_key: "b" },
      { source_node_key: "b", target_node_key: "a" },
    ];
    expect(() => topologicalOrder(nodes, edges)).toThrow("workflow_cycle_detected");
  });
});

describe("serialize/parse roundtrip", () => {
  it("preserves nodes, edges and groups", () => {
    const nodes = [rfNode("script_generate_1", "script_generate", 0, 0), rfNode("export_1", "export", 300, 0)];
    const edges = [{ id: "e1", source: "script_generate_1", target: "export_1" }];
    const json = serializeWorkflow("demo", nodes, edges, [{ id: "g1", label: "Group", color: "#fff" }]);
    const parsed = parseWorkflow(json);
    expect(parsed.name).toBe("demo");
    expect(parsed.nodes.map((n) => n.node_key)).toEqual(["script_generate_1", "export_1"]);
    expect(parsed.edges.map((e) => e.edge_key)).toEqual(["e1"]);
    expect(parsed.groups).toEqual([{ id: "g1", label: "Group", color: "#fff" }]);
  });

  it("normalizes missing node keys and drops dangling edges", () => {
    const json = JSON.stringify({
      schema_version: 1,
      name: "x",
      nodes: [{ node_type: "export", config: {} }],
      edges: [{ source_node_key: "missing", target_node_key: "ghost", on_failure: "stop" as const }],
    });
    const parsed = parseWorkflow(json);
    expect(parsed.nodes).toHaveLength(1);
    expect(parsed.nodes[0].node_key).toBeTruthy();
    expect(parsed.edges).toHaveLength(0);
  });
});

describe("to/from ReactFlow", () => {
  it("roundtrips positions and config", () => {
    const workflowNodes = [
      {
        node_key: "a",
        node_type: "script_generate",
        config: { episode: 2, disabled: false },
        ui_position: { x: 10, y: 20 },
      },
      {
        node_key: "b",
        node_type: "export",
        config: { disabled: true },
        ui_position: { x: 260, y: 20 },
      },
    ];
    const workflowEdges = [{ edge_key: "a-b", source_node_key: "a", target_node_key: "b", on_failure: "stop" as const }];
    const { nodes, edges } = toReactFlow(workflowNodes, workflowEdges, {}, []);
    expect(nodes).toHaveLength(2);
    expect((nodes[0].data as WorkflowNodeData).config.episode).toBe(2);
    const back = fromReactFlow(nodes, edges, []);
    expect(back.nodes[1].disabled).toBe(true);
    expect(back.nodes[0].ui_position?.x).toBe(10);
    expect(back.edges[0].source_node_key).toBe("a");
  });

  it("rejects connection cycles through the validator", () => {
    const workflowNodes = [
      { node_key: "a", node_type: "export", config: {}, ui_position: { x: 0, y: 0 } },
      { node_key: "b", node_type: "export", config: {}, ui_position: { x: 200, y: 0 } },
    ];
    const workflowEdges = [{ edge_key: "a-b", source_node_key: "a", target_node_key: "b", on_failure: "stop" as const }];
    const { nodes, edges } = toReactFlow(workflowNodes, workflowEdges, {}, []);
    // a -> b exists; adding b -> a would close a cycle — topologicalOrder must throw.
    const cyclic = [
      ...edges.map((e) => ({ source_node_key: e.source, target_node_key: e.target })),
      { source_node_key: "b", target_node_key: "a" },
    ];
    expect(() =>
      topologicalOrder(
        nodes.map((n) => ({ node_key: n.id })),
        cyclic,
      ),
    ).toThrow("workflow_cycle_detected");
  });
});

