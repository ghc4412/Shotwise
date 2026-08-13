import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PresetIcon } from "@/components/agent/PresetIcon";

describe("PresetIcon", () => {
  it("renders lobehub icon when iconKey known", async () => {
    render(<PresetIcon iconKey="DeepSeek" size={24} />);
    const icon = await screen.findByTestId("lobehub-stub-icon");
    expect(icon).toBeInTheDocument();
    // The upstream SVG contains a <title>, which otherwise triggers an
    // unthemeable browser-native tooltip when hovering a provider chip.
    expect(icon.parentElement).toHaveAttribute("aria-hidden", "true");
    expect(icon.parentElement).toHaveClass("pointer-events-none");
  });

  it("falls back to monogram on unknown iconKey", async () => {
    render(<PresetIcon iconKey="NonExistentBrand" size={24} />);
    await waitFor(() =>
      expect(screen.getByTestId("preset-icon-monogram")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("preset-icon-monogram").textContent).toBe("N");
  });

  it("falls back to monogram for null iconKey", async () => {
    render(<PresetIcon iconKey={null} size={24} />);
    await waitFor(() =>
      expect(screen.getByTestId("preset-icon-monogram")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("preset-icon-monogram").textContent).toBe("?");
  });
});
