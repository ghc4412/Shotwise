import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n";
import { GalleryToolbar } from "./GalleryToolbar";

describe("GalleryToolbar relationship entry", () => {
  it("renders the relationship graph button before the library action", () => {
    const onViewRelations = vi.fn();
    render(
      <I18nextProvider i18n={i18n}>
        <GalleryToolbar title="Characters" count={2} onViewRelations={onViewRelations} onPickFromLibrary={vi.fn()} />
      </I18nextProvider>,
    );

    const buttons = screen.getAllByRole("button");
    expect(buttons[0]?.textContent).toMatch(/查看关系图谱|View Relationship Graph|Xem sơ đồ quan hệ/i);
    fireEvent.click(buttons[0]!);
    expect(onViewRelations).toHaveBeenCalledTimes(1);
  });
});
