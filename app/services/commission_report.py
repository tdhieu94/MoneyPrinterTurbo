"""Summarise a Shopee Affiliate commission report (CSV or Excel export).

The report lists one row per ordered item. Column names differ slightly
between report versions and languages, so columns are found by keywords after
removing accents (e.g. "Hoa hồng ròng tiếp thị liên kết(₫)" → hoa_hong_rong).
The summary shows which products and which Sub_IDs (one per video, when the
seller puts a Sub_ID in each video's link) actually earn commission.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from app.services import product_batch

MAX_REPORT_BYTES = 20 * 1024 * 1024

# Checked in order: the first matching header wins for each column.
_COLUMN_KEYWORDS = {
    "order_id": ("id_don_hang", "ma_don_hang", "order_id"),
    "status": ("trang_thai_dat_hang", "trang_thai_don", "trang_thai", "order_status", "status"),
    "product": ("ten_item", "ten_san_pham", "item_name", "product_name", "ten_sp"),
    "shop": ("ten_shop", "shop_name"),
    "quantity": ("so_luong", "qty", "quantity"),
    "commission": (
        "hoa_hong_rong",
        "net_commission",
        "affiliate_net_commission",
        "tong_hoa_hong_don_hang",
        "tong_hoa_hong",
        "hoa_hong",
        "commission",
    ),
    "sub_id": ("sub_id1", "sub_id_1", "sub_id"),
    "channel": ("kenh", "channel"),
}

_CANCELLED_WORDS = ("huy", "cancel", "that_bai", "failed", "unpaid", "chua_thanh_toan")
_PENDING_WORDS = ("dang_cho", "cho_xu_ly", "pending", "dang_xu_ly", "chua_hoan_thanh")


class CommissionReportError(ValueError):
    """The report cannot be read; the message is user-facing."""


@dataclass
class Group:
    name: str
    orders: set = field(default_factory=set)
    items: int = 0
    commission: float = 0.0

    def row(self, label: str) -> dict:
        return {
            label: self.name,
            "orders": len(self.orders),
            "items": self.items,
            "commission": round(self.commission),
        }


@dataclass
class ReportSummary:
    total_commission: float = 0.0
    pending_commission: float = 0.0
    cancelled_commission: float = 0.0
    orders: int = 0
    cancelled_orders: int = 0
    products: list[dict] = field(default_factory=list)
    sub_ids: list[dict] = field(default_factory=list)
    has_sub_id: bool = False


def _find_columns(headers: list[str]) -> dict[str, int]:
    normalized = [product_batch._normalize_header(h) for h in headers]
    columns: dict[str, int] = {}
    for column, keywords in _COLUMN_KEYWORDS.items():
        for keyword in keywords:
            match = next(
                (
                    index
                    for index, header in enumerate(normalized)
                    if index not in columns.values()
                    and (header == keyword or header.startswith(keyword))
                ),
                None,
            )
            if match is not None:
                columns[column] = match
                break
    if "commission" not in columns:
        raise CommissionReportError(
            "Không thấy cột hoa hồng. Hãy dùng file báo cáo hoa hồng tải từ Shopee Affiliate."
        )
    return columns


def parse_money(value) -> float:
    """Read amounts like "12.345", "12,345.50", "₫1.234.567" or 12345.0."""
    text = str(value or "").strip()
    text = re.sub(r"[^\d,.\-]", "", text)
    if not text or text in {"-", ".", ","}:
        return 0.0
    if "," in text and "." in text:
        # The last separator is the decimal one.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = text.replace(",", "") if len(tail) == 3 else head.replace(",", "") + "." + tail
    elif text.count(".") > 1 or (text.count(".") == 1 and len(text.rpartition(".")[2]) == 3):
        # Vietnamese thousands separators: 12.345 / 1.234.567
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _status_kind(status: str) -> str:
    normalized = product_batch._normalize_header(status)
    if any(word in normalized for word in _CANCELLED_WORDS):
        return "cancelled"
    if any(word in normalized for word in _PENDING_WORDS):
        return "pending"
    return "done"


def _read_table(filename: str, data: bytes) -> list[list[str]]:
    if len(data) > MAX_REPORT_BYTES:
        raise CommissionReportError("File báo cáo vượt quá 20 MB.")
    extension = os.path.splitext(filename or "")[1].lower()
    try:
        if extension == ".xlsx":
            return product_batch._read_xlsx(data)
        if extension in {".csv", ".txt"}:
            return product_batch._read_csv(data)
    except product_batch.ProductSheetError as exc:
        raise CommissionReportError(str(exc)) from exc
    raise CommissionReportError("Chỉ hỗ trợ file .csv hoặc .xlsx.")


def summarize_report(filename: str, data: bytes) -> ReportSummary:
    table = [row for row in _read_table(filename, data) if any(str(c).strip() for c in row)]
    # Some exports put a title line above the header row.
    header_index = next(
        (
            index
            for index, row in enumerate(table[:10])
            if sum(1 for c in row if str(c).strip()) >= 3
            and any("hoa_hong" in product_batch._normalize_header(c) or
                   "commission" in product_batch._normalize_header(c) for c in row)
        ),
        None,
    )
    if header_index is None:
        raise CommissionReportError(
            "Không thấy cột hoa hồng. Hãy dùng file báo cáo hoa hồng tải từ Shopee Affiliate."
        )
    columns = _find_columns(table[header_index])

    products: dict[str, Group] = {}
    sub_ids: dict[str, Group] = {}
    orders: set = set()
    cancelled_orders: set = set()
    summary = ReportSummary(has_sub_id="sub_id" in columns)

    for line, row in enumerate(table[header_index + 1:], start=header_index + 2):
        def cell(column: str) -> str:
            index = columns.get(column)
            return str(row[index]).strip() if index is not None and index < len(row) else ""

        order_id = cell("order_id") or f"dong-{line}"
        commission = parse_money(cell("commission"))
        quantity = int(parse_money(cell("quantity")) or 1)
        kind = _status_kind(cell("status"))
        if kind == "cancelled":
            summary.cancelled_commission += commission
            cancelled_orders.add(order_id)
            continue
        if kind == "pending":
            summary.pending_commission += commission
        summary.total_commission += commission
        orders.add(order_id)
        for groups, key in (
            (products, cell("product") or "(không rõ sản phẩm)"),
            (sub_ids, cell("sub_id") or "(không có Sub_ID)"),
        ):
            group = groups.setdefault(key, Group(key))
            group.orders.add(order_id)
            group.items += quantity
            group.commission += commission

    summary.orders = len(orders)
    summary.cancelled_orders = len(cancelled_orders - orders)

    def ranked(groups: dict[str, Group], label: str) -> list[dict]:
        ordered = sorted(groups.values(), key=lambda g: (-g.commission, -len(g.orders), g.name))
        return [group.row(label) for group in ordered]

    summary.products = ranked(products, "product")
    summary.sub_ids = ranked(sub_ids, "sub_id") if summary.has_sub_id else []
    return summary


def format_vnd(amount: float) -> str:
    return f"{round(amount):,}".replace(",", ".") + "đ"
