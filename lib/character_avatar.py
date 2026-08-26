"""Create standard square avatars from generated character design sheets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

AVATAR_SIZE = 256


def create_character_avatar(source_path: str | Path, destination_path: str | Path) -> Path:
    """Crop the main portrait area of a design sheet into a square PNG avatar."""
    source = Path(source_path)
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        # Generated sheets place the primary portrait on the left and variants to
        # its right. Narrow images are already portrait-like, so keep the full frame.
        if image.width > image.height * 1.25:
            image = image.crop((0, 0, max(image.height, image.width // 3), image.height))
        avatar = ImageOps.fit(
            image,
            (AVATAR_SIZE, AVATAR_SIZE),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.42),
        )
        avatar.save(destination, format="PNG", optimize=True)

    return destination
