"""Sales overlays for affiliate product videos.

Three optional layers drawn on top of the final video:

* hook: a large headline in the upper third for the first seconds, to stop
  the scroll ("Khăn giấy 59k mà mềm thế này?");
* price badge: the sale price on an accent pill, with the original price
  struck through above it, shown for the rest of the video;
* call to action: a white pill near the lower third for the last seconds
  ("Bấm giỏ hàng để mua ngay").

Each layer is rendered once with Pillow into an RGBA image and turned into
a MoviePy ImageClip with a start time and duration, so it adds almost no
per-frame cost.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from loguru import logger
from moviepy import ImageClip
from PIL import Image, ImageDraw, ImageFont

from app.utils import utils

ACCENT = (238, 77, 45, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
DEFAULT_FONT = "BeVietnamPro-Bold.ttf"

HOOK_SECONDS = 3.0
CTA_SECONDS = 3.5


@dataclass(frozen=True)
class OverlayTimeline:
    hook: tuple[float, float] | None
    price: tuple[float, float] | None
    cta: tuple[float, float] | None


def hook_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def params_for_variant(params, index: int):
    """Return params for the ``index``-th (1-based) video of a batch.

    The hook field may hold one hook per line; video N uses line N (wrapping
    around), so one run produces versions with different openings. Params
    with a single hook, or none, are returned unchanged.
    """
    hooks = hook_lines(getattr(params, "hook_text", ""))
    if len(hooks) <= 1:
        return params
    hook = hooks[(max(1, int(index)) - 1) % len(hooks)]
    if hasattr(params, "model_copy"):
        return params.model_copy(update={"hook_text": hook})
    import copy

    variant = copy.copy(params)
    variant.hook_text = hook
    return variant


def has_overlays(params) -> bool:
    return any(
        str(getattr(params, name, "") or "").strip()
        for name in ("hook_text", "price_text", "cta_text")
    )


def plan_timeline(
    duration: float, *, hook: bool, price: bool, cta: bool
) -> OverlayTimeline:
    """Decide when each layer is visible: (start, end) in seconds."""
    duration = max(0.0, float(duration or 0.0))
    if duration <= 0:
        return OverlayTimeline(None, None, None)

    hook_end = min(HOOK_SECONDS, duration * 0.4) if hook else 0.0
    cta_start = max(hook_end, duration - CTA_SECONDS) if cta else duration

    # The price stays on screen until the end, including during the call to
    # action, so viewers who decide late still see it.
    price_span = None
    if price:
        start = hook_end if duration - hook_end >= 0.5 else 0.0
        price_span = (start, duration)

    return OverlayTimeline(
        hook=(0.0, hook_end) if hook and hook_end > 0 else None,
        price=price_span,
        cta=(cta_start, duration) if cta and duration - cta_start > 0 else None,
    )


def _font(size: int, font_path: str | None = None) -> ImageFont.FreeTypeFont:
    path = font_path or os.path.join(utils.font_dir(), DEFAULT_FONT)
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        logger.warning(f"sales overlay font not found, using default: {path}")
        return ImageFont.load_default(size=size)


def _wrap(text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if not line or font.getlength(candidate) <= max_width:
                line = candidate
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
    return lines or [text]


def render_hook(text: str, width: int, font_path: str | None = None) -> Image.Image:
    size = max(24, int(width * 0.075))
    font = _font(size, font_path)
    stroke = max(2, size // 12)
    lines = _wrap(text.strip(), font, int(width * 0.86))[:3]
    line_height = int(size * 1.25)
    height = line_height * len(lines) + stroke * 2 + 8
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        line_width = font.getlength(line)
        draw.text(
            ((width - line_width) / 2, stroke + index * line_height),
            line,
            font=font,
            fill=WHITE,
            stroke_width=stroke,
            stroke_fill=BLACK,
        )
    return image


def render_price(
    price: str, original: str, width: int, font_path: str | None = None
) -> Image.Image:
    price_size = max(28, int(width * 0.085))
    old_size = max(18, int(price_size * 0.5))
    price_font = _font(price_size, font_path)
    old_font = _font(old_size, font_path)
    pad_x = int(price_size * 0.55)
    pad_y = int(price_size * 0.3)

    price = price.strip()
    original = original.strip()
    price_w = price_font.getlength(price) if price else 0
    old_w = old_font.getlength(original) if original else 0
    inner_w = int(max(price_w, old_w))
    old_h = int(old_size * 1.3) if original else 0
    price_h = int(price_size * 1.2) if price else 0
    box_w = inner_w + pad_x * 2
    box_h = old_h + price_h + pad_y * 2

    image = Image.new("RGBA", (box_w + 8, box_h + 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # soft shadow, then the accent pill
    draw.rounded_rectangle(
        (6, 8, box_w + 6, box_h + 6), radius=box_h // 3, fill=(0, 0, 0, 90)
    )
    draw.rounded_rectangle(
        (0, 0, box_w, box_h), radius=box_h // 3, fill=ACCENT
    )
    y = pad_y
    if original:
        x = (box_w - old_w) / 2
        draw.text((x, y), original, font=old_font, fill=(255, 235, 228, 255))
        strike_y = y + old_size * 0.62
        draw.line(
            (x - 2, strike_y, x + old_w + 2, strike_y),
            fill=(255, 235, 228, 255),
            width=max(2, old_size // 10),
        )
        y += old_h
    if price:
        draw.text(((box_w - price_w) / 2, y), price, font=price_font, fill=WHITE)
    return image


def render_cta(text: str, width: int, font_path: str | None = None) -> Image.Image:
    size = max(22, int(width * 0.055))
    font = _font(size, font_path)
    lines = _wrap(text.strip(), font, int(width * 0.78))[:2]
    line_height = int(size * 1.3)
    text_w = int(max(font.getlength(line) for line in lines))
    pad_x = int(size * 0.9)
    pad_y = int(size * 0.55)
    box_w = text_w + pad_x * 2
    box_h = line_height * len(lines) + pad_y * 2
    image = Image.new("RGBA", (box_w + 8, box_h + 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (6, 8, box_w + 6, box_h + 6), radius=box_h // 2, fill=(0, 0, 0, 90)
    )
    draw.rounded_rectangle(
        (0, 0, box_w, box_h), radius=box_h // 2, fill=WHITE,
        outline=ACCENT, width=max(3, size // 9),
    )
    for index, line in enumerate(lines):
        draw.text(
            ((box_w - font.getlength(line)) / 2, pad_y + index * line_height),
            line,
            font=font,
            fill=ACCENT,
        )
    return image


def _clip(image: Image.Image, span, x, y):
    start, end = span
    return (
        ImageClip(np.asarray(image))
        .with_start(start)
        .with_duration(max(0.01, end - start))
        .with_position((int(x), int(y)))
    )


def build_overlay_clips(params, width: int, height: int, duration: float) -> list:
    """Return positioned ImageClips for the overlays requested in ``params``."""
    hooks = hook_lines(getattr(params, "hook_text", ""))
    hook = hooks[0] if hooks else ""
    price = str(getattr(params, "price_text", "") or "").strip()
    original = str(getattr(params, "original_price_text", "") or "").strip()
    cta = str(getattr(params, "cta_text", "") or "").strip()
    timeline = plan_timeline(duration, hook=bool(hook), price=bool(price), cta=bool(cta))

    clips = []
    if timeline.hook:
        image = render_hook(hook, width)
        clips.append(_clip(image, timeline.hook, 0, height * 0.12))
    if timeline.price:
        image = render_price(price, original, width)
        clips.append(
            _clip(image, timeline.price, (width - image.width) / 2, height * 0.1)
        )
    if timeline.cta:
        image = render_cta(cta, width)
        clips.append(
            _clip(image, timeline.cta, (width - image.width) / 2, height * 0.6)
        )
    return clips
