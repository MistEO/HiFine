import struct

import pillow_heif
import pytest
from PIL import ExifTags, Image, ImageCms, PngImagePlugin

from hifine.imaging import ImageLoadError, list_images, load_image, make_thumbnail


@pytest.mark.parametrize("extension", ["jpg", "png", "bmp", "gif", "webp", "tiff", "ico", "avif"])
def test_common_formats(tmp_path, extension):
    path = tmp_path / f"相册.{extension}"
    image = Image.new("RGB", (48, 48), (60, 150, 20))
    image.save(path, **({"sizes": [image.size]} if extension == "ico" else {}))
    decoded = load_image(path)
    assert decoded.image.size == (48, 48)
    assert decoded.image.getpixel((12, 12))[1] > 100
    assert decoded.metadata["file_size"] == path.stat().st_size
    assert make_thumbnail(path, 16).size == (16, 16)


def test_hif_primary_image_is_not_always_first(tmp_path):
    path = tmp_path / "合影.HIF"
    first = Image.new("RGB", (48, 32), "red")
    primary = Image.new("RGB", (32, 48), "blue")
    first.save(path, format="HEIF", save_all=True, append_images=[primary], primary_index=1)
    result = load_image(path)
    assert result.metadata["format"] == "HEIF"
    assert result.image.size == primary.size
    assert result.image.getpixel((16, 16))[2] > 230
    thumb = make_thumbnail(path, 24)
    assert thumb.size == (16, 24)
    assert thumb.mode == "RGBA"
    assert thumb.getpixel((8, 8))[2] > 230


def test_hif_ten_bit_422(tmp_path):
    path = tmp_path / "camera.HIF"
    pixels = struct.pack("<HHH", 41000, 20500, 10000) * (48 * 32)
    image = pillow_heif.from_bytes("RGB;16", (48, 32), pixels)
    image.save(path, chroma="422", quality=95)
    result = load_image(path)
    assert result.metadata["bit_depth"] == 10
    assert result.image.mode == "RGB"
    assert result.image.getpixel((16, 16)) == pytest.approx((160, 80, 39), abs=5)
    assert make_thumbnail(path, 16).getpixel((8, 8))[:3] == pytest.approx((160, 80, 39), abs=5)


@pytest.mark.parametrize("extension", ["jpg", "hif"])
def test_orientation_and_exif(tmp_path, extension):
    path = tmp_path / f"portrait.{extension}"
    T = ExifTags.Base
    exif = Image.Exif()
    exif[T.Make] = "Example"
    exif[T.Model] = "Camera 1"
    exif[T.Orientation] = 6
    exif[ExifTags.IFD.Exif] = {
        T.LensModel: "50 mm F1.4", T.DateTimeOriginal: "2025:04:01 11:22:33",
        T.ISOSpeedRatings: 400, T.FocalLength: 50, T.FNumber: 2.8, T.ExposureTime: 1 / 125,
    }
    image = Image.new("RGB", (48, 32), "red")
    image.paste("blue", (0, 0, 24, 32))
    image.save(path, format="JPEG" if extension == "jpg" else "HEIF", exif=exif.tobytes())
    result = load_image(path)
    assert result.image.size == (32, 48)
    assert (result.metadata["width"], result.metadata["height"]) == (32, 48)
    assert result.image.getpixel((4, 4))[2] > 220
    assert result.image.getpixel((4, 43))[0] > 220
    assert result.metadata["camera_model"] == "Camera 1"
    assert result.metadata["lens"] == "50 mm F1.4"
    assert result.metadata["aperture"] == "f/2.8"
    assert result.metadata["exposure"] == "1/125 s"
    assert result.metadata["iso"] == "400"
    assert result.metadata["taken_at"] == "2025-04-01 11:22:33"
    assert make_thumbnail(path, 24).size == (16, 24)


def test_transparency_and_embedded_profile(tmp_path):
    path = tmp_path / "alpha.png"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGBA", (2, 3), (26, 187, 55, 88)).save(path, icc_profile=profile)
    assert load_image(path).image.getpixel((0, 0)) == (26, 187, 55, 88)
    thumb = make_thumbnail(path, 100)
    assert thumb.size == (2, 3)
    assert thumb.getpixel((0, 0)) == (26, 187, 55, 88)


@pytest.mark.parametrize(("mode", "channels"), [("RGB", 3), ("RGBA", 4), ("P", 4)])
def test_prefetch_budget_skips_pixel_decode(tmp_path, monkeypatch, mode, channels):
    path = tmp_path / "budget.png"
    image = Image.new(mode, (8, 4))
    if mode == "P":
        image.info["transparency"] = 0
    image.save(path)
    pixel_bytes = image.width * image.height * channels
    with monkeypatch.context() as patch:
        def unexpected_load(*args, **kwargs):
            pytest.fail("over-budget prefetch decoded image pixels")

        patch.setattr(PngImagePlugin.PngImageFile, "load", unexpected_load)
        with pytest.raises(ImageLoadError, match="预读缓存"):
            load_image(path, max_pixel_bytes=pixel_bytes - 1)
    assert load_image(path, max_pixel_bytes=pixel_bytes).image.size == image.size
    assert load_image(path).image.size == image.size


def test_grayscale_16bit(tmp_path):
    path = tmp_path / "16-bit.png"
    Image.new("I;16", (4, 2), 32768).save(path)
    assert load_image(path).image.getpixel((0, 0))[0] == pytest.approx(128, abs=1)


def test_navigation_includes_broken_files(tmp_path):
    names = ["相片_02.jpg", "相片_10.HIF", "相片_1.png"]
    for name in names + ["notes.txt"]:
        (tmp_path / name).touch()
    (tmp_path / "subfolder.JPG").mkdir()
    assert [p.name for p in list_images(tmp_path)] == [names[2], names[0], names[1]]
    for reader in [load_image, lambda p: make_thumbnail(p, 64)]:
        with pytest.raises(ImageLoadError):
            reader(tmp_path / names[1])


@pytest.mark.parametrize("decode", [load_image, lambda path: make_thumbnail(path, 64)])
def test_image_can_be_moved_during_decode(tmp_path, monkeypatch, decode):
    photo = tmp_path / "照片.png"
    moved = tmp_path / "moved.png"
    Image.new("RGB", (8, 8)).save(photo)
    open_image = Image.open

    def move_while_open(*args, **kwargs):
        image = open_image(*args, **kwargs)
        photo.rename(moved)
        moved.rename(photo)
        return image

    monkeypatch.setattr(Image, "open", move_while_open)
    decode(photo)
