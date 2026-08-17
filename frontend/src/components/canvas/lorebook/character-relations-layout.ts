import type { CharacterRelationEdge } from "@/types";

export type CharacterRelationsLayout = "hierarchy" | "radial";

export interface GraphPosition {
  x: number;
  y: number;
}

const HORIZONTAL_GAP = 220;
const VERTICAL_GAP = 140;
const MAX_HIERARCHY_COLUMNS = 10;

function buildAdjacency(names: string[], edges: CharacterRelationEdge[]) {
  const adjacency = new Map(names.map((name) => [name, new Set<string>()]));
  for (const edge of edges) {
    if (!adjacency.has(edge.source) || !adjacency.has(edge.target)) continue;
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
  }
  return adjacency;
}

function byImportance(adjacency: Map<string, Set<string>>) {
  return (left: string, right: string) => {
    const degreeDifference = (adjacency.get(right)?.size ?? 0) - (adjacency.get(left)?.size ?? 0);
    return degreeDifference || left.localeCompare(right);
  };
}

export function primaryCharacterName(names: string[], edges: CharacterRelationEdge[]): string | null {
  if (names.length === 0) return null;
  const adjacency = buildAdjacency(names, edges);
  return [...names].sort(byImportance(adjacency))[0] ?? null;
}

function hierarchyLayout(names: string[], edges: CharacterRelationEdge[]): Record<string, GraphPosition> {
  const adjacency = buildAdjacency(names, edges);
  const importance = byImportance(adjacency);
  const root = [...names].sort(importance)[0];
  if (!root) return {};

  const levels = new Map<string, number>([[root, 0]]);
  const queue = [root];
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) continue;
    const nextLevel = (levels.get(current) ?? 0) + 1;
    const neighbors = [...(adjacency.get(current) ?? [])].sort(importance);
    for (const neighbor of neighbors) {
      if (levels.has(neighbor)) continue;
      levels.set(neighbor, nextLevel);
      queue.push(neighbor);
    }
  }

  const connectedDepth = Math.max(0, ...levels.values());
  for (const name of [...names].sort(importance)) {
    if (!levels.has(name)) levels.set(name, connectedDepth + 1);
  }

  const grouped = new Map<number, string[]>();
  for (const [name, level] of levels) {
    const group = grouped.get(level) ?? [];
    group.push(name);
    grouped.set(level, group);
  }

  const positions: Record<string, GraphPosition> = {};
  let y = 0;
  for (const level of [...grouped.keys()].sort((left, right) => left - right)) {
    const group = (grouped.get(level) ?? []).sort(importance);
    const columns = Math.min(MAX_HIERARCHY_COLUMNS, Math.max(1, group.length));
    const rows = Math.ceil(group.length / columns);
    group.forEach((name, index) => {
      const row = Math.floor(index / columns);
      const itemsInRow = Math.min(columns, group.length - row * columns);
      const column = index % columns;
      positions[name] = {
        x: (column - (itemsInRow - 1) / 2) * HORIZONTAL_GAP,
        y: y + row * VERTICAL_GAP,
      };
    });
    y += rows * VERTICAL_GAP;
  }
  return positions;
}

function radialLayout(names: string[], edges: CharacterRelationEdge[]): Record<string, GraphPosition> {
  const adjacency = buildAdjacency(names, edges);
  const importance = byImportance(adjacency);
  const ordered = [...names].sort(importance);
  const root = ordered.shift();
  if (!root) return {};

  const positions: Record<string, GraphPosition> = { [root]: { x: 0, y: 0 } };
  let offset = 0;
  let ring = 1;
  while (offset < ordered.length) {
    const capacity = 8 + (ring - 1) * 6;
    const members = ordered.slice(offset, offset + capacity);
    const radius = 280 + (ring - 1) * 190;
    members.forEach((name, index) => {
      const angle = -Math.PI / 2 + (index * Math.PI * 2) / members.length;
      positions[name] = {
        x: Math.round(Math.cos(angle) * radius),
        y: Math.round(Math.sin(angle) * radius),
      };
    });
    offset += members.length;
    ring += 1;
  }
  return positions;
}

export function layoutCharacterRelations(
  names: string[],
  edges: CharacterRelationEdge[],
  layout: CharacterRelationsLayout,
): Record<string, GraphPosition> {
  return layout === "radial" ? radialLayout(names, edges) : hierarchyLayout(names, edges);
}

export function connectionHandles(source: GraphPosition, target: GraphPosition) {
  const deltaX = target.x - source.x;
  const deltaY = target.y - source.y;
  if (Math.abs(deltaX) >= Math.abs(deltaY)) {
    return deltaX >= 0
      ? { sourceHandle: "source-right", targetHandle: "target-left" }
      : { sourceHandle: "source-left", targetHandle: "target-right" };
  }
  return deltaY >= 0
    ? { sourceHandle: "source-bottom", targetHandle: "target-top" }
    : { sourceHandle: "source-top", targetHandle: "target-bottom" };
}
