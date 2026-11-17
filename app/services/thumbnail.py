"""Cover image (thumbnail) for a finished product video.

Shopee Video, TikTok and Reels show a cover in the feed and on the profile
grid. A frame with a big product title and the price gets more taps than a
random frame, so after rendering we save ``anh-bia.jpg`` next to the video.
"""

from __future__ import annotations

import os

import numpy as np
from loguru import logger
from PIL import Image, ImageDraw

from app.services import sales_overlay

COVER_FILENAME = "anh-bia.jpg"
_TITLE_MAX_CHARS = 60


def cover_title(params) -> str:
    hooks = sales_overlay.hook_lines(getattr(params, "hook_text", ""))
    title = hooks[0] if hooks else str(getattr(params, "video_subject", "") or "")
    title = " ".join(title.split())
    if len(title) > _TITLE_MAX_CHARS:
        title = title[: _TITLE_MAX_CHARS - 1].rsplit(" ", 1)[0] + "…"
    return title


def _bottom_shade(image: Image.Image, start: float = 0.45) -> Image.Image:
    """Darken the lower part so white text stays readable on any frame."""
    width, height = image.size
    top = int(height * start)
    alpha = np.linspace(0, 200, height - top, dtype=np.float32)
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[top:, :] = alpha[:, None].astype(np.uint8)
    shade = Image.new("RGBA", image.size, (0, 0, 0, 255))
    shade.putalpha(Image.fromarray(mask))
    return Image.alpha_composite(image.convert("RGBA"), shade)


def compose_cover(frame: np.ndarray, title: str, price: str = "", original_price: str = "") -> Image.Image:
    image = _bottom_shade(Image.fromarray(np.asarray(frame).astype("uint8")).convert("RGB"))
    width, height = image.size
    draw = ImageDraw.Draw(image)
    y = height * 0.93
    if price:
        badge = sales_overlay.render_price(price, original_price, width)
        y -= badge.height
        image.alpha_composite(badge, (int((width - badge.width) / 2), int(y)))
        y -= height * 0.02
    if title:
        size = max(28, int(width * 0.09))
        font = sales_overlay._font(size)
        lines = sales_overlay._wrap(title, font, int(width * 0.88))[:3]
        line_height = int(size * 1.2)
        y -= line_height * len(lines)
        stroke = max(2, size // 10)
        for index, line in enumerate(lines):
            draw.text(
                ((width - font.getlength(line)) / 2, y + index * line_height),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 255),
            )
    return image.convert("RGB")


def save_cover(params, video_path: str, task_dir: str) -> str:
    """Save the cover next to the task's videos; return its path or "".

    ``video_path`` should be the combined footage before subtitles and sales
    overlays are added, so the cover does not show them twice.
    """
    from moviepy import VideoFileClip

    clip = None
    try:
        clip = VideoFileClip(video_path, audio=False)
        duration = float(clip.duration or 0)
        # A frame a little into the video, usually the product itself.
        moment = min(max(0.0, duration - 0.1), duration * 0.35)
        frame = clip.get_frame(moment)
        cover = compose_cover(
            frame,
            cover_title(params),
            str(getattr(params, "price_text", "") or "").strip(),
            str(getattr(params, "original_price_text", "") or "").strip(),
        )
        path = os.path.join(task_dir, COVER_FILENAME)
        cover.save(path, "JPEG", quality=90)
        return path
    except Exception as exc:  # the video itself is already finished
        logger.warning(f"failed to build cover image: {type(exc).__name__}: {exc}")
        return ""
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass
