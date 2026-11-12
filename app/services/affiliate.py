"""Script requirement templates for affiliate product videos.

The templates are plain "additional user requirements" text. They are written
into the existing custom script requirements field, so the script pipeline,
the API and saved tasks need no new parameters. The product itself (name,
price, highlights) is described in the video subject.
"""

from app.services.llm import MAX_SCRIPT_PROMPT_LENGTH

AFFILIATE_TEMPLATE_NONE = "none"

_COMMON_RULES = """
Quy tắc chung:
- Viết bằng tiếng Việt, giọng nói chuyện tự nhiên như người thật đang chia sẻ, câu ngắn, dễ đọc thành lời.
- Tổng độ dài 60-90 từ để video dài khoảng 25-40 giây.
- Chỉ dùng thông tin có trong phần mô tả sản phẩm. Không bịa thông số, giá, khuyến mãi, chứng nhận hay công dụng chữa bệnh.
- Nếu có giá thì nói "giá tham khảo" hoặc "đang có giá khoảng", vì giá có thể thay đổi.
- Không dùng emoji, hashtag, ký hiệu đặc biệt hay chú thích cảnh quay; chỉ viết lời đọc.
- Câu cuối kêu gọi hành động: bấm vào giỏ hàng hoặc link bên dưới để xem giá mới nhất.
""".strip()

AFFILIATE_SCRIPT_TEMPLATES = {
    "quick_review": (
        "Đây là video review nhanh một sản phẩm để tiếp thị liên kết.\n"
        "Cấu trúc:\n"
        "1. Câu mở đầu gây tò mò trong 3 giây, nêu đúng vấn đề người xem đang gặp.\n"
        "2. Giới thiệu sản phẩm là cách giải quyết vấn đề đó.\n"
        "3. Hai đến ba điểm nổi bật, mỗi điểm một câu, nói theo lợi ích người dùng nhận được.\n"
        "4. Giá và ưu đãi nếu có.\n"
        "5. Kêu gọi hành động.\n\n" + _COMMON_RULES
    ),
    "top_reasons": (
        "Đây là video dạng \"3 lý do nên mua\" một sản phẩm để tiếp thị liên kết.\n"
        "Cấu trúc:\n"
        "1. Câu mở đầu: \"3 lý do khiến mình chọn\" kèm tên sản phẩm ngắn gọn.\n"
        "2. Lý do thứ nhất, thứ hai, thứ ba; mỗi lý do một đến hai câu, cụ thể, có so sánh với cách làm cũ.\n"
        "3. Giá và ưu đãi nếu có.\n"
        "4. Kêu gọi hành động.\n\n" + _COMMON_RULES
    ),
    "deal_alert": (
        "Đây là video báo deal giảm giá một sản phẩm để tiếp thị liên kết.\n"
        "Cấu trúc:\n"
        "1. Câu mở đầu nhấn vào mức giá hoặc ưu đãi đang có.\n"
        "2. Sản phẩm là gì và dành cho ai, trong một câu.\n"
        "3. Hai điểm đáng tiền nhất.\n"
        "4. Nhắc ưu đãi có thời hạn hoặc số lượng có hạn, chỉ khi mô tả sản phẩm có nói.\n"
        "5. Kêu gọi hành động.\n\n" + _COMMON_RULES
    ),
}

AFFILIATE_TEMPLATE_IDS = (AFFILIATE_TEMPLATE_NONE, *AFFILIATE_SCRIPT_TEMPLATES)


def get_affiliate_script_prompt(template_id: str | None) -> str:
    """Return the requirements text for a template, or "" when none is selected."""
    prompt = AFFILIATE_SCRIPT_TEMPLATES.get(str(template_id or "").strip(), "")
    return prompt[:MAX_SCRIPT_PROMPT_LENGTH]
