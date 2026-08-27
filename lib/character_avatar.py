"""Create standard square avatars from generated character design sheets."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

AVATAR_SIZE = 256
WIDE_SHEET_FACE_BOX = (0.06, 0.10, 0.36, 0.72)
WIDE_SHEET_DETECTION_WIDTH = 0.50


def _fallback_crop_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Return the legacy crop box when the sheet has no detectable face."""
    if image.width <= image.height * 1.25:
        return None
    left, top, right, bottom = WIDE_SHEET_FACE_BOX
    return (
        round(image.width * left),
        round(image.height * top),
        round(image.width * right),
        round(image.height * bottom),
    )


def _expand_face_box(image_size: tuple[int, int], face_box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Expand a detected face into a square crop containing the head and chin."""
    image_width, image_height = image_size
    face_left, face_top, face_width, face_height = face_box
    side = min(
        image_width,
        image_height,
        round(max(face_width * 2.1, face_height * 2.5)),
    )
    center_x = face_left + face_width / 2
    center_y = face_top + face_height * 0.72
    left = round(center_x - side / 2)
    top = round(center_y - side / 2)
    left = max(0, min(left, image_width - side))
    top = max(0, min(top, image_height - side))
    return left, top, left + side, top + side


def _detect_face_crop_box(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Detect the main face and return a square head crop, if one is found."""
    detection_image = image
    if image.width > image.height * 1.25:
        # Wide sheets contain turnarounds and references on the right. Restrict
        # detection to the left portrait panel so another face cannot win.
        detection_width = round(image.width * WIDE_SHEET_DETECTION_WIDTH)
        detection_image = image.crop((0, 0, detection_width, image.height))

    gray = cv2.cvtColor(np.asarray(detection_image), cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)
    min_face_side = max(24, min(detection_image.size) // 20)
    detections: list[tuple[int, int, int, int]] = []
    cascade_dir = Path(str(cv2.__file__)).resolve().parent / "data"
    for cascade_name in (
        "haarcascade_frontalface_default.xml",
        "haarcascade_frontalface_alt2.xml",
        "haarcascade_frontalface_alt.xml",
    ):
        cascade = cv2.CascadeClassifier(str(cascade_dir / cascade_name))
        if cascade.empty():
            continue
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=4,
            minSize=(min_face_side, min_face_side),
        )
        for face in faces:
            values = [int(value) for value in face]
            if len(values) == 4:
                detections.append((values[0], values[1], values[2], values[3]))

    if not detections:
        return None

    face_left, face_top, face_width, face_height = max(
        detections,
        key=lambda face: face[2] * face[3],
    )
    return _expand_face_box(
        image.size,
        (face_left, face_top, face_width, face_height),
    )


def create_character_avatar(source_path: str | Path, destination_path: str | Path) -> Path:
    """Crop the detected head into a square PNG avatar with a safe fallback."""
    source = Path(source_path)
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        detected_box = _detect_face_crop_box(image)
        fallback_box = _fallback_crop_box(image)
        crop_box = detected_box or fallback_box
        if crop_box is not None:
            image = image.crop(crop_box)
        avatar = ImageOps.fit(
            image,
            (AVATAR_SIZE, AVATAR_SIZE),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.42),
        )
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp:
                temp_path = Path(temp.name)
            avatar.save(temp_path, format="PNG", optimize=True)
            os.replace(temp_path, destination)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    return destination
