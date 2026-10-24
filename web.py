"""
web.py - Giao diện web cho cw_scanner (chỉ dùng thư viện có sẵn của Python, không cần cài thêm).

Cách chạy:  python web.py   -> trình duyệt tự mở http://localhost:8000
- Trang chính: bấm "Quét ngay" để chạy cw_scanner.main(); luôn hiển thị kết quả mới nhất trong ket_qua/.
- Bấm vào một mã CW: trang phân tích chi tiết (biểu đồ, kịch bản lãi/lỗ, so sánh các CW cùng mã cơ sở).
- Trang "Hướng dẫn sử dụng" (/huong-dan): giải thích cho người mới, có đường dẫn ở đầu mọi trang.
"""

import contextlib
import html
import io
import json
import math
import re
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import pandas as pd

import chiet_khau
import cw_scanner
import danh_muc
import etf

CONG = 8000
VON_MAC_DINH = 10  # triệu đồng: số tiền mặc định ở mục "Rủi ro với số tiền của bạn"
BO_NHO_IV = {}  # (mã CW, ngày) -> [[ngày, IV %]]: lịch sử giá CW chỉ tải 1 lần mỗi ngày
LOI = ""  # lỗi của lần quét gần nhất (chỉ 1 người dùng trên máy mình nên dùng biến toàn cục là đủ)
NHAT_KY = ""  # mọi dòng cw_scanner in ra trong lần quét gần nhất
LOI_DANH_MUC = ""  # lỗi của lần thêm/xóa lệnh gần nhất (hiện 1 lần ở trang Danh mục)
ESC = html.escape
# kết luận -> (lớp màu, biểu tượng, nhãn). Màu luôn đi kèm biểu tượng + chữ, không dùng màu một mình
KET_LUAN = {
    "NÊN XEM XÉT": ("tot", "✓", "Nên xem xét"),
    "THEO DÕI": ("canh-bao", "!", "Theo dõi"),
    "BỎ QUA": ("bo-qua", "✕", "Bỏ qua"),
}
# Các cột của bảng danh sách: (tiêu đề, căn lề, giải thích cho người mới - hiện khi rê chuột lên tiêu đề và ở trang Hướng dẫn)
COT = [
    (
        "Mã CW",
        "",
        "Mã chứng quyền: C + mã cổ phiếu + năm phát hành + số thứ tự. Ví dụ CVPB2615 là CW của VPB phát hành năm 2026.",
    ),
    ("Mã CS", "", "Mã cổ phiếu cơ sở - cổ phiếu mà chứng quyền dựa vào."),
    ("TCPH", "", "Tổ chức phát hành (công ty chứng khoán). Đây cũng là bên đặt giá mua/bán CW trên sàn."),
    ("Còn (ngày)", "so", "Số ngày còn lại đến ngày đáo hạn. Càng ít ngày, CW mất giá theo thời gian càng nhanh."),
    (
        "Giá mua",
        "so",
        (
            "Giá thấp nhất đang chào bán trong sổ lệnh lúc quét (đồng/CW) - giá bạn phải trả nếu mua ngay. "
            "Sổ lệnh trống thì dùng giá khớp gần nhất (ghi “khớp”) hoặc giá tham chiếu (ghi “TC”). Mọi chỉ số định giá đều tính theo giá này."
        ),
    ),
    (
        "Giá hợp lý",
        "so",
        "Giá 1 CW tính bằng công thức Black-Scholes từ giá cổ phiếu, giá thực hiện, thời gian còn lại và mức dao động của cổ phiếu 1 năm qua.",
    ),
    (
        "So với giá hợp lý",
        "so",
        (
            "Rẻ = giá mua thấp hơn giá hợp lý (có lợi cho người mua). Đắt = cao hơn giá hợp lý. "
            "Chỉ để tham khảo: tiêu chí chấm điểm dùng cột IV − HV."
        ),
    ),
    ("IV", "so", "Biến động ngầm định (%/năm): mức dao động của cổ phiếu cơ sở mà giá mua CW đang “giả định”."),
    (
        "IV − HV",
        "so",
        (
            "IV trừ biến động lịch sử 1 năm (HV), tính bằng điểm %. Âm = giá CW đang giả định cổ phiếu dao động ít hơn 1 năm qua (rẻ), "
            f"dương = nhiều hơn (đắt). Dùng để so sánh các CW với nhau, kể cả CW ở xa giá thực hiện. Tiêu chí: ≤ {cw_scanner.MAX_IV_TRU_HV * 100:+.0f} điểm. "
            "“—” = không giải được (rê chuột lên ô để xem lý do)."
        ),
    ),
    (
        "CS cần tăng để hòa vốn",
        "so",
        "Cổ phiếu cơ sở phải tăng bấy nhiêu % tính đến ngày đáo hạn thì bạn mới hòa vốn (tính theo giá mua). Số càng nhỏ càng dễ có lãi.",
    ),
    (
        "Đòn bẩy",
        "so",
        "Cổ phiếu tăng (hoặc giảm) 1% thì CW tăng (hoặc giảm) khoảng bấy nhiêu %. Đòn bẩy cao: lãi nhanh nhưng lỗ cũng nhanh.",
    ),
    (
        "Delta",
        "so",
        "Từ 0 đến 1: cổ phiếu tăng 1 đ thì giá trị quyền trên 1 cổ phiếu tăng bấy nhiêu đ. Gần 1: CW bám sát cổ phiếu; gần 0: gần như không phản ứng.",
    ),
    ("KL khớp", "so", "Số CW đã khớp lệnh trong phiên. Càng nhiều càng dễ mua/bán đúng giá."),
    (
        "Đang chào bán",
        "so",
        "Tổng số CW đang được rao bán ở 3 mức giá thấp nhất trong sổ lệnh (lúc quét) - lượng bạn có thể mua ngay.",
    ),
    ("Đánh giá", "", "Kết luận theo 4 tiêu chí: Nên xem xét (đạt cả 4) / Theo dõi (trượt 1) / Bỏ qua (trượt từ 2)."),
    ("Lý do", "", "Những tiêu chí mà CW bị trượt."),
]

# Màu theo bảng màu đã kiểm định cho người mù màu (sáng/tối)
CSS = """
:root { color-scheme: light; --nen:#f9f9f7; --be-mat:#fcfcfb; --chu:#0b0b0b; --chu-phu:#52514e; --chu-mo:#898781;
  --luoi:#e1e0d9; --truc:#c3c2b7; --vien:rgba(11,11,11,.10); --xanh:#2a78d6; --cam:#eb6834; --lien-ket:#1c5cab;
  --tot:#0ca30c; --canh-bao:#fab219; --chu-duong:#006300; --chu-am:#c62f2f; --nut:#256abf; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark; --nen:#0d0d0d; --be-mat:#1a1a19;
  --chu:#f0efec; --chu-phu:#c3c2b7; --luoi:#2c2c2a; --truc:#383835; --vien:rgba(255,255,255,.10); --xanh:#3987e5;
  --cam:#d95926; --lien-ket:#86b6ef; --chu-duong:#0ca30c; --chu-am:#e66767; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--nen); color: var(--chu); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }
a { color: var(--lien-ket); }
h1 { font-size: 26px; margin: 0; line-height: 1.25; }
h2 { font-size: 18px; margin: 0; }
.phu { color: var(--chu-phu); margin: 4px 0 0; font-size: 14px; }
.dau-trang { display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; align-items: flex-start; }
.nut { background: var(--nut); color: #fff; border: 0; border-radius: 8px; padding: 10px 22px; font: 600 15px system-ui, sans-serif; cursor: pointer; }
.nut:disabled { opacity: .6; cursor: wait; }
.the { background: var(--be-mat); border: 1px solid var(--vien); border-radius: 12px; padding: 20px; margin-top: 16px; }
.luoi-o { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin-top: 16px; }
.o-so { background: var(--be-mat); border: 1px solid var(--vien); border-radius: 12px; padding: 14px 16px; }
.o-so .nhan { color: var(--chu-phu); font-size: 13px; }
.o-so .gia-tri { font-size: 24px; font-weight: 600; margin-top: 2px; }
.o-so .goi-y { color: var(--chu-phu); font-size: 13px; margin-top: 2px; }
.cuon { overflow: auto; margin-top: 12px; }
.cuon.cao { max-height: 560px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; white-space: nowrap; }
th { position: sticky; top: 0; background: var(--be-mat); color: var(--chu-phu); font-weight: 600; text-align: left;
  padding: 8px 10px; border-bottom: 1px solid var(--truc); }
td { padding: 8px 10px; border-bottom: 1px solid var(--luoi); }
.so { text-align: right; font-variant-numeric: tabular-nums; }
th button { all: unset; cursor: pointer; }
th button:focus-visible { outline: 2px solid var(--lien-ket); outline-offset: 2px; border-radius: 2px; }
th button::after { content: " ↕"; color: var(--chu-mo); }
th[aria-sort="ascending"] button::after { content: " ▲"; color: var(--chu); }
th[aria-sort="descending"] button::after { content: " ▼"; color: var(--chu); }
tr[data-href] { cursor: pointer; }
tbody tr:hover, tr.dang-xem { background: color-mix(in srgb, var(--xanh) 9%, transparent); }
td a { font-weight: 600; text-decoration: none; }
td a:hover { text-decoration: underline; }
.ly-do { color: var(--chu-phu); white-space: normal; min-width: 220px; font-size: 13px; }
.duong { color: var(--chu-duong); }
.am { color: var(--chu-am); }
.huy-hieu { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px 2px 8px; border-radius: 999px; font-size: 13px;
  font-weight: 600; background: color-mix(in srgb, var(--mau) 15%, transparent); white-space: nowrap; }
.huy-hieu span { color: var(--mau); font-weight: 800; }
.huy-hieu.lon { font-size: 15px; padding: 4px 14px 4px 10px; }
.tot { --mau: var(--tot); } .canh-bao { --mau: var(--canh-bao); } .bo-qua { --mau: var(--chu-mo); }
.chip { font-size: 11px; font-weight: 700; color: var(--lien-ket); border: 1px solid currentColor; border-radius: 4px; padding: 0 4px; margin-left: 6px; }
.loi { color: var(--chu-am); font-weight: 600; }
summary { cursor: pointer; color: var(--chu-phu); font-weight: 600; }
pre { white-space: pre-wrap; font-size: 12px; color: var(--chu-phu); margin: 8px 0 0; }
input[type=search] { width: 100%; max-width: 360px; padding: 8px 12px; border: 1px solid var(--truc); border-radius: 8px;
  background: var(--be-mat); color: var(--chu); font: inherit; margin-top: 12px; }
.tieu-chi { list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 6px; }
.tieu-chi b { display: inline-block; width: 1.4em; }
.tieu-chi small { color: var(--chu-phu); }
.cong-thuc { font-size: 17px; font-weight: 600; padding: 12px 16px; border-radius: 8px; max-width: 860px;
  background: color-mix(in srgb, var(--xanh) 9%, transparent); }
.cac-buoc { list-style: none; padding: 0; margin: 12px 0 0; max-width: 900px; }
.cac-buoc li { margin: 0 0 12px; padding-left: 12px; border-left: 3px solid var(--luoi); }
.tom-tat { font-size: 16px; margin: 12px 0 0; max-width: 860px; }
.cuon-bieu-do { overflow-x: auto; margin-top: 8px; }
.bieu-do { position: relative; min-width: 760px; }
.bieu-do svg { width: 100%; height: auto; display: block; }
.bieu-do line, .bieu-do polyline, .bieu-do circle { vector-effect: non-scaling-stroke; }
.bieu-do svg:focus-visible { outline: 2px solid var(--lien-ket); outline-offset: 4px; border-radius: 4px; }
.luoi-ngang { stroke: var(--luoi); stroke-width: 1; }
.truc { stroke: var(--truc); stroke-width: 1; }
.nhan-truc { fill: var(--chu-mo); font-size: 12px; font-variant-numeric: tabular-nums; }
.duong-gia { fill: none; stroke: var(--xanh); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.diem { fill: var(--xanh); stroke: var(--be-mat); stroke-width: 2; }
.tc-thuc-hien { stroke: var(--chu-mo); stroke-width: 1.5; }
.tc-hoa-von { stroke: var(--cam); stroke-width: 1.5; }
.ma-ngan { fill: none; stroke: var(--cam); stroke-width: 1.5; }
.ma-dai { fill: none; stroke: var(--chu-mo); stroke-width: 1.5; stroke-dasharray: 5 4; }
.dan { stroke: var(--truc); stroke-width: 1; }
.nhan-tc { fill: var(--chu-phu); font-size: 12px; }
.gia-tc { fill: var(--chu); font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tro { stroke: var(--chu-mo); stroke-width: 1; visibility: hidden; }
.diem-tro { visibility: hidden; }
.o-tro { position: absolute; transform: translate(-50%, calc(-100% - 14px)); background: var(--be-mat); border: 1px solid var(--vien);
  border-radius: 8px; padding: 6px 10px; font-size: 13px; pointer-events: none; box-shadow: 0 2px 8px rgba(0,0,0,.15); white-space: nowrap; }
.o-tro.duoi { transform: translate(-50%, 14px); }
.o-tro b { display: block; font-size: 14px; }
.ghi-chu-canh-bao { border-left: 4px solid var(--canh-bao); padding: 8px 12px; margin: 12px 0 0;
  background: color-mix(in srgb, var(--canh-bao) 10%, transparent); border-radius: 4px; }
.o-tro span { color: var(--chu-phu); }
dl.dieu-khoan { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px 24px; margin: 12px 0 0; }
dl.dieu-khoan dt { color: var(--chu-phu); font-size: 13px; }
dl.dieu-khoan dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
tr.hang-goc td { font-weight: 600; background: color-mix(in srgb, var(--xanh) 9%, transparent); }
.thanh-tren { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-bottom: 12px; font-size: 14px; font-weight: 600; }
.thanh-tren a { text-decoration: none; }
.thanh-tren a[aria-current] { color: var(--chu); border-bottom: 2px solid var(--nut); }
.huong-dan p, .huong-dan li { max-width: 860px; }
.huong-dan h2 { margin-bottom: 8px; }
.huong-dan li { margin: 6px 0; }
.bang-chu td, .bang-chu th { white-space: normal; vertical-align: top; }
.muc-luc { columns: 2 240px; margin: 8px 0 0; }
footer { color: var(--chu-phu); font-size: 12px; margin-top: 32px; }
.form-lenh label { display: inline-flex; flex-direction: column; gap: 2px; margin: 10px 12px 0 0; font-size: 13px; color: var(--chu-phu); }
.form-lenh input, .form-lenh select { padding: 6px 8px; border: 1px solid var(--truc); border-radius: 6px; background: var(--be-mat); color: var(--chu); font: inherit; }
.nut-nho { all: unset; cursor: pointer; color: var(--chu-am); font-size: 13px; text-decoration: underline; }
"""

JS = """
// Bấm vào cả dòng để mở trang chi tiết (đường link trong ô mã vẫn dùng được bằng bàn phím)
document.querySelectorAll("tr[data-href]").forEach(tr => tr.addEventListener("click", e => {
  if (!e.target.closest("a")) location.href = tr.dataset.href;
}));
// Bấm tiêu đề cột để sắp xếp tăng dần, bấm lần nữa để đảo chiều. Ô có data-v thì so số gốc, còn lại so chữ
document.querySelectorAll("th button").forEach(nut => nut.addEventListener("click", () => {
  const th = nut.parentElement, bang = th.closest("table"), cot = th.cellIndex;
  const tang = th.getAttribute("aria-sort") !== "ascending";
  bang.querySelectorAll("th").forEach(o => o.removeAttribute("aria-sort"));
  th.setAttribute("aria-sort", tang ? "ascending" : "descending");
  const gt = tr => tr.cells[cot].dataset.v ?? tr.cells[cot].textContent.trim();
  const dong = [...bang.tBodies[0].rows].sort((a, b) => {
    const x = gt(a), y = gt(b), kq = isNaN(x) || isNaN(y) ? x.localeCompare(y, "vi") : x - y;
    return tang ? kq : -kq;
  });
  bang.tBodies[0].append(...dong);
}));
// Ô tìm kiếm: ẩn các dòng không chứa chữ cần tìm
document.querySelectorAll("input[data-loc]").forEach(o => o.addEventListener("input", () => {
  const q = o.value.trim().toUpperCase();
  document.querySelectorAll(o.dataset.loc + " tbody tr").forEach(tr => { tr.hidden = q && !tr.textContent.toUpperCase().includes(q); });
}));
// Biểu đồ: đường dọc bám theo chuột (hoặc phím mũi tên) và hiện giá của ngày gần nhất
document.querySelectorAll(".bieu-do").forEach(khung => {
  const svg = khung.querySelector("svg"), diem = JSON.parse(khung.querySelector("script").textContent);
  const tro = svg.querySelector(".tro"), cham = svg.querySelector(".diem-tro"), hop = khung.querySelector(".o-tro");
  const rong = svg.viewBox.baseVal.width;
  let chiSo = diem.length - 1;
  khung.parentElement.scrollLeft = khung.parentElement.scrollWidth;  // màn hình hẹp: mở ở phần giá mới nhất
  const hien = i => {
    chiSo = Math.max(0, Math.min(diem.length - 1, i));
    const [x, y, ngay, gia] = diem[chiSo], ty = svg.getBoundingClientRect().width / rong;
    tro.setAttribute("x1", x); tro.setAttribute("x2", x); cham.setAttribute("cx", x); cham.setAttribute("cy", y);
    tro.style.visibility = cham.style.visibility = "visible";
    hop.querySelector("b").textContent = gia.toLocaleString("vi-VN") + " " + khung.dataset.donVi;
    hop.querySelector("span").textContent = ngay.split("-").reverse().join("/");
    hop.style.left = x * ty + "px"; hop.style.top = y * ty + "px"; hop.hidden = false;
    hop.classList.toggle("duoi", y * ty < 70);  // sát mép trên thì hiện bên dưới điểm để không bị che
  };
  const an = () => { tro.style.visibility = cham.style.visibility = "hidden"; hop.hidden = true; };
  svg.addEventListener("pointermove", e => {
    const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) * rong / r.width;
    let gan = 0;
    diem.forEach((d, i) => { if (Math.abs(d[0] - x) < Math.abs(diem[gan][0] - x)) gan = i; });
    hien(gan);
  });
  svg.addEventListener("pointerleave", an);
  svg.addEventListener("blur", an);
  svg.addEventListener("focus", () => hien(chiSo));
  svg.addEventListener("keydown", e => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); hien(chiSo + (e.key === "ArrowLeft" ? -1 : 1)); }
  });
});
"""


# ============ ĐỊNH DẠNG ============
def so(x, le=0, dau=False):
    """Số kiểu Việt Nam: 1.234.567 và 12,5 (dau=True: luôn có dấu + hoặc -)."""
    if not math.isfinite(x):
        return "—"
    return f"{x:{'+' if dau else ''},.{le}f}".translate(str.maketrans(",.", ".,"))


def dat_re(phan_tram):
    """(-36.2) -> ('Rẻ 36,2%', lớp màu). Có chữ Rẻ/Đắt nên không phụ thuộc vào màu."""
    if not math.isfinite(phan_tram):
        return "—", ""
    if phan_tram > 1000:  # giá hợp lý gần 0 đ (CW gần hết hạn, quá xa giá thực hiện): con số % không còn ý nghĩa
        return "Đắt > 1.000%", "am"
    lop = "duong" if phan_tram < 0 else ("am" if phan_tram > 0 else "")
    return f"{'Rẻ' if phan_tram < 0 else 'Đắt'} {so(abs(phan_tram), 1)}%", lop


def huy_hieu(ket_luan, lon=False):
    lop, bieu_tuong, nhan = KET_LUAN.get(ket_luan, ("bo-qua", "", ket_luan))
    return f'<span class="huy-hieu {lop}{" lon" if lon else ""}"><span aria-hidden="true">{bieu_tuong}</span>{ESC(nhan)}</span>'


def o_so(nhan, gia_tri, goi_y=""):
    return f'<div class="o-so"><div class="nhan">{nhan}</div><div class="gia-tri">{gia_tri}</div><div class="goi-y">{goi_y}</div></div>'


def trang(tieu_de, than, duong_dan=""):
    """Khung chung của mọi trang: thanh điều hướng trên cùng + nội dung + lưu ý cuối trang."""
    menu = "".join(
        f'<a href="{dd}"{" aria-current=page" if dd == duong_dan else ""}>{ten}</a>'
        for dd, ten in (
            ("/", "Chứng quyền"),
            ("/danh-muc", "💼 Danh mục"),
            ("/luot-cw", "⚡ Lướt CW"),
            ("/etf", "📊 ETF"),
            ("/sap-ra-mat", "🆕 Sắp ra mắt"),
            ("/huong-dan", "❓ Hướng dẫn"),
        )
    )
    return (
        f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{ESC(tieu_de)}</title><link rel="icon" href="data:,"><style>{CSS}</style></head><body><main>'
        f'<nav class="thanh-tren" aria-label="Điều hướng">{menu}</nav>{than}'
        f"<footer>Công cụ sàng lọc theo mô hình Black-Scholes, không phải khuyến nghị đầu tư. Luôn kiểm tra điều khoản CW trên website "
        f"tổ chức phát hành / HOSE trước khi mua. 4 tiêu chí chấm điểm chưa tính phí giao dịch và thuế.</footer></main><script>{JS}</script></body></html>"
    )


# ============ DỮ LIỆU ============
def doc_von(duong_dan):
    """?von=50 -> 50 (triệu đồng). Chỉ nhận số nguyên 1..10.000, sai thì về mặc định (chặn dữ liệu lạ từ URL)."""
    chuoi = (parse_qs(urlsplit(duong_dan).query).get("von") or [""])[0]
    return int(chuoi) if chuoi.isdigit() and 1 <= int(chuoi) <= 10_000 else VON_MAC_DINH


COT_SO_LUOT = (  # cột số của phần lướt sóng (cw_scanner.dinh_gia); ô trống = không tính được
    "Giá chờ mua",
    "Spread %",
    "Bên mua 3 bước (triệu)",
    "Mất giá/ngày %",
    "Lướt: CS cần tăng %",
    "Lướt: lãi kịch bản %",
)


def doc_ket_qua():
    """(bảng kết quả mới nhất, ngày quét) hoặc (None, None) nếu chưa quét lần nào."""
    cac_file = sorted(cw_scanner.THU_MUC_KET_QUA.glob("cw_*.csv"))
    if not cac_file:
        return None, None
    # keep_default_na=False để ô chữ trống giữ là "", riêng 2 cột IV có ô trống (không giải được) thì đọc thành NaN
    df = pd.read_csv(
        cac_file[-1],
        encoding="utf-8-sig",
        keep_default_na=False,
        na_values={c: [""] for c in ("IV %", "IV − HV", "IV cùng mã %", *COT_SO_LUOT)},
    )
    for cot in (
        "KL niêm yết",
        "KL chào bán",
        "KL chờ mua",
        "Delta",
        "IV %",
        "IV − HV",
        "IV cùng mã %",
        *COT_SO_LUOT,
    ):  # file quét bằng bản cũ chưa có các cột này -> hiện "—"
        if cot not in df:
            df[cot] = math.nan
    if "Giá mua" not in df:  # bản cũ định giá theo giá khớp
        df["Giá mua"], df["Nguồn giá mua"] = df["Giá CW"], "khớp"
    for cot in ("Ghi chú IV", "Cảnh báo"):
        if cot not in df:
            df[cot] = ""
    return df, date.fromisoformat(cac_file[-1].stem[3:])


def bang(df, ma_dang_xem="", id_bang=""):
    """Bảng danh sách CW; bấm vào dòng hoặc mã để mở trang chi tiết."""
    v = lambda x: x if math.isfinite(x) else 1e18  # data-v: số gốc để sắp xếp đúng (chữ hiển thị là "1.240", "Rẻ 36%")
    dong = []
    for _, h in df.iterrows():
        ma = ESC(h["Mã CW"])
        chu_dat_re, lop = dat_re(h["Đắt/rẻ %"])
        moi = '<span class="chip">Mới</span>' if h["Mới"] == "MỚI" else ""
        if h["Cảnh báo"]:  # IV bất thường so với các CW cùng mã CS
            moi += f'<span class="chip" style="color:var(--chu-am)" title="{ESC(h["Cảnh báo"])}" aria-label="Cảnh báo: {ESC(h["Cảnh báo"])}">⚠</span>'
        nguon = {"khớp": ' <small class="phu">khớp</small>', "tham chiếu": ' <small class="phu">TC</small>'}.get(
            h["Nguồn giá mua"], ""
        )
        iv, iv_hv = h["IV %"], h["IV − HV"]
        o_iv = f'<td class="so" data-v="{v(iv)}">{so(iv, 0) + "%" if math.isfinite(iv) else "—"}</td>'
        o_iv_hv = (
            f'<td class="so {"duong" if iv_hv < 0 else "am" if iv_hv > 0 else ""}" data-v="{iv_hv}">{so(iv_hv, 1, True)}</td>'
            if math.isfinite(iv_hv)
            else f'<td class="so" data-v="{v(iv_hv)}" title="{ESC(h["Ghi chú IV"])}">—</td>'
        )
        dong.append(
            f'<tr data-href="/cw/{ma}"{" class=dang-xem" if h["Mã CW"] == ma_dang_xem else ""}>'
            f'<td><a href="/cw/{ma}">{ma}</a>{moi}</td><td>{ESC(h["Mã CS"])}</td><td>{ESC(h["TCPH"])}</td>'
            f'<td class="so" data-v="{h["Ngày còn lại"]}">{so(h["Ngày còn lại"])}</td>'
            f'<td class="so" data-v="{h["Giá mua"]}">{so(h["Giá mua"])}{nguon}</td><td class="so" data-v="{h["Giá hợp lý"]}">{so(h["Giá hợp lý"])}</td>'
            f'<td class="so {lop}" data-v="{v(h["Đắt/rẻ %"])}">{chu_dat_re}</td>{o_iv}{o_iv_hv}'
            f'<td class="so" data-v="{h["CS tăng % để hòa vốn"]}">{so(h["CS tăng % để hòa vốn"], 1, True)}%</td>'
            f'<td class="so" data-v="{h["Đòn bẩy"]}">{so(h["Đòn bẩy"], 1)}x</td>'
            f'<td class="so" data-v="{h["Delta"] if math.isfinite(h["Delta"]) else -1}">{so(h["Delta"], 2)}</td>'
            f'<td class="so" data-v="{h["KL khớp"]}">{so(h["KL khớp"])}</td>'
            f'<td class="so" data-v="{h["KL chào bán"] if math.isfinite(h["KL chào bán"]) else -1}">{so(h["KL chào bán"])}</td>'
            f'<td data-v="{list(KET_LUAN).index(h["Đánh giá"]) if h["Đánh giá"] in KET_LUAN else 9}">{huy_hieu(h["Đánh giá"])}</td>'
            f'<td class="ly-do">{ESC(h["Lý do"])}</td></tr>'
        )
    dau = "".join(
        f'<th class="{lop}"><button type="button" title="{ESC(giai_thich)} (Bấm để sắp xếp.)">{ten}</button></th>'
        for ten, lop, giai_thich in COT
    )
    return f'<table{f" id={id_bang}" if id_bang else ""}><thead><tr>{dau}</tr></thead><tbody>{"".join(dong)}</tbody></table>'


# ============ TRANG CHÍNH ============
def trang_chinh():
    df, ngay = doc_ket_qua()
    co_key = bool(cw_scanner.doc_env().get("VNSTOCK_API_KEY"))
    phan = [
        (
            '<div class="dau-trang"><div><h1>Quét chứng quyền</h1>'
            f'<p class="phu">{f"Dữ liệu ngày {ngay:%d/%m/%Y} · {len(df)} CW · định giá bằng Black-Scholes" if ngay else "Chưa có dữ liệu"}'
            f' · API key vnstock: {"đã nhập ✓" if co_key else "<b>chưa nhập</b> (mở file .env để điền)"}</p></div>'
            '<form method="post" action="/quet" onsubmit="this.nut.disabled = true; this.nut.textContent = \'Đang quét... (1-3 phút)\';">'
            '<button class="nut" name="nut">Quét ngay</button></form></div>'
        )
    ]
    if LOI:
        phan.append(f'<p class="loi" role="alert">{ESC(LOI)}</p>')
    if NHAT_KY:  # tự mở nhật ký nếu có cảnh báo [!]
        phan.append(
            f'<details class="the"{" open" if "[!]" in NHAT_KY else ""}><summary>Nhật ký lần quét gần nhất</summary><pre>{ESC(NHAT_KY)}</pre></details>'
        )
    if df is None:
        phan.append(
            '<div class="the"><h2>Chưa có kết quả</h2><p>Lần đầu dùng? Làm theo 3 bước:</p><ol>'
            "<li>Bấm nút <b>Quét ngay</b> ở góc trên bên phải và chờ 1-3 phút.</li>"
            "<li>Xem bảng <b>Nên xem xét</b> hiện ra - đó là những chứng quyền đạt cả 4 tiêu chí.</li>"
            "<li>Bấm vào một mã để xem phân tích chi tiết trước khi quyết định.</li></ol>"
            '<p>Chưa biết chứng quyền là gì? Đọc <a href="/huong-dan">Hướng dẫn sử dụng</a> (khoảng 5 phút).</p></div>'
        )
        return trang("Quét chứng quyền", "".join(phan), "/")

    dem = df["Đánh giá"].value_counts()
    moi, tot = df[df["Mới"] == "MỚI"], df[df["Đánh giá"] == "NÊN XEM XÉT"]
    phan.append(
        '<div class="luoi-o">'
        + "".join(o_so(huy_hieu(k), so(dem.get(k, 0))) for k in KET_LUAN)
        + o_so(
            "CW mới phát hành", so(len(moi)), 'so với lần quét trước · <a href="/sap-ra-mat">xem CW sắp ra mắt →</a>'
        )
        + "</div>"
    )
    phan.append(
        f'<p class="phu">Tiêu chí (tính theo giá mua = giá chào bán thấp nhất): còn ≥ {cw_scanner.MIN_NGAY_CON_LAI} ngày · IV − HV ≤ {so(cw_scanner.MAX_IV_TRU_HV * 100, 0, True)} điểm'
        f" · cổ phiếu cơ sở tăng ≤ {cw_scanner.MAX_TANG_DE_HOA_VON:.0%} là hòa vốn · khớp ≥ {so(cw_scanner.MIN_KHOI_LUONG)} CW/phiên."
        " Bấm vào một mã để xem phân tích chi tiết, rê chuột lên tiêu đề cột để xem giải thích."
        ' Chưa rõ cách dùng? Đọc <a href="/huong-dan">Hướng dẫn sử dụng</a>.</p>'
    )
    if len(moi):
        phan.append(
            f'<section class="the"><h2>CW mới phát hành ({len(moi)})</h2><div class="cuon">{bang(moi)}</div></section>'
        )
    phan.append(
        f'<section class="the"><h2>Nên xem xét ({len(tot)})</h2><p class="phu">Đạt cả 4 tiêu chí, xếp theo IV − HV (thấp nhất trước = rẻ nhất so với mức dao động 1 năm qua).</p>'
        + (f'<div class="cuon">{bang(tot)}</div>' if len(tot) else "<p>Hôm nay không có CW nào đạt cả 4 tiêu chí.</p>")
        + "</section>"
    )
    phan.append(
        f'<section class="the"><h2>Tất cả {len(df)} CW</h2>'
        '<input type="search" data-loc="#bang-tat-ca" placeholder="Tìm theo mã CW, mã cổ phiếu hoặc TCPH (vd: VPB, SSI)" aria-label="Tìm chứng quyền">'
        f'<div class="cuon cao">{bang(df, id_bang="bang-tat-ca")}</div></section>'
    )
    return trang("Quét chứng quyền", "".join(phan), "/")


# ============ TRANG CHI TIẾT ============
def bieu_do(lich_su, duong_ke, ten, don_vi="đ", ten_cot="Giá đóng cửa (đ)", duong_phu=(), so_le=0):
    """SVG một chuỗi số theo ngày [[ngày, giá trị]] + đường tham chiếu [(nhãn, giá trị, lớp)], kèm bảng dữ liệu cho người không xem được hình.
    duong_phu [(nhãn, [giá trị từng ngày hoặc None], lớp)]: đường vẽ cùng trục (vd MA50), nhãn ở mép phải. so_le: số lẻ khi hiện số.
    """
    R, C, TRAI, PHAI, TREN, DUOI = 900, 320, 60, 150, 16, 30
    gia = [g for _, g in lich_su]
    moi_so = gia + [v for _, v, _ in duong_ke] + [v for _, ds, _ in duong_phu for v in ds if v is not None]
    thap, cao = min(moi_so), max(moi_so)
    le = (cao - thap) * 0.06 or 1
    thap, cao = thap - le, cao + le
    x = lambda i: TRAI + i * (R - TRAI - PHAI) / max(len(gia) - 1, 1)
    y = lambda v: TREN + (cao - v) * (C - TREN - DUOI) / (cao - thap)
    # vạch trục tung tròn số: bước 1/2/2,5/5 x 10^n
    buoc_tho = (cao - thap) / 4
    mu = 10 ** math.floor(math.log10(buoc_tho))
    buoc = next(b * mu for b in (1, 2, 2.5, 5, 10) if b * mu >= buoc_tho)
    vach = [
        math.ceil(thap / buoc) * buoc + k * buoc for k in range(int((cao - math.ceil(thap / buoc) * buoc) // buoc) + 1)
    ]
    phan = [
        f'<line class="luoi-ngang" x1="{TRAI}" x2="{R - PHAI}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
        f'<text class="nhan-truc" x="{TRAI - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{so(v, so_le)}</text>'
        for v in vach
    ]
    phan.append(f'<line class="truc" x1="{TRAI}" x2="{R - PHAI}" y1="{C - DUOI}" y2="{C - DUOI}"/>')
    for i in sorted({0, len(gia) // 4, len(gia) // 2, 3 * len(gia) // 4, len(gia) - 1}):
        neo = "start" if i == 0 else ("end" if i == len(gia) - 1 else "middle")
        phan.append(
            f'<text class="nhan-truc" x="{x(i):.1f}" y="{C - 8}" text-anchor="{neo}">{lich_su[i][0][5:7]}/{lich_su[i][0][:4]}</text>'
        )
    # đường tham chiếu + nhãn bên phải; nhãn gần nhau thì đẩy ra và nối bằng đường dẫn (không chồng chữ)
    vi_tri = sorted(
        [(y(v), nhan, v, lop, True) for nhan, v, lop in duong_ke]
        + [(y(ds[-1]), nhan, ds[-1], lop, False) for nhan, ds, lop in duong_phu if ds and ds[-1] is not None]
    )
    for k in range(1, len(vi_tri)):
        if vi_tri[k][0] - vi_tri[k - 1][0] < 34:
            vi_tri[k] = (vi_tri[k - 1][0] + 34,) + vi_tri[k][1:]
    for yn, nhan, v, lop, ke_ngang in vi_tri:
        phan.append(
            (f'<line class="{lop}" x1="{TRAI}" x2="{R - PHAI}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>' if ke_ngang else "")
            + f'<line class="dan" x1="{R - PHAI}" x2="{R - PHAI + 10}" y1="{y(v):.1f}" y2="{yn:.1f}"/>'
            f'<line class="{lop}" x1="{R - PHAI + 12}" x2="{R - PHAI + 24}" y1="{yn:.1f}" y2="{yn:.1f}"/>'
            f'<text class="nhan-tc" x="{R - PHAI + 30}" y="{yn - 2:.1f}">{nhan}</text>'
            f'<text class="gia-tc" x="{R - PHAI + 30}" y="{yn + 13:.1f}">{so(v, so_le)}</text>'
        )
    for _, ds, lop in duong_phu:
        diem_phu = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(ds) if v is not None)
        phan.append(f'<polyline class="{lop}" points="{diem_phu}"/>')
    phan.append(
        f'<polyline class="duong-gia" points="{" ".join(f"{x(i):.1f},{y(g):.1f}" for i, g in enumerate(gia))}"/>'
    )
    phan.append(f'<circle class="diem" r="4" cx="{x(len(gia) - 1):.1f}" cy="{y(gia[-1]):.1f}"/>')
    phan.append(f'<line class="tro" y1="{TREN}" y2="{C - DUOI}"/><circle class="diem diem-tro" r="5"/>')
    diem = json.dumps([[round(x(i), 1), round(y(g), 1), d, g] for i, (d, g) in enumerate(lich_su)]).replace(
        "</", "<\\/"
    )
    mo_ta = (
        f"{ten} từ {lich_su[0][0]} đến {lich_su[-1][0]}, thấp nhất {so(min(gia), so_le)} {don_vi}, cao nhất {so(max(gia), so_le)} {don_vi}, "
        f"hiện tại {so(gia[-1], so_le)} {don_vi}"
    )
    dong_bang = "".join(
        f'<tr><td>{d[8:]}/{d[5:7]}/{d[:4]}</td><td class="so">{so(g, so_le)}</td></tr>' for d, g in reversed(lich_su)
    )
    return (
        f'<div class="cuon-bieu-do"><div class="bieu-do" data-don-vi="{ESC(don_vi)}"><svg viewBox="0 0 {R} {C}" tabindex="0" role="img" aria-label="{ESC(mo_ta)}. Dùng phím mũi tên để xem từng ngày.">'
        f'{"".join(phan)}</svg><div class="o-tro" hidden><b></b><span></span></div>'
        f'<script type="application/json">{diem}</script></div></div>'
        f'<details style="margin-top:8px"><summary>Xem dữ liệu dạng bảng</summary><div class="cuon cao" style="max-width:360px">'
        f'<table><thead><tr><th>Ngày</th><th class="so">{ESC(ten_cot)}</th></tr></thead><tbody>{dong_bang}</tbody></table></div></details>'
    )


def trang_chi_tiet(ma, von=VON_MAC_DINH):
    df, ngay = doc_ket_qua()
    if df is None or ma not in set(df["Mã CW"]):
        return None
    h, C = df[df["Mã CW"] == ma].iloc[0].to_dict(), cw_scanner
    cs, sigma_ls, ket_luan_quet = h["Mã CS"], float(h["Biến động %/năm"]) / 100, h["Đánh giá"]
    r = (
        float(h["r %"]) / 100 if "r %" in h else C.LAI_SUAT_PHI_RUI_RO
    )  # đúng lãi suất của lần quét (file cũ: cấu hình hiện tại)
    # Định giá lại theo giá trực tiếp: CW + cổ phiếu cơ sở trong 1 lần gọi (chờ tối đa 5 giây); σ và r giữ như lúc quét
    try:
        bang_gia = C.lay_bang_gia([ma, cs], cho=5)
        niem_yet, khop, so_lenh = bang_gia[ma]
        S_truc_tiep = C.gia_hien_tai(*bang_gia[cs])
    # mất mạng / máy chủ lỗi / thiếu mã: dùng đúng số lúc quét và báo rõ trên trang
    except Exception as e:  # noqa: BLE001
        so_lenh, ngay_tinh, truc_tiep = {}, ngay, False
        nguon = f"KHÔNG tải được giá trực tiếp ({ESC(str(e)[:120])}), đang dùng số liệu lúc quét ngày {ngay:%d/%m/%Y}"
    else:
        h.update(C.dinh_gia(niem_yet, khop, so_lenh, S_truc_tiep, sigma_ls, date.today(), r))
        ngay_tinh, truc_tiep = date.today(), True
        nguon = (
            f"bảng giá Vietcap lúc {datetime.now():%H:%M %d/%m/%Y} "
            f"({'trạng thái cuối phiên gần nhất' if khop.get('session') == 'ENDED' else 'trong phiên'})"
        )
    # P = giá mua (chào bán thấp nhất): giá người mua phải trả, dùng cho mọi chỉ số bên dưới
    S, K, ty_le, P = float(h["Giá CS"]), float(h["Giá thực hiện"]), float(h["Tỷ lệ CĐ"]), float(h["Giá mua"])
    P_khop, nguon_gia, ngay_con_lai = float(h["Giá CW"]), h["Nguồn giá mua"], int(h["Ngày còn lại"])
    T, hoa_von, tang = ngay_con_lai / 365, K + P * ty_le, float(h["CS tăng % để hòa vốn"])
    ngay_dao_han = ngay_tinh + timedelta(days=ngay_con_lai)
    iv = cw_scanner.bien_dong_ngam_dinh(P, S, K, T, r, ty_le)
    toi_thieu = cw_scanner.can_duoi(S, K, T, r)  # giá tối thiểu của quyền trên 1 cổ phiếu theo mô hình
    tv_cung_ma, canh_bao_iv = cw_scanner.so_iv_cung_ma(
        df, ma, cs, iv * 100 if iv else math.nan
    )  # IV so với CW khác cùng mã CS
    # IV − HV (điểm %): ưu tiên số trong CSV để khớp với kết luận lúc quét; file cũ chưa có cột này thì tính lại
    iv_hv = float(h["IV − HV"]) if math.isfinite(h["IV − HV"]) else ((iv - sigma_ls) * 100 if iv else math.nan)
    mo_ta_gia = (
        f"giá chào bán thấp nhất; giá khớp gần nhất {so(P_khop)} đ"
        if nguon_gia == "ask"
        else f"sổ lệnh trống nên dùng giá {nguon_gia}"
    )
    noi_tai = max(S - K, 0) / ty_le  # phần lãi nếu đáo hạn ngay hôm nay
    gia_tri_tg = P - noi_tai  # phần sẽ mất dần về 0 đến ngày đáo hạn
    if iv:  # mất giá theo thời gian tính theo mức biến động thị trường đang dùng
        mat_gia = (
            cw_scanner.black_scholes_call(S, K, T, r, iv)[0]
            - cw_scanner.black_scholes_call(S, K, T - 1 / 365, r, iv)[0]
        ) / ty_le
    else:  # không giải được: chia đều phần giá trị thời gian còn lại cho số ngày
        mat_gia = max(gia_tri_tg, 0) / max(ngay_con_lai, 1)
    chu_dat_re, lop_dat_re = dat_re(h["Đắt/rẻ %"])

    phan = [
        f'<div class="dau-trang"><div><h1>{ESC(ma)}</h1><p class="phu">Chứng quyền mua <b>{ESC(cs)}</b> · TCPH {ESC(h["TCPH"])}'
        f" · đáo hạn {ngay_dao_han:%d/%m/%Y} (còn {ngay_con_lai} ngày)</p>"
        f'<p class="{"phu" if truc_tiep else "loi"}"{"" if truc_tiep else " role=alert"}>Định giá theo {nguon}. '
        f"σ lịch sử và lãi suất lấy từ lần quét ngày {ngay:%d/%m/%Y}.</p></div>"
        f'<div>{huy_hieu(h["Đánh giá"], True)}'
        + (
            f'<p class="phu">Lúc quét {ngay:%d/%m}: {ESC(KET_LUAN.get(ket_luan_quet, ("", "", ket_luan_quet))[2])}</p>'
            if h["Đánh giá"] != ket_luan_quet
            else ""
        )
        + "</div></div>"
    ]

    # Tóm tắt + 4 tiêu chí
    if math.isfinite(iv_hv):
        dat_iv, noi_dung_iv = (
            iv_hv <= C.MAX_IV_TRU_HV * 100,
            f"IV − HV = {so(iv_hv, 1, True)} điểm ({chu_dat_re} so với giá hợp lý)",
        )
    elif (
        P * ty_le < toi_thieu
    ):  # không giải được IV vì giá quá thấp: rẻ hơn mọi mức dao động -> đạt (kèm cảnh báo ở trên)
        dat_iv, noi_dung_iv = True, "Giá mua dưới mức tối thiểu của mô hình, rẻ hơn mọi mức dao động (xem lưu ý ở trên)"
    else:
        dat_iv, noi_dung_iv = False, "Giá mua cao bất thường, không giải được IV"
    tieu_chi = [
        (
            ngay_con_lai >= C.MIN_NGAY_CON_LAI,
            f"Còn {ngay_con_lai} ngày đến đáo hạn",
            f"cần ≥ {C.MIN_NGAY_CON_LAI} ngày",
        ),
        (dat_iv, noi_dung_iv, f"cần IV − HV ≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm"),
        (
            tang <= C.MAX_TANG_DE_HOA_VON * 100,
            f"{ESC(cs)} cần tăng {so(tang, 1, True)}% để hòa vốn",
            f"cần ≤ {C.MAX_TANG_DE_HOA_VON:.0%}",
        ),
        (
            int(h["KL khớp"]) >= C.MIN_KHOI_LUONG,
            f"Khớp {so(h['KL khớp'])} CW trong phiên",
            f"cần ≥ {so(C.MIN_KHOI_LUONG)}",
        ),
    ]
    dong_tc = "".join(
        f'<li><b class="{"duong" if dat else "am"}" aria-label="{"Đạt" if dat else "Không đạt"}">{"✓" if dat else "✕"}</b>'
        f"<span>{noi_dung} <small>({yeu_cau})</small></span></li>"
        for dat, noi_dung, yeu_cau in tieu_chi
    )
    phan.append(
        f'<section class="the"><h2>Tóm tắt</h2><p class="tom-tat">Bạn trả <b>{so(P)} đ</b> cho 1 CW ({mo_ta_gia}; mô hình tính giá hợp lý là {so(h["Giá hợp lý"])} đ). '
        f"Nếu giữ đến ngày {ngay_dao_han:%d/%m/%Y}, giá {ESC(cs)} cần cao hơn <b>{so(hoa_von)} đ</b> ({so(tang, 1, True)}% so với hiện tại {so(S)} đ) thì mới có lãi. "
        f"Trong {so(P)} đ có {so(noi_tai)} đ <b>giá trị nội tại</b> (phần lãi nếu đáo hạn ngay hôm nay) và {so(gia_tri_tg)} đ <b>giá trị thời gian</b> "
        f"(mất dần về 0 đến ngày đáo hạn, khoảng {so(mat_gia, 1 if mat_gia < 10 else 0)} đ/ngày nếu giá {ESC(cs)} đứng yên).</p>"
        + (
            f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ Bất thường:</b> giá CW đang thấp hơn cả giá trị nội tại. Có thể do sắp điều chỉnh '
            f'điều khoản (cổ tức, chia tách…) hoặc thanh khoản kém. Hãy đọc thông báo mới nhất của {ESC(h["TCPH"])} về mã này trước khi mua.</p>'
            if gia_tri_tg < 0
            else (
                f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ Lưu ý:</b> giá mua × tỷ lệ = {so(P * ty_le)} đ, thấp hơn mức tối thiểu theo mô hình '
                f"S − K × e<sup>−rT</sup> = {so(toi_thieu)} đ (lãi suất giả định {so(r * 100, 1)}%). Không có mức dao động nào cho ra giá này, nên chữ "
                f"“{chu_dat_re}” chủ yếu đến từ giả định (lãi suất, mức dao động 1 năm qua), không chắc là món hời. "
                f'Hãy so với các CW khác của {ESC(cs)} và đọc thông báo của {ESC(h["TCPH"])} trước khi mua.</p>'
                if P * ty_le < toi_thieu
                else ""
            )
        )
        + (
            f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ IV bất thường:</b> {ESC(canh_bao_iv)}.</p>'
            if canh_bao_iv
            else ""
        )
        + f'<ul class="tieu-chi">{dong_tc}</ul>'
        '<p class="phu">Chưa hiểu các con số? Xem <a href="/huong-dan#trang-phan-tich">cách đọc trang phân tích</a> và '
        '<a href="/huong-dan#truoc-khi-mua">5 câu tự hỏi trước khi mua</a>.</p></section>'
    )

    # Rủi ro với số tiền của bạn (đã tính phí mua, thuế khi nhận tiền; con số "xác suất" là của mô hình, không phải dự báo)
    rr = C.rui_ro_theo_tien(von * 1_000_000, P, S, K, ty_le, T, r, sigma_ls, float(h["Đòn bẩy"]))
    gd_cuoi = date.fromisoformat(h["Ngày GD cuối"]) if h.get("Ngày GD cuối") else None
    phi_chu, thue_chu = so(C.PHI_GIAO_DICH * 100, 2), so(C.THUE_BAN * 100, 1)
    phan.append(
        f'<section class="the" id="rui-ro"><h2>Rủi ro với số tiền của bạn</h2>'
        f'<form method="get" action="/cw/{ESC(ma)}#rui-ro" style="margin-top:8px"><label>Số tiền định đầu tư '
        f'<input type="number" name="von" min="1" max="10000" step="1" value="{von}" style="width:7em"> triệu đồng</label> '
        '<button class="nut" style="padding:6px 14px">Tính lại</button></form><div class="luoi-o">'
        + o_so(
            "Mua được",
            f"{so(rr['so_cw'])} CW" if rr["so_cw"] else "Chưa đủ 1 lô",
            f"≈ {so(rr['tien_chi'])} đ, đã gồm phí mua {phi_chu}% (lô 100 CW)",
        )
        + o_so(
            "Tương đương nắm",
            f"{so(rr['tiep_xuc'] / 1e6, 1)} triệu đ {ESC(cs)}",
            f"≈ {so(rr['so_cp'])} cổ phiếu · gấp {so(rr['tiep_xuc'] / (von * 1e6), 1)} lần số tiền bỏ ra",
        )
        + o_so(
            "Mất toàn bộ tiền nếu",
            f"{ESC(cs)} ≤ {so(K)} đ",
            (
                f"tức giảm {so(-rr['giam_ve_0'] * 100, 1)}% vào lúc đáo hạn · xác suất theo mô hình ≈ {so(rr['xs_ve_0'] * 100, 0)}% "
                "(σ lịch sử, không phải dự báo)"
                if rr["giam_ve_0"] < 0
                else f"{ESC(cs)} đang thấp hơn giá thực hiện"
            ),
        )
        + o_so(
            f"{ESC(cs)} giảm 1%",
            f"≈ −{so(rr['mat_khi_giam_1pct'])} đ",
            f"trước ngày đáo hạn, theo đòn bẩy {so(h['Đòn bẩy'], 1)}x; giảm sâu thì mất nhanh hơn",
        )
        + o_so(
            "Ngày giao dịch cuối",
            f"{gd_cuoi:%d/%m/%Y}" if gd_cuoi else "Không rõ",
            (
                f"còn {(gd_cuoi - ngay_tinh).days} ngày để bán; sau đó chỉ chờ nhận tiền theo giá trung bình 5 phiên trước "
                f"ngày đáo hạn {ngay_dao_han:%d/%m/%Y}"
                if gd_cuoi
                else "bấm Quét ngay để lấy ngày này"
            ),
        )
        + o_so(
            "Hòa vốn có phí, thuế",
            f"{so(rr['hoa_von_phi'])} đ",
            f"{ESC(cs)} cần {so((rr['hoa_von_phi'] / S - 1) * 100, 1, True)}% (chưa tính phí: {so(hoa_von)} đ). "
            f"Phí {phi_chu}% + thuế {thue_chu}% khi nhận tiền là giả định - kiểm tra với công ty chứng khoán của bạn",
        )
        + "</div></section>"
    )

    # Các chỉ số chính
    delta = C.black_scholes_call(S, K, T, r, sigma_ls)[
        1
    ]  # N(d1): giá trị quyền trên 1 cổ phiếu tăng bao nhiêu khi cổ phiếu tăng 1 đ
    so_sanh_bd = (
        (
            f"IV − HV = {so(iv_hv, 1, True)} điểm → thị trường đang định giá CW "
            + ("rẻ hơn" if iv_hv < 0 else "đắt hơn")
            + " mức dao động 1 năm qua."
        )
        if math.isfinite(iv_hv)
        else (
            f"Không giải được: giá mua dưới mức tối thiểu S − K × e^(−rT) (lãi suất giả định {so(r * 100, 1)}%)."
            if P * ty_le < toi_thieu
            else "Không giải được: giá mua cao bất thường so với mô hình."
        )
    )
    phan.append(
        '<div class="luoi-o">'
        + o_so(
            "Giá mua / giá hợp lý",
            f"{so(P)} / {so(h['Giá hợp lý'])}",
            '<a href="#cach-tinh" onclick="document.getElementById(\'cach-tinh\').open = true">Xem cách tính giá hợp lý ↓</a>',
        )
        + o_so("So với giá hợp lý", f'<span class="{lop_dat_re}">{chu_dat_re}</span>', "Rẻ = giá mua thấp hơn mô hình")
        + o_so("Điểm hòa vốn", f"{so(hoa_von)} đ", f"{ESC(cs)} cần {so(tang, 1, True)}% đến ngày đáo hạn")
        + o_so(
            "Đòn bẩy", f"{so(h['Đòn bẩy'], 1)}x", f"{ESC(cs)} tăng/giảm 1% → CW tăng/giảm khoảng {so(h['Đòn bẩy'], 1)}%"
        )
        + o_so(
            "Delta", so(delta, 2), f"{ESC(cs)} tăng/giảm 1.000 đ → 1 CW tăng/giảm khoảng {so(delta / ty_le * 1000)} đ"
        )
        + o_so(
            "Mất giá theo thời gian",
            f"{so(mat_gia, 1 if mat_gia < 10 else 0)} đ/ngày",
            f"≈ {so(mat_gia / P * 100, 2 if mat_gia / P < 0.001 else 1)}% giá CW mỗi ngày nếu {ESC(cs)} đứng yên",
        )
        + o_so(
            "Biến động ngầm định (IV)",
            f"{so(iv * 100, 0)}%" if iv else "—",
            f"Lịch sử 1 năm (HV): {so(sigma_ls * 100, 0)}%. {so_sanh_bd}"
            + (f" Trung vị IV các CW {ESC(cs)} khác: {so(tv_cung_ma, 0)}%." if math.isfinite(tv_cung_ma) else ""),
        )
        + "</div>"
    )

    # Giá hợp lý được tính thế nào: từng bước bằng số thật của mã này, nói bằng lời thường
    if ngay_con_lai > 0:
        N, bdd, kc = (
            C.phan_phoi_chuan,
            sigma_ls * math.sqrt(T),
            math.log(S / K),
        )  # bdd: biên độ dao động đến ngày đáo hạn
        d1 = (kc + (r + sigma_ls**2 / 2) * T) / bdd
        d2, ck = d1 - bdd, math.exp(-r * T)
        nhan, tra = S * N(d1), K * ck * N(d2)
        gia_cw_tinh, mo_phong = (nhan - tra) / ty_le, C.mo_phong_gia(S, K, T, r, sigma_ls) / ty_le
        c = ESC(cs)
        buoc = [
            (
                "Thu thập 5 con số",
                (
                    f"Giá {c} hôm nay <b>S = {so(S)} đ</b> · giá thực hiện <b>K = {so(K)} đ</b> · còn <b>{ngay_con_lai} ngày = {so(T, 3)} năm</b>"
                    f" · {c} dao động khoảng <b>σ = {so(sigma_ls * 100, 1)}%/năm</b> (đo từ giá 1 năm qua) · lãi suất <b>r = {so(r * 100, 1)}%/năm</b>."
                ),
            ),
            (
                "Giá đang cách giá thực hiện bao xa?",
                (
                    f"ln(S ÷ K) = ln({so(S)} ÷ {so(K)}) = <b>{so(kc, 3)}</b> → giá {c} đang "
                    f"{'cao' if kc >= 0 else 'thấp'} hơn giá thực hiện khoảng <b>{so(abs(kc) * 100, 1)}%</b>."
                ),
            ),
            (
                "Từ nay đến ngày đáo hạn, giá thường dao động bao nhiêu?",
                (
                    f"σ × √T = {so(sigma_ls * 100, 1)}% × √{so(T, 3)} = <b>{so(bdd * 100, 1)}%</b>"
                    f" → trong {ngay_con_lai} ngày tới, giá {c} thường lên/xuống trong khoảng <b>±{so(bdd * 100, 0)}%</b>."
                ),
            ),
            (
                "Đổi khoảng cách thành “số bước dao động”",
                (
                    f"d1 = (khoảng cách + một chút cho lãi suất và dao động) ÷ biên độ = ({so(kc, 3)} + "
                    f"{so((r + sigma_ls**2 / 2) * T, 3)}) ÷ {so(bdd, 3)} = <b>{so(d1, 2)}</b> · d2 = d1 − biên độ = <b>{so(d2, 2)}</b>."
                    f" Hiểu đơn giản: giá đang {'trên' if d2 >= 0 else 'dưới'} giá thực hiện khoảng {so(abs(d2), 1)} bước dao động."
                ),
            ),
            (
                "Đổi “số bước” thành xác suất",
                (
                    f"Tra bảng phân phối chuẩn (Excel: hàm NORM.S.DIST): <b>N(d2) = {so(N(d2) * 100, 0)}%</b> = khả năng tới ngày đáo hạn "
                    f"giá {c} vẫn trên {so(K)} đ (theo mô hình) · <b>N(d1) = {so(N(d1) * 100, 0)}%</b> – đây chính là <b>delta = {so(N(d1), 2)}</b>."
                ),
            ),
            (
                "Ráp vào công thức",
                (
                    f"Giá 1 quyền chọn = <b>phần nhận được − phần phải trả</b> = S × N(d1) − K × e<sup>−rT</sup> × N(d2) = "
                    f"{so(S)} × {so(N(d1), 3)} − {so(K)} × {so(ck, 3)} × {so(N(d2), 3)} = {so(nhan)} − {so(tra)} = <b>{so(nhan - tra)} đ</b> (cho 1 cổ phiếu)."
                ),
            ),
            (
                "Chia cho tỷ lệ chuyển đổi",
                f"{so(nhan - tra)} ÷ {so(ty_le, 4)} = <b>{so(gia_cw_tinh)} đ / 1 CW</b>. Giá mua là {so(P)} đ → <b>{chu_dat_re}</b> so với giá hợp lý."
                + (
                    f" <small class='phu'>(Bảng ghi {so(h['Giá hợp lý'])} đ: chênh vài đồng do mức dao động hiển thị đã làm tròn.)</small>"
                    if round(gia_cw_tinh) != int(h["Giá hợp lý"])
                    else ""
                ),
            ),
        ]
        phan.append(
            f'<details class="the" id="cach-tinh"><summary><h2 style="display:inline">📐 Giá hợp lý {so(h["Giá hợp lý"])} đ được tính thế nào?</h2>'
            ' <span class="phu">(bấm để xem từng bước)</span></summary>'
            f'<p class="tom-tat"><b>Ý tưởng:</b> tưởng tượng hàng nghìn kịch bản giá {c} có thể xảy ra đến ngày đáo hạn, với mức dao động như 1 năm qua. '
            f"Mỗi kịch bản, CW trả một số tiền hoặc về 0. <b>Giá hợp lý = trung bình số tiền đó, quy về tiền hôm nay.</b> "
            'Công thức Black-Scholes tính ra con số trung bình này chỉ bằng 7 bước:</p><ol class="cac-buoc">'
            + "".join(
                f"<li><b>Bước {k} – {t}{'' if t.endswith('?') else '.'}</b><br>{nd}</li>"
                for k, (t, nd) in enumerate(buoc, 1)
            )
            + f'</ol><p class="ghi-chu-canh-bao" style="border-left-color: var(--xanh); background: color-mix(in srgb, var(--xanh) 8%, transparent)">'
            f"<b>Kiểm chứng:</b> chương trình vừa thử <b>20.000 kịch bản</b> ngẫu nhiên cho giá {c} đến ngày đáo hạn. Trung bình CW trả "
            f"<b>≈ {so(mo_phong)} đ</b> (quy về hôm nay), gần bằng kết quả công thức {so(gia_cw_tinh)} đ.</p>"
            '<p class="phu">Nhớ: con số này dựa trên giả định cổ phiếu sẽ dao động như 1 năm qua. Nó là thước đo để so sánh, không phải dự báo giá.</p></details>'
        )

    # Khối lượng CW: sổ lệnh tải cùng lần định giá trực tiếp ở đầu trang (lỗi thì dùng số lúc quét)
    kl_ny, kl_khop = float(h["KL niêm yết"]), h["KL khớp"]
    ban, mua = (so_lenh.get("askPrices") or [])[:3], (so_lenh.get("bidPrices") or [])[:3]
    kl_ban = C.tong_kl(so_lenh, "askPrices") if so_lenh else h["KL chào bán"]
    kl_mua = C.tong_kl(so_lenh, "bidPrices") if so_lenh else h["KL chờ mua"]
    gia = lambda m: m.get("price") or 0
    tien = lambda m: gia(m) * (m.get("volume") or 0)  # thành tiền của một mức giá (đ)

    def o_sl(ds, i):  # 3 ô (giá, khối lượng, thành tiền) của một mức giá; không có mức đó thì "—"
        if i >= len(ds):
            return '<td class="so">—</td>' * 3
        return f'<td class="so">{so(gia(ds[i]))}</td><td class="so">{so(ds[i].get("volume") or 0)}</td><td class="so">{so(tien(ds[i]) / 1e6, 1)}</td>'

    def goi_y_ben(
        ds, ten_gia, viec
    ):  # vd: "ở giá thấp nhất 920 đ chỉ có 5.100 CW (≈ 4,7 triệu đ). Mua hết cả 3 mức ..."
        kl3, tien3 = sum(m.get("volume") or 0 for m in ds), sum(tien(m) for m in ds)
        return (
            f"Ở giá {ten_gia} {so(gia(ds[0]))} đ chỉ có <b>{so(ds[0].get('volume') or 0)} CW</b> (≈ {so(tien(ds[0]) / 1e6, 1)} triệu đ). "
            f"{viec} hết cả {len(ds)} mức ({so(gia(ds[0]))}–{so(gia(ds[-1]))} đ): ≈ {so(tien3 / 1e6, 1)} triệu đ, "
            f"giá trung bình ≈ {so(tien3 / kl3 if kl3 else math.nan)} đ"
        )

    dong_sl = (
        "".join(f"<tr>{o_sl(mua, i)}{o_sl(ban, i)}</tr>" for i in range(3))
        if (ban or mua)
        else '<tr><td colspan="6">Sổ lệnh đang trống (ngoài giờ giao dịch hoặc chưa có lệnh).</td></tr>'
    )
    phan.append(
        '<section class="the" id="khoi-luong"><h2>Khối lượng CW</h2><div class="luoi-o">'
        + o_so("Khối lượng phát hành", f"{so(kl_ny)} CW", "tổng số CW được niêm yết (được phép bán ra)")
        + o_so(
            "Đang chào bán (3 mức giá)",
            f"{so(kl_ban)} CW",
            goi_y_ben(ban, "thấp nhất", "Mua") if ban else "ở 3 mức giá bán thấp nhất",
        )
        + o_so(
            "Đang chờ mua (3 mức giá)",
            f"{so(kl_mua)} CW",
            goi_y_ben(mua, "cao nhất", "Bán") if mua else "ở 3 mức giá mua cao nhất",
        )
        + o_so(
            "Đã khớp trong phiên",
            f"{so(kl_khop)} CW",
            f"≈ {so(kl_khop / kl_ny * 100, 1)}% khối lượng phát hành" if kl_ny > 0 else "",
        )
        + '</div><div class="cuon"><table style="max-width:820px"><thead><tr><th class="so">Giá chờ mua (đ)</th><th class="so">KL chờ mua</th>'
        '<th class="so">Thành tiền (triệu đ)</th><th class="so">Giá chào bán (đ)</th><th class="so">KL chào bán</th><th class="so">Thành tiền (triệu đ)</th>'
        f"</tr></thead><tbody>{dong_sl}</tbody></table></div>"
        '<p class="phu">Sổ lệnh 3 mức giá tốt nhất. Mua nhiều hơn khối lượng ở giá thấp nhất thì phần còn lại phải mua ở các mức giá cao hơn '
        f"(bán thì ngược lại). Nguồn: {nguon}.</p>"
        '<details><summary>Vì sao không có "số CW đã bán ra" và "số CW còn lại"?</summary>'
        "<p>Các nguồn dữ liệu miễn phí (bảng giá Vietcap, KBS, vnstock gói miễn phí) chỉ công bố <b>tổng khối lượng phát hành</b>, "
        "không công bố nhà đầu tư đang nắm bao nhiêu CW. Phần CW chưa bán thường nằm trong tay <b>tổ chức phát hành</b>: họ là bên tạo lập "
        'thị trường, đặt lệnh bán dần ra và đặt lệnh mua lại. Vì vậy con số <b>"có thể mua ngay"</b> trên thực tế là khối lượng '
        "<b>đang chào bán</b> trong sổ lệnh. Tổ chức phát hành có thể đặt thêm lệnh bán sau đó, nhưng không vượt quá khối lượng phát hành. "
        "Nếu cần con số chính xác, hãy xem thông báo của tổ chức phát hành hoặc ứng dụng của công ty chứng khoán bạn dùng (nếu có hiển thị).</p></details></section>"
    )

    # Biểu đồ giá cổ phiếu cơ sở
    file_ls = C.THU_MUC_KET_QUA / f"lich_su_{ngay}.json"
    lich_su = json.loads(file_ls.read_text(encoding="utf-8")).get(cs) if file_ls.exists() else None
    phan.append(
        f'<section class="the"><h2>Giá {ESC(cs)} 1 năm qua</h2>'
        f'<p class="phu">Muốn có lãi khi giữ đến đáo hạn, giá {ESC(cs)} phải nằm trên đường <b>hòa vốn</b>. Rê chuột lên biểu đồ để xem giá từng ngày.</p>'
        + (
            bieu_do(lich_su, [("Giá thực hiện", K, "tc-thuc-hien"), ("Hòa vốn", hoa_von, "tc-hoa-von")], f"Giá {cs}")
            if lich_su
            else "<p>Chưa có dữ liệu biểu đồ. Bấm <b>Quét ngay</b> ở trang chính để tải.</p>"
        )
        + "</section>"
    )

    # IV theo thời gian: giá CW từ vnstock (1 lượt gọi, nhớ trong ngày) + giá CS đã điều chỉnh quyền trong file lịch sử lúc quét
    bo_nho, loi_iv = BO_NHO_IV.get((ma, date.today())), ""
    if bo_nho is None and lich_su:
        try:
            df_cw = C.lay_gia_dong_cua(ma)
            he_so = 10 ** round(math.log10(P_khop / float(df_cw["close"].iloc[-1])))  # vnstock có thể trả nghìn đồng
            gia_cw = {str(t)[:10]: float(g) * he_so for t, g in zip(df_cw["time"], df_cw["close"])}
            kl_cw = {str(t)[:10]: float(v) for t, v in zip(df_cw["time"], df_cw["volume"])}
            bo_nho = BO_NHO_IV[(ma, date.today())] = {
                "iv": C.lich_su_iv(gia_cw, dict(lich_su), K, ty_le, ngay_dao_han, r),
                "gia": gia_cw,
                "kl": kl_cw,
            }
        # lỗi mạng / hết lượt gọi: chỉ mục này không có biểu đồ, phần còn lại của trang vẫn dùng được
        except Exception as e:  # noqa: BLE001
            loi_iv = f"Chưa tải được lịch sử giá {ESC(ma)} ({ESC(str(e)[:120])}). Mở lại trang sau ít phút."
    iv_ls = bo_nho["iv"] if bo_nho else None
    duong_ke_iv = [("HV 1 năm", sigma_ls * 100, "tc-thuc-hien")] + (
        [("Trung vị cùng mã", tv_cung_ma, "tc-hoa-von")] if math.isfinite(tv_cung_ma) else []
    )
    phan.append(
        f'<section class="the"><h2>IV của {ESC(ma)} theo thời gian</h2>'
        f'<p class="phu">Mức dao động mà giá CW "giả định" mỗi ngày, so với dao động thật 1 năm qua (HV) và trung vị IV các CW {ESC(cs)} khác '
        f"hôm nay. IV thường cao lúc mới phát hành rồi giảm dần; đáng chú ý khi IV xuống thấp hẳn dưới HV và trung vị cùng mã (tổ chức phát hành "
        f"đang bán ra rẻ, giá có thể còn thấp nữa trước khi đáo hạn). Điểm ở 0% = giá dưới "
        f"mức tối thiểu của mô hình. Tính bằng điều khoản hiện tại, giá {ESC(cs)} đã điều chỉnh quyền và lãi suất {so(r * 100, 1)}%.</p>"
        + (
            bieu_do(iv_ls, duong_ke_iv, f"IV của {ma}", "%", "IV (%)")
            if iv_ls and len(iv_ls) >= 2
            else f'<p>{loi_iv or "Chưa đủ dữ liệu để vẽ (cần ít nhất 2 ngày có giá CW và giá cổ phiếu cơ sở)."}</p>'
        )
        + "</section>"
    )

    # Lệch so với cổ phiếu cơ sở 20 phiên (mốc = phiên đầu tiên đủ thanh khoản)
    moc, hang_lech = (
        C.lech_20_phien(bo_nho["gia"], bo_nho["kl"], dict(lich_su), K, ty_le, ngay_dao_han, r) if bo_nho else (None, [])
    )
    lech_ls = [[d, round(lech * 100, 1)] for d, *_, lech in hang_lech]
    nguong_lech = danh_muc.CANH_BAO_LECH * 100
    mau_bang = hang_lech[:: max(len(hang_lech) // 4, 1)][:4] + hang_lech[-1:] if hang_lech else []
    phan.append(
        f'<section class="the"><h2>{ESC(ma)} có theo kịp {ESC(cs)} không?</h2>'
        f'<p class="phu">Lệch = giá CW thực tế so với giá "lẽ ra" nếu CW giữ nguyên mức IV của ngày mốc và chỉ chạy theo giá {ESC(cs)} '
        f"(đã gồm đòn bẩy và mất giá theo thời gian). Âm: CW không theo kịp cổ phiếu; dương: CW chạy nhanh hơn, dễ bị kéo về. "
        f"Trong khoảng ±{so(nguong_lech, 0)}% là bình thường. Mốc: "
        + (
            f"{moc[8:]}/{moc[5:7]}/{moc[:4]} (phiên đầu tiên trong 20 phiên gần nhất khớp ≥ {so(C.MIN_KHOI_LUONG)} CW).</p>"
            if moc
            else "—.</p>"
        )
        + (
            bieu_do(
                lech_ls,
                [
                    (f"−{so(nguong_lech, 0)}%", -nguong_lech, "tc-hoa-von"),
                    ("0%", 0, "tc-thuc-hien"),
                    (f"+{so(nguong_lech, 0)}%", nguong_lech, "tc-hoa-von"),
                ],
                f"Lệch của {ma}",
                "%",
                "Lệch (%)",
            )
            + '<div class="cuon"><table style="max-width:640px"><thead><tr><th>Ngày</th>'
            f'<th class="so">{ESC(cs)}</th><th class="so">CW thực tế</th><th class="so">CW lẽ ra</th><th class="so">Lệch</th></tr></thead><tbody>'
            + "".join(
                f'<tr><td>{d[8:]}/{d[5:7]}</td><td class="so">{so(a * 100, 1, True)}%</td><td class="so">{so(b * 100, 1, True)}%</td>'
                f'<td class="so">{so(c * 100, 1, True)}%</td><td class="so {"am" if e <= -danh_muc.CANH_BAO_LECH else ""}">'
                f"<b>{so(e * 100, 1, True)}%</b></td></tr>"
                for d, a, b, c, e in mau_bang
            )
            + "</tbody></table></div>"
            if len(lech_ls) >= 2
            else f'<p>{loi_iv or "Chưa đủ dữ liệu (cần ít nhất 2 phiên có giao dịch đủ thanh khoản)."}</p>'
        )
        + "</section>"
    )

    # Kịch bản lãi/lỗ khi đáo hạn
    so_cw, gia_von = rr["so_cw"], P * (1 + C.PHI_GIAO_DICH)  # giá vốn 1 CW đã gồm phí mua
    dong = []
    for thay_doi in (-20, -10, -5, 0, 5, 10, 15, 20, 30):
        gia_cs = S * (1 + thay_doi / 100)
        nhan_ve = max(gia_cs - K, 0) / ty_le
        lai = nhan_ve * (1 - C.THUE_BAN) - gia_von  # đã trừ thuế khi nhận tiền
        lop = "duong" if lai > 0 else ("am" if lai < 0 else "")
        dong.append(
            f'<tr{" class=hang-goc" if thay_doi == 0 else ""}><td>{"Giữ nguyên" if thay_doi == 0 else f"{thay_doi:+d}%"}</td>'
            f'<td class="so">{so(gia_cs)}</td><td class="so">{so(nhan_ve)}</td><td class="so {lop}">{so(lai, 0, True)}</td>'
            f'<td class="so {lop}">{so(lai / gia_von * 100, 0, True)}%</td><td class="so {lop}">{so(lai * so_cw, 0, True)}</td></tr>'
        )
    phan.append(
        f'<section class="the"><h2>Nếu giữ đến ngày đáo hạn ({ngay_dao_han:%d/%m/%Y})</h2>'
        f'<p class="phu">Lãi/lỗ theo giá {ESC(cs)} lúc đáo hạn (giá thanh toán thực tế là trung bình 5 phiên trước đáo hạn). '
        f'Đã trừ phí mua {phi_chu}% và thuế {thue_chu}% khi nhận tiền. Lỗ tối đa là toàn bộ tiền mua CW.</p><div class="cuon"><table><thead><tr><th>{ESC(cs)} thay đổi</th><th class="so">Giá {ESC(cs)} (đ)</th>'
        f'<th class="so">Nhận về / CW (đ)</th><th class="so">Lãi/lỗ / CW (đ)</th><th class="so">Lãi/lỗ</th>'
        f'<th class="so">Với {so(so_cw)} CW ≈ {von} triệu (đ)</th></tr></thead><tbody>{"".join(dong)}</tbody></table></div></section>'
    )

    # So sánh các CW cùng mã cơ sở
    cung_cs = df[df["Mã CS"] == cs].sort_values("IV − HV", na_position="last")
    phan.append(
        f'<section class="the"><h2>Các CW khác của {ESC(cs)} ({len(cung_cs)})</h2>'
        f'<p class="phu">Cùng một cổ phiếu cơ sở nhưng khác TCPH, giá thực hiện và thời hạn. Xếp theo IV − HV (thấp nhất = rẻ nhất trước); dòng tô nền là CW đang xem.</p>'
        f'<div class="cuon">{bang(cung_cs, ma)}</div></section>'
    )

    # Điều khoản
    dk = [
        ("Mã cổ phiếu cơ sở", ESC(cs)),
        ("Tổ chức phát hành", ESC(h["TCPH"])),
        ("Giá thực hiện", f"{so(K)} đ"),
        ("Tỷ lệ chuyển đổi", f"{so(ty_le, 4)} CW : 1 cổ phiếu"),
        ("Ngày đáo hạn", f"{ngay_dao_han:%d/%m/%Y}"),
        ("Giá cổ phiếu cơ sở", f"{so(S)} đ"),
        ("Giá mua lúc quét", f"{so(P)} đ (giá {nguon_gia})"),
        ("Giá khớp gần nhất", f"{so(P_khop)} đ"),
        ("Khối lượng khớp", f"{so(h['KL khớp'])} CW"),
        ("Biến động lịch sử 1 năm", f"{so(sigma_ls * 100, 1)}%"),
        ("Lãi suất phi rủi ro (giả định)", f"{so(r * 100, 1)}%"),
    ]
    phan.append(
        '<section class="the"><h2>Điều khoản &amp; số liệu</h2><dl class="dieu-khoan">'
        + "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in dk)
        + "</dl></section>"
    )
    return trang(f"{ma} – phân tích chứng quyền", "".join(phan))


# ============ TRANG CW SẮP RA MẮT ============
def trang_sap_ra_mat(tai_moi=False):
    """CW đã được HOSE chấp thuận niêm yết nhưng chưa giao dịch, kèm giá hợp lý dự kiến để so sánh khi lên sàn."""
    C = cw_scanner
    df, ngay = doc_ket_qua()
    phan = [
        (
            '<div class="dau-trang"><div><h1>Chứng quyền sắp ra mắt</h1><p class="phu">Các CW đã được HOSE chấp thuận niêm yết '
            "nhưng <b>chưa giao dịch</b>. Mã CW (ví dụ CVPB26xx) sẽ có khi lên sàn.</p></div></div>"
        )
    ]
    luu = sorted(C.THU_MUC_KET_QUA.glob("sap_ra_mat_*.json"))
    tai_lai = ' · <a href="/sap-ra-mat?tai_moi=1">tải lại trực tiếp từ HOSE</a> (có thể mất 10-40 giây)'
    try:
        # đã quét hôm nay thì dùng ngay danh sách vừa lưu (máy chủ HOSE thường chậm); muốn mới nhất thì bấm "tải lại"
        if luu and luu[-1].stem[11:] == str(date.today()) and not tai_moi:
            ds, nguon = (
                C.doc_cw_sap_ra_mat(json.loads(luu[-1].read_text(encoding="utf-8"))),
                "hsx.vn, danh sách lưu lúc quét hôm nay" + tai_lai,
            )
        else:
            ds, nguon = (
                C.doc_cw_sap_ra_mat(C.tai_du_lieu_hose_cw(cho=12)),
                "hsx.vn (Niêm yết mới → DS CW được chấp thuận chính thức), tải trực tiếp lúc mở trang",
            )
    # ranh giới gọi vnstock/mạng: lỗi được báo ra (nhật ký hoặc trên trang), không nuốt
    except Exception as e:  # noqa: BLE001
        if not luu:
            phan.append(
                f'<p class="loi" role="alert">Không tải được danh sách từ HOSE ({ESC(str(e))}). Máy chủ HOSE có thể đang chậm, '
                "hãy tải lại trang sau ít phút hoặc bấm Quét ngay ở trang chính.</p>"
            )
            return trang("CW sắp ra mắt", "".join(phan), "/sap-ra-mat")
        ds = C.doc_cw_sap_ra_mat(json.loads(luu[-1].read_text(encoding="utf-8")))
        nguon = (
            f"không tải được trực tiếp từ HOSE ({ESC(str(e))}), dùng danh sách lưu lúc quét ngày {date.fromisoformat(luu[-1].stem[11:]):%d/%m/%Y}"
            + tai_lai
        )

    # Bỏ mã đã hết hạn và mã đã lên sàn (cùng mã CS + giá thực hiện + ngày đáo hạn với một CW trong lần quét gần nhất)
    hom_nay, co_so, dang_gd = date.today(), {}, set()
    if df is not None:
        dang_gd = {
            (h["Mã CS"], round(h["Giá thực hiện"]), ngay + timedelta(days=int(h["Ngày còn lại"])))
            for _, h in df.iterrows()
        }
        co_so = df.groupby("Mã CS")[["Giá CS", "Biến động %/năm"]].first().to_dict("index")
    sap = sorted(
        (
            x
            for x in ds
            if x["ngay_dao_han"]
            and x["ngay_dao_han"] > hom_nay
            and (x["ma_cs"], round(x["gia_thuc_hien"] or 0), x["ngay_dao_han"]) not in dang_gd
        ),
        key=lambda x: (x["ngay_chap_thuan"] or date.min, x["ten"]),
        reverse=True,
    )

    dv = lambda v: (
        v if isinstance(v, (int, float)) and math.isfinite(v) else -1
    )  # giá trị để sắp xếp; thiếu số liệu xếp cuối
    dong = []
    for x in sap:
        K, cs, con = x["gia_thuc_hien"], co_so.get(x["ma_cs"]), (x["ngay_dao_han"] - hom_nay).days
        ngay_ct = f'{x["ngay_chap_thuan"]:%d/%m/%Y}' if x["ngay_chap_thuan"] else "—"
        S = cs["Giá CS"] if cs else math.nan
        try:  # giá hợp lý dự kiến nếu CW lên sàn hôm nay, dùng giá & mức dao động của cổ phiếu cơ sở ở lần quét gần nhất
            gia_hl = C.black_scholes_call(S, K, con / 365, C.LAI_SUAT_PHI_RUI_RO, cs["Biến động %/năm"] / 100)[
                0
            ] / C.doc_ty_le(x["ty_le"])
        except (TypeError, ValueError, ZeroDivisionError):  # thiếu giá CS / giá thực hiện / tỷ lệ từ HOSE -> hiện "—"
            gia_hl = math.nan
        lech = (K / S - 1) * 100 if K and not math.isnan(S) else math.nan
        dong.append(
            f'<tr><td data-v="{x["ngay_chap_thuan"] or ""}">{ngay_ct}</td><td>{ESC(x["ten"].replace("Chứng quyền ", ""))}</td>'
            f'<td class="so" data-v="{dv(gia_hl)}"><b>{so(gia_hl)}</b></td>'
            f'<td class="so" data-v="{dv(S)}">{so(S)}</td><td class="so" data-v="{dv(K)}">{so(K or math.nan)}</td>'
            f'<td class="so" data-v="{dv(lech)}">{so(lech, 1, True)}%</td><td class="so">{ESC(x["ty_le"])}</td>'
            f'<td data-v="{x["ngay_dao_han"]}">{x["ngay_dao_han"]:%d/%m/%Y}</td><td class="so" data-v="{con}">{so(con)}</td>'
            f'<td class="so" data-v="{dv(x["kl_niem_yet"])}">{so(x["kl_niem_yet"] or math.nan)}</td></tr>'
        )
    cot = [
        ("Ngày chấp thuận", ""),
        ("Chứng quyền", ""),
        ("Giá hợp lý dự kiến", "so"),
        ("Giá CS", "so"),
        ("Giá thực hiện", "so"),
        ("So với giá CS", "so"),
        ("Tỷ lệ CĐ", "so"),
        ("Đáo hạn", ""),
        ("Còn (ngày)", "so"),
        ("KL niêm yết", "so"),
    ]
    dau = "".join(
        f'<th class="{lop}"><button type="button" title="Bấm để sắp xếp">{ten}</button></th>' for ten, lop in cot
    )
    phan.append(
        f'<section class="the"><h2>{len(sap)} CW đang chờ lên sàn</h2>'
        + (
            f'<div class="cuon"><table><thead><tr>{dau}</tr></thead><tbody>{"".join(dong)}</tbody></table></div>'
            if sap
            else "<p>Hiện không có CW nào đang chờ lên sàn.</p>"
        )
        + f'<p class="phu">Nguồn: {nguon}.</p></section>'
        '<section class="the"><h2>Đọc bảng này thế nào?</h2><ul>'
        '<li><b>Chứng quyền</b>: tên đầy đủ theo HOSE, dạng <i>Mã CS / Tổ chức phát hành / thời hạn / số thứ tự</i>. Ví dụ "VPB/MSVN/7M/0226" là CW của VPB do MSVN phát hành, thời hạn 7 tháng.</li>'
        "<li><b>So với giá CS</b>: giá thực hiện so với giá cổ phiếu hiện tại. Số dương = giá thực hiện cao hơn (cổ phiếu phải tăng thêm chừng đó mới có giá trị nội tại).</li>"
        "<li><b>Giá hợp lý dự kiến</b> (đồng/CW): tính bằng Black-Scholes như các CW đang giao dịch, dùng giá và mức dao động của cổ phiếu cơ sở ở lần quét gần nhất"
        f'{f" (ngày {ngay:%d/%m/%Y})" if ngay else ""}. Khi CW lên sàn, so giá giao dịch với con số này: <b>thấp hơn là rẻ</b>, cao hơn là đắt.</li>'
        '<li>Mã nào chưa có giá cổ phiếu cơ sở trong lần quét gần nhất thì giá hợp lý hiện "—".</li>'
        '<li>Khi CW đã lên sàn, nó sẽ tự biến mất khỏi trang này và xuất hiện trong <a href="/">danh sách chính</a> (được đánh dấu <span class="chip">Mới</span>).</li>'
        "</ul></section>"
    )
    return trang("CW sắp ra mắt", "".join(phan), "/sap-ra-mat")


# ============ TRANG HƯỚNG DẪN ============
def trang_huong_dan():
    """Hướng dẫn cho người mới: CW là gì, cách dùng trang, ý nghĩa các con số, việc cần làm trước khi mua."""
    C = cw_scanner
    df, _ = doc_ket_qua()
    tot = df[df["Đánh giá"] == "NÊN XEM XÉT"] if df is not None else None
    vi_du = (
        f' Xem thử một ví dụ thật: <a href="/cw/{ESC(tot["Mã CW"].iloc[0])}">{ESC(tot["Mã CW"].iloc[0])}</a>.'
        if tot is not None and len(tot)
        else ""
    )
    muc = [
        ("cong-cu", "Công cụ này làm gì?"),
        ("cw-la-gi", "Chứng quyền là gì? (1 phút)"),
        ("5-buoc", "Dùng trang web trong 5 bước"),
        ("tieu-chi", "4 tiêu chí chấm điểm"),
        ("cac-cot", "Ý nghĩa từng cột trong bảng"),
        ("trang-phan-tich", "Đọc trang phân tích một mã"),
        ("gia-hop-ly", "Giá hợp lý được tính thế nào?"),
        ("truoc-khi-mua", "5 câu tự hỏi trước khi mua"),
        ("hoi-dap", "Câu hỏi thường gặp"),
    ]
    phan = [
        '<div class="huong-dan"><h1>Hướng dẫn sử dụng</h1><p class="phu">Đọc lần lượt từ trên xuống, khoảng 5 phút. '
        "Không cần biết lập trình hay công thức toán.</p>"
        '<nav class="the" aria-label="Mục lục"><h2>Mục lục</h2><ol class="muc-luc">'
        + "".join(f'<li><a href="#{a}">{t}</a></li>' for a, t in muc)
        + "</ol></nav>"
    ]

    phan.append(
        '<section class="the" id="cong-cu"><h2>1. Công cụ này làm gì?</h2>'
        "<p>Mỗi lần bạn bấm <b>Quét ngay</b>, chương trình tải giá của <b>tất cả chứng quyền đang niêm yết trên HOSE</b>, "
        "tính <b>giá hợp lý</b> của từng mã bằng công thức Black-Scholes, rồi chấm điểm theo 4 tiêu chí để bạn biết "
        "<b>nên xem kỹ mã nào</b> và <b>nên bỏ qua mã nào</b>.</p>"
        "<p>Chương trình <b>không mua bán giúp bạn</b>, <b>không dự báo cổ phiếu sẽ tăng hay giảm</b>, và <b>không phải lời khuyên đầu tư</b>. "
        'Nó giúp bạn trả lời câu hỏi: <i>"Nếu tôi đã muốn đặt cược vào cổ phiếu X, thì chứng quyền nào của X đang có giá tốt?"</i></p></section>'
    )

    phan.append(
        '<section class="the" id="cw-la-gi"><h2>2. Chứng quyền là gì? (1 phút)</h2><ul>'
        "<li>Mua chứng quyền (CW) = trả một khoản tiền nhỏ để được hưởng <b>phần tăng giá của một cổ phiếu</b> "
        "(gọi là <b>cổ phiếu cơ sở</b>) vượt trên một mức gọi là <b>giá thực hiện</b>, tính vào <b>ngày đáo hạn</b>.</li>"
        "<li><b>Ví dụ:</b> CW của VPB có giá thực hiện 22.605 đ, tỷ lệ chuyển đổi 1,5863 CW : 1 cổ phiếu. "
        "Nếu ngày đáo hạn VPB là 26.000 đ, mỗi CW nhận về (26.000 − 22.605) ÷ 1,5863 ≈ <b>2.140 đ</b>. "
        "Nếu VPB dưới 22.605 đ, CW <b>về 0 đ</b>.</li>"
        "<li><b>Lỗ tối đa</b> = toàn bộ tiền bạn bỏ ra mua CW. Không bao giờ lỗ nhiều hơn số đó.</li>"
        "<li><b>Lãi có thể gấp nhiều lần</b> nhờ <b>đòn bẩy</b>: cổ phiếu tăng 10% thì CW có thể tăng 50-100%.</li>"
        "<li><b>CW mất giá dần theo thời gian</b>: nếu cổ phiếu đứng yên, giá CW giảm dần mỗi ngày đến ngày đáo hạn.</li>"
        "<li>CW ngừng giao dịch <b>2 phiên trước ngày đáo hạn</b>. Nếu còn giữ đến đáo hạn, bạn nhận tiền mặt (không nhận cổ phiếu).</li>"
        "</ul></section>"
    )

    phan.append(
        '<section class="the" id="5-buoc"><h2>3. Dùng trang web trong 5 bước</h2><ol>'
        '<li><b>Bấm "Quét ngay"</b> ở <a href="/">trang chính</a> và chờ 1-3 phút. Nên quét <b>sau 15:00</b> các ngày giao dịch để có giá đóng cửa.</li>'
        "<li><b>Xem 4 ô số</b> ở đầu trang: có bao nhiêu mã <i>Nên xem xét</i>, <i>Theo dõi</i>, <i>Bỏ qua</i> và bao nhiêu mã mới phát hành.</li>"
        '<li><b>Xem bảng "Nên xem xét"</b>: đây là các mã đạt cả 4 tiêu chí. '
        '<b>Bấm vào tiêu đề cột để sắp xếp</b> (ví dụ bấm "So với giá hợp lý" để mã rẻ nhất lên đầu). '
        'Muốn tìm CW của một cổ phiếu cụ thể, gõ mã (VPB, HPG…) vào <b>ô tìm kiếm</b> của bảng "Tất cả".</li>'
        f"<li><b>Bấm vào một mã CW</b> để mở trang phân tích chi tiết (xem mục 6).{vi_du}</li>"
        "<li><b>Tự trả lời 5 câu hỏi</b> ở mục 8 rồi mới quyết định mua hay không. Đặt lệnh qua ứng dụng của công ty chứng khoán bạn đang dùng.</li>"
        '</ol><p class="phu">Mẹo: rê chuột lên tiêu đề cột bất kỳ để xem giải thích ngắn của cột đó.</p></section>'
    )

    phan.append(
        '<section class="the" id="tieu-chi"><h2>4. Bốn tiêu chí chấm điểm</h2><div class="cuon"><table class="bang-chu"><thead><tr>'
        "<th>Tiêu chí</th><th>Mức đang dùng</th><th>Vì sao quan trọng</th></tr></thead><tbody>"
        f"<tr><td>Thời gian còn lại</td><td>≥ {C.MIN_NGAY_CON_LAI} ngày</td><td>Gần ngày đáo hạn, CW mất giá rất nhanh và ít thời gian để cổ phiếu tăng.</td></tr>"
        f"<tr><td>Biến động ngầm định so với lịch sử (IV − HV)</td><td>≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm</td><td>Không trả cho mức dao động "
        'cao hơn hẳn 1 năm qua (tính theo giá mua = giá chào bán thấp nhất). Dùng IV thay cho "% đắt hơn giá hợp lý" vì cùng đắt 10% về giá, '
        "CW ngoài tiền chỉ tương đương khoảng +1,6 điểm IV còn CW sâu trong tiền tới khoảng +14 điểm; mức +3 điểm tương đương đắt 10% ở CW quanh tiền. "
        "CW có giá mua dưới mức tối thiểu của mô hình (không giải được IV) được tính là đạt, kèm cảnh báo.</td></tr>"
        f"<tr><td>Mức tăng cần để hòa vốn</td><td>≤ {C.MAX_TANG_DE_HOA_VON:.0%}</td><td>Mục tiêu phải thực tế: cổ phiếu tăng vài % dễ hơn nhiều so với tăng 30%.</td></tr>"
        f"<tr><td>Thanh khoản</td><td>≥ {so(C.MIN_KHOI_LUONG)} CW khớp/phiên</td><td>Đủ người mua bán thì bạn mới bán ra được đúng giá khi cần.</td></tr>"
        "</tbody></table></div><p>"
        + " · ".join(
            f"{huy_hieu(k)} {m}" for k, m in zip(KET_LUAN, ("đạt cả 4", "trượt 1 tiêu chí", "trượt từ 2 tiêu chí"))
        )
        + '</p><p class="phu">Muốn đổi các mức trên: mở file <code>cw_scanner.py</code>, sửa phần <b>CẤU HÌNH</b> ở đầu file, lưu lại rồi bấm Quét ngay.</p></section>'
    )

    phan.append(
        '<section class="the" id="cac-cot"><h2>5. Ý nghĩa từng cột trong bảng</h2><div class="cuon"><table class="bang-chu">'
        "<thead><tr><th>Cột</th><th>Ý nghĩa</th></tr></thead><tbody>"
        + "".join(f"<tr><td><b>{ten}</b></td><td>{ESC(gt)}</td></tr>" for ten, _, gt in COT)
        + "</tbody></table></div></section>"
    )

    phan.append(
        '<section class="the" id="trang-phan-tich"><h2>6. Đọc trang phân tích một mã</h2><ul>'
        "<li><b>Tóm tắt</b>: đọc đoạn này trước. Nó nói bạn trả bao nhiêu, cổ phiếu phải lên mức nào mới có lãi, và mỗi ngày CW mất bao nhiêu tiền. "
        "Bên dưới là 4 tiêu chí với dấu ✓ (đạt) hoặc ✕ (không đạt).</li>"
        "<li><b>Giá trị nội tại và giá trị thời gian</b>: giá CW = phần lãi nếu đáo hạn ngay hôm nay (<i>nội tại</i>) + phần trả thêm cho thời gian còn lại "
        "(<i>thời gian</i>). Phần thời gian luôn giảm về 0 vào ngày đáo hạn. Phần này càng nhỏ, bạn càng ít mất tiền do thời gian.</li>"
        "<li><b>Điểm hòa vốn</b>: giá cổ phiếu cần đạt vào ngày đáo hạn để bạn không lỗ không lãi.</li>"
        "<li><b>📐 Giá hợp lý … được tính thế nào?</b>: bấm vào để xem 7 bước tính giá hợp lý bằng số thật của mã đó, "
        "kèm phần kiểm chứng bằng 20.000 kịch bản (xem thêm mục 7).</li>"
        "<li><b>Khối lượng CW</b>: tổng số CW phát hành, số CW <b>đang chào bán</b> (lượng bạn mua được ngay và giá thấp nhất), "
        "số CW đang chờ mua (lượng bán ra được ngay) và sổ lệnh 3 mức giá, tải trực tiếp lúc mở trang.</li>"
        "<li><b>Đòn bẩy</b>: ví dụ 9x nghĩa là cổ phiếu tăng 1% thì CW tăng khoảng 9%, cổ phiếu giảm 1% thì CW giảm khoảng 9%.</li>"
        '<li><b>Delta</b> (từ 0 đến 1): mức CW "chạy theo" cổ phiếu. Ô này ghi sẵn cổ phiếu tăng/giảm 1.000 đ thì 1 CW tăng/giảm khoảng bao nhiêu đồng. '
        "Delta gần 1: CW bám sát cổ phiếu; gần 0: CW gần như không phản ứng (thường do giá cổ phiếu còn xa dưới giá thực hiện).</li>"
        '<li><b>Biến động ngầm định (IV)</b>: mức dao động mà giá mua CW đang "giả định". So với mức dao động thật 1 năm qua (HV): '
        '<b>IV − HV</b> âm → CW đang rẻ, dương → đắt. Khác với "% so với giá hợp lý", con số này so sánh được giữa các CW ở gần và xa giá thực hiện, '
        f'nên bảng xếp theo nó và dùng nó làm tiêu chí (≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm). "—" nghĩa là không giải được, thường do giá mua thấp hơn <b>mức tối thiểu</b> S − K × e<sup>−rT</sup> của mô hình '
        '(có khung ⚠ Lưu ý): khi đó chữ "Rẻ" chủ yếu đến từ giả định lãi suất và mức dao động, không chắc là món hời.</li>'
        "<li><b>Biểu đồ</b>: đường xanh là giá cổ phiếu 1 năm qua; đường xám là giá thực hiện; đường cam là <b>điểm hòa vốn</b>. "
        "Muốn có lãi khi giữ đến đáo hạn, giá cổ phiếu phải <b>nằm trên đường cam</b>. Rê chuột (hoặc bấm vào biểu đồ rồi dùng phím ← →) để xem giá từng ngày.</li>"
        '<li><b>Bảng "Nếu giữ đến ngày đáo hạn"</b>: xem trước lãi/lỗ theo từng kịch bản cổ phiếu tăng/giảm. '
        "Nhìn dòng <b>−10%</b> và <b>−20%</b> để biết <b>kịch bản xấu</b>, cột cuối cho biết lãi/lỗ theo số tiền bạn nhập ở mục <b>Rủi ro với số tiền của bạn</b>.</li>"
        "<li><b>Rủi ro với số tiền của bạn</b>: nhập số tiền định bỏ ra để xem mua được bao nhiêu CW, tương đương nắm bao nhiêu tiền cổ phiếu "
        "(thường gấp 5-15 lần), cổ phiếu giảm đến đâu thì mất toàn bộ, ngày cuối cùng còn bán được và điểm hòa vốn sau phí, thuế.</li>"
        '<li><b>IV theo thời gian</b>: biểu đồ mức dao động mà giá CW "giả định" từng ngày từ lúc lên sàn. IV thường cao lúc mới phát hành rồi '
        "giảm dần. Đáng chú ý khi IV xuống thấp hẳn dưới HV và trung vị các CW cùng mã (ví dụ CVPB2608, CVPB2615 của ACBS tháng 10/2026): "
        "tổ chức phát hành đang bán ra rẻ, nên giá có thể còn thấp nữa trước khi đáo hạn.</li>"
        "<li>Mọi con số ở trang phân tích được <b>tính lại theo giá trực tiếp</b> lúc mở trang (dòng đầu trang ghi giờ lấy giá). "
        "Kết luận có thể khác bảng ở trang chính (bảng đó là số lúc quét).</li>"
        "<li><b>Các CW khác của cùng cổ phiếu</b>: cùng đặt cược vào một cổ phiếu, hãy so để chọn CW rẻ hơn, còn nhiều ngày hơn hoặc dễ hòa vốn hơn.</li>"
        "<li>Khung màu vàng <b>⚠ Bất thường</b> (nếu có): giá CW thấp hơn cả giá trị nội tại. Hãy đọc thông báo của tổ chức phát hành trước khi mua.</li>"
        "</ul></section>"
    )

    phan.append(
        '<section class="the" id="gia-hop-ly"><h2>7. Giá hợp lý được tính thế nào? (nói đơn giản)</h2>'
        "<p><b>Ý tưởng:</b> tưởng tượng hàng nghìn kịch bản giá cổ phiếu có thể xảy ra đến ngày đáo hạn (cổ phiếu dao động mạnh hay yếu "
        "giống như 1 năm qua). Trong mỗi kịch bản, CW trả một số tiền hoặc về 0. <b>Giá hợp lý = trung bình số tiền đó, quy về tiền hôm nay.</b> "
        "Công thức Black-Scholes là cách tính nhanh ra con số trung bình này mà không cần thử từng kịch bản.</p>"
        "<p><b>Ví dụ dễ hình dung:</b> cổ phiếu giá 100 đ, giá thực hiện 100 đ, tỷ lệ 1 : 1.</p><ul>"
        "<li>Nếu đến ngày đáo hạn cổ phiếu chỉ có thể là <b>90 hoặc 110</b> (mỗi khả năng một nửa): CW trả 0 hoặc 10 → trung bình <b>5 đ</b>.</li>"
        "<li>Nếu cổ phiếu dao động mạnh hơn, là <b>70 hoặc 130</b>: CW trả 0 hoặc 30 → trung bình <b>15 đ</b>.</li></ul>"
        "<p>Cùng một cổ phiếu, dao động mạnh hơn thì CW đáng giá gấp 3. Lý do: lỗ tối đa chỉ là tiền mua CW, còn lãi thì không giới hạn.</p>"
        "<p><b>Công thức viết bằng lời:</b></p>"
        '<p class="cong-thuc">Giá hợp lý 1 CW = ( Giá cổ phiếu × A − Giá thực hiện × B ) ÷ Tỷ lệ chuyển đổi</p><ul>'
        '<li><b>Giá cổ phiếu × A</b> = phần bạn "nhận được"; <b>Giá thực hiện × B</b> = phần bạn "phải trả". Chênh lệch là giá trị của quyền.</li>'
        "<li><b>A</b> và <b>B</b> là hai hệ số từ 0 đến 1. <b>B</b> gần bằng <b>xác suất</b> đến ngày đáo hạn giá cổ phiếu vẫn trên giá thực hiện.</li>"
        "<li>A và B được tính từ 3 câu hỏi: giá đang cách giá thực hiện bao xa? còn bao nhiêu thời gian? cổ phiếu hay dao động cỡ nào?</li></ul>"
        "<p><b>3 quy luật dễ nhớ – CW đáng giá hơn khi:</b></p><ol>"
        "<li>Giá cổ phiếu <b>càng cao hơn</b> giá thực hiện.</li><li><b>Còn càng nhiều thời gian</b> đến ngày đáo hạn.</li>"
        "<li>Cổ phiếu <b>càng hay dao động mạnh</b> (như ví dụ trên).</li></ol>"
        f'<p>Muốn xem <b>từng bước tính bằng số thật</b>: mở trang phân tích một mã bất kỳ, bấm mục <b>"📐 Giá hợp lý … được tính thế nào?"</b>.{vi_du}</p></section>'
        '<section class="the" id="truoc-khi-mua"><h2>8. Năm câu tự hỏi trước khi mua</h2><ol>'
        "<li><b>Tôi có lý do tin cổ phiếu cơ sở sẽ lên trên điểm hòa vốn trước ngày đáo hạn không?</b> "
        "Công cụ chỉ cho biết CW đắt hay rẻ, không cho biết cổ phiếu sẽ tăng.</li>"
        "<li><b>Nếu cổ phiếu giảm 10-20%, tôi mất bao nhiêu?</b> Xem bảng kịch bản. Có thể mất gần hết tiền mua CW.</li>"
        f"<li><b>Còn đủ thời gian không?</b> Ưu tiên CW còn trên {C.MIN_NGAY_CON_LAI} ngày.</li>"
        "<li><b>Có CW nào khác của cùng cổ phiếu tốt hơn không?</b> Xem bảng so sánh ở cuối trang phân tích.</li>"
        "<li><b>Nếu mất hết số tiền này, tôi vẫn ổn chứ?</b> Chỉ dùng phần tiền bạn chấp nhận mất.</li></ol>"
        "<p><b>Khi đặt lệnh:</b> dùng <b>lệnh giới hạn (LO)</b> với mức giá bạn muốn thay vì mua bằng mọi giá; kiểm tra lại điều khoản CW "
        "trên website tổ chức phát hành / HOSE; ghi nhớ ngày giao dịch cuối cùng (2 phiên trước ngày đáo hạn).</p></section>"
    )

    hoi_dap = [
        (
            "Vì sao quét mất 1-3 phút?",
            "Gói miễn phí của vnstock giới hạn số lượt lấy dữ liệu mỗi phút, chương trình tự chờ rồi chạy tiếp. Có API key hợp lệ thì nhanh hơn.",
        ),
        (
            "Nhật ký có dòng [!] … số thiết bị tối đa?",
            "Tài khoản vnstock của bạn đã dùng hết số máy được phép. Vào trang tài khoản trên vnstocks.com để gỡ thiết bị cũ. Trong lúc đó chương trình vẫn quét được, chỉ chậm hơn.",
        ),
        (
            "Dữ liệu được cập nhật khi nào?",
            "Mỗi lần bấm Quét ngay. Ngày của dữ liệu ghi ở đầu trang chính. Giá trong ngày thay đổi liên tục nên hãy quét lại trước khi đặt lệnh.",
        ),
        (
            'Chữ "Mới" cạnh mã CW là gì?',
            "CW chưa có ở lần quét trước, tức là mới niêm yết. Lần quét đầu tiên chưa đánh dấu mã nào.",
        ),
        (
            "Xem các chứng quyền sắp ra mắt ở đâu?",
            (
                'Bấm "🆕 Sắp ra mắt" ở đầu trang. Đó là các CW HOSE đã chấp thuận niêm yết nhưng chưa giao dịch, '
                "kèm giá hợp lý dự kiến để so sánh khi CW lên sàn. Danh sách tải trực tiếp từ HOSE; nếu HOSE chậm thì dùng danh sách lưu ở lần quét gần nhất."
            ),
        ),
        (
            "Xem số CW đã bán ra và còn lại ở đâu?",
            (
                "Các nguồn dữ liệu miễn phí chỉ công bố tổng khối lượng phát hành, không công bố nhà đầu tư đang nắm bao nhiêu. "
                'Trang phân tích mỗi mã có mục "Khối lượng CW": khối lượng phát hành, số CW đang chào bán (lượng mua được ngay), đang chờ mua và sổ lệnh 3 mức giá, '
                'tải trực tiếp lúc mở trang. Cột "Đang chào bán" trong bảng là số liệu lúc quét.'
            ),
        ),
        (
            "Vì sao dùng giá chào bán (giá mua) chứ không dùng giá khớp?",
            (
                "Muốn mua ngay, bạn phải trả giá thấp nhất đang chào bán, thường cao hơn giá khớp gần nhất "
                "(có mã cao hơn hơn 10%). Định giá theo giá khớp có thể làm CW trông rẻ hơn thực tế. Khi sổ lệnh trống (trước giờ giao dịch), chương trình "
                'dùng giá khớp hoặc giá tham chiếu và ghi chữ nhỏ "khớp" / "TC" cạnh giá.'
            ),
        ),
        (
            '"Đắt > 1.000%" là sao?',
            "CW gần hết hạn và giá cổ phiếu còn quá xa giá thực hiện, nên giá hợp lý gần 0 đ. Gần như chắc chắn nên bỏ qua.",
        ),
        (
            '"Giá hợp lý" có chắc đúng không?',
            "Không. Nó dựa trên giả định mức dao động của cổ phiếu 1 năm qua sẽ lặp lại. Hãy coi nó là một ý kiến tham khảo, không phải sự thật.",
        ),
        (
            "Theo dõi CW đang nắm ở đâu?",
            (
                'Trang "💼 Danh mục": nhập lệnh mua/bán, xem lãi/lỗ nếu bán ngay, mức tiếp xúc với từng cổ phiếu cơ sở và '
                "cảnh báo. Có DISCORD_WEBHOOK_URL trong file .env thì cảnh báo được gửi lên Discord (chỉ mã, %, giá, lý do; không gửi số tiền) khi vừa xuất hiện: "
                "còn ít ngày tới ngày giao dịch cuối, cổ phiếu gần giá thực hiện, chạm chốt lời/cắt lỗ, không ai đặt mua, IV bất thường, phát hành thêm."
            ),
        ),
        (
            "Tắt chương trình thế nào?",
            "Đóng cửa sổ Terminal (Mac) hoặc cửa sổ đen (Windows), hoặc nhấn Ctrl + C trong cửa sổ đó.",
        ),
    ]
    phan.append(
        '<section class="the" id="hoi-dap"><h2>9. Câu hỏi thường gặp</h2>'
        + "".join(
            f'<details style="margin-top:10px"><summary>{ESC(q)}</summary><p>{ESC(a)}</p></details>' for q, a in hoi_dap
        )
        + "</section></div>"
    )
    return trang("Hướng dẫn sử dụng", "".join(phan), "/huong-dan")


# ============ TRANG DANH MỤC ============
def o_trang_thai(tt):
    """Ô "Trạng thái" của 1 vị thế: mức, các lý do (lý do chính đứng đầu), ghi chú dưới sàn lý thuyết."""
    if not tt:
        return "—"
    dong = [f"<b>{ESC(danh_muc.TEN_MUC[tt['muc']])}</b>"]
    dong += [f"<small>{ESC(nd or danh_muc.LY_DO_BAN[l])}</small>" for l, nd in tt["ly_do"]]  # nd: nội dung cảnh báo
    dong += [f"<small>ℹ {ESC(x)}</small>" for x in tt.get("thong_tin", [])]
    if tt["duoi_san"]:
        dong.append(f"<small class=am>🛑 bán dưới giá trị tối thiểu nếu giữ tới đáo hạn ({so(tt['san'])} đ)</small>")
    return "<br>".join(dong)


def trang_danh_muc():
    """Danh mục CW đang nắm: thêm/xóa lệnh, vị thế và cảnh báo theo giá trực tiếp."""
    global LOI_DANH_MUC
    C, D = cw_scanner, danh_muc
    df, ngay_quet = doc_ket_qua()
    phi_thue = f"phí {so(C.PHI_GIAO_DICH * 100, 2)}% + thuế {so(C.THUE_BAN * 100, 1)}%"
    phan = [
        (
            '<div class="dau-trang"><div><h1>Danh mục của tôi</h1><p class="phu">Lệnh lưu trong file <code>danh_muc.csv</code> trên máy này '
            f"(không đưa lên git, sao lưu mỗi ngày cùng kết quả quét). Lãi/lỗ tính <b>nếu bán ngay</b> ở giá chờ mua tốt nhất, đã trừ {phi_thue}; "
            "giá vốn bình quân đã gồm phí mua. Cảnh báo gửi Discord khi vừa xuất hiện (xem Hướng dẫn).</p></div></div>"
        )
    ]
    if LOI_DANH_MUC:
        phan.append(f'<p class="loi" role="alert">{ESC(LOI_DANH_MUC)}</p>')
        LOI_DANH_MUC = ""
    try:
        ds = D.doc_lenh()
        tat_ca = D.tinh_vi_the(ds)
    except Exception as e:  # file bị sửa tay sai định dạng: dừng lại, không ghi đè lên dữ liệu  # noqa: BLE001
        phan.append(
            f'<p class="loi" role="alert">File danh_muc.csv bị lỗi, hãy sửa lại bằng tay (bản trước: danh_muc.csv.bak): {ESC(str(e))}</p>'
        )
        return trang("Danh mục", "".join(phan), "/danh-muc")
    vt = {m: v for m, v in tat_ca.items() if v["so_luong"] > 0}

    # Vị thế đang nắm (giá trực tiếp)
    if vt:
        try:
            bang_gia = D.tai_bang_gia(list(vt), df, cho=5)
            nguon = f"bảng giá Vietcap lúc {datetime.now():%H:%M %d/%m/%Y}"
        except Exception as e:  # mất mạng: chỉ hiện số đang nắm và giá vốn  # noqa: BLE001
            bang_gia, nguon = None, f"KHÔNG tải được giá trực tiếp ({ESC(str(e)[:120])})"
        if bang_gia is not None:
            tt = json.loads(D.FILE_TRANG_THAI.read_text(encoding="utf-8")) if D.FILE_TRANG_THAI.exists() else {}
            dong, canh_bao, _ = D.danh_gia_danh_muc(
                vt,
                bang_gia,
                df if df is not None else pd.DataFrame(columns=["Mã CW", "Mã CS", "IV %"]),
                date.today(),
                tt.get("kl_niem_yet", {}),
                D.doc_lich_su(ngay_quet),
            )
        else:
            dong, canh_bao = [{"ma": m, **v, "co_gia": False} for m, v in sorted(vt.items())], []
        if canh_bao:
            phan.append(
                '<section class="the"><h2>⚠ Cảnh báo hiện tại</h2><ul>'
                + "".join(f"<li><b>{ESC(m)}</b>: {ESC(nd)}</li>" for m, _, nd in canh_bao)
                + "</ul></section>"
            )
        hang = []
        for d in dong:
            ma = ESC(d["ma"])
            if not d["co_gia"]:
                hang.append(
                    f'<tr><td><a href="/cw/{ma}">{ma}</a></td><td></td><td class="so">{so(d["so_luong"])}</td>'
                    f'<td class="so">{so(d["gia_von"], 1)}</td><td colspan="7">không có giá trực tiếp</td></tr>'
                )
                continue
            lop = "duong" if d["lai"] > 0 else ("am" if d["lai"] < 0 else "")
            # tính trước: f-string lồng nhau dùng lại cùng dấu nháy chỉ chạy từ Python 3.12 (web phải chạy được từ 3.10)
            ngay_gd = (
                f"{d['ngay_gd_cuoi']:%d/%m/%Y}<br><small>còn {d['con_ngay']} ngày</small>" if d["ngay_gd_cuoi"] else "—"
            )
            hang.append(
                f'<tr><td><a href="/cw/{ma}">{ma}</a></td><td>{ESC(d["cs"])}</td><td class="so">{so(d["so_luong"])}</td>'
                f'<td class="so">{so(d["gia_von"], 1)}</td><td class="so">{so(d["gia_ban"])}{"" if d["co_nguoi_mua"] else " <small class=am>không ai mua</small>"}</td>'
                f'<td class="so {lop}">{so(d["lai"], 0, True)}<br><small>{so(d["lai_pct"] * 100, 1, True)}%</small></td>'
                f'<td class="so">+{so(d["chot_loi"] * 100, 0)}% / −{so(d["cat_lo"] * 100, 0)}%</td>'
                f'<td class="so">{so(d["S"])} / {so(d["K"])}<br><small>{so(d["cach_K"] * 100, 1, True)}%</small></td>'
                f"<td>{ngay_gd}</td>"
                f'<td class="so">{so(d["don_bay"], 1)}x</td><td>{o_trang_thai(d.get("trang_thai"))}</td></tr>'
            )
        co_gia = [d for d in dong if d["co_gia"]]
        tiep_xuc = {}
        for d in co_gia:
            tiep_xuc[d["cs"]] = tiep_xuc.get(d["cs"], 0) + d["tiep_xuc"]
        von = sum(d["so_luong"] * d["gia_von"] for d in dong)
        phan.append(
            f'<section class="the"><h2>Đang nắm ({len(dong)} mã)</h2><p class="phu">Giá: {nguon}.</p><div class="luoi-o">'
            + o_so(
                "Tiền vốn đang nằm trong CW", f"{so(von / 1e6, 1)} triệu đ", "theo giá vốn bình quân, đã gồm phí mua"
            )
            + (
                o_so(
                    "Lãi/lỗ nếu bán hết ngay",
                    f'<span class="{"duong" if sum(d["lai"] for d in co_gia) >= 0 else "am"}">'
                    f'{so(sum(d["lai"] for d in co_gia) / 1e6, 2, True)} triệu đ</span>',
                    f"đã trừ {phi_thue} khi bán",
                )
                if co_gia
                else ""
            )
            + o_so(
                "Tương đương nắm cổ phiếu cơ sở",
                " · ".join(f"{ESC(cs)} {so(v / 1e6, 0)} tr" for cs, v in sorted(tiep_xuc.items())) or "—",
                "giá trị cổ phiếu mà các CW đang đại diện (thường gấp 5–15 lần tiền vốn)",
            )
            + "</div>"
            '<div class="cuon"><table><thead><tr><th>Mã CW</th><th>Mã CS</th><th class="so">Số lượng</th><th class="so">Giá vốn</th>'
            '<th class="so">Giá bán được</th><th class="so">Lãi/lỗ nếu bán ngay</th><th class="so">Chốt lời / cắt lỗ</th>'
            '<th class="so">Giá CS / giá TH</th><th>Ngày GD cuối</th><th class="so">Đòn bẩy</th><th>Trạng thái</th></tr></thead>'
            f'<tbody>{"".join(hang)}</tbody></table></div></section>'
        )
    lai_chot = sum(v["lai_da_chot"] for v in tat_ca.values())

    # Thêm lệnh
    hom_nay, ds_ma = date.today(), sorted(df["Mã CW"]) if df is not None else []
    phan.append(
        '<form method="post" action="/danh-muc/them" class="the form-lenh"><h2>Thêm lệnh</h2>'
        f'<label>Ngày<input type="date" name="ngay" value="{hom_nay}" max="{hom_nay}" required></label>'
        '<label>Mã CW<input name="ma_cw" list="ds-ma" required size="10" pattern="[Cc][A-Za-z]{3}[0-9]{4}" placeholder="CVPB2615"></label>'
        f'<datalist id="ds-ma">{"".join(f"<option value={ESC(m)}>" for m in ds_ma)}</datalist>'
        '<label>Loại<select name="loai"><option value="MUA">Mua</option><option value="BAN">Bán</option></select></label>'
        '<label>Số lượng (lô 100)<input type="number" name="so_luong" min="100" step="100" required></label>'
        '<label>Giá khớp (vd 0,87 hoặc 870)<input name="gia" inputmode="decimal" required size="10" placeholder="0,87"></label>'
        f'<label>Chốt lời % (lệnh mua)<input type="number" name="chot_loi" min="1" max="1000" placeholder="{so(danh_muc.CHOT_LOI_MAC_DINH * 100, 0)}"></label>'
        f'<label>Cắt lỗ % (lệnh mua)<input type="number" name="cat_lo" min="1" max="100" placeholder="{so(danh_muc.CAT_LO_MAC_DINH * 100, 0)}"></label>'
        '<label>Ghi chú<input name="ghi_chu" maxlength="200" size="18"></label>'
        '<p><button class="nut">Lưu lệnh</button></p>'
        '<p class="phu">Chốt lời / cắt lỗ để trống thì dùng mức mặc định ở đầu file danh_muc.py. Lệnh bán không được vượt số đang nắm.</p></form>'
    )

    # Lịch sử lệnh
    if ds:
        nguong = lambda d: (
            ("" if d["chot_loi"] is None else f"+{so(d['chot_loi'] * 100, 0)}%")
            + ("" if d["cat_lo"] is None else f" / −{so(d['cat_lo'] * 100, 0)}%")
        )
        hang = "".join(
            f'<tr><td class="so">{d["id"]}</td><td>{d["ngay"][8:]}/{d["ngay"][5:7]}/{d["ngay"][:4]}</td><td>{ESC(d["ma_cw"])}</td>'
            f'<td>{"Mua" if d["loai"] == "MUA" else "Bán"}</td><td class="so">{so(d["so_luong"])}</td><td class="so">{so(d["gia"])}</td>'
            f'<td class="so">{nguong(d)}</td><td class="ly-do">{ESC(d["ghi_chu"])}</td>'
            f'<td><form method="post" action="/danh-muc/xoa" onsubmit="return confirm(\'Xóa lệnh số {d["id"]}?\')">'
            f'<input type="hidden" name="id" value="{d["id"]}"><button class="nut-nho">Xóa</button></form></td></tr>'
            for d in sorted(ds, key=lambda d: (d["ngay"], d["id"]), reverse=True)
        )
        phan.append(
            f'<section class="the"><h2>Lịch sử lệnh ({len(ds)})</h2><p class="phu">Lãi/lỗ đã chốt (các lệnh bán): '
            f'<b class="{"duong" if lai_chot >= 0 else "am"}">{so(lai_chot, 0, True)} đ</b>. Xóa nhầm thì bản trước nằm trong danh_muc.csv.bak.</p>'
            '<div class="cuon"><table><thead><tr><th class="so">Số</th><th>Ngày</th><th>Mã CW</th><th>Loại</th><th class="so">Số lượng</th>'
            f'<th class="so">Giá</th><th class="so">Chốt / cắt</th><th>Ghi chú</th><th></th></tr></thead><tbody>{hang}</tbody></table></div></section>'
        )
    return trang("Danh mục", "".join(phan), "/danh-muc")


# ============ ETF ============
GIAI_THICH_SO_CS = (
    "Chỉ số giá chưa gồm cổ tức nên quỹ thường cao hơn một chút; thấp hơn nhiều: xem NAV so với chỉ số để biết do quỹ "
    "bám kém hay do giá rời NAV"
)
# (cột trong file kết quả, tiêu đề, số lẻ (None = chữ), có dấu +/−, hậu tố, giải thích khi rê chuột)
COT_CHI_SO = [
    ("Giá", "Điểm", 2, False, "", "Điểm chỉ số phiên cuối"),
    ("1T %", "1T", 1, True, "%", "Lợi nhuận 1 tháng lịch (theo giá, chưa gồm cổ tức)"),
    ("3T %", "3T", 1, True, "%", "Lợi nhuận 3 tháng lịch"),
    ("6T %", "6T", 1, True, "%", "Lợi nhuận 6 tháng lịch"),
    ("1N %", "1N", 1, True, "%", "Lợi nhuận 1 năm"),
    (
        "Xu hướng",
        "Xu hướng",
        None,
        False,
        "",
        "Tăng: giá và MA50 cùng trên MA200 · Giảm: cùng dưới · còn lại: Đi ngang",
    ),
    ("RSI14", "RSI14", 0, False, "", "RSI 14 phiên (Wilder): trên 70 là tăng nóng, dưới 30 là bị bán quá mức"),
    ("Biến động năm %", "Biến động", 1, False, "%", "Độ lệch chuẩn lợi suất ngày × √250 (như HV của CW)"),
    ("Giảm sâu nhất 1N %", "Sâu nhất 1N", 1, True, "%", "Mức giảm lớn nhất từ đỉnh trong 1 năm"),
    ("Cách đỉnh 1N %", "Cách đỉnh", 1, True, "%", "Giá hiện tại so với đỉnh 1 năm"),
]
COT_ETF = (
    [("Chỉ số", "Chỉ số", None, False, "", "Chỉ số mà quỹ mô phỏng"), ("Giá", "Giá (đ)", 0, False, "", "Giá khớp cuối")]
    + COT_CHI_SO[1:5]
    + [
        (
            "so CS",
            "so CS 1N",
            1,
            True,
            "",
            "Lợi nhuận 1 năm của quỹ − của chỉ số (điểm %). " + GIAI_THICH_SO_CS,
        )
    ]
    + COT_CHI_SO[5:]
    + [
        (
            "GTGD TB20 (tỷ)",
            "GTGD TB20",
            2,
            False,
            "",
            "Giá trị giao dịch TB 20 phiên, tỷ đồng (phiên không khớp tính 0)",
        ),
        ("Khối ngoại ròng (tỷ)", "Khối ngoại", 2, True, "", "Nhà đầu tư nước ngoài mua − bán trong phiên, tỷ đồng"),
        ("CCQ lưu hành", "CCQ lưu hành", 0, False, "", "Số chứng chỉ quỹ lưu hành: tăng = có tiền góp thêm vào quỹ"),
        (
            "Phiên khớp 1N",
            "Phiên khớp",
            0,
            False,
            "",
            f"Số phiên có khớp lệnh trong 1 năm (dưới {etf.MIN_PHIEN_KHOP}: chỉ số kỹ thuật kém tin cậy)",
        ),
        ("Phí quản lý %", "Phí QL", 2, False, "%", "Phí quản lý %/năm (điền trong etf.py, PHI_QUAN_LY)"),
    ]
)


COT_CK = [
    (
        "Đạt",
        "Đạt ngưỡng",
        None,
        False,
        "",
        "🟢: lãi ròng nếu về NAV ≥ ngưỡng và mua được ≥ mức tối thiểu (chiet_khau.py)",
    ),
    ("Chỉ số", "Chỉ số", None, False, "", "Chỉ số mà quỹ mô phỏng"),
    (
        "Giá chào bán",
        "Chào bán (đ)",
        0,
        False,
        "",
        "Giá chào bán tốt nhất: giá mua được ngay (sau 14:45 là sổ lệnh còn lại)",
    ),
    ("KL chào bán", "KL chào bán", 0, False, "", "Số CCQ ở giá chào bán tốt nhất"),
    ("iNAV", "iNAV (đ)", 0, False, "", "NAV ước tính trong phiên (SSI iBoard); sau 14:45 là iNAV cuối phiên"),
    ("Chiết khấu mua được %", "CK", 1, True, "%", "Giá chào bán / iNAV − 1: âm = mua được dưới NAV"),
    (
        "Lãi ròng nếu về NAV %",
        "Lãi ròng",
        1,
        True,
        "%",
        "Lãi nếu mua ở giá chào bán rồi bán đúng NAV, sau phí mua/bán và thuế bán",
    ),
    ("Mua được đạt ngưỡng (đ)", "Mua được (đ)", 0, False, "", "Giá trị chào bán ở các mức giá đạt ngưỡng lãi ròng"),
    (
        "CL NAV trung vị 1N %",
        "Thường lệch",
        1,
        True,
        "%",
        "Trung vị (giá đóng cửa / NAV − 1) 1 năm của chính quỹ: quỹ luôn chiết khấu thì CK âm chưa chắc là rẻ bất thường",
    ),
    ("CL NAV thấp nhất 1N %", "Sâu nhất 1N", 1, True, "%", "Mức chiết khấu sâu nhất 1 năm (theo giá đóng cửa)"),
    (
        "Phiên chưa khớp",
        "Phiên chưa khớp",
        0,
        False,
        "",
        "Số phiên từ lần khớp cuối: giá khớp cũ thì đừng tin giá khớp",
    ),
    ("GTGD TB20 (tỷ)", "GTGD TB20", 2, False, "", "Giá trị giao dịch TB 20 phiên, tỷ đồng: thấp = khó bán ra"),
    ("Phí quản lý %", "Phí QL", 2, False, "%", "Phí quản lý %/năm"),
    (
        "NAV so CS 1N",
        "NAV−CS 1N",
        1,
        True,
        "",
        "Lợi nhuận NAV 1 năm − của chỉ số (điểm %): âm nhiều = quỹ bám chỉ số kém. " + GIAI_THICH_SO_CS,
    ),
]


def bang_etf(df, cot, la_quy, id_bang="", cot_ma="Mã", lien_ket="/etf/", ten_ma=None):
    """Bảng số theo danh sách cột (dùng cho ETF và trang Lướt CW); bấm tiêu đề để sắp xếp, bấm vào mã để mở trang chi tiết
    (la_quy: có liên kết lien_ket + mã)."""
    dau = "".join(
        f'<th class="{"" if le is None else "so"}"><button type="button" title="{ESC(gt)} (Bấm để sắp xếp.)">{ESC(td)}</button></th>'
        for _, td, le, _, _, gt in cot
    )
    dong = []
    for _, h in df.iterrows():
        ma = ESC(h[cot_ma])
        chip = (
            f'<span class="chip" style="color:var(--chu-am)" title="{ESC(h["Cảnh báo"])}" aria-label="Cảnh báo: {ESC(h["Cảnh báo"])}">⚠</span>'
            if h["Cảnh báo"]
            else ""
        )
        o = [f'<td><a href="{lien_ket}{ma}">{ma}</a>{chip}</td>' if la_quy else f"<td>{ma}{chip}</td>"]
        for c, _, le, co_dau, hau_to, _ in cot:
            v = h[c]
            if le is None:
                o.append(f"<td>{ESC(str(v))}</td>")
            elif not math.isfinite(v):
                o.append('<td class="so" data-v="-1e18">—</td>')
            else:
                lop = (" duong" if v > 0 else " am" if v < 0 else "") if co_dau else ""
                o.append(f'<td class="so{lop}" data-v="{v}">{so(v, le, co_dau)}{hau_to}</td>')
        href = f' data-href="{lien_ket}{ma}"' if la_quy else ""
        dong.append(f'<tr{href}>{"".join(o)}</tr>')
    return (
        f'<table{f" id={id_bang}" if id_bang else ""}><thead><tr><th><button type="button" title="Bấm để sắp xếp.">'
        f'{ten_ma or ("Quỹ" if la_quy else "Chỉ số")}</button></th>{dau}</tr></thead><tbody>{"".join(dong)}</tbody></table>'
    )


def doc_etf():
    """(chỉ số, quỹ có cột "so CS", ngày) từ file kết quả ETF mới nhất; chưa có -> (None, None, None)."""
    df, ngay = etf.doc_ket_qua()
    if df is None:
        return None, None, None
    cs, quy = df[df["Loại"] == "Chỉ số"], df[df["Loại"] == "ETF"].copy()
    quy["so CS"] = quy["1N %"] - quy["Chỉ số"].map(dict(zip(cs["Mã"], cs["1N %"])))
    return cs, quy, ngay


def trang_etf():
    cs, quy, ngay = doc_etf()
    phan = [
        '<h1>Quỹ ETF</h1><p class="phu">'
        + (
            f"Dữ liệu ngày {ngay:%d/%m/%Y} · {len(quy)} quỹ · tự cập nhật 9:40 thứ Hai–Sáu (giữa phiên)"
            if ngay
            else "Chưa có dữ liệu"
        )
        + "</p>"
    ]
    if ngay is None:
        phan.append(
            '<div class="the"><h2>Chưa có kết quả</h2><p>Chạy <code>.venv/bin/python etf.py --no-discord</code> '
            "trong thư mục dự án (hoặc chờ lịch 9:40) rồi tải lại trang.</p></div>"
        )
        return trang("Quỹ ETF", "".join(phan), "/etf")
    phan.append(
        '<p class="phu">Rê chuột lên tiêu đề cột để xem giải thích, bấm vào một quỹ để xem biểu đồ giá và chênh lệch so với NAV.</p>'
    )
    ck = quy.assign(
        Đạt=lambda d: d["Mua được đạt ngưỡng (đ)"].map(lambda v: "🟢" if v >= chiet_khau.MIN_GIA_TRI_CHAO_BAN else "")
    ).sort_values("Lãi ròng nếu về NAV %", ascending=False)
    phan.append(
        '<section class="the"><h2>Chiết khấu so với NAV</h2>'
        f'<p class="phu">Ngưỡng: lãi ròng nếu mua ở giá chào bán rồi bán đúng NAV ≥ {chiet_khau.NGUONG_LAI_RONG:.0%} và mua được '
        f"≥ {so(chiet_khau.MIN_GIA_TRI_CHAO_BAN / 1e6)} triệu. Chỉ có lời khi giá quay về sát NAV — quỹ ít giao dịch có thể "
        "chiết khấu rất lâu (xem cột Thường lệch).</p>"
        f'<div class="cuon">{bang_etf(ck, COT_CK, True)}</div></section>'
    )
    phan.append(
        f'<section class="the"><h2>Chỉ số ({len(cs)})</h2><div class="cuon">{bang_etf(cs, COT_CHI_SO, False)}</div></section>'
    )
    phan.append(
        f'<section class="the"><h2>Tất cả {len(quy)} quỹ</h2>'
        '<input type="search" data-loc="#bang-etf" placeholder="Tìm theo mã quỹ hoặc chỉ số (vd: VN30, DIAMOND)" aria-label="Tìm quỹ ETF">'
        f'<div class="cuon cao">{bang_etf(quy, COT_ETF, True, "bang-etf")}</div></section>'
    )
    canh_bao = [(h["Mã"], h["Cảnh báo"]) for d in (cs, quy) for _, h in d.iterrows() if h["Cảnh báo"]]
    if canh_bao:
        phan.append(
            f'<details class="the"><summary>Cảnh báo dữ liệu ({len(canh_bao)})</summary><ul>'
            + "".join(f"<li><b>{ESC(m)}</b>: {ESC(c)}</li>" for m, c in canh_bao)
            + "</ul></details>"
        )
    return trang("Quỹ ETF", "".join(phan), "/etf")


def doc_nav(ma):
    """NAV đã làm sạch của 1 quỹ từ file ket_qua/nav_etf_*.csv.gz mới nhất CÓ quỹ đó (etf.py lưu lúc 9:40; hôm nguồn lỗi
    thì quỹ thiếu ở file mới) -> Series, chưa có -> None. File hỏng: báo lỗi (trang hiện lý do)."""
    for tep in sorted(cw_scanner.THU_MUC_KET_QUA.glob("nav_etf_*.csv.gz"), reverse=True):
        d = pd.read_csv(tep, compression="gzip")
        d = d[d["Mã"] == ma]
        if len(d):
            return pd.Series(d["NAV"].to_numpy(float), pd.DatetimeIndex(d["Ngày"]))
    return None


def trang_etf_chi_tiet(ma):
    _, quy, ngay = doc_etf()
    if ngay is None or ma not in set(quy["Mã"]):  # chỉ nhận mã có trong file kết quả (chặn mã lạ từ URL)
        return None
    h = quy[quy["Mã"] == ma].iloc[0]
    o = lambda c, le=1, dau=True, hau_to="%": so(h[c], le, dau) + (hau_to if math.isfinite(h[c]) else "")
    phan = [
        (
            f'<p><a href="/etf">← Tất cả quỹ ETF</a></p><h1>{ESC(ma)}</h1>'
            f'<p class="phu">Mô phỏng {ESC(h["Chỉ số"])} · dữ liệu ngày {ngay:%d/%m/%Y}</p>'
        )
    ]
    if h["Cảnh báo"]:
        phan.append(f'<p class="ghi-chu-canh-bao">⚠ {ESC(h["Cảnh báo"])}</p>')
    phan.append(
        '<div class="luoi-o">'
        + o_so(
            "Chiết khấu mua được",
            o("Chiết khấu mua được %"),
            f"chào bán {so(h['Giá chào bán'])} × {so(h['KL chào bán'])} CCQ so với iNAV {so(h['iNAV'])} · "
            f"lãi ròng nếu về NAV {o('Lãi ròng nếu về NAV %')}",
        )
        + o_so(
            "Thường lệch NAV (1 năm)",
            o("CL NAV trung vị 1N %"),
            f"trung vị giá đóng cửa / NAV − 1; sâu nhất {o('CL NAV thấp nhất 1N %')}",
        )
        + o_so(
            "NAV so với chỉ số (1 năm)", o("NAV so CS 1N", hau_to=" điểm"), f"NAV đến {ESC(h['Ngày NAV cuối']) or '—'}"
        )
        + o_so("Giá", f"{so(h['Giá'])} đ", f"phiên khớp cuối {ESC(h['Ngày giá cuối'])}")
        + o_so("Lợi nhuận 1 năm", o("1N %"), f"1T {o('1T %')} · 3T {o('3T %')} · 6T {o('6T %')}")
        + o_so(
            f"So với {ESC(h['Chỉ số'])} (1 năm)",
            o("so CS", hau_to=" điểm"),
            GIAI_THICH_SO_CS,
        )
        + o_so("Xu hướng", ESC(h["Xu hướng"]) or "—", f"MA50 {so(h['MA50'])} · MA200 {so(h['MA200'])}")
        + o_so("RSI14", so(h["RSI14"], 0), "trên 70 tăng nóng · dưới 30 bị bán quá mức")
        + o_so("Biến động năm", o("Biến động năm %", dau=False), f"giảm sâu nhất 1 năm {o('Giảm sâu nhất 1N %')}")
        + o_so("Cách đỉnh 1 năm", o("Cách đỉnh 1N %"))
        + o_so(
            "Giá trị giao dịch TB 20 phiên",
            f"{so(h['GTGD TB20 (tỷ)'], 2)} tỷ",
            f"{so(h['Phiên khớp 1N'])} phiên có khớp lệnh trong 1 năm",
        )
        + o_so("Khối ngoại ròng trong phiên", f"{so(h['Khối ngoại ròng (tỷ)'], 2, True)} tỷ")
        + o_so("Chứng chỉ quỹ lưu hành", so(h["CCQ lưu hành"]), "tăng = có tiền góp thêm vào quỹ")
        + "</div>"
    )
    bd_cl = "<p>Chưa có lịch sử NAV của quỹ này.</p>"
    try:  # 1 lượt gọi vnstock mỗi lần mở trang
        ls = cw_scanner.lay_gia_dong_cua(ma, etf.SO_NGAY_LICH_SU, "VCI")
        gia = etf.chuoi_gia(ls, 10 ** round(math.log10(h["Giá"] / float(ls["close"].iloc[-1]))))[
            0
        ]  # nghìn đồng -> đồng
        trong_1_nam = gia.index > gia.index[-1] - pd.DateOffset(years=1)
        lich_su = [[str(d.date()), float(g)] for d, g in gia[trong_1_nam].items()]
        phu = [
            (f"MA{n}", [None if math.isnan(v) else float(v) for v in gia.rolling(n).mean()[trong_1_nam]], lop)
            for n, lop in ((etf.MA_NGAN, "ma-ngan"), (etf.MA_DAI, "ma-dai"))
        ]
        bd = (
            bieu_do(lich_su, [], f"Giá {ma}", duong_phu=phu)
            if len(lich_su) > 1
            else "<p>Quá ít phiên có khớp lệnh trong 1 năm để vẽ biểu đồ.</p>"
        )
    except Exception as e:  # mất mạng / vnstock lỗi: báo rõ trên trang  # noqa: BLE001
        gia, bd = None, f'<p class="loi" role="alert">Không tải được lịch sử giá: {ESC(str(e)[:200])}</p>'
    if gia is not None:
        try:  # file NAV hỏng không được làm mất biểu đồ giá
            nav = doc_nav(ma)
            cl = ((gia / nav).dropna() - 1) * 100 if nav is not None else pd.Series(dtype=float)  # chỉ phiên có khớp
            cl = cl[cl.index > cl.index[-1] - pd.DateOffset(years=1)] if len(cl) else cl
            if len(cl) > 1:
                bd_cl = bieu_do(
                    [[str(d.date()), round(float(v), 2)] for d, v in cl.items()],
                    [("Trung vị", float(cl.median()), "tc-thuc-hien"), ("Ngang NAV", 0.0, "tc-hoa-von")],
                    f"Chênh lệch giá/NAV {ma}",
                    don_vi="%",
                    ten_cot="Giá / NAV − 1 (%)",
                    so_le=1,
                )
        except Exception as e:  # noqa: BLE001
            bd_cl = f'<p class="loi" role="alert">Không đọc được lịch sử NAV: {ESC(str(e)[:200])}</p>'
    phan.append(
        '<section class="the"><h2>Chênh lệch giá / NAV 1 năm</h2>'
        '<p class="phu">Giá đóng cửa các phiên có khớp chia NAV cùng ngày − 1. Dưới 0 = chiết khấu. Giá đóng cửa của quỹ ít '
        "giao dịch thường là 1 lô nhỏ nên đường này nhiễu; đường xám là trung vị, đường cam là ngang NAV.</p>"
        f"{bd_cl}</section>"
    )
    phan.append(
        '<section class="the"><h2>Giá 1 năm, MA50 và MA200</h2>'
        '<p class="phu">MA50 (cam) / MA200 (xám, nét đứt): trung bình giá đóng cửa 50 / 200 phiên có khớp lệnh.</p>'
        f"{bd}</section>"
    )
    return trang(f"{ma} - Quỹ ETF", "".join(phan), "/etf")


# ============ LƯỚT CW ============
COT_LUOT = [
    ("Mã CS", "Mã CS", None, False, "", "Cổ phiếu cơ sở: hướng đi của nó là phần bạn tự nhận định"),
    (
        "Lướt: CS cần tăng %",
        f"CS cần tăng ({cw_scanner.SO_PHIEN_GIU} phiên)",
        2,
        True,
        "%",
        (
            f"Ưu tiên 2 (xếp theo cột này): CS phải tăng bao nhiêu trong {cw_scanner.SO_PHIEN_GIU} phiên để hòa vốn — mua ở giá "
            "chào bán + phí, bán ở mức giá chờ mua − phí, thuế, CW mất giá theo thời gian; IV giữ nguyên. Càng thấp càng tốt"
        ),
    ),
    (
        "Lướt: lãi kịch bản %",
        f"Lãi nếu CS +{cw_scanner.KICH_BAN_TANG:.0%}",
        1,
        True,
        "%",
        (
            f"Ưu tiên 3: lãi sau phí, thuế nếu CS tăng {cw_scanner.KICH_BAN_TANG:.0%} trong {cw_scanner.SO_PHIEN_GIU} phiên "
            "(cùng giả định); CS đứng yên hoặc giảm thì lỗ tương ứng"
        ),
    ),
    (
        "Lướt: lãi kịch bản hiệu chỉnh %",
        f"Lãi nếu CS +{cw_scanner.KICH_BAN_TANG:.0%} (hiệu chỉnh TCPH)",
        1,
        True,
        "%",
        (
            f"Như cột trước nhưng IV bán ra = IV chờ mua + β × {cw_scanner.KICH_BAN_TANG:.0%}: β = số điểm IV TCPH này đã đổi khi "
            "CS tăng 1% (đo lịch sử, ACBS và Vietcap hạ IV khi CS tăng). — = TCPH ít mẫu, không hiệu chỉnh. Không dùng để xếp hạng"
        ),
    ),
    (
        "Đòn bẩy",
        "Đòn bẩy",
        1,
        False,
        "x",
        "CS +1% thì CW tăng khoảng bấy nhiêu % (theo giá mua); lỗ cũng nhanh như vậy",
    ),
    ("Mất giá/ngày %", "Mất giá/ngày", 2, True, "%", "CW mất bao nhiêu mỗi ngày nếu CS và IV đứng yên"),
    (
        "IV − HV",
        "IV − HV",
        1,
        True,
        "",
        "Ưu tiên 4: IV (theo giá mua) − biến động lịch sử, điểm %: cao = đắt, IV giảm về thì CW mất giá dù CS tăng",
    ),
    (
        "IV cùng mã %",
        "IV TV cùng mã",
        0,
        False,
        "%",
        "Trung vị IV các CW khác cùng mã CS: IV của CW này cao hơn = đắt hơn",
    ),
    ("Giá mua", "Chào bán", 0, False, "", "Giá chào bán thấp nhất lúc quét: giá mua được ngay"),
    ("Giá chờ mua", "Chờ mua", 0, False, "", "Giá chờ mua cao nhất lúc quét: giá bán ra được ngay"),
    ("Spread %", "Spread", 1, False, "%", "(chào bán − chờ mua) / giá giữa"),
    ("Bên mua 3 bước (triệu)", "Bên mua (tr)", 1, False, "", "Tổng giá trị chờ mua ở 3 bước giá: chỗ để bán ra"),
    ("KL chào bán", "KL chào bán", 0, False, "", "Ưu tiên 5: còn nhiều = TCPH sẵn hàng, giá khó lên nhanh"),
    ("Ngày GD cuối", "GD cuối", None, False, "", "Sau ngày này không bán được"),
    ("TCPH", "TCPH", None, False, "", "Tổ chức phát hành (bên yết giá chính)"),
]


def trang_luot():
    df, ngay = doc_ket_qua()
    phan = ["<h1>⚡ Lướt CW 2–5 phiên</h1>"]
    if df is None:
        phan.append(
            '<div class="the"><p>Chưa có kết quả quét. Bấm <b>Quét ngay</b> ở <a href="/">trang chính</a>.</p></div>'
        )
        return trang("Lướt CW", "".join(phan), "/luot-cw")
    dat, loai = cw_scanner.chon_luot(df, ngay)
    C = cw_scanner
    tep_he_so, beta = C.doc_he_so_iv()
    dat = dat.assign(**{"Lướt: lãi kịch bản hiệu chỉnh %": C.lai_kb_hieu_chinh(dat, ngay, beta)})
    he_so = (
        f"Cột <b>(hiệu chỉnh TCPH)</b> chỉ để tham khảo, không đổi thứ tự: IV bán ra = IV chờ mua + β × {C.KICH_BAN_TANG:.0%}, "
        f"β theo <code>{ESC(tep_he_so)}</code> (kiem_chung_truyen_dan.py, TCPH có ≥ {C.MIN_MAU_HE_SO_IV} cửa sổ đo): "
        + ", ".join(f"{ESC(t)} {so(b, 2, True)}" for t, b in sorted(beta.items(), key=lambda x: x[1]))
        + " điểm IV khi CS +1%. Đo bằng giá đóng cửa, không phải giá yết của TCPH; hệ số đổi theo thời kỳ."
        if tep_he_so
        else "Chưa có bảng hệ số IV theo TCPH (chạy <code>python kiem_chung_truyen_dan.py</code>): cột hiệu chỉnh để trống."
    )
    phan.append(
        f'<p class="phu">Số liệu lần quét {ngay:%d/%m/%Y} (sổ lệnh lúc quét; bấm vào mã để định giá lại theo giá trực tiếp). '
        f"Python <b>không đoán hướng cổ phiếu</b>: bạn chọn mã CS mình nhận định sẽ tăng, trang này chỉ ra CW nào rẻ và hiệu quả "
        f"nhất để đặt cược đó.</p>"
        '<details class="the" open><summary>Thứ tự ưu tiên khi chọn CW để lướt</summary><ol>'
        f"<li><b>Loại CW khó thoát lệnh:</b> không có người chào bán / chờ mua, bên mua dưới {so(C.MIN_BEN_MUA_LUOT / 1e6)} triệu, "
        f"spread trên {C.MAX_SPREAD_LUOT:.0%}, còn dưới {C.MIN_NGAY_GD_CUOI_LUOT} ngày tới ngày GD cuối.</li>"
        f"<li><b>CS cần tăng ít nhất để hòa vốn trong {C.SO_PHIEN_GIU} phiên</b> (bảng xếp theo cột này): đã gồm đòn bẩy, mất giá "
        "theo thời gian, spread, phí, thuế.</li>"
        f"<li><b>Lãi nếu CS tăng {C.KICH_BAN_TANG:.0%}</b>: CW nào khuếch đại tốt nhất sau chi phí.</li>"
        "<li><b>IV:</b> IV − HV cao hoặc IV cao hơn các CW cùng mã = đắt, IV giảm về thì CW mất giá dù CS tăng.</li>"
        "<li><b>Tổ chức phát hành:</b> khối lượng chào bán còn rất nhiều hoặc vừa phát hành thêm thì giá khó lên.</li></ol>"
        f'<p class="phu">Giả định IV giữ nguyên {C.SO_PHIEN_GIU} phiên; mua phiên T thì sớm nhất chiều T+2 mới bán được. '
        f'Đòn bẩy cao cũng là lỗ nhanh.</p><p class="phu">{he_so}</p></details>'
    )
    if dat["Lướt: CS cần tăng %"].isna().all() and loai["Lướt: CS cần tăng %"].isna().all():
        phan.append('<p class="loi">File quét này từ bản cũ, chưa có số liệu lướt: bấm Quét ngay ở trang chính.</p>')
    phan.append(
        f'<section class="the"><h2>Lướt được ({len(dat)} CW)</h2>'
        '<input type="search" data-loc="#bang-luot" placeholder="Lọc theo mã cổ phiếu hoặc mã CW (vd: VPB, HPG)" '
        'aria-label="Lọc CW theo mã">'
        f'<div class="cuon cao">{bang_etf(dat, COT_LUOT, True, "bang-luot", "Mã CW", "/cw/", "Mã CW")}</div></section>'
    )
    phan.append(
        f'<details class="the"><summary>Bị loại ({len(loai)} CW) và lý do</summary><div class="cuon cao">'
        + bang_etf(
            loai,
            [("Mã CS", "Mã CS", None, False, "", "Cổ phiếu cơ sở"), ("Lý do loại lướt", "Lý do", None, False, "", "")],
            True,
            "",
            "Mã CW",
            "/cw/",
            "Mã CW",
        )
        + "</div></details>"
    )
    return trang("Lướt CW", "".join(phan), "/luot-cw")


def nguon_hop_le(headers):
    """Chặn POST từ trang web khác (CSRF): chỉ nhận khi Origin (hoặc Referer) là chính trang này."""
    nguon = headers.get("Origin") or headers.get("Referer") or ""
    goc = (f"http://localhost:{CONG}", f"http://127.0.0.1:{CONG}")
    return nguon in goc or nguon.startswith(tuple(g + "/" for g in goc))


class XuLy(BaseHTTPRequestHandler):
    def do_GET(self):
        duong_dan = self.path.split("?")[0]
        m = re.fullmatch(r"/cw/([A-Z0-9]{4,12})", duong_dan)  # chỉ nhận mã hợp lệ
        m_etf = re.fullmatch(r"/etf/(" + chiet_khau.MAU_MA_QUY.pattern + ")", duong_dan)
        noi_dung = (
            trang_luot()
            if duong_dan == "/luot-cw"
            else (
                trang_etf()
                if duong_dan == "/etf"
                else (
                    trang_etf_chi_tiet(m_etf.group(1))
                    if m_etf
                    else (
                        trang_chinh()
                        if duong_dan == "/"
                        else (
                            trang_huong_dan()
                            if duong_dan == "/huong-dan"
                            else (
                                trang_danh_muc()
                                if duong_dan == "/danh-muc"
                                else (
                                    trang_sap_ra_mat("tai_moi=1" in self.path)
                                    if duong_dan == "/sap-ra-mat"
                                    else trang_chi_tiet(m.group(1), doc_von(self.path)) if m else None
                                )
                            )
                        )
                    )
                )
            )
        )
        self.send_response(200 if noi_dung else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            (
                noi_dung
                or trang("Không tìm thấy", '<h1>Không tìm thấy</h1><p><a href="/">← Về danh sách chứng quyền</a></p>')
            ).encode("utf-8")
        )

    def do_POST(self):
        global LOI, NHAT_KY, LOI_DANH_MUC
        duong_dan = urlsplit(self.path).path
        if not nguon_hop_le(self.headers):  # trang web lạ không được tự bấm "Quét ngay" hay thêm/xóa lệnh hộ bạn
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Từ chối: yêu cầu không gửi từ trang cw_scanner.".encode())
            return
        ve_trang = "/"
        if duong_dan == "/quet":
            bo_dem = io.StringIO()
            try:
                with contextlib.redirect_stdout(bo_dem):  # gom lời nhắn của cw_scanner để hiện lên trang
                    cw_scanner.main()
                LOI = ""
            except Exception as e:  # lỗi mạng/API: báo trên trang thay vì làm sập máy chủ  # noqa: BLE001
                LOI = f"Lỗi khi quét: {e}"
            NHAT_KY = bo_dem.getvalue()
        elif duong_dan in ("/danh-muc/them", "/danh-muc/xoa"):
            ve_trang = "/danh-muc"
            form = parse_qs(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)).decode("utf-8"))
            try:
                if duong_dan.endswith("them"):
                    df, _ = doc_ket_qua()
                    LOI_DANH_MUC = "; ".join(
                        danh_muc.them_lenh(form, set(df["Mã CW"]) if df is not None else set(), date.today())
                    )
                else:
                    so_lenh = (form.get("id") or [""])[0]
                    LOI_DANH_MUC = danh_muc.xoa_lenh(int(so_lenh)) if so_lenh.isdigit() else "số lệnh không hợp lệ"
            # vd file danh_muc.csv bị sửa tay sai định dạng: báo lên trang, không ghi gì
            except Exception as e:  # noqa: BLE001
                LOI_DANH_MUC = f"Không lưu được: {e}"
        else:
            self.send_error(404)
            return
        self.send_response(303)  # quay về trang để bấm F5 không gửi lại form
        self.send_header("Location", ve_trang)
        self.end_headers()


if __name__ == "__main__":
    # Chỉ mở cho máy của bạn (127.0.0.1), người khác trong mạng không truy cập được
    may_chu = HTTPServer(("127.0.0.1", CONG), XuLy)
    print(f"Giao diện web: http://localhost:{CONG}  (Ctrl+C để tắt)")
    webbrowser.open(f"http://localhost:{CONG}")
    may_chu.serve_forever()
