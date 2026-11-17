"""带货发布文案：组装、链接过滤和失败降级。"""

import os
from types import SimpleNamespace
from unittest.mock import patch

from app.services import sales_post


def test_compose_post_text_includes_price_link_and_shop_hashtags():
    text = sales_post.compose_post_text(
        caption="Khăn giấy siêu mềm cho cả nhà.",
        hashtags=["#khangiay", "shopee"],
        price="59.000đ",
        original_price="99.000đ",
        cta="Bấm giỏ hàng để mua ngay",
        link="https://s.shopee.vn/abc123",
    )
    assert "Khăn giấy siêu mềm cho cả nhà." in text
    assert "Giá chỉ 59.000đ (giá gốc 99.000đ)" in text
    assert "Bấm giỏ hàng để mua ngay: https://s.shopee.vn/abc123" in text
    tags = text.strip().splitlines()[-1].split()
    assert tags[0] == "#khangiay"
    assert tags.count("#shopee") == 1


def test_compose_post_text_drops_invalid_links():
    text = sales_post.compose_post_text(
        caption="x", hashtags=[], cta="Mua ngay", link="javascript:alert(1)"
    )
    assert "javascript" not in text
    assert "Mua ngay" in text


def test_save_post_text_writes_file(tmp_path):
    params = SimpleNamespace(
        video_subject="Khăn giấy", video_language="vi-VN", price_text="59k",
        original_price_text="", cta_text="Mua ngay", affiliate_link="https://s.shopee.vn/x",
    )
    metadata = {"title": "t", "caption": "Caption hay", "hashtags": ["#a"]}
    with patch.object(sales_post.llm, "generate_social_metadata", return_value=metadata):
        text = sales_post.save_post_text(params, "script", str(tmp_path))
    assert "Caption hay" in text
    saved = (tmp_path / sales_post.POST_FILENAME).read_text(encoding="utf-8")
    assert saved == text


def test_save_post_text_failure_returns_empty(tmp_path):
    params = SimpleNamespace(video_subject="x")
    with patch.object(sales_post.llm, "generate_social_metadata", side_effect=RuntimeError("down")):
        assert sales_post.save_post_text(params, "", str(tmp_path)) == ""
    assert not os.listdir(tmp_path)


def test_generate_hooks_parses_model_lines():
    from app.services import llm

    response = "1. Khăn giấy 59k mà mềm thế này?\n- Hết cảnh giấy bở\n\n" + "x" * 200
    with patch.object(llm, "_generate_response", return_value=response):
        assert llm.generate_hooks("Khăn giấy", count=5) == [
            "Khăn giấy 59k mà mềm thế này?",
            "Hết cảnh giấy bở",
        ]


def test_generate_hooks_returns_empty_on_model_error():
    from app.services import llm

    with patch.object(llm, "_generate_response", return_value="Error: quota"):
        assert llm.generate_hooks("Khăn giấy") == []
