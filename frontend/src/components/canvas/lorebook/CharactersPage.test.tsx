import { fireEvent, render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import type { Character } from "@/types";
import { CharactersPage } from "./CharactersPage";

vi.mock("@/hooks/useScrollTarget", () => ({ useScrollTarget: vi.fn() }));

vi.mock("./CharacterCard", () => ({
  CharacterCard: ({ name }: { name: string }) => <div data-testid={`character-${name}`} />,
}));

vi.mock("./GalleryEmptyState", () => ({ GalleryEmptyState: () => null }));
vi.mock("@/components/assets/AssetFormModal", () => ({ AssetFormModal: () => null }));
vi.mock("@/components/assets/AssetPickerModal", () => ({ AssetPickerModal: () => null }));
vi.mock("./CharacterRelationsModal", () => ({ CharacterRelationsModal: () => null }));

vi.mock("./GalleryToolbar", () => ({
  GalleryToolbar: ({
    onGenerateDesigns,
    generateDesignsDisabled,
    pendingDesignCount,
  }: {
    onGenerateDesigns?: (mode: "missing" | "all") => void;
    generateDesignsDisabled?: boolean;
    pendingDesignCount?: number;
  }) => (
    <div>
      <button
        type="button"
        onClick={() => onGenerateDesigns?.("missing")}
        disabled={generateDesignsDisabled || pendingDesignCount === 0}
      >
        generate-missing
      </button>
      <button type="button" onClick={() => onGenerateDesigns?.("all")} disabled={generateDesignsDisabled}>
        generate-all
      </button>
      <span data-testid="pending-count">{pendingDesignCount}</span>
    </div>
  ),
}));

function renderPage(characters: Record<string, Character>, onGenerateCharacter = vi.fn()) {
  render(
    <I18nextProvider i18n={i18n}>
      <CharactersPage
        projectName="demo"
        characters={characters}
        onSaveCharacter={vi.fn()}
        onGenerateCharacter={onGenerateCharacter}
        onAddCharacter={vi.fn()}
      />
    </I18nextProvider>,
  );
}

describe("CharactersPage batch design generation", () => {
  it("submits only characters without a design sheet in missing mode", () => {
    const onGenerateCharacter = vi.fn();

    renderPage(
      {
        Completed: { description: "done", character_sheet: "characters/Completed.png" },
        EmptySheet: { description: "empty", character_sheet: "" },
        MissingSheet: { description: "missing" },
      },
      onGenerateCharacter,
    );

    fireEvent.click(screen.getByRole("button", { name: "generate-missing" }));

    expect(onGenerateCharacter.mock.calls).toEqual([["EmptySheet"], ["MissingSheet"]]);
  });

  it("submits every character in full regeneration mode", () => {
    const onGenerateCharacter = vi.fn();

    renderPage(
      {
        Completed: { description: "done", character_sheet: "characters/Completed.png" },
        EmptySheet: { description: "empty", character_sheet: "" },
        MissingSheet: { description: "missing" },
      },
      onGenerateCharacter,
    );

    fireEvent.click(screen.getByRole("button", { name: "generate-all" }));

    expect(onGenerateCharacter.mock.calls).toEqual([["Completed"], ["EmptySheet"], ["MissingSheet"]]);
  });

  it("keeps full regeneration available when every character already has a design sheet", () => {
    renderPage({
      First: { description: "first", character_sheet: "characters/First.png" },
      Second: { description: "second", character_sheet: "characters/Second.png" },
    });

    expect(screen.getByTestId("pending-count")).toHaveTextContent("0");
    expect(screen.getByRole("button", { name: "generate-missing" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "generate-all" })).not.toBeDisabled();
  });
});