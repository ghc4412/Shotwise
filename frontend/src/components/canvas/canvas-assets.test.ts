import { describe, expect, it } from "vitest";

import { loadCanvasAssets, type CanvasAssetLoaders } from "./canvas-assets";

const makeLoaders = (): CanvasAssetLoaders => ({
  characters: async () => [{ id: "character-1", name: "Hero", image_url: "/hero.png" }],
  scenes: async () => [{ id: "scene-1", name: "Street" }],
  props: async () => [{ id: "prop-1", name: "Lantern" }],
  products: async () => [{ id: "product-1", name: "Phone" }],
  media: async () => [{ id: "media-1", name: "Shot", preview_url: "/shot.jpg", mime_type: "image/jpeg" }],
  globalAssets: async () => [
    {
      id: "global-character-1",
      asset_type: "character",
      name: "Global Hero",
      image_url: "/global-hero.png",
      is_imported: false,
    },
  ],
});

describe("canvas asset catalog", () => {
  it("keeps project references usable and global references import-safe", async () => {
    const catalog = await loadCanvasAssets(makeLoaders(), "demo-project");
    const projectCharacter = catalog.assets.find((asset) => asset.source === "project" && asset.kind === "character");
    const globalCharacter = catalog.assets.find((asset) => asset.source === "global");
    const media = catalog.byKind.media[0];

    expect(projectCharacter?.reference).toEqual({
      source: "project",
      kind: "character",
      id: "character-1",
      projectName: "demo-project",
      requiresImport: false,
    });
    expect(globalCharacter?.global).toMatchObject({
      globalId: "global-character-1",
      importState: "not-imported",
      canImport: true,
    });
    expect(globalCharacter?.reference).toMatchObject({
      source: "global",
      id: "global-character-1",
      requiresImport: true,
    });
    expect(globalCharacter?.reference.projectName).toBeUndefined();
    expect(media.previewUrl).toBe("/shot.jpg");
    expect(media.mimeType).toBe("image/jpeg");
  });

  it("returns available assets when one endpoint fails", async () => {
    const loaders = makeLoaders();
    loaders.scenes = async () => {
      throw new Error("scenes unavailable");
    };

    const catalog = await loadCanvasAssets(loaders, "demo-project");

    expect(catalog.assets.some((asset) => asset.kind === "character")).toBe(true);
    expect(catalog.assets.some((asset) => asset.kind === "media")).toBe(true);
    expect(catalog.errors).toEqual([
      { source: "project", kind: "scene", message: "scenes unavailable" },
    ]);
  });

  it("normalizes project assets stored in name-keyed buckets", async () => {
    const loaders = makeLoaders();
    loaders.characters = async () => ({
      林冲: { description: "禁军教头" },
      鲁智深: { description: "花和尚" },
    });
    loaders.scenes = async () => ({ 京城街道: { description: "黄昏街道" } });
    loaders.props = async () => ({ 长剑: { description: "黑色长剑" } });

    const catalog = await loadCanvasAssets(loaders, "demo-project");

    expect(catalog.assets.filter((asset) => asset.source === "project" && asset.kind === "character").map((asset) => asset.name)).toEqual([
      "林冲",
      "鲁智深",
    ]);
    expect(catalog.assets.find((asset) => asset.name === "林冲")?.reference.id).toBe("林冲");
    expect(catalog.assets.find((asset) => asset.name === "京城街道")?.reference.id).toBe("京城街道");
    expect(catalog.assets.find((asset) => asset.name === "长剑")?.reference.id).toBe("长剑");
  });

  it("uses character avatars in sidebars and design sheets on the canvas", async () => {
    const loaders = makeLoaders();
    loaders.characters = async () => ({
      林冲: {
        character_avatar: "characters/林冲_avatar.png",
        character_sheet: "characters/林冲.png",
        reference_image: "characters/refs/林冲.png",
        description: "禁军教头",
      },
      鲁智深: { character_sheet: "characters/鲁智深.png", description: "花和尚" },
    });

    const catalog = await loadCanvasAssets(loaders, "demo-project");
    const hero = catalog.assets.find((asset) => asset.name === "林冲");
    const monk = catalog.assets.find((asset) => asset.name === "鲁智深");

    expect(hero?.previewUrl).toBe("characters/林冲_avatar.png");
    expect(hero?.sidebarPreviewUrl).toBe("characters/林冲_avatar.png");
    expect(hero?.canvasPreviewUrl).toBe("characters/林冲.png");
    expect(monk?.sidebarPreviewUrl).toBe("characters/鲁智深.png");
    expect(monk?.canvasPreviewUrl).toBe("characters/鲁智深.png");
  });

  it("uses generated project sheets as previews, with character reference-image fallback", async () => {
    const loaders = makeLoaders();
    loaders.characters = async () => ({
      林冲: { character_sheet: "characters/林冲.png", description: "禁军教头" },
      鲁智深: { reference_image: "characters/refs/鲁智深.png", description: "花和尚" },
    });
    loaders.scenes = async () => ({
      京城街道: { scene_sheet: "scenes/京城街道.png" },
    });
    loaders.props = async () => ({
      长剑: { prop_sheet: "props/长剑.png" },
    });

    const catalog = await loadCanvasAssets(loaders, "demo-project");

    expect(catalog.assets.find((asset) => asset.name === "林冲")?.previewUrl).toBe("characters/林冲.png");
    expect(catalog.assets.find((asset) => asset.name === "鲁智深")?.previewUrl).toBe("characters/refs/鲁智深.png");
    expect(catalog.assets.find((asset) => asset.name === "京城街道")?.previewUrl).toBe("scenes/京城街道.png");
    expect(catalog.assets.find((asset) => asset.name === "长剑")?.previewUrl).toBe("props/长剑.png");
  });
});
