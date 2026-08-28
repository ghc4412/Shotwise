import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import { AssetSidebar } from "@/components/layout/AssetSidebar";

vi.mock("@/api", () => ({
  API: {
    listFiles: vi.fn(),
    getCostEstimate: vi.fn(),
  },
}));

function renderSidebar(path = "/app/projects/demo/characters") {
  const location = memoryLocation({ path, record: true });
  const view = render(
    <Router hook={location.hook}>
      <Route path="/app/projects/:projectName" nest>
        <AssetSidebar />
      </Route>
    </Router>,
  );
  return { ...view, location };
}

describe("AssetSidebar", () => {
  beforeEach(() => {
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    useProjectsStore.setState({
      currentProjectName: "demo",
      currentProjectData: {
        title: "Demo",
        content_mode: "narration",
        style: "Anime",
        episodes: [{ episode: 1, title: "第一集", script_file: "scripts/episode_1.json" }],
        characters: {},
        scenes: {},
        props: {},
      },
    });
    vi.mocked(API.listFiles).mockResolvedValue({ files: { source: [] } } as never);
    vi.mocked(API.getCostEstimate).mockResolvedValue({ episodes: [] } as never);
  });

  it("切换到创作画布时保留项目路由并继续显示侧栏", () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const { location } = renderSidebar();

    fireEvent.click(screen.getByRole("button", { name: "创作画布" }));

    expect(location.history).toEqual([
      "/app/projects/demo/characters",
      "/app/projects/demo/creative-board",
    ]);
    expect(openSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "创作画布" })).toBeInTheDocument();
  });
});
