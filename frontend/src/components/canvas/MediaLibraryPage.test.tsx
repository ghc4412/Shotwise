import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MediaLibraryPage } from "./MediaLibraryPage";
import { API } from "@/api";

const locationState = vi.hoisted(() => ({ value: "", navigate: vi.fn() }));
const translate = vi.hoisted(() => (key: string) => key);
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("wouter", () => ({ useLocation: () => [locationState.value, locationState.navigate] }));
vi.mock("@/api", () => ({ API: {
  listMediaAssets: vi.fn(), listCreationResources: vi.fn(), getMediaAssetContentUrl: vi.fn(() => "/media"),
  uploadMediaAsset: vi.fn(), getMediaAsset: vi.fn(), bindMediaAsset: vi.fn(), archiveMediaAsset: vi.fn(),
} }));

const asset = { id: "asset-1", kind: "image", original_name: "hero.png", physical_path: "assets/hero.png", size_bytes: 10, origin: "upload", archived: false, bindings: [] };

describe("MediaLibraryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    locationState.value = "";
    locationState.navigate.mockReset();
    vi.mocked(API.listMediaAssets).mockResolvedValue({ items: [asset] });
    vi.mocked(API.listCreationResources).mockResolvedValue({ items: [{ id: "character-1", type: "character", label: "Ava" }] });
    vi.mocked(API.getMediaAsset).mockResolvedValue({ ...asset, bindings: [{ id: "binding-1", binding_kind: "character", target_id: "character-1", purpose: "reference" }] });
  });

  it("uses project resources for semantic binding", async () => {
    render(<MediaLibraryPage projectName="demo" />);
    await screen.findByText("hero.png");
    fireEvent.click(screen.getByText("hero.png"));
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[1], { target: { value: "character" } });
    fireEvent.change(selects[2], { target: { value: "character-1" } });
    fireEvent.click(screen.getByRole("button", { name: "media_library_bind" }));
    await waitFor(() => expect(API.bindMediaAsset).toHaveBeenCalledWith("demo", "asset-1", { binding_kind: "character", target_id: "character-1", purpose: "reference" }));
  });

  it("sends semantic binding filters to the media index", async () => {
    render(<MediaLibraryPage projectName="demo" />);
    await screen.findByText("hero.png");
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "character" } });
    await waitFor(() => expect(API.listMediaAssets).toHaveBeenLastCalledWith("demo", expect.objectContaining({ binding_kind: "character" })));
  });

  it("opens the asset detail panel from a media deep link", async () => {
    locationState.value = "/media?asset=asset-1";

    render(<MediaLibraryPage projectName="demo" />);

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveTextContent("hero.png");
  });

  it("navigates to the creative board within the current project", async () => {
    render(<MediaLibraryPage projectName="demo" />);

    await screen.findByText("hero.png");
    fireEvent.click(screen.getByRole("button", { name: "media_library_open_board" }));

    expect(locationState.navigate).toHaveBeenCalledWith("/creative-board");
  });
});
