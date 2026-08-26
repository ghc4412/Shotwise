import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CreativeBoardPage } from "./CreativeBoardPage";
import { API } from "@/api";

const workspaceProps = vi.hoisted(() => ({ projectNames: [] as string[] }));
vi.mock("./CreativeBoardWorkspace", () => ({
  CreativeBoardWorkspace: ({ projectName }: { projectName: string }) => {
    workspaceProps.projectNames.push(projectName);
    return <div data-testid="creative-board-workspace">{projectName}</div>;
  },
}));
vi.mock("@/api", () => ({ API: {
  listCreativeBoards: vi.fn(), getCreativeBoard: vi.fn(), createCreativeBoard: vi.fn(), listMediaAssets: vi.fn(),
  addCreativeBoardItem: vi.fn(), updateCreativeBoard: vi.fn(), updateCreativeBoardItem: vi.fn(), deleteCreativeBoardItem: vi.fn(),
  addCreativeBoardEdge: vi.fn(), deleteCreativeBoardEdge: vi.fn(),
} }));

describe("CreativeBoardPage", () => {
  it("renders the shared workspace and forwards projectName", () => {
    render(<CreativeBoardPage projectName="demo" />);

    expect(screen.getByTestId("creative-board-workspace")).toHaveTextContent("demo");
    expect(workspaceProps.projectNames).toEqual(["demo"]);
  });

  it("does not load media or boards itself", () => {
    render(<CreativeBoardPage projectName="demo" />);

    expect(API.listCreativeBoards).not.toHaveBeenCalled();
    expect(API.listMediaAssets).not.toHaveBeenCalled();
  });
});
