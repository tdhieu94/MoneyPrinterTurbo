"""Read a product list (CSV or Excel) and turn each row into video parameters.

Hieu prepares one row per Shopee product: name, price, original price,
opening hook, affiliate link and the folder holding that product's photos.
The WebUI then queues one generation task per row, reusing every other
setting (voice, subtitles, music, layout) from the form.
"""

from __future__ import annotations

import csv
import io
import os
import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

from app.models.schema import MaterialInfo, VideoParams
from app.services import material_upload

MAX_SHEET_BYTES = 2 * 1024 * 1024
MAX_ROWS = 50
MAX_IMAGES_PER_PRODUCT = 30
_MAX_XLSX_PART_BYTES = 20 * 1024 * 1024
# Free stock sources that need no per-task confirmation.
BATCH_STOCK_SOURCES = frozenset({"local", "pexels", "pixabay", "coverr"})

TEMPLATE_HEADERS = (
    "ten_san_pham",
    "gia",
    "gia_goc",
    "cau_mo_dau",
    "link",
    "thu_muc_anh",
    "kich_ban",
    "keu_goi",
)

_TEMPLATE_EXAMPLE = (
    "Khăn giấy Top Gia 10 gói",
    "59000",
    "89000",
    "Nhà bạn hết khăn giấy chưa?|Đừng mua khăn giấy trước khi xem video này",
    "https://s.shopee.vn/xxxxxxx",
    r"E:\anh-san-pham\khan-giay",
    "",
    "",
)

# Header names are compared after removing accents, case and punctuation, so
# "Tên sản phẩm", "ten san pham" and "TEN_SAN_PHAM" all match.
_COLUMN_ALIASES = {
    "name": {
        "ten_san_pham", "san_pham", "ten", "ten_sp", "chu_de", "name",
        "product", "product_name", "video_subject", "subject",
    },
    "price": {
        "gia", "gia_ban", "gia_khuyen_mai", "gia_sale", "price", "sale_price",
    },
    "original_price": {"gia_goc", "gia_cu", "original_price", "old_price"},
    "hook": {"cau_mo_dau", "mo_dau", "hook", "hooks", "hook_text"},
    "link": {
        "link", "link_affiliate", "link_shopee", "affiliate_link", "url",
    },
    "images": {
        "thu_muc_anh", "anh", "hinh_anh", "thu_muc", "images", "image_folder",
        "folder", "materials",
    },
    "script": {"kich_ban", "noi_dung", "script", "video_script"},
    "cta": {"keu_goi", "loi_keu_goi", "cau_keu_goi", "cta", "cta_text"},
}

_SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class ProductSheetError(ValueError):
    """The uploaded product list cannot be used; the message is user-facing."""


@dataclass
class ProductRow:
    line: int
    name: str
    price: str = ""
    original_price: str = ""
    hook: str = ""
    link: str = ""
    images: str = ""
    script: str = ""
    cta: str = ""
    errors: list[str] = field(default_factory=list)


def template_csv() -> bytes:
    """A ready-to-fill CSV. The BOM lets Excel show Vietnamese correctly."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerow(_TEMPLATE_EXAMPLE)
    return buffer.getvalue().encode("utf-8-sig")


def _normalize_header(value: str) -> str:
    text = str(value or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _column_map(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(headers):
        normalized = _normalize_header(header)
        for column, aliases in _COLUMN_ALIASES.items():
            if normalized in aliases and column not in mapping:
                mapping[column] = index
    if "name" not in mapping:
        raise ProductSheetError(
            "File thiếu cột tên sản phẩm (ten_san_pham). Hãy dùng file mẫu."
        )
    return mapping


def format_price(value: str) -> str:
    """Show plain numbers like 59000 as "59.000đ"; keep anything else as typed."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d+(\.0+)?", text):
        amount = int(float(text))
        return f"{amount:,}".replace(",", ".") + "đ"
    return text


def _clean_cell(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    # Excel stores whole numbers typed into a cell as floats ("59000.0").
    if re.fullmatch(r"-?\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text


def _read_csv(data: bytes) -> list[list[str]]:
    for encoding in ("utf-8-sig", "cp1258", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes almost anything
        raise ProductSheetError("Không đọc được file CSV (cần mã hoá UTF-8).")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref or "")
    if not letters:
        return -1
    index = 0
    for letter in letters.group(0):
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


def _read_zip_part(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > _MAX_XLSX_PART_BYTES:
        raise ProductSheetError("File Excel quá lớn.")
    return archive.read(name)


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    try:
        workbook = ElementTree.fromstring(_read_zip_part(archive, "xl/workbook.xml"))
        rels = ElementTree.fromstring(
            _read_zip_part(archive, "xl/_rels/workbook.xml.rels")
        )
        sheet = workbook.find(f"{_SPREADSHEET_NS}sheets/{_SPREADSHEET_NS}sheet")
        rel_id = sheet.get(f"{_REL_NS}id") if sheet is not None else None
        for rel in rels.iter(f"{_PACKAGE_REL_NS}Relationship"):
            if rel.get("Id") == rel_id:
                target = rel.get("Target", "").lstrip("/")
                if not target.startswith("xl/"):
                    target = posixpath.normpath(posixpath.join("xl", target))
                return target
    except KeyError:
        pass
    return "xl/worksheets/sheet1.xml"


def _read_xlsx(data: bytes) -> list[list[str]]:
    """Read the first worksheet without extra dependencies (no openpyxl)."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ProductSheetError("File Excel bị lỗi hoặc không phải .xlsx.") from exc
    with archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(
                _read_zip_part(archive, "xl/sharedStrings.xml")
            )
            for item in root.iter(f"{_SPREADSHEET_NS}si"):
                shared.append(
                    "".join(t.text or "" for t in item.iter(f"{_SPREADSHEET_NS}t"))
                )
        try:
            sheet = ElementTree.fromstring(
                _read_zip_part(archive, _first_sheet_path(archive))
            )
        except KeyError as exc:
            raise ProductSheetError("File Excel không có trang tính nào.") from exc

    rows: list[list[str]] = []
    for row in sheet.iter(f"{_SPREADSHEET_NS}row"):
        values: dict[int, str] = {}
        for position, cell in enumerate(row.iter(f"{_SPREADSHEET_NS}c")):
            column = _column_index(cell.get("r", ""))
            if column < 0:
                column = position
            cell_type = cell.get("t", "n")
            if cell_type == "inlineStr":
                value = "".join(
                    t.text or "" for t in cell.iter(f"{_SPREADSHEET_NS}t")
                )
            else:
                raw = cell.findtext(f"{_SPREADSHEET_NS}v") or ""
                if cell_type == "s":
                    try:
                        value = shared[int(raw)]
                    except (ValueError, IndexError):
                        value = ""
                elif cell_type == "b":
                    value = "TRUE" if raw == "1" else "FALSE"
                else:
                    value = raw
            values[column] = value
        if values:
            width = max(values) + 1
            rows.append([values.get(index, "") for index in range(width)])
    return rows


def parse_product_sheet(filename: str, data: bytes) -> list[ProductRow]:
    if len(data) > MAX_SHEET_BYTES:
        raise ProductSheetError("File danh sách sản phẩm vượt quá 2 MB.")
    extension = os.path.splitext(filename or "")[1].lower()
    if extension == ".xlsx":
        table = _read_xlsx(data)
    elif extension in {".csv", ".txt"}:
        table = _read_csv(data)
    else:
        raise ProductSheetError("Chỉ hỗ trợ file .xlsx hoặc .csv.")

    table = [row for row in table if any(_clean_cell(cell) for cell in row)]
    if len(table) < 2:
        raise ProductSheetError("File cần có dòng tiêu đề và ít nhất một sản phẩm.")
    mapping = _column_map(table[0])

    products: list[ProductRow] = []
    for line, row in enumerate(table[1:], start=2):
        def cell(column: str) -> str:
            index = mapping.get(column)
            if index is None or index >= len(row):
                return ""
            return _clean_cell(row[index])

        product = ProductRow(
            line=line,
            name=cell("name"),
            price=format_price(cell("price")),
            original_price=format_price(cell("original_price")),
            hook=cell("hook"),
            link=cell("link"),
            images=cell("images"),
            script=cell("script"),
            cta=cell("cta"),
        )
        if not product.name and not product.script:
            product.errors.append("thiếu tên sản phẩm")
        products.append(product)

    if len(products) > MAX_ROWS:
        raise ProductSheetError(
            f"Mỗi lần chỉ làm tối đa {MAX_ROWS} sản phẩm; file có {len(products)}."
        )
    return products


def hook_text_from_cell(value: str) -> str:
    """Several hooks in one cell (separated by | or new lines) become variants."""
    parts = re.split(r"\s*\|\s*|\r?\n", value or "")
    return "\n".join(part.strip() for part in parts if part.strip())


def material_paths(images: str) -> list[str]:
    """Image/video files from a folder, or from a ;-separated list of files."""
    supported = material_upload.SUPPORTED_MATERIAL_EXTENSIONS
    paths: list[str] = []
    for entry in re.split(r"\s*;\s*", images or ""):
        entry = os.path.expanduser(entry.strip().strip('"').strip("'"))
        if not entry:
            continue
        if os.path.isdir(entry):
            for name in sorted(os.listdir(entry), key=str.lower):
                full_path = os.path.join(entry, name)
                if os.path.isfile(full_path) and name.lower().endswith(supported):
                    paths.append(full_path)
        elif os.path.isfile(entry) and entry.lower().endswith(supported):
            paths.append(entry)
        else:
            raise ProductSheetError(f"không tìm thấy ảnh ở: {entry}")
    if len(paths) > MAX_IMAGES_PER_PRODUCT:
        paths = paths[:MAX_IMAGES_PER_PRODUCT]
    return paths


def check_product(product: ProductRow, base: VideoParams) -> list[str]:
    """Problems that would stop this row; checked before anything is queued."""
    errors = list(product.errors)
    if product.images:
        try:
            if not material_paths(product.images):
                errors.append("thư mục không có ảnh/clip")
        except ProductSheetError as exc:
            errors.append(str(exc))
    elif base.video_source == "local":
        errors.append("thiếu thư mục ảnh (cột thu_muc_anh)")
    elif base.video_source not in BATCH_STOCK_SOURCES:
        # Paid generators need a per-request quote and confirmation in the
        # form; a spreadsheet must never start those charges by itself.
        errors.append("nguồn video này không hỗ trợ làm hàng loạt, hãy thêm thư mục ảnh")
    return errors


def _import_materials(paths: list[str]) -> list[MaterialInfo]:
    """Copy (and convert WebP to PNG) through the same checks as WebUI uploads."""
    directory = material_upload.uploaded_material_dir(create=True)
    materials = []
    for path in paths:
        with open(path, "rb") as source:
            stored_name = material_upload.save_material_upload(
                os.path.basename(path), source
            )
        material = MaterialInfo()
        material.provider = "local"
        material.url = os.path.join(directory, stored_name)
        materials.append(material)
    return materials


def build_product_params(base: VideoParams, product: ProductRow) -> VideoParams:
    """The form's settings with this product's subject, prices, hook and photos."""
    params = base.model_copy(deep=True)
    params.video_subject = product.name or params.video_subject
    # Each product needs its own script; never reuse the one typed in the form.
    params.video_script = product.script
    params.video_terms = None
    params.hook_text = hook_text_from_cell(product.hook)
    params.price_text = product.price
    params.original_price_text = product.original_price
    params.affiliate_link = product.link
    if product.cta:
        params.cta_text = product.cta
    params.custom_audio_file = None
    if product.images:
        params.video_source = "local"
        params.video_materials = _import_materials(material_paths(product.images))
    elif params.video_source != "local":
        params.video_materials = None
    return params
