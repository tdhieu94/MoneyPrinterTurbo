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


PLATFORMS = (
    ("shopee", "Shopee Video"),
    ("tiktok", "TikTok"),
    ("facebook", "Facebook Reels"),
)
SHOPEE_CAPTION_LIMIT = 150
TIKTOK_HASHTAGS = ["#xuhuong", "#reviewsanpham", "#muasamonline", "#shopee"]


def _shorten(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:!-") + "…"


def _price_line(price: str, original_price: str) -> str:
    price = (price or "").strip()
    original_price = (original_price or "").strip()
    if not price:
        return ""
    line = f"Giá chỉ {price}"
    if original_price:
        line += f" (giá gốc {original_price})"
    return line


# A question at the end of a caption invites comments, which the feed rewards.
ENGAGEMENT_QUESTIONS = (
    "Nhà bạn đang dùng loại nào? Bình luận cho mình biết nhé!",
    "Giá này bạn thấy hời không? Comment \"hời\" hoặc \"chưa\" nhé!",
    "Bạn muốn mình review thêm món nào? Để lại bình luận nhé!",
    "Tag ngay một người đang cần món này nhé!",
    "Bạn đã thử chưa? Kể mình nghe dưới bình luận nhé!",
)


def engagement_question(seed: str = "") -> str:
    """Pick a question deterministically, so re-running a task keeps its text."""
    import zlib

    index = zlib.crc32(str(seed or "").encode("utf-8")) % len(ENGAGEMENT_QUESTIONS)
    return ENGAGEMENT_QUESTIONS[index]


def compose_platform_texts(
    *,
    caption: str,
    hashtags,
    price: str = "",
    original_price: str = "",
    cta: str = "",
    link: str = "",
    ask_question: bool = True,
    question_seed: str = "",
) -> dict[str, str]:
    """One post per platform, following what each one allows.

    - Shopee Video: short caption; the product is tagged in the app, so no link.
    - TikTok: links in captions are not clickable, so point to the bio link.
    - Facebook Reels: the affiliate link goes straight into the post.
    """
    price_line = _price_line(price, original_price)
    cta = (cta or "").strip()
    question = engagement_question(question_seed or caption) if ask_question else ""

    shopee = [_shorten(caption, SHOPEE_CAPTION_LIMIT)] if caption else []
    if price_line:
        shopee.append(price_line)
    shopee.append(cta or "Bấm giỏ hàng để mua ngay")
    if question:
        shopee.append(question)
    shopee.append(" ".join(_merge_hashtags(hashtags, limit=5)))

    tiktok = [caption.strip()] if caption and caption.strip() else []
    if price_line:
        tiktok.append(price_line)
    tiktok.append("👉 Link mua ở bio" if clean_link(link) else (cta or ""))
    if question:
        tiktok.append(question)
    tiktok.append(" ".join(_merge_hashtags(hashtags, TIKTOK_HASHTAGS, limit=8)))

    def join(lines):
        return "\n\n".join(line for line in lines if line and line.strip()).strip() + "\n"

    facebook = compose_post_text(
        caption=caption,
        hashtags=hashtags,
        price=price,
        original_price=original_price,
        cta=cta,
        link=link,
    )
    if question:
        # Keep the hashtags last: insert the question before them.
        head, sep, tags = facebook.rstrip("\n").rpartition("\n\n")
        if sep and tags.startswith("#"):
            facebook = f"{head}\n\n{question}\n\n{tags}\n"
        else:
            facebook = facebook.rstrip("\n") + f"\n\n{question}\n"
    return {"shopee": join(shopee), "tiktok": join(tiktok), "facebook": facebook}


def platform_texts_file(texts: dict[str, str]) -> str:
    blocks = []
    for key, label in PLATFORMS:
        if texts.get(key):
            blocks.append(f"===== {label} =====\n\n{texts[key].strip()}\n")
    return "\n".join(blocks)


def build_platform_texts(params, video_script: str) -> dict[str, str]:
    """Ask the configured LLM for a caption and compose a post per platform.

    ``llm.generate_social_metadata`` already falls back to a heuristic result
    when the model is unavailable, so this always returns usable text.
    """
    metadata = llm.generate_social_metadata(
        video_subject=getattr(params, "video_subject", "") or "",
        video_script=video_script or "",
        language=getattr(params, "video_language", "") or "vi-VN",
        platform="facebook_reels",
    )
    return compose_platform_texts(
        caption=metadata.get("caption") or metadata.get("title") or "",
        hashtags=metadata.get("hashtags") or [],
        price=getattr(params, "price_text", ""),
        original_price=getattr(params, "original_price_text", ""),
        cta=getattr(params, "cta_text", ""),
        link=getattr(params, "affiliate_link", ""),
        question_seed=getattr(params, "video_subject", "") or "",
    )


def build_post_text(params, video_script: str) -> str:
    return build_platform_texts(params, video_script)["facebook"]


def save_post_texts(params, video_script: str, task_dir: str) -> dict[str, str]:
    """Build and save the posts; return them, or {} when it failed."""
    try:
        texts = build_platform_texts(params, video_script)
        with open(os.path.join(task_dir, POST_FILENAME), "w", encoding="utf-8") as f:
            f.write(platform_texts_file(texts))
        return texts
    except Exception as exc:  # the video itself is already finished
        logger.warning(f"failed to build post text: {type(exc).__name__}: {exc}")
        return {}


def save_post_text(params, video_script: str, task_dir: str) -> str:
    """Backwards-compatible: save all posts and return the Facebook one."""
    return save_post_texts(params, video_script, task_dir).get("facebook", "")
