"""Ready-to-paste post text for affiliate videos.

After a video is rendered, build one block of text the seller can paste into
Shopee Video, Facebook Reels or TikTok: an AI caption, the price, the call to
action with the affiliate link, and hashtags. The text is saved as
``dang-bai.txt`` in the task folder and returned to the WebUI.
"""

from __future__ import annotations

import os
import re

from loguru import logger

from app.services import llm

POST_FILENAME = "dang-bai.txt"
SHOP_HASHTAGS = ["#shopee", "#shopeeaffiliate", "#reviewsanpham", "#muasamonline"]
_URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)


def clean_link(link: str) -> str:
    link = str(link or "").strip()
    return link if _URL_PATTERN.match(link) else ""


def _merge_hashtags(generated, extra=SHOP_HASHTAGS, limit: int = 10) -> list[str]:
    merged: list[str] = []
    for tag in [*(generated or []), *extra]:
        tag = str(tag or "").strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        if tag.lower() not in {t.lower() for t in merged}:
            merged.append(tag)
    return merged[:limit]


def compose_post_text(
    *,
    caption: str,
    hashtags,
    price: str = "",
    original_price: str = "",
    cta: str = "",
    link: str = "",
) -> str:
    lines = [caption.strip()] if caption and caption.strip() else []
    price = (price or "").strip()
    original_price = (original_price or "").strip()
    if price:
        price_line = f"Giá chỉ {price}"
        if original_price:
            price_line += f" (giá gốc {original_price})"
        lines.append(price_line)
    link = clean_link(link)
    cta = (cta or "").strip()
    if link:
        lines.append(f"{cta or 'Mua tại đây'}: {link}")
    elif cta:
        lines.append(cta)
    tags = _merge_hashtags(hashtags)
    if tags:
        lines.append(" ".join(tags))
    return "\n\n".join(lines).strip() + "\n"


def build_post_text(params, video_script: str) -> str:
    """Ask the configured LLM for a caption and compose the post text.

    ``llm.generate_social_metadata`` already falls back to a heuristic result
    when the model is unavailable, so this always returns usable text.
    """
    metadata = llm.generate_social_metadata(
        video_subject=getattr(params, "video_subject", "") or "",
        video_script=video_script or "",
        language=getattr(params, "video_language", "") or "vi-VN",
        platform="facebook_reels",
    )
    return compose_post_text(
        caption=metadata.get("caption") or metadata.get("title") or "",
        hashtags=metadata.get("hashtags") or [],
        price=getattr(params, "price_text", ""),
        original_price=getattr(params, "original_price_text", ""),
        cta=getattr(params, "cta_text", ""),
        link=getattr(params, "affiliate_link", ""),
    )


def save_post_text(params, video_script: str, task_dir: str) -> str:
    """Build and save the post text; return it, or "" when it failed."""
    try:
        text = build_post_text(params, video_script)
        with open(os.path.join(task_dir, POST_FILENAME), "w", encoding="utf-8") as f:
            f.write(text)
        return text
    except Exception as exc:  # the video itself is already finished
        logger.warning(f"failed to build post text: {type(exc).__name__}: {exc}")
        return ""
