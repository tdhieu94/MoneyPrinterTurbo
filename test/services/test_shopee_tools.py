import csv
import io
import json

from app.services import commission_report, posting_log, sales_post

DAY = 86400


def test_posting_pace_counts_a_rolling_30_day_window(tmp_path, monkeypatch):
    monkeypatch.setattr(posting_log.utils, "storage_dir", lambda sub="", create=False: str(tmp_path))
    now = 1_800_000_000.0
    posting_log.set_posted("old", "Cũ", now=now - 40 * DAY)
    posting_log.set_posted("a", "Khăn giấy", now=now - 10 * DAY)
    posting_log.set_posted("b", "Nồi chiên", now=now - 4 * DAY)
    pace = posting_log.pace(now)
    assert pace["count"] == 2 and pace["remaining"] == 3
    assert [p["task_id"] for p in pace["posts"]] == ["b", "a"]
    assert int(pace["days_since_last"]) == 4
    assert posting_log.is_posted("a")
    posting_log.set_posted("a", posted=False)
    assert not posting_log.is_posted("a")
    assert json.loads((tmp_path / "posting_log.json").read_text(encoding="utf-8"))


def test_posting_log_survives_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(posting_log.utils, "storage_dir", lambda sub="", create=False: str(tmp_path))
    (tmp_path / "posting_log.json").write_text("{not json", encoding="utf-8")
    assert posting_log.pace()["count"] == 0
    posting_log.set_posted("x", "A")
    assert posting_log.is_posted("x")


def _report(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Báo cáo hoa hồng tháng 11"])
    writer.writerow([
        "ID đơn hàng", "Trạng thái đặt hàng", "Tên Item", "Số lượng",
        "Tổng hoa hồng đơn hàng(₫)", "Hoa hồng ròng tiếp thị liên kết(₫)", "Sub_id1",
    ])
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def test_commission_report_groups_by_product_and_sub_id():
    data = _report([
        ["1", "Hoàn thành", "Khăn giấy", "2", "20.000", "12.000", "video1"],
        ["1", "Hoàn thành", "Nồi chiên", "1", "90.000", "45.500", "video2"],
        ["2", "Đang chờ xử lý", "Khăn giấy", "1", "10.000", "6.000", "video1"],
        ["3", "Đã hủy", "Nồi chiên", "1", "90.000", "45.000", "video2"],
    ])
    summary = commission_report.summarize_report("bao-cao.csv", data)
    assert summary.total_commission == 63_500
    assert summary.pending_commission == 6_000
    assert summary.cancelled_commission == 45_000
    assert summary.orders == 2 and summary.cancelled_orders == 1
    assert summary.products[0] == {"product": "Nồi chiên", "orders": 1, "items": 1, "commission": 45500}
    assert summary.products[1]["items"] == 3
    assert [row["sub_id"] for row in summary.sub_ids] == ["video2", "video1"]
    assert commission_report.format_vnd(summary.total_commission) == "63.500đ"


def test_parse_money_formats():
    assert commission_report.parse_money("₫1.234.567") == 1234567
    assert commission_report.parse_money("12,345.50") == 12345.5
    assert commission_report.parse_money("12.345,5") == 12345.5
    assert commission_report.parse_money("12345.0") == 12345
    assert commission_report.parse_money("") == 0


def test_commission_report_rejects_other_files():
    import pytest

    with pytest.raises(commission_report.CommissionReportError):
        commission_report.summarize_report("a.csv", b"ten,gia\nA,1\n")


def test_platform_posts_follow_each_platform():
    texts = sales_post.compose_platform_texts(
        caption="Khăn giấy siêu mềm, dai, không bụi. " * 8,
        hashtags=["khangiay", "#giadung"],
        price="59.000đ",
        original_price="89.000đ",
        cta="Bấm giỏ hàng để mua",
        link="https://s.shopee.vn/abc",
    )
    assert set(texts) == {"shopee", "tiktok", "facebook"}
    assert "https://" not in texts["shopee"]
    assert len(texts["shopee"].strip()) <= sales_post.SHOPEE_CAPTION_LIMIT
    assert "59.000đ" in texts["shopee"] and "Bấm giỏ hàng để mua" in texts["shopee"]
    assert "#" in texts["shopee"]
    assert "bio" in texts["tiktok"] and "https://" not in texts["tiktok"]
    assert "https://s.shopee.vn/abc" in texts["facebook"]
    combined = sales_post.platform_texts_file(texts)
    assert combined.index("Shopee Video") < combined.index("TikTok") < combined.index("Facebook Reels")


def test_shopee_description_fits_the_whole_limit():
    long_caption = "Khăn giấy siêu mềm, dai, không bụi, an toàn cho bé và cả nhà. " * 6
    for kwargs in (
        {"price": "59.000đ", "original_price": "89.000đ"},
        {"price": "1.259.000đ", "original_price": "2.999.000đ", "cta": "Chốt đơn ngay hôm nay kẻo hết hàng nha cả nhà ơi " * 3},
        {},
    ):
        texts = sales_post.compose_platform_texts(
            caption=long_caption,
            hashtags=["#khangiaymem", "#giadungtienich", "#mevabe", "#sale", "#freeship"],
            link="https://s.shopee.vn/abc",
            **kwargs,
        )
        shopee = texts["shopee"].strip()
        assert len(shopee) <= sales_post.SHOPEE_CAPTION_LIMIT, shopee
        assert shopee.startswith("Khăn giấy siêu mềm")
        if kwargs.get("price"):
            assert kwargs["price"] in shopee

    short = sales_post.compose_platform_texts(
        caption="Khăn giấy mềm", hashtags=["#a"], price="59k", question_seed="x"
    )["shopee"]
    assert sales_post.engagement_question("x") in short
    assert len(short.strip()) <= sales_post.SHOPEE_CAPTION_LIMIT
