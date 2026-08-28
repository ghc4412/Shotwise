import { act, createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { CreativeBoardWorkspace } from "./CreativeBoardWorkspace";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";

const translate = vi.hoisted(() => (key: string) => key);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));

vi.mock("@/api", () => ({
  API: {
    listCreativeBoards: vi.fn(),
    getCreativeBoard: vi.fn(),
    getProject: vi.fn(),
  },
  getCreativeBoardConflictRevision: vi.fn(),
  isCreativeBoardRevisionConflict: vi.fn(),
}));

const loadCanvasAssets = vi.hoisted(() => vi.fn());
vi.mock("./canvas-assets", () => ({
  loadCanvasAssets,
}));

vi.mock("./CanvasSaveStatus", () => ({
  CanvasSaveStatus: () => null,
}));

vi.mock("./ConflictModal", () => ({
  ConflictModal: () => null,
}));

vi.mock("./CreativeBoardActions", () => ({
  CreativeBoardActions: () => null,
}));

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function makeBoard(id: string, itemId: string, name: string) {
  return {
    id,
    project_id: "demo",
    name,
    viewport: { x: 28, y: 28, zoom: 1 },
    items: [
      {
        id: itemId,
        item_type: "document",
        resource_type: "document",
        resource_id: itemId,
        position: { x: 10, y: 10 },
        size: { width: 100, height: 80 },
      },
    ],
    edges: [],
    revision: 1,
  };
}

describe("CreativeBoardWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    useProjectsStore.setState({
      currentProjectName: "demo",
      currentProjectData: {
        title: "Demo",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
    });
    vi.mocked(API.listCreativeBoards).mockResolvedValue({
      items: [
        { id: "board-a", name: "Canvas A" },
        { id: "board-b", name: "Canvas B" },
      ],
    } as never);
    vi.mocked(API.getProject).mockResolvedValue({ project: {}, asset_fingerprints: {} } as never);
    vi.mocked(API.getCreativeBoard).mockResolvedValue(makeBoard("board-a", "item-a", "Canvas A") as never);
    loadCanvasAssets.mockResolvedValue({ assets: [], byKind: {}, errors: [] });
  });

  it("filters assets by Personal, Agent, and Global categories", async () => {
    loadCanvasAssets.mockResolvedValue({
      assets: [
        { id: "media-1", name: "Personal media", kind: "media", source: "media", resourceType: "media_asset", imagePath: null, reference: { source: "media", kind: "media", id: "media-1", projectName: "demo", requiresImport: false } },
        { id: "character-1", name: "Agent character", kind: "character", source: "project", resourceType: "character", imagePath: null, reference: { source: "project", kind: "character", id: "character-1", projectName: "demo", requiresImport: false } },
        { id: "scene-1", name: "Agent scene", kind: "scene", source: "project", resourceType: "scene", imagePath: null, reference: { source: "project", kind: "scene", id: "scene-1", projectName: "demo", requiresImport: false } },
        { id: "prop-1", name: "Agent prop", kind: "prop", source: "project", resourceType: "prop", imagePath: null, reference: { source: "project", kind: "prop", id: "prop-1", projectName: "demo", requiresImport: false } },
        { id: "global-1", name: "Global asset", kind: "character", source: "global", resourceType: "character", imagePath: null, reference: { source: "global", kind: "character", id: "global-1", requiresImport: true } },
      ],
      byKind: {},
      errors: [],
    });

    render(
      <Router hook={memoryLocation({ path: "/creative-board" }).hook}>
        <Route path="/creative-board">
          <CreativeBoardWorkspace projectName="demo" />
        </Route>
      </Router>,
    );

    await screen.findByRole("button", { name: "creative_board_assets_label" });
    act(() => screen.getByRole("button", { name: "creative_board_assets_label" }).click());
    expect(await screen.findByText("Personal media")).toBeInTheDocument();
    expect(screen.queryByText("Agent character")).not.toBeInTheDocument();

    act(() => screen.getByRole("tab", { name: "creative_board_asset_category_agent" }).click());
    expect(await screen.findByText("Agent character")).toBeInTheDocument();
    expect(screen.getByText("Agent scene")).toBeInTheDocument();
    expect(screen.getByText("Agent prop")).toBeInTheDocument();
    expect(screen.queryByText("Personal media")).not.toBeInTheDocument();
    expect(screen.queryByText("Global asset")).not.toBeInTheDocument();

    act(() => screen.getByRole("tab", { name: "creative_board_asset_category_global" }).click());
    expect(await screen.findByText("Global asset")).toBeInTheDocument();
    expect(screen.queryByText("Agent character")).not.toBeInTheDocument();
  });

  it("moves a canvas image from both its picture and empty card area", async () => {
    const board = makeBoard("board-a", "item-a", "Canvas A");
    board.items[0] = {
      ...board.items[0],
      item_type: "character",
      resource_type: "character",
      resource_id: "character-1",
    };
    vi.mocked(API.getCreativeBoard).mockResolvedValue(board as never);
    loadCanvasAssets.mockResolvedValue({
      assets: [{
        id: "project:character:character-1",
        sourceId: "character-1",
        name: "Hero",
        kind: "character",
        source: "project",
        previewUrl: "/hero-avatar.png",
        sidebarPreviewUrl: "/hero-avatar.png",
        canvasPreviewUrl: "/hero-design.png",
        reference: { source: "project", kind: "character", id: "character-1", projectName: "demo", requiresImport: false },
      }],
      byKind: {},
      errors: [],
    });

    render(
      <Router hook={memoryLocation({ path: "/creative-board" }).hook}>
        <Route path="/creative-board">
          <CreativeBoardWorkspace projectName="demo" />
        </Route>
      </Router>,
    );

    const node = await screen.findByTestId("creative-board-item-item-a");
    const image = await screen.findByRole("img", { name: "Hero" });
    const canvas = screen.getByTestId("creative-board-canvas");
    expect(image).toHaveAttribute("draggable", "false");
    expect(node).toHaveStyle({ left: "10px", top: "10px" });

    act(() => {
      const pointerDown = createEvent.pointerDown(image, { button: 0, clientX: 100, clientY: 100, pointerId: 7 });
      fireEvent(image, pointerDown);
      expect(pointerDown.defaultPrevented).toBe(true);
      fireEvent.pointerMove(canvas, { clientX: 101, clientY: 101, pointerId: 7 });
    });

    expect(node).toHaveStyle({ left: "10px", top: "10px" });

    act(() => {
      fireEvent.pointerMove(canvas, { clientX: 140, clientY: 130, pointerId: 7 });
    });

    expect(node).toHaveStyle({ left: "50px", top: "40px" });
    expect(node).toHaveClass("cursor-grabbing", "select-none");

    act(() => {
      fireEvent.pointerUp(canvas, { clientX: 140, clientY: 130, pointerId: 7 });
    });

    expect(node).not.toHaveClass("cursor-grabbing", "select-none");

    act(() => {
      fireEvent.pointerUp(canvas, { clientX: 140, clientY: 130, pointerId: 7 });
      fireEvent.pointerDown(node, { button: 0, clientX: 140, clientY: 130, pointerId: 8 });
      fireEvent.pointerMove(canvas, { clientX: 0, clientY: 0, pointerId: 8 });
    });

    expect(node).toHaveStyle({ left: "-90px", top: "-90px" });

    act(() => {
      fireEvent.pointerUp(canvas, { clientX: 0, clientY: 0, pointerId: 8 });
    });
  });

  it("switches boards without duplicating the existing query string", async () => {
    const location = memoryLocation({ path: "/creative-board?project=demo&board=board-a&episode=2", record: true });

    render(
      <Router hook={location.hook}>
        <Route path="/creative-board">
          <CreativeBoardWorkspace projectName="demo" />
        </Route>
      </Router>,
    );

    await screen.findByText("Canvas A");
    act(() => screen.getByRole("button", { name: "creative_board_switch" }).click());
    act(() => screen.getByRole("menuitem", { name: /Canvas B/ }).click());

    expect(location.history.at(-1)).toBe("/creative-board?project=demo&board=board-b&episode=2");
  });


  it("keeps the newly selected board when an older board request resolves later", async () => {
    const boardA = deferred<ReturnType<typeof makeBoard>>();
    const boardB = deferred<ReturnType<typeof makeBoard>>();
    vi.mocked(API.getCreativeBoard).mockImplementation((boardId: string) =>
      (boardId === "board-a" ? boardA.promise : boardB.promise) as never,
    );
    const location = memoryLocation({ path: "/creative-board?project=demo&board=board-a" });

    render(
      <Router hook={location.hook}>
        <Route path="/creative-board">
          <CreativeBoardWorkspace projectName="demo" />
        </Route>
      </Router>,
    );

    await waitFor(() => expect(API.getCreativeBoard).toHaveBeenCalledWith("board-a"));

    act(() => {
      location.navigate("/creative-board?project=demo&board=board-b");
    });
    await waitFor(() => expect(API.getCreativeBoard).toHaveBeenCalledWith("board-b"));

    await act(async () => {
      boardB.resolve(makeBoard("board-b", "item-b", "Canvas B"));
    });
    expect((await screen.findAllByText("item-b")).length).toBeGreaterThan(0);

    await act(async () => {
      boardA.resolve(makeBoard("board-a", "item-a", "Canvas A"));
    });
    await waitFor(() => expect(screen.getAllByText("item-b").length).toBeGreaterThan(0));
    expect(screen.queryByText("item-a")).not.toBeInTheDocument();
  });
});
