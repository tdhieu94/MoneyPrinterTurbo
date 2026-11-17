import io
import os
import zipfile

import pytest
from PIL import Image

from app.models.schema import VideoParams
from app.services import material_upload, product_batch


def _xlsx(rows):
    """Write a minimal .xlsx with shared and inline strings plus numbers."""
    shared = []
    sheet_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(ord('A') + c)}{r}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            elif c % 2:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
            else:
                shared.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook {ns} {rel_ns}><sheets><sheet name="SP" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/data.xml" Type="worksheet"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>",
        )
        archive.writestr(
            "xl/worksheets/data.xml",
            f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>',
        )
    return buffer.getvalue()


def test_template_round_trips_through_the_parser():
    rows = product_batch.parse_product_sheet("mau.csv", product_batch.template_csv())
    assert len(rows) == 1
    assert rows[0].name == "Khăn giấy Top Gia 10 gói"
    assert rows[0].price == "59.000đ"
    assert rows[0].original_price == "89.000đ"


def test_xlsx_with_vietnamese_headers_and_numeric_prices():
    data = _xlsx(
        [
            ["Tên sản phẩm", "Giá", "Giá gốc", "Câu mở đầu"],
            ["Nồi chiên", 459000, "599k", "Mẹo 1|Mẹo 2"],
            ["Ấm siêu tốc", 129000.0, "", ""],
        ]
    )
    rows = product_batch.parse_product_sheet("sp.xlsx", data)
    assert [r.name for r in rows] == ["Nồi chiên", "Ấm siêu tốc"]
    assert rows[0].price == "459.000đ"
    assert rows[0].original_price == "599k"
    assert rows[1].price == "129.000đ"
    assert product_batch.hook_text_from_cell(rows[0].hook) == "Mẹo 1\nMẹo 2"


def test_semicolon_csv_and_missing_name_column():
    rows = product_batch.parse_product_sheet(
        "a.csv", "ten;gia\nKem chống nắng;99000\n".encode("utf-8")
    )
    assert rows[0].name == "Kem chống nắng"
    with pytest.raises(product_batch.ProductSheetError):
        product_batch.parse_product_sheet("a.csv", b"gia,link\n1,2\n")
    with pytest.raises(product_batch.ProductSheetError):
        product_batch.parse_product_sheet("a.pdf", b"x")


def test_row_limit():
    body = "ten\n" + "\n".join(f"sp {i}" for i in range(product_batch.MAX_ROWS + 1))
    with pytest.raises(product_batch.ProductSheetError):
        product_batch.parse_product_sheet("a.csv", body.encode())


def test_build_params_imports_folder_images(tmp_path, monkeypatch):
    folder = tmp_path / "anh"
    folder.mkdir()
    Image.new("RGB", (40, 40), "red").save(folder / "b.webp", "WEBP")
    Image.new("RGB", (40, 40), "blue").save(folder / "a.jpg", "JPEG")
    (folder / "ghi-chu.txt").write_text("x")
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(
        material_upload, "uploaded_material_dir", lambda create=True: str(storage)
    )

    base = VideoParams(
        video_subject="cũ",
        video_script="kịch bản cũ",
        video_source="pexels",
        cta_text="Mua ngay",
    )
    row = product_batch.ProductRow(
        line=2,
        name="Nồi chiên",
        price="459.000đ",
        hook="Mẹo 1|Mẹo 2",
        link="https://s.shopee.vn/abc",
        images=str(folder),
    )
    assert product_batch.check_product(row, base) == []
    params = product_batch.build_product_params(base, row)

    assert params.video_subject == "Nồi chiên"
    assert params.video_script == ""
    assert params.hook_text == "Mẹo 1\nMẹo 2"
    assert params.cta_text == "Mua ngay"
    assert params.video_source == "local"
    names = [os.path.basename(m.url) for m in params.video_materials]
    assert len(names) == 2
    assert all(os.path.isfile(m.url) for m in params.video_materials)
    assert not any(name.endswith(".webp") for name in names)
    assert base.video_script == "kịch bản cũ"


def test_check_product_reports_missing_images(tmp_path):
    local = VideoParams(video_subject="x", video_source="local")
    row = product_batch.ProductRow(line=3, name="A")
    assert product_batch.check_product(row, local)
    row.images = str(tmp_path / "khong-co")
    assert product_batch.check_product(row, VideoParams(video_subject="x"))
    paid = VideoParams(video_subject="x", video_source="wavespeed")
    assert product_batch.check_product(product_batch.ProductRow(line=4, name="B"), paid)
