/**
 * Shared asset catalog boundary for canvas consumers.
 *
 * API response wrappers are handled here instead of in canvas components.
 * Callers provide the existing API methods as loaders, so this module remains
 * reusable when an endpoint response shape changes.
 */

export const CANVAS_ASSET_KINDS = [
  "character",
  "scene",
  "prop",
  "product",
  "media",
  "asset",
] as const;

export type CanvasAssetKind = (typeof CANVAS_ASSET_KINDS)[number];
export type CanvasAssetSource = "project" | "global";
export type CanvasAssetImportState = "imported" | "not-imported" | "unknown";

export interface CanvasAssetReference {
  source: CanvasAssetSource;
  kind: CanvasAssetKind;
  /** Project asset id for project assets, global asset id for global assets. */
  id: string;
  projectName?: string;
  /** Global assets must be imported before they can become project references. */
  requiresImport: boolean;
}

export interface CanvasGlobalAssetInfo {
  globalId: string;
  importState: CanvasAssetImportState;
  importedAssetId?: string;
  importedAssetKind?: CanvasAssetKind;
  canImport: boolean;
}

export interface CanvasAsset {
  /** Catalog identity; this is not used as a project asset reference. */
  id: string;
  sourceId: string;
  source: CanvasAssetSource;
  kind: CanvasAssetKind;
  name: string;
  /** Media and image assets use this URL for thumbnails/previews. */
  previewUrl: string | null;
  mimeType?: string;
  projectName?: string;
  reference: CanvasAssetReference;
  global?: CanvasGlobalAssetInfo;
}

export interface CanvasAssetLoadError {
  source: CanvasAssetSource;
  kind?: CanvasAssetKind;
  message: string;
}

export interface CanvasAssetCatalog {
  assets: CanvasAsset[];
  byKind: Record<CanvasAssetKind, CanvasAsset[]>;
  errors: CanvasAssetLoadError[];
}

type CanvasAssetLoaderResult = object | null | undefined;
export type CanvasAssetLoader = (projectName: string) => CanvasAssetLoaderResult | Promise<CanvasAssetLoaderResult>;

/** Adapters for the current project asset, media, and global asset endpoints. */
export interface CanvasAssetLoaders {
  characters: CanvasAssetLoader;
  scenes: CanvasAssetLoader;
  props: CanvasAssetLoader;
  products: CanvasAssetLoader;
  media: CanvasAssetLoader;
  globalAssets: CanvasAssetLoader;
}

export interface CanvasAssetNormalizeContext {
  source: CanvasAssetSource;
  projectName?: string;
  fallbackKind?: CanvasAssetKind;
}

interface NormalizedRecord {
  value: Record<string, unknown>;
  fallbackKind?: CanvasAssetKind;
}

const KIND_ALIASES: Record<string, CanvasAssetKind> = {
  character: "character",
  characters: "character",
  person: "character",
  scene: "scene",
  scenes: "scene",
  prop: "prop",
  props: "prop",
  product: "product",
  products: "product",
  media: "media",
  image: "media",
  video: "media",
  asset: "asset",
  assets: "asset",
};

const asRecord = (value: unknown): Record<string, unknown> | null => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
};

const firstString = (record: Record<string, unknown>, keys: string[]): string | undefined => {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return undefined;
};

const firstBoolean = (record: Record<string, unknown>, keys: string[]): boolean | undefined => {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "boolean") return value;
    if (value === "true" || value === "1") return true;
    if (value === "false" || value === "0") return false;
  }
  return undefined;
};

const kindFromValue = (value: unknown, fallback?: CanvasAssetKind): CanvasAssetKind => {
  if (typeof value === "string") return KIND_ALIASES[value.toLowerCase()] ?? fallback ?? "asset";
  return fallback ?? "asset";
};

const kindFromRecord = (record: Record<string, unknown>, fallback?: CanvasAssetKind): CanvasAssetKind =>
  kindFromValue(
    firstString(record, ["asset_type", "assetType", "type", "kind", "category", "media_type", "mediaType"]),
    fallback,
  );

const PROJECT_PREVIEW_FIELDS: Partial<Record<CanvasAssetKind, string[]>> = {
  // AI 生成的定型图是项目角色在画布中的首选预览；用户上传的参考图
  // 作为没有定型图时的可用回退。
  character: ["character_sheet", "characterSheet", "reference_image", "referenceImage"],
  scene: ["scene_sheet", "sceneSheet"],
  prop: ["prop_sheet", "propSheet"],
  product: ["product_sheet", "productSheet"],
};

const previewUrlFromRecord = (record: Record<string, unknown>, kind: CanvasAssetKind): string | null =>
  firstString(record, [
    ...(PROJECT_PREVIEW_FIELDS[kind] ?? []),
    "preview_url",
    "previewUrl",
    "thumbnail_url",
    "thumbnailUrl",
    "image_url",
    "imageUrl",
    "file_url",
    "fileUrl",
    "download_url",
    "downloadUrl",
    "image_path",
    "video_path",
    "file_path",
    "path",
    "url",
  ]) ?? null;

const importedAssetDetails = (record: Record<string, unknown>) => {
  const nested = asRecord(record.imported_asset) ?? asRecord(record.importedAsset) ?? {};
  const id =
    firstString(record, [
      "imported_asset_id",
      "importedAssetId",
      "project_asset_id",
      "projectAssetId",
      "local_asset_id",
    ]) ?? firstString(nested, ["id", "asset_id", "assetId"]);
  const kindValue =
    firstString(record, ["imported_asset_type", "importedAssetType"]) ??
    firstString(nested, ["asset_type", "assetType", "type", "kind"]);
  return { id, kind: kindValue ? kindFromValue(kindValue) : undefined };
};

const importStateFromRecord = (
  record: Record<string, unknown>,
  importedAssetId?: string,
): CanvasAssetImportState => {
  if (importedAssetId) return "imported";
  const explicitState = firstString(record, ["import_status", "importStatus", "import_state", "importState"]);
  if (explicitState) {
    const normalized = explicitState.toLowerCase();
    if (normalized === "imported" || normalized === "ready" || normalized === "complete") return "imported";
    if (normalized === "not-imported" || normalized === "not_imported" || normalized === "pending") {
      return "not-imported";
    }
  }
  const imported = firstBoolean(record, ["is_imported", "isImported", "imported"]);
  return imported === undefined ? "unknown" : imported ? "imported" : "not-imported";
};

const extractRecords = (payload: unknown, fallbackKind?: CanvasAssetKind): NormalizedRecord[] => {
  if (Array.isArray(payload)) return payload.flatMap((item) => extractRecords(item, fallbackKind));

  const record = asRecord(payload);
  if (!record) return [];

  for (const key of ["items", "results", "records", "assets", "data"]) {
    if (record[key] === undefined) continue;
    const nested = extractRecords(record[key], fallbackKind);
    if (nested.length) return nested;
  }

  const grouped = CANVAS_ASSET_KINDS.flatMap((kind) => {
    const group = record[kind] ?? record[kind + "s"];
    return group === undefined ? [] : extractRecords(group, kind);
  });
  if (grouped.length) return grouped;

  // Project assets are persisted as name-keyed buckets in project.json:
  // { "林冲": { description: "..." }, "鲁智深": { description: "..." } }.
  // Give each entry the stable name/id that the canvas reference contract needs.
  const hasIdentity =
    firstString(record, [
      "id",
      "uuid",
      "_id",
      "asset_id",
      "assetId",
      "media_id",
      "mediaId",
      "name",
      "title",
      "display_name",
      "displayName",
      "filename",
      "file_name",
    ]) !== undefined;
  const bucketEntries = Object.entries(record);
  if (!hasIdentity && bucketEntries.length > 0 && bucketEntries.every(([, value]) => asRecord(value) !== null)) {
    return bucketEntries.flatMap(([name, value]) => {
      const item = asRecord(value);
      if (!item) return [];
      const id = firstString(item, ["id", "uuid", "_id", "asset_id", "assetId"]) ?? name;
      const itemName = firstString(item, ["name", "title", "display_name", "displayName"]) ?? name;
      return [{ value: { ...item, id, name: itemName }, fallbackKind }];
    });
  }

  return [{ value: record, fallbackKind }];
};

/** Normalize one project or global endpoint record into the canvas contract. */
export function normalizeCanvasAsset(record: unknown, context: CanvasAssetNormalizeContext): CanvasAsset | null {
  const value = asRecord(record);
  if (!value) return null;

  const sourceId = firstString(value, [
    "id",
    "uuid",
    "_id",
    "asset_id",
    "assetId",
    "media_id",
    "mediaId",
    "character_id",
    "scene_id",
    "prop_id",
    "product_id",
  ]);
  const name = firstString(value, ["name", "title", "display_name", "displayName", "filename", "file_name"]);
  if (!sourceId || !name) return null;

  const kind = kindFromRecord(value, context.fallbackKind);
  const projectName = context.source === "project" ? context.projectName : undefined;
  const imported = context.source === "global" ? importedAssetDetails(value) : undefined;
  const importState = context.source === "global" ? importStateFromRecord(value, imported?.id) : undefined;
  const reference: CanvasAssetReference = {
    source: context.source,
    kind,
    id: sourceId,
    ...(projectName ? { projectName } : {}),
    requiresImport: context.source === "global" && importState !== "imported",
  };

  return {
    id: context.source + ":" + kind + ":" + sourceId,
    sourceId,
    source: context.source,
    kind,
    name,
    previewUrl: previewUrlFromRecord(value, kind),
    mimeType: firstString(value, ["mime_type", "mimeType", "content_type", "contentType"]),
    ...(projectName ? { projectName } : {}),
    reference,
    ...(context.source === "global"
      ? {
          global: {
            globalId: sourceId,
            importState: importState ?? "unknown",
            ...(imported?.id ? { importedAssetId: imported.id } : {}),
            ...(imported?.kind ? { importedAssetKind: imported.kind } : {}),
            canImport: importState !== "imported",
          },
        }
      : {}),
  };
}

const errorMessage = (reason: unknown): string => {
  if (reason instanceof Error && reason.message) return reason.message;
  if (typeof reason === "string") return reason;
  return "Asset catalog request failed";
};

const emptyByKind = (): Record<CanvasAssetKind, CanvasAsset[]> => ({
  character: [],
  scene: [],
  prop: [],
  product: [],
  media: [],
  asset: [],
});

/** Load every catalog source concurrently and retain successful results on partial failure. */
export async function loadCanvasAssets(
  loaders: CanvasAssetLoaders,
  projectName: string,
): Promise<CanvasAssetCatalog> {
  const jobs: Array<{
    source: CanvasAssetSource;
    kind?: CanvasAssetKind;
    load: CanvasAssetLoader;
  }> = [
    { source: "project", kind: "character", load: loaders.characters },
    { source: "project", kind: "scene", load: loaders.scenes },
    { source: "project", kind: "prop", load: loaders.props },
    { source: "project", kind: "product", load: loaders.products },
    { source: "project", kind: "media", load: loaders.media },
    { source: "global", load: loaders.globalAssets },
  ];

  const settled = await Promise.allSettled(jobs.map((job) => Promise.resolve().then(() => job.load(projectName))));
  const assets: CanvasAsset[] = [];
  const errors: CanvasAssetLoadError[] = [];

  settled.forEach((result, index) => {
    const job = jobs[index];
    if (result.status === "rejected") {
      errors.push({
        source: job.source,
        ...(job.kind ? { kind: job.kind } : {}),
        message: errorMessage(result.reason),
      });
      return;
    }

    for (const item of extractRecords(result.value, job.kind)) {
      const asset = normalizeCanvasAsset(item.value, {
        source: job.source,
        projectName,
        fallbackKind: item.fallbackKind,
      });
      if (asset) assets.push(asset);
    }
  });

  const byKind = emptyByKind();
  for (const asset of assets) byKind[asset.kind].push(asset);
  return { assets, byKind, errors };
}
