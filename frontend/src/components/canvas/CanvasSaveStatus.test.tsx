import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CanvasSaveStatus } from "./CanvasSaveStatus";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("CanvasSaveStatus", () => {
  it("announces a conflict and offers retry plus reload", () => {
    const retry = vi.fn(async () => true);
    render(<CanvasSaveStatus status="error" conflict onSave={async () => true} onRetry={retry} />);

    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByRole("button", { name: "canvas.saveStatus.retry" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "canvas.saveStatus.retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
