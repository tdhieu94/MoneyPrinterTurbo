from unittest.mock import patch

from app.models.schema import MaterialInfo, VideoParams
from app.services import llm, task, video_variants


def _params(**kwargs):
    base = dict(
        video_subject="Khăn giấy",
        video_source="local",
        video_count=3,
        video_script="Kịch bản có sẵn",
        hook_text="Câu 1\nCâu 2\nCâu 3",
    )
    base.update(kwargs)
    return VideoParams(**base)


def test_split_gives_each_video_its_own_script_hook_and_index():
    variants = video_variants.split_params(_params())
    assert [v.variant_index for v in variants] == [1, 2, 3]
    assert all(v.video_count == 1 and v.variant_total == 3 for v in variants)
    assert variants[0].video_script == "Kịch bản có sẵn"
    assert variants[1].video_script == "" and variants[2].video_script == ""
    assert [v.hook_text for v in variants] == ["Câu 1", "Câu 2", "Câu 3"]


def test_split_only_for_free_sources_without_uploaded_voice():
    assert video_variants.can_split(_params())
    assert not video_variants.can_split(_params(video_count=1))
    assert not video_variants.can_split(_params(custom_audio_file="a.mp3"))
    assert not video_variants.can_split(_params(video_source="loomloom"))


def test_photo_order_differs_per_version_and_is_repeatable():
    items = list("abcdef")
    orders = [video_variants.reorder(items, i) for i in range(1, 6)]
    assert orders[0] == items
    assert len({tuple(o) for o in orders}) == 5
    assert len({o[0] for o in orders}) == 5
    assert all(sorted(o) == items for o in orders)
    assert video_variants.reorder(items, 3) == orders[2]


def test_later_versions_ask_the_llm_for_another_angle():
    assert video_variants.script_prompt("Viết ngắn", 1, 3, 2000) == "Viết ngắn"
    prompt = video_variants.script_prompt("x" * 3000, 2, 3, 2000)
    assert len(prompt) <= 2000 and "phiên bản 2/3" in prompt

    params = video_variants.split_params(_params(video_script_prompt="Viết ngắn"))[1]
    with patch.object(llm, "generate_script", return_value="Bản mới") as generate:
        assert task.generate_script("t", params) == "Bản mới"
    sent = generate.call_args.kwargs["video_script_prompt"]
    assert sent.startswith("Viết ngắn") and "phiên bản 2/3" in sent


def test_local_materials_are_reordered_for_the_version():
    materials = []
    for name in "abc":
        m = MaterialInfo()
        m.provider, m.url = "local", name
        materials.append(m)
    params = _params(video_materials=materials, variant_index=2, variant_total=3)
    assert [m.url for m in task._with_before_after_scene(params)][0] == "b"
