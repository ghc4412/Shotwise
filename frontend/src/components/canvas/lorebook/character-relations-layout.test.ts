import { describe, expect, it } from "vitest";
import type { CharacterRelationEdge } from "@/types";
import { connectionHandles, layoutCharacterRelations, primaryCharacterName } from "./character-relations-layout";

function edge(source: string, target: string): CharacterRelationEdge {
  return {
    id: `${source}-${target}`,
    source,
    target,
    type: "friend",
    label: "",
    directed: false,
    description: "",
    origin: "ai",
    manual_override: false,
    confidence: 0.8,
    evidence: [],
  };
}

describe("character relationship layouts", () => {
  const names = ["Lead", "Friend", "Mentor", "Rival", "Extra"];
  const edges = [edge("Lead", "Friend"), edge("Lead", "Mentor"), edge("Lead", "Rival")];

  it("places the most connected character at the top of the hierarchy", () => {
    const positions = layoutCharacterRelations(names, edges, "hierarchy");
    expect(primaryCharacterName(names, edges)).toBe("Lead");
    expect(positions.Lead?.y).toBe(0);
    expect(positions.Friend?.y).toBeGreaterThan(positions.Lead?.y ?? 0);
  });

  it("places the most connected character at the center of the radial layout", () => {
    const positions = layoutCharacterRelations(names, edges, "radial");
    expect(positions.Lead).toEqual({ x: 0, y: 0 });
    expect(positions.Friend).not.toEqual({ x: 0, y: 0 });
  });

  it("chooses handles that face the connected node", () => {
    expect(connectionHandles({ x: 0, y: 0 }, { x: 100, y: 10 })).toEqual({
      sourceHandle: "source-right",
      targetHandle: "target-left",
    });
    expect(connectionHandles({ x: 0, y: 0 }, { x: 5, y: -100 })).toEqual({
      sourceHandle: "source-top",
      targetHandle: "target-bottom",
    });
  });
});
