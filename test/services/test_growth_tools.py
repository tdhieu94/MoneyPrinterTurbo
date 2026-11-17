import io
import json
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app.models.schema import VideoParams
from app.services import app_backup, posting_log, product_images, sales_overlay, thumbnail, video


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(posting_log.utils, "storage_dir", lambda sub="", create=False: str(tmp_path))
    monkeypatch.setattr(app_backup.utils, "storage_dir", lambda sub="", create=False: str(tmp_path))
    return tmp_path


def test_cover_has_title_and_price_on_a_shaded_frame():
    frame = np.full((1920, 1080, 3), 230, dtype=np.uint8)
    cover = thumbnail.compose_cover(frame, "Khăn giấy siêu mềm", "59.000đ", "89.000đ")
    assert cover.size == (1080, 1920)
    pixels = np.asarray(cover)
    assert pixels[100, 540].mean() > 200  # top untouched
    assert pixels[1900, 20].mean() < pixels[100, 20].mean()  # bottom shaded
    params = VideoParams(video_subject="Nồi chiên", hook_text="Câu 1\nCâu 2")
    assert thumbnail.cover_title(params) == "Câu 1"


def test_proof_and_urgency_badges():
    params = VideoParams(
        video_subject="x", price_text="59k", sold_text="Đã bán 10k+",
        rating_text="4.9", urgency_text="Chỉ hôm nay",
    )
    clips = sales_overlay.build_overlay_clips(params, 1080, 1920, 20.0)
    assert len(clips) == 3  # price, proof, urgency
    urgency = clips[-1]
    assert urgency.start == 0 and urgency.pos(0)[0] > 540
    assert sales_overlay.has_overlays(VideoParams(video_subject="x", urgency_text="Sale"))


def test_clean_background_and_before_after(tmp_path):
    cutout = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    cutout.paste((200, 30, 30, 255), (50, 50, 150, 250))
    cleaned = product_images.place_on_clean_background(cutout)
    assert cleaned.mode == "RGB"
    assert cleaned.size[0] < 200  # trimmed to the product plus padding
    assert np.asarray(cleaned)[2, 2].mean() > 220  # light backdrop

    before, after = tmp_path / "b.png", tmp_path / "a.png"
    Image.new("RGB", (400, 400), "gray").save(before)
    Image.new("RGB", (400, 400), "white").save(after)
    out = product_images.compose_before_after(str(before), str(after), str(tmp_path / "c.png"), (540, 960))
    with Image.open(out) as image:
        assert image.size == (540, 960)
        top, bottom = np.asarray(image)[700, 20], np.asarray(image)[300, 20]
        assert top.mean() > bottom.mean()  # "after" (white) is the lower half


def test_remove_background_without_rembg_keeps_the_photo(monkeypatch, tmp_path):
    monkeypatch.setattr(product_images, "rembg_available", lambda: False)
    assert product_images.remove_background(str(tmp_path / "x.jpg")) == str(tmp_path / "x.jpg")


def test_smart_trim_drops_blurry_and_dark_slices(monkeypatch):
    sharp = np.zeros((90, 160, 3), dtype=np.uint8)
    sharp[::2, :] = 255
    blurry = np.full((90, 160, 3), 128, dtype=np.uint8)
    dark = np.full((90, 160, 3), 5, dtype=np.uint8)
    frames = {0.5: sharp, 1.5: sharp, 2.5: blurry, 3.5: dark}

    class FakeClip:
        def get_frame(self, t):
            return frames[t]

    monkeypatch.setattr(video, "_open_video_clip_quietly", lambda path: FakeClip())
    monkeypatch.setattr(video, "close_clip", lambda clip: None)
    items = [
        SimpleNamespace(source_file_path="/v/quay.mp4", start_time=t - 0.5, end_time=t + 0.5)
        for t in (0.5, 1.5, 2.5, 3.5)
    ]
    photo = SimpleNamespace(source_file_path="/v/" + "a" * 64 + ".gentle-" + "b" * 16 + ".mp4", start_time=0, end_time=1)
    kept = video._drop_weak_slices([*items, photo])
    assert [i.start_time for i in kept if i is not photo] == [0.0, 1.0]
    assert photo in kept


def test_auto_plan_spreads_videos_one_per_day(storage):
    plan = posting_log.auto_plan(["a", "b", "c"], "2026-11-17")
    assert plan == {"a": "2026-11-17", "b": "2026-11-18", "c": "2026-11-19"}
    posting_log.set_plan_date("c", "2026-11-25")
    posting_log.set_posted("a", "A")
    plan = posting_log.auto_plan(["a", "b", "c", "d"], "2026-11-18")
    assert "a" not in plan
    assert plan["b"] == "2026-11-18" and plan["c"] == "2026-11-25" and plan["d"] == "2026-11-19"


def test_winning_hooks_join_posts_with_sub_ids(storage):
    posting_log.set_posted("t1", "Khăn", hook="Nhà bạn hết khăn giấy chưa?", sub_id="khan-v1")
    posting_log.set_posted("t2", "Khăn", hook="Đừng mua khăn giấy", sub_id="khan-v2")
    winners = posting_log.match_winning_hooks([
        {"sub_id": "KHAN-V1", "orders": 3, "commission": 30000},
        {"sub_id": "khan-v2", "orders": 0, "commission": 0},
    ])
    assert [w["hook"] for w in winners] == ["Nhà bạn hết khăn giấy chưa?"]
    assert posting_log.load_winning_hooks()[0]["orders"] == 3


def test_backup_round_trip_without_secrets(storage, monkeypatch):
    posting_log.set_posted("t1", "Khăn")
    monkeypatch.setattr(app_backup.config, "ui", {"font_size": 72, "openai_api_key": "sk-x", "language": "vi"})
    data = app_backup.build_backup()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        settings = json.loads(archive.read("ui_settings.json"))
    assert "openai_api_key" not in settings and settings["font_size"] == 72
    (storage / posting_log.LOG_FILENAME).unlink()
    result = app_backup.restore_backup(data)
    assert result["files"] == 1 and posting_log.is_posted("t1")
    assert result["settings"] == {"font_size": 72, "language": "vi"}
    with pytest.raises(app_backup.BackupError):
        app_backup.restore_backup(b"not a zip")


def test_engagement_tips():
    from app.services import affiliate, sales_post

    assert "problem_solution" in affiliate.AFFILIATE_TEMPLATE_IDS
    prompt = affiliate.get_affiliate_script_prompt("problem_solution")
    assert "45-70 từ" in prompt and len(prompt) <= affiliate.MAX_SCRIPT_PROMPT_LENGTH

    texts = sales_post.compose_platform_texts(
        caption="Khăn giấy mềm", hashtags=["#a"], price="59k", link="https://s.shopee.vn/x",
        question_seed="Khăn giấy",
    )
    question = sales_post.engagement_question("Khăn giấy")
    for text in texts.values():
        assert question in text
    facebook_blocks = texts["facebook"].strip().split("\n\n")
    assert facebook_blocks[-1].startswith("#") and facebook_blocks[-2] == question
    plain = sales_post.compose_platform_texts(caption="x", hashtags=[], ask_question=False)
    assert all(q not in plain["tiktok"] for q in sales_post.ENGAGEMENT_QUESTIONS)

    assert posting_log.posting_window_status(12) == "now"
    assert posting_log.posting_window_status(18) == "soon"
    assert posting_log.posting_window_status(15) == ""
