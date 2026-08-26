from pathlib import Path

import pytest
from PIL import Image

from lib.asset_types import ASSET_SPECS
from lib.character_avatar import create_character_avatar


@pytest.mark.unit
def test_character_avatar_is_an_independent_asset_field():
    assert "character_avatar" in ASSET_SPECS["character"].extra_string_fields


@pytest.mark.unit
def test_create_character_avatar_crops_wide_sheet_to_standard_png(tmp_path: Path):
    source = tmp_path / "sheet.png"
    destination = tmp_path / "characters" / "hero_avatar.png"
    image = Image.new("RGB", (1200, 800), "red")
    image.paste("blue", (800, 0, 1200, 800))
    image.save(source)

    result = create_character_avatar(source, destination)

    assert result == destination
    assert destination.exists()
    with Image.open(destination) as avatar:
        assert avatar.size == (256, 256)
        assert avatar.format == "PNG"
        assert avatar.getpixel((128, 128))[0] > avatar.getpixel((128, 128))[2]
