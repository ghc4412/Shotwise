"""
Image utility helpers.

Used by WebUI upload endpoints to validate, compress, and normalize uploaded images.
"""

from __future__ import annotations

import re
from base64 import b64decode, b64encode
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

_COMPRESS_THRESHOLD = 2 * 1024 * 1024  # 2 MB
_MAX_LONG_EDGE = 2048
# 解码后的像素总数上限（8192×8192）。字节上限拦不住这一层：低熵 PNG 能把上亿像素压进
# 30MB 以内；PIL 自带的 MAX_IMAGE_PIXELS 也只在超过其两倍时才抛 DecompressionBombError，
# 介于一倍与两倍之间（约 8900 万至 1.78 亿像素）仅告警放行，而一份 RGBA 缓冲即数百 MB。
# 宫格联合图最高档位为 4K 见方（约 1700 万像素），此处留出数倍余量后显式拒绝。
MAX_UPLOAD_PIXELS = 8192 * 8192
_JPEG_QUALITY = 85
# sentinel：意为「不向 PIL 传 subsampling」。PIL 的 subsampling=-1 仅在 JPEG→JPEG 时表示
# “保持源色度”，对 PNG/其它源解码后再编码不合法，故默认用本 sentinel 拦掉，保证缺省行为不变。
_SUBSAMPLING_KEEP = -1

# Chat attachments are persisted in the session event log as well as sent to the SDK.
# Keep both paths bounded after one server-side normalization pass.
CHAT_IMAGE_MAX_BYTES = 8 * 1024 * 1024
CHAT_IMAGES_MAX_BYTES = 24 * 1024 * 1024
CHAT_IMAGES_MAX_BASE64_CHARS = 32 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:(?P<media_type>[^;,]+);base64,(?P<data>.*)$", re.DOTALL)
_CHAT_MEDIA_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class ChatImageError(ValueError):
    """A user-correctable chat attachment validation failure."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


@dataclass(frozen=True)
class NormalizedChatImage:
    data: str
    media_type: str


# EXIF Orientation tag（ImageOps.exif_transpose 读取的字段）
_EXIF_ORIENTATION = 0x0112


class ImagePixelLimitError(ValueError):
    """图片解码后的像素总数超过 ``MAX_UPLOAD_PIXELS``。

    继承 ValueError：调用方不单独处理时，与其它无效图片一样收口为 400。
    """


def _ensure_pixel_budget(size: tuple[int, int]) -> None:
    """在解码分配像素缓冲之前拦掉超大图。"""
    if size[0] * size[1] > MAX_UPLOAD_PIXELS:
        raise ImagePixelLimitError(f"image has {size[0]}x{size[1]} pixels, over the {MAX_UPLOAD_PIXELS} limit")


def _open_oriented(content: bytes, *, target_modes: tuple[str, ...], fallback_mode: str) -> Image.Image:
    """解码 + EXIF 方向矫正 + 收敛到目标颜色模式。返回与源解码器解耦的图像对象。"""
    with Image.open(BytesIO(content)) as src:
        img = ImageOps.exif_transpose(src)
        if img.mode not in target_modes:
            img = img.convert(fallback_mode)
        return img.copy() if img is src else img


def _fit_long_edge(img: Image.Image, max_long_edge: int) -> Image.Image:
    """长边超限时等比缩放；极端宽高比下短边钳到至少 1 像素，避免 resize(…, 0) 报错。"""
    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= max_long_edge:
        return img
    scale = max_long_edge / long_edge
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)


def convert_image_bytes_to_png(content: bytes) -> bytes:
    """
    Convert arbitrary image bytes (jpg/png/webp/...) into PNG bytes.

    Raises:
        ValueError: if the input bytes are not a valid image.
    """
    try:
        with _open_oriented(content, target_modes=("RGB", "RGBA"), fallback_mode="RGBA") as img:
            out = BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    except Exception as e:
        raise ValueError("Invalid image") from e


def normalize_storyboard_upload(content: bytes, *, max_long_edge: int | None = _MAX_LONG_EDGE) -> bytes:
    """
    将上传的分镜图归一化为 PNG 字节：exif 矫正方向、长边超限时等比缩放。

    分镜图 canonical 路径固定为 .png（resource_paths / VersionManager / restore
    均按此扩展名工作），因此无论输入格式一律转 PNG。
    已合规的 PNG（模式/方向/尺寸均达标）原样返回，不做无谓的解码重编码。

    ``max_long_edge=None`` 表示不缩放，只做格式/方向归一化——宫格联合图等
    分辨率即信息量的上传走此档，避免 4K 联合图被静默降采样后切格失真。

    Raises:
        ImagePixelLimitError: if the decoded pixel count exceeds MAX_UPLOAD_PIXELS.
        ValueError: if the input bytes are not a valid image.
    """
    try:
        with Image.open(BytesIO(content)) as probe:
            # 尺寸来自文件头，此时尚未分配像素缓冲
            _ensure_pixel_budget(probe.size)
            if (
                probe.format == "PNG"
                and probe.mode in ("RGB", "RGBA")
                and (max_long_edge is None or max(probe.size) <= max_long_edge)
                and probe.getexif().get(_EXIF_ORIENTATION, 1) == 1
            ):
                return content

        with _open_oriented(content, target_modes=("RGB", "RGBA"), fallback_mode="RGBA") as img:
            if max_long_edge is not None:
                img = _fit_long_edge(img, max_long_edge)
            out = BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    except ImagePixelLimitError:
        # 图片本身可解析，只是过大——保留该类型，让调用方给出可操作的提示
        raise
    except Exception as e:
        raise ValueError("Invalid image") from e


def validate_image_bytes(content: bytes) -> None:
    """Validate that *content* is a decodable image.

    Raises:
        ValueError: if the input bytes are not a valid image.
    """
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
    except Exception as e:
        raise ValueError("Invalid image") from e


def compress_image_bytes(
    content: bytes,
    *,
    max_long_edge: int = _MAX_LONG_EDGE,
    quality: int = _JPEG_QUALITY,
    subsampling: int = _SUBSAMPLING_KEEP,
) -> bytes:
    """
    将任意图片字节压缩为 JPEG：等比缩放到长边不超过 max_long_edge，
    quality 控制 JPEG 压缩质量。

    subsampling 控制 JPEG 色度抽样（0=4:4:4 视觉无损，2=4:2:0 默认）；缺省为
    _SUBSAMPLING_KEEP，此时完全不向 PIL 传该参数，保持 PIL 默认（与历史行为一致）。

    Raises:
        ValueError: if the input bytes are not a valid image.
    """
    try:
        with _open_oriented(content, target_modes=("RGB",), fallback_mode="RGB") as img:
            img = _fit_long_edge(img, max_long_edge)
            save_kwargs: dict[str, object] = {"format": "JPEG", "quality": quality, "optimize": True}
            if subsampling >= 0:
                save_kwargs["subsampling"] = subsampling
            out = BytesIO()
            img.save(out, **save_kwargs)  # pyright: ignore[reportArgumentType]
            return out.getvalue()
    except Exception as e:
        raise ValueError("Invalid image") from e


def normalize_uploaded_image(
    content: bytes,
    original_suffix: str,
    *,
    compress_threshold: int = _COMPRESS_THRESHOLD,
) -> tuple[bytes, str]:
    """Validate (and optionally compress) an uploaded image.

    If *content* exceeds *compress_threshold* bytes the image is compressed to
    JPEG and ``".jpg"`` is returned as the suffix.  Otherwise the original
    bytes are returned after validation, together with *original_suffix* (or
    ``".png"`` when empty).

    Returns:
        ``(processed_content, final_suffix)``

    Raises:
        ValueError: if the input bytes are not a valid image.
    """
    if len(content) > compress_threshold:
        return compress_image_bytes(content), ".jpg"
    validate_image_bytes(content)
    return content, original_suffix or ".png"


def normalize_chat_images(images: Sequence[object]) -> list[NormalizedChatImage]:
    """Decode, validate, compress, and bound chat image attachments.

    The frontend may send either bare base64 or a data URL. The returned JPEG
    payload is the only representation callers should pass to both the model
    SDK and the session event log.
    """
    normalized: list[NormalizedChatImage] = []
    total = 0
    total_base64_chars = 0
    for image in images:
        data = getattr(image, "data", None)
        media_type = getattr(image, "media_type", None)
        if not isinstance(data, str) or not isinstance(media_type, str):
            raise ChatImageError("assistant_image_invalid")
        match = _DATA_URL_RE.fullmatch(data)
        if match:
            data = match.group("data")
            media_type = match.group("media_type")
        media_type = media_type.strip().lower()
        expected_format = _CHAT_MEDIA_TYPES.get(media_type)
        if expected_format is None:
            raise ChatImageError("assistant_image_type_unsupported")
        if len(data) > CHAT_IMAGE_MAX_BYTES * 2:
            raise ChatImageError("assistant_image_too_large")
        total_base64_chars += len(data)
        if total_base64_chars > CHAT_IMAGES_MAX_BASE64_CHARS:
            raise ChatImageError("assistant_images_too_large")
        try:
            raw = b64decode(data, validate=True)
        except Exception as exc:
            raise ChatImageError("assistant_image_invalid") from exc
        try:
            with Image.open(BytesIO(raw)) as probe:
                _ensure_pixel_budget(probe.size)
                if probe.format != expected_format:
                    raise ChatImageError("assistant_image_invalid")
            compressed = compress_image_bytes(raw)
        except ImagePixelLimitError as exc:
            raise ChatImageError("assistant_image_pixels_too_large") from exc
        except Exception as exc:
            raise ChatImageError("assistant_image_invalid") from exc
        if len(compressed) > CHAT_IMAGE_MAX_BYTES:
            raise ChatImageError("assistant_image_too_large")
        total += len(compressed)
        if total > CHAT_IMAGES_MAX_BYTES:
            raise ChatImageError("assistant_images_too_large")
        normalized.append(NormalizedChatImage(data=b64encode(compressed).decode("ascii"), media_type="image/jpeg"))
    return normalized
