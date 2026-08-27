from pathlib import Path
from typing import cast

import pytest
from PIL import Image

import lib.character_avatar as character_avatar
from lib.asset_types import ASSET_SPECS
from lib.character_avatar import create_character_avatar


@pytest.mark.unit
def test_character_avatar_is_an_independent_asset_field():
    assert "character_avatar" in ASSET_SPECS["character"].extra_string_fields


@pytest.mark.unit
def test_create_character_avatar_prefers_detected_head_crop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "sheet.png"
    destination = tmp_path / "characters" / "hero_avatar.png"
    image = Image.new("RGB", (1200, 800), "blue")
    image.paste("red", (300, 100, 700, 700))
    image.save(source)
    monkeypatch.setattr(character_avatar, "_detect_face_crop_box", lambda _image: (300, 100, 700, 700))

    result = create_character_avatar(source, destination)

    assert result == destination
    with Image.open(destination) as avatar:
        assert avatar.size == (256, 256)
        assert avatar.format == "PNG"
        red, _, blue = cast(tuple[int, int, int], avatar.convert("RGB").getpixel((128, 128)))
        assert red > blue


@pytest.mark.unit
def test_create_character_avatar_falls_back_to_left_face_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "sheet.png"
    destination = tmp_path / "characters" / "hero_avatar.png"
    image = Image.new("RGB", (1200, 800), "blue")
    image.paste("red", (0, 0, 480, 800))
    image.save(source)
    monkeypatch.setattr(character_avatar, "_detect_face_crop_box", lambda _image: None)

    result = create_character_avatar(source, destination)

    assert result == destination
    assert destination.exists()
    with Image.open(destination) as avatar:
        assert avatar.size == (256, 256)
        assert avatar.format == "PNG"
        red, _, blue = cast(tuple[int, int, int], avatar.convert("RGB").getpixel((128, 128)))
        assert red > blue
