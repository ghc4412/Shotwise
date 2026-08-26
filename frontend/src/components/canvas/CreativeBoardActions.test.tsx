import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { CreativeBoardActions } from "./CreativeBoardActions";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string, values?: Record<string, unknown>) => values ? key + ":" + Object.values(values).join(",") : key }) }));
vi.mock("@/api", () => ({ API: { listCreativeBoardVersions: vi.fn(), getCreativeBoardVersion: vi.fn(), createCreativeBoardVersion: vi.fn(), restoreCreativeBoardVersion: vi.fn(), duplicateCreativeBoard: vi.fn() } }));

const snapshot = { boardId: "board-1", name: "Board", viewport: { x: 0, y: 0, zoom: 1 }, items: [{ id: "item-1", item_type: "media", resource_type: "media", resource_id: "asset-1", position: { x: 10, y: 10 }, size: { width: 100, height: 80 } }], edges: [], revision: 4 };
const props = () => ({ boardId: "board-1", projectName: "demo", snapshot, saveStatus: "saved" as const, ensureSaved: vi.fn().mockResolvedValue(true), onRestored: vi.fn().mockResolvedValue(undefined), onCopied: vi.fn(), onError: vi.fn() });

beforeEach(() => { vi.clearAllMocks(); vi.mocked(API.listCreativeBoardVersions).mockResolvedValue({ items: [{ id: "v1", board_id: "board-1", version_number: 2, version_name: "Rough cut", created_at: "2026-08-25T10:00:00Z" }] }); vi.mocked(API.getCreativeBoardVersion).mockResolvedValue({ id: "v1", board_id: "board-1", version_number: 2, version_name: "Rough cut", created_at: "2026-08-25T10:00:00Z", snapshot: { board_id: "board-1", name: "Board", viewport: { x: 0, y: 0, zoom: 1 }, items: snapshot.items, edges: snapshot.edges, revision: 2 } }); vi.mocked(API.createCreativeBoardVersion).mockResolvedValue({ id: "v2", board_id: "board-1", version_number: 3, version_name: "Named", created_at: "2026-08-25T10:00:00Z" }); vi.mocked(API.restoreCreativeBoardVersion).mockResolvedValue({ board: {}, revision: 5 }); vi.mocked(API.duplicateCreativeBoard).mockResolvedValue({ id: "board-2" }); });

describe("CreativeBoardActions", () => {
  it("renders versions, saves a named version, and restores after confirmation", async () => {
    const testProps = props();
    render(<CreativeBoardActions {...testProps} />);
    fireEvent.click(screen.getByRole("button", { name: "creative_board_actions" }));
    fireEvent.change(screen.getByLabelText("creative_board_version_name"), { target: { value: "Named" } });
    fireEvent.click(screen.getByRole("button", { name: /creative_board_save_version/ }));
    await waitFor(() => expect(API.createCreativeBoardVersion).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /creative_board_version_list/ }));
    expect(await screen.findByText(/Rough cut/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Rough cut/ }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /creative_board_version_restore$/ }));
    await waitFor(() => expect(API.restoreCreativeBoardVersion).toHaveBeenCalledWith("board-1", "v1", 4));
    expect(testProps.onRestored).toHaveBeenCalled();
  });

  it("copies the canvas and exports JSON without bypassing the save gate", async () => {
    const testProps = props();
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<CreativeBoardActions {...testProps} />);
    fireEvent.click(screen.getByRole("button", { name: "creative_board_actions" }));
    fireEvent.change(screen.getByLabelText("creative_board_copy_name"), { target: { value: "Copy" } });
    fireEvent.click(screen.getByRole("button", { name: /creative_board_copy$/ }));
    await waitFor(() => expect(testProps.onCopied).toHaveBeenCalledWith("board-2"));
    fireEvent.click(screen.getByRole("button", { name: /creative_board_export_json/ }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(click).toHaveBeenCalled();
    createObjectURL.mockRestore();
    click.mockRestore();
  });

  it("blocks actions and exposes retry when the automatic save fails", async () => {
    const testProps = props();
    testProps.ensureSaved.mockResolvedValue(false);
    render(<CreativeBoardActions {...testProps} />);
    fireEvent.click(screen.getByRole("button", { name: "creative_board_actions" }));
    fireEvent.change(screen.getByLabelText("creative_board_version_name"), { target: { value: "Blocked" } });
    fireEvent.click(screen.getByRole("button", { name: /creative_board_save_version/ }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(API.createCreativeBoardVersion).not.toHaveBeenCalled();
    expect(testProps.onError).toHaveBeenCalled();
  });
});
