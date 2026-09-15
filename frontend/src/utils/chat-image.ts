export const CHAT_IMAGE_MAX_BYTES = 8 * 1024 * 1024;
export const CHAT_IMAGES_MAX_BYTES = 24 * 1024 * 1024;
export const CHAT_IMAGES_MAX_BASE64_CHARS = 32 * 1024 * 1024;
export const CHAT_IMAGE_MAX_INPUT_BYTES = 32 * 1024 * 1024;
export const CHAT_IMAGE_MAX_LONG_EDGE = 4096;
export const CHAT_IMAGE_MAX_PIXELS = CHAT_IMAGE_MAX_LONG_EDGE * CHAT_IMAGE_MAX_LONG_EDGE;
export const CHAT_IMAGE_OUTPUT_LONG_EDGE = 2048;

export const CHAT_IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
type ChatImageMimeType = (typeof CHAT_IMAGE_MIME_TYPES)[number];

export type ChatImageErrorKey =
  | "assistant_image_type_unsupported"
  | "assistant_image_invalid"
  | "assistant_image_pixels_too_large"
  | "assistant_image_too_large"
  | "assistant_images_too_large"
  | "assistant_image_compression_failed";

export type PreparedChatImage = {
  dataUrl: string;
  mimeType: ChatImageMimeType;
};

export class ChatImageValidationError extends Error {
  readonly key: ChatImageErrorKey;

  constructor(key: ChatImageErrorKey) {
    super(key);
    this.name = "ChatImageValidationError";
    this.key = key;
  }
}

function supportedMimeType(type: string): type is ChatImageMimeType {
  return (CHAT_IMAGE_MIME_TYPES as readonly string[]).includes(type.toLowerCase());
}

function base64ByteLength(dataUrl: string): number {
  const payload = dataUrl.slice(dataUrl.indexOf(",") + 1);
  return Math.floor((payload.length * 3) / 4);
}

function loadImage(file: File): Promise<{ image: CanvasImageSource; width: number; height: number; close?: () => void }> {
  if (typeof createImageBitmap === "function") {
    return createImageBitmap(file).then((bitmap) => ({
      image: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      close: () => bitmap.close(),
    }));
  }

  return new Promise((resolve, reject) => {
    const image = new Image();
    const objectUrl = URL.createObjectURL(file);
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve({ image, width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new ChatImageValidationError("assistant_image_invalid"));
    };
    image.src = objectUrl;
  });
}

function outputSize(width: number, height: number): [number, number] {
  const longEdge = Math.max(width, height);
  if (longEdge <= CHAT_IMAGE_OUTPUT_LONG_EDGE) return [width, height];
  const scale = CHAT_IMAGE_OUTPUT_LONG_EDGE / longEdge;
  return [Math.max(1, Math.round(width * scale)), Math.max(1, Math.round(height * scale))];
}

async function prepareImage(file: File): Promise<PreparedChatImage> {
  const type = file.type.toLowerCase();
  if (!supportedMimeType(type)) throw new ChatImageValidationError("assistant_image_type_unsupported");
  if (file.size > CHAT_IMAGE_MAX_INPUT_BYTES) {
    throw new ChatImageValidationError("assistant_image_too_large");
  }

  let loaded: Awaited<ReturnType<typeof loadImage>> | undefined;
  try {
    loaded = await loadImage(file);
    if (!loaded.width || !loaded.height || loaded.width * loaded.height > CHAT_IMAGE_MAX_PIXELS) {
      throw new ChatImageValidationError("assistant_image_pixels_too_large");
    }

    const [width, height] = outputSize(loaded.width, loaded.height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) throw new ChatImageValidationError("assistant_image_compression_failed");
    context.drawImage(loaded.image, 0, 0, width, height);

    let dataUrl: string;
    try {
      dataUrl = canvas.toDataURL("image/jpeg", 0.85);
    } catch {
      throw new ChatImageValidationError("assistant_image_compression_failed");
    }
    if (!dataUrl.startsWith("data:image/jpeg;base64,")) {
      throw new ChatImageValidationError("assistant_image_compression_failed");
    }
    if (base64ByteLength(dataUrl) > CHAT_IMAGE_MAX_BYTES) {
      throw new ChatImageValidationError("assistant_image_too_large");
    }
    return { dataUrl, mimeType: "image/jpeg" };
  } catch (error) {
    if (error instanceof ChatImageValidationError) throw error;
    throw new ChatImageValidationError("assistant_image_invalid");
  } finally {
    loaded?.close?.();
  }
}

export async function prepareChatImages(files: File[], existingDataUrls: string[] = []): Promise<PreparedChatImage[]> {
  const result: PreparedChatImage[] = [];
  let totalBytes = existingDataUrls.reduce((sum, dataUrl) => sum + base64ByteLength(dataUrl), 0);
  let totalBase64Chars = existingDataUrls.reduce(
    (sum, dataUrl) => sum + dataUrl.slice(dataUrl.indexOf(",") + 1).length,
    0,
  );
  for (const file of files) {
    if (existingDataUrls.length + result.length >= 5) break;
    const image = await prepareImage(file);
    const payloadLength = image.dataUrl.length - image.dataUrl.indexOf(",") - 1;
    totalBytes += base64ByteLength(image.dataUrl);
    totalBase64Chars += payloadLength;
    if (totalBytes > CHAT_IMAGES_MAX_BYTES || totalBase64Chars > CHAT_IMAGES_MAX_BASE64_CHARS) {
      throw new ChatImageValidationError("assistant_images_too_large");
    }
    result.push(image);
  }
  return result;
}
