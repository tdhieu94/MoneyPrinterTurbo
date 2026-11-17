"""Product photo helpers: background removal and before/after scenes.

* ``remove_background`` cuts the product out of a cluttered photo with the
  optional ``rembg`` package (free, runs offline on CPU) and places it on a
  clean light backdrop with a soft shadow. Without rembg the photo is used
  unchanged and a warning is logged.
* ``compose_before_after`` puts two photos side by side with "TRƯỚC" and
  "SAU" labels, to use as one scene of the video.
"""

from __future__ import annotations

import hashlib
import io
import os

from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.services import sales_overlay

_rembg_session = None
_rembg_missing_logged = False
_CANVAS_PADDING = 0.08


def rembg_available() -> bool:
    try:
        import rembg  # noqa: F401
    except Exception:
        return False
    return True


def _cutout(image: Image.Image) -> Image.Image:
    """Return the product as RGBA with a transparent background."""
    global _rembg_session
    import rembg

    if _rembg_session is None:
        _rembg_session = rembg.new_session("u2net")
    result = rembg.remove(image, session=_rembg_session)
    if not isinstance(result, Image.Image):
        result = Image.open(io.BytesIO(result))
    return result.convert("RGBA")


def place_on_clean_background(cutout: Image.Image) -> Image.Image:
    """Center a transparent cutout on a light gradient with a soft shadow."""
    box = cutout.getbbox()
    if box:
        cutout = cutout.crop(box)
    width, height = cutout.size
    pad = int(max(width, height) * _CANVAS_PADDING)
    canvas_w, canvas_h = width + pad * 2, height + pad * 2
    top, bottom = (252, 250, 247), (236, 232, 226)
    background = Image.new("RGB", (1, 2))
    background.putpixel((0, 0), top)
    background.putpixel((0, 1), bottom)
    background = background.resize((canvas_w, canvas_h), Image.BILINEAR).convert("RGBA")

    shadow_alpha = cutout.getchannel("A").point(lambda a: int(a * 0.35))
    shadow = Image.new("RGBA", cutout.size, (0, 0, 0, 255))
    shadow.putalpha(shadow_alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, pad // 4)))
    offset = max(2, pad // 5)
    background.alpha_composite(shadow, (pad + offset, pad + offset))
    background.alpha_composite(cutout, (pad, pad))
    return background.convert("RGB")


def remove_background(image_path: str) -> str:
    """Return the path of a clean-background PNG, or ``image_path`` on failure."""
    global _rembg_missing_logged
    if not rembg_available():
        if not _rembg_missing_logged:
            logger.warning(
                "background removal skipped: install it with "
                "'pip install rembg[cpu]' in the app environment"
            )
            _rembg_missing_logged = True
        return image_path
    try:
        with open(image_path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()[:24]
        output = os.path.join(os.path.dirname(image_path), f"{digest}.nobg.png")
        if os.path.isfile(output):
            return output
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        cleaned = place_on_clean_background(_cutout(image))
        temp = output + ".tmp.png"
        cleaned.save(temp, "PNG")
        os.replace(temp, output)
        return output
    except Exception as exc:
        logger.warning(f"background removal failed for {image_path}: {exc}")
        return image_path


def _label(draw, text, font, center_x, y, fill):
    text_w = font.getlength(text)
    pad_x, pad_y = font.size * 0.6, font.size * 0.3
    draw.rounded_rectangle(
        (center_x - text_w / 2 - pad_x, y, center_x + text_w / 2 + pad_x, y + font.size * 1.3 + pad_y * 2),
        radius=int(font.size * 0.4),
        fill=fill,
    )
    draw.text((center_x - text_w / 2, y + pad_y), text, font=font, fill=(255, 255, 255))


def compose_before_after(before_path: str, after_path: str, output_path: str,
                         size: tuple[int, int] = (1080, 1920)) -> str:
    """Two photos side by side (stacked on a vertical canvas) with labels."""
    width, height = size
    vertical = height > width
    canvas = Image.new("RGB", size, (24, 24, 24))
    halves = []
    for path in (before_path, after_path):
        with Image.open(path) as source:
            halves.append(ImageOps.exif_transpose(source).convert("RGB"))
    if vertical:
        cell = (width, height // 2)
        positions = [(0, 0), (0, height // 2)]
    else:
        cell = (width // 2, height)
        positions = [(0, 0), (width // 2, 0)]
    for image, position in zip(halves, positions):
        canvas.paste(ImageOps.fit(image, cell, Image.LANCZOS), position)
    draw = ImageDraw.Draw(canvas)
    line = max(4, width // 160)
    if vertical:
        draw.rectangle((0, height // 2 - line // 2, width, height // 2 + line // 2), fill=(255, 255, 255))
    else:
        draw.rectangle((width // 2 - line // 2, 0, width // 2 + line // 2, height), fill=(255, 255, 255))
    font = sales_overlay._font(max(24, int(width * 0.06)))
    for (x, y), text, color in zip(positions, ("TRƯỚC", "SAU"), ((90, 90, 90), sales_overlay.ACCENT[:3])):
        _label(draw, text, font, x + cell[0] / 2, y + cell[1] * 0.06, color)
    canvas.save(output_path, "PNG")
    return output_path
