import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CHAT_IMAGE_MAX_INPUT_BYTES,
  CHAT_IMAGE_MAX_LONG_EDGE,
  CHAT_IMAGE_MAX_BYTES,
  ChatImageValidationError,
  prepareChatImages,
} from "./chat-image";

function makeFile(type = "image/png", size = 16): File {
  return new File([new Uint8Array(size)], "attachment.png", { type });
}

function installImageMocks(width = 800, height = 600, dataUrl = "data:image/jpeg;base64,AAAA") {
  const close = vi.fn();
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn().mockResolvedValue({ width, height, close }),
  );
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage,
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue(dataUrl);
  return { close, drawImage };
}

async function expectImageError(files: File[], key: string, existingDataUrls: string[] = []) {
  const error = await prepareChatImages(files, existingDataUrls).catch((value: unknown) => value);
  expect(error).toBeInstanceOf(ChatImageValidationError);
  expect((error as ChatImageValidationError).key).toBe(key);
}

describe("prepareChatImages", () => {
  beforeEach(() => {
    installImageMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("validates and converts supported images to bounded JPEG data URLs", async () => {
    const { drawImage } = installImageMocks(CHAT_IMAGE_MAX_LONG_EDGE * 2, CHAT_IMAGE_MAX_LONG_EDGE / 2);

    const [image] = await prepareChatImages([makeFile()]);

    expect(image.mimeType).toBe("image/jpeg");
    expect(image.dataUrl).toBe("data:image/jpeg;base64,AAAA");
    expect(drawImage).toHaveBeenCalledWith(
      expect.anything(),
      0,
      0,
      CHAT_IMAGE_MAX_LONG_EDGE / 2,
      CHAT_IMAGE_MAX_LONG_EDGE / 8,
    );
  });

  it("rejects unsupported formats before decoding", async () => {
    await expectImageError([makeFile("image/gif")], "assistant_image_type_unsupported");
    expect(createImageBitmap).not.toHaveBeenCalled();
  });

  it("rejects oversized source files", async () => {
    await expectImageError(
      [makeFile("image/png", CHAT_IMAGE_MAX_INPUT_BYTES + 1)],
      "assistant_image_too_large",
    );
  });

  it("rejects images over the pixel budget", async () => {
    installImageMocks(CHAT_IMAGE_MAX_LONG_EDGE * 2, CHAT_IMAGE_MAX_LONG_EDGE * 2);
    await expectImageError([makeFile()], "assistant_image_pixels_too_large");
  });

  it("rejects a normalized image over the per-image byte limit", async () => {
    installImageMocks(800, 600, `data:image/jpeg;base64,${"A".repeat(CHAT_IMAGE_MAX_BYTES * 2 + 4)}`);
    await expectImageError([makeFile()], "assistant_image_too_large");
  });

  it("never prepares more than five attachments", async () => {
    const images = await prepareChatImages(Array.from({ length: 6 }, () => makeFile()));
    expect(images).toHaveLength(5);
  });
});
