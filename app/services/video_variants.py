"""Make every video of a multi-video request different.

When the seller asks for several videos of one product, the WebUI submits
one task per video instead of one task that renders the same voiceover over
reshuffled footage. Each task carries ``variant_index``/``variant_total``:

* the first version keeps the script already in the form (if any); later
  versions are written again by the LLM with a different selling angle;
* local photos are put in a different order for every version;
* version N uses the N-th opening hook line.
"""

from __future__ import annotations

import random

from app.services import sales_overlay

# One selling angle per version, so the LLM does not write the same script.
ANGLES = (
    "nêu một vấn đề người mua hay gặp rồi đưa sản phẩm ra làm giải pháp",
    "đi thẳng vào lợi ích nổi bật nhất và cảm giác khi dùng",
    "kể như trải nghiệm thật của người đã mua và dùng thử",
    "so sánh trước và sau khi dùng, nhấn mạnh sự khác biệt",
    "nhấn vào giá hời, ưu đãi và lý do nên mua ngay hôm nay",
    "trả lời nhanh 2-3 thắc mắc người mua hay hỏi về sản phẩm",
)

SPLIT_SOURCES = {"local", "pexels", "pixabay", "coverr"}


def can_split(params) -> bool:
    """Only free footage sources; uploaded voiceovers fix the script."""
    return (
        int(getattr(params, "video_count", 1) or 1) > 1
        and str(getattr(params, "video_source", "") or "") in SPLIT_SOURCES
        and not str(getattr(params, "custom_audio_file", "") or "").strip()
    )


def split_params(params) -> list:
    """One params copy per video, each with ``video_count`` = 1."""
    total = max(1, int(getattr(params, "video_count", 1) or 1))
    variants = []
    for index in range(1, total + 1):
        variant = sales_overlay.params_for_variant(params, index)
        update = {
            "video_count": 1,
            "variant_index": index,
            "variant_total": total,
        }
        if index > 1:
            # A new script also needs new search terms for stock footage.
            update.update(video_script="", video_terms=None)
        variants.append(variant.model_copy(update=update))
    return variants


def angle_instruction(index: int, total: int) -> str:
    if index <= 1 or total <= 1:
        return ""
    angle = ANGLES[(index - 1) % len(ANGLES)]
    return (
        f"Đây là phiên bản {index}/{total} của cùng sản phẩm. Viết kịch bản mới "
        "hoàn toàn, câu mở đầu và câu chữ khác các phiên bản khác. "
        f"Hướng tiếp cận: {angle}."
    )


def script_prompt(base_prompt: str, index: int, total: int, limit: int) -> str:
    """The user's prompt plus the angle, kept within ``limit`` characters."""
    extra = angle_instruction(index, total)
    base = (base_prompt or "").strip()
    if not extra:
        return base
    room = max(0, limit - len(extra) - 2)
    return f"{base[:room]}\n\n{extra}".strip()


def reorder(items: list, index: int) -> list:
    """A different, repeatable order of ``items`` for every version.

    Version 1 keeps the seller's order. Version N starts from a different
    photo (rotating through them) and shuffles the rest with a fixed seed,
    so re-running the same task gives the same video.
    """
    items = list(items)
    if index <= 1 or len(items) <= 1:
        return items
    lead = (index - 1) % len(items)
    first, rest = items[lead], items[:lead] + items[lead + 1:]
    random.Random(f"variant-{index}-{len(items)}").shuffle(rest)
    return [first, *rest]
