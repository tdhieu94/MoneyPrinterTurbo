"""带货叠加文字：时间轴规划与渲染，不依赖真实视频。"""

from types import SimpleNamespace

import pytest

from app.models.schema import VideoParams
from app.services import sales_overlay as so


def _params(**kwargs):
    base = dict(hook_text="", price_text="", original_price_text="", cta_text="")
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_timeline_places_hook_price_and_cta():
    plan = so.plan_timeline(20, hook=True, price=True, cta=True)
    assert plan.hook == (0.0, 3.0)
    assert plan.price == (3.0, 20)
    assert plan.cta == (16.5, 20)


def test_timeline_short_video_keeps_layers_inside_duration():
    plan = so.plan_timeline(4, hook=True, price=True, cta=True)
    assert plan.hook[1] <= 4 * 0.4 + 1e-9
    assert plan.cta[0] >= plan.hook[1]
    assert plan.price[1] == 4


def test_timeline_without_hook_shows_price_from_start():
    plan = so.plan_timeline(10, hook=False, price=True, cta=False)
    assert plan.hook is None and plan.cta is None
    assert plan.price == (0.0, 10)


def test_no_overlays_when_fields_empty():
    params = _params()
    assert not so.has_overlays(params)
    assert so.build_overlay_clips(params, 1080, 1920, 10) == []


def test_build_overlay_clips_renders_vietnamese_text():
    params = _params(
        hook_text="Khăn giấy 59k mà mềm thế này?",
        price_text="59.000đ",
        original_price_text="99.000đ",
        cta_text="Bấm giỏ hàng để mua ngay",
    )
    clips = so.build_overlay_clips(params, 1080, 1920, 12)
    assert len(clips) == 3
    for clip in clips:
        width, height = clip.size
        assert 0 < width <= 1088 and 0 < height < 1920
        assert clip.start >= 0 and clip.end <= 12 + 1e-6


def test_long_hook_wraps_to_canvas_width():
    image = so.render_hook("Mua ngay kẻo lỡ " * 10, 720)
    assert image.width == 720


def test_video_params_accept_sales_fields_and_limit_length():
    params = VideoParams(video_subject="x", price_text="59k", cta_text="Mua ngay")
    assert params.price_text == "59k"
    with pytest.raises(Exception):
        VideoParams(video_subject="x", hook_text="a" * 900)


def test_params_for_variant_rotates_hook_lines():
    params = VideoParams(video_subject="x", hook_text="Câu A\n\nCâu B\nCâu C")
    assert so.params_for_variant(params, 1).hook_text == "Câu A"
    assert so.params_for_variant(params, 2).hook_text == "Câu B"
    assert so.params_for_variant(params, 4).hook_text == "Câu A"
    assert params.hook_text.startswith("Câu A\n")


def test_params_for_variant_keeps_single_hook():
    params = VideoParams(video_subject="x", hook_text="Một câu")
    assert so.params_for_variant(params, 3) is params


def test_multi_line_hook_renders_first_line_only():
    params = _params(hook_text="Dòng một\nDòng hai")
    clips = so.build_overlay_clips(params, 1080, 1920, 10)
    assert len(clips) == 1
