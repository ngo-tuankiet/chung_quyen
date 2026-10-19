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
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, HTTPServer

import pandas as pd

import cw_scanner

CONG = 8000
VON_MAC_DINH = 10  # triệu đồng: số tiền mặc định ở mục "Rủi ro với số tiền của bạn"
LOI = ""  # lỗi của lần quét gần nhất (chỉ 1 người dùng trên máy mình nên dùng biến toàn cục là đủ)
NHAT_KY = ""  # mọi dòng cw_scanner in ra trong lần quét gần nhất
ESC = html.escape
# kết luận -> (lớp màu, biểu tượng, nhãn). Màu luôn đi kèm biểu tượng + chữ, không dùng màu một mình
KET_LUAN = {"NÊN XEM XÉT": ("tot", "✓", "Nên xem xét"), "THEO DÕI": ("canh-bao", "!", "Theo dõi"), "BỎ QUA": ("bo-qua", "✕", "Bỏ qua")}
# Các cột của bảng danh sách: (tiêu đề, căn lề, giải thích cho người mới - hiện khi rê chuột lên tiêu đề và ở trang Hướng dẫn)
COT = [
    ("Mã CW", "", "Mã chứng quyền: C + mã cổ phiếu + năm phát hành + số thứ tự. Ví dụ CVPB2615 là CW của VPB phát hành năm 2026."),
    ("Mã CS", "", "Mã cổ phiếu cơ sở - cổ phiếu mà chứng quyền dựa vào."),
    ("TCPH", "", "Tổ chức phát hành (công ty chứng khoán). Đây cũng là bên đặt giá mua/bán CW trên sàn."),
    ("Còn (ngày)", "so", "Số ngày còn lại đến ngày đáo hạn. Càng ít ngày, CW mất giá theo thời gian càng nhanh."),
    ("Giá mua", "so", "Giá thấp nhất đang chào bán trong sổ lệnh lúc quét (đồng/CW) - giá bạn phải trả nếu mua ngay. "
     "Sổ lệnh trống thì dùng giá khớp gần nhất (ghi “khớp”) hoặc giá tham chiếu (ghi “TC”). Mọi chỉ số định giá đều tính theo giá này."),
    ("Giá hợp lý", "so", "Giá 1 CW tính bằng công thức Black-Scholes từ giá cổ phiếu, giá thực hiện, thời gian còn lại và mức dao động của cổ phiếu 1 năm qua."),
    ("So với giá hợp lý", "so", "Rẻ = giá mua thấp hơn giá hợp lý (có lợi cho người mua). Đắt = cao hơn giá hợp lý. "
     "Chỉ để tham khảo: tiêu chí chấm điểm dùng cột IV − HV."),
    ("IV", "so", "Biến động ngầm định (%/năm): mức dao động của cổ phiếu cơ sở mà giá mua CW đang “giả định”."),
    ("IV − HV", "so", "IV trừ biến động lịch sử 1 năm (HV), tính bằng điểm %. Âm = giá CW đang giả định cổ phiếu dao động ít hơn 1 năm qua (rẻ), "
     f"dương = nhiều hơn (đắt). Dùng để so sánh các CW với nhau, kể cả CW ở xa giá thực hiện. Tiêu chí: ≤ {cw_scanner.MAX_IV_TRU_HV * 100:+.0f} điểm. "
     "“—” = không giải được (rê chuột lên ô để xem lý do)."),
    ("CS cần tăng để hòa vốn", "so", "Cổ phiếu cơ sở phải tăng bấy nhiêu % tính đến ngày đáo hạn thì bạn mới hòa vốn (tính theo giá mua). Số càng nhỏ càng dễ có lãi."),
    ("Đòn bẩy", "so", "Cổ phiếu tăng (hoặc giảm) 1% thì CW tăng (hoặc giảm) khoảng bấy nhiêu %. Đòn bẩy cao: lãi nhanh nhưng lỗ cũng nhanh."),
    ("Delta", "so", "Từ 0 đến 1: cổ phiếu tăng 1 đ thì giá trị quyền trên 1 cổ phiếu tăng bấy nhiêu đ. Gần 1: CW bám sát cổ phiếu; gần 0: gần như không phản ứng."),
    ("KL khớp", "so", "Số CW đã khớp lệnh trong phiên. Càng nhiều càng dễ mua/bán đúng giá."),
    ("Đang chào bán", "so", "Tổng số CW đang được rao bán ở 3 mức giá thấp nhất trong sổ lệnh (lúc quét) - lượng bạn có thể mua ngay."),
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
.thanh-tren { display: flex; flex-wrap: wrap; gap: 8px 24px; margin-bottom: 16px; font-size: 14px; font-weight: 600; }
.thanh-tren a { text-decoration: none; }
.thanh-tren a[aria-current] { color: var(--chu); border-bottom: 2px solid var(--nut); }
.huong-dan p, .huong-dan li { max-width: 860px; }
.huong-dan h2 { margin-bottom: 8px; }
.huong-dan li { margin: 6px 0; }
.bang-chu td, .bang-chu th { white-space: normal; vertical-align: top; }
.muc-luc { columns: 2 240px; margin: 8px 0 0; }
footer { color: var(--chu-phu); font-size: 12px; margin-top: 32px; }
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
    hop.querySelector("b").textContent = gia.toLocaleString("vi-VN") + " đ";
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
    menu = "".join(f'<a href="{dd}"{" aria-current=page" if dd == duong_dan else ""}>{ten}</a>'
                   for dd, ten in (("/", "Danh sách chứng quyền"), ("/sap-ra-mat", "🆕 CW sắp ra mắt"), ("/huong-dan", "❓ Hướng dẫn sử dụng")))
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{ESC(tieu_de)}</title><link rel="icon" href="data:,"><style>{CSS}</style></head><body><main>'
            f'<nav class="thanh-tren" aria-label="Điều hướng">{menu}</nav>{than}'
            f'<footer>Công cụ sàng lọc theo mô hình Black-Scholes, không phải khuyến nghị đầu tư. Luôn kiểm tra điều khoản CW trên website '
            f'tổ chức phát hành / HOSE trước khi mua. Chưa tính phí giao dịch và thuế.</footer></main><script>{JS}</script></body></html>')


# ============ DỮ LIỆU ============
def doc_von(duong_dan):
    """?von=50 -> 50 (triệu đồng). Chỉ nhận số nguyên 1..10.000, sai thì về mặc định (chặn dữ liệu lạ từ URL)."""
    chuoi = (parse_qs(urlsplit(duong_dan).query).get("von") or [""])[0]
    return int(chuoi) if chuoi.isdigit() and 1 <= int(chuoi) <= 10_000 else VON_MAC_DINH


def doc_ket_qua():
    """(bảng kết quả mới nhất, ngày quét) hoặc (None, None) nếu chưa quét lần nào."""
    cac_file = sorted(cw_scanner.THU_MUC_KET_QUA.glob("cw_*.csv"))
    if not cac_file:
        return None, None
    # keep_default_na=False để ô chữ trống giữ là "", riêng 2 cột IV có ô trống (không giải được) thì đọc thành NaN
    df = pd.read_csv(cac_file[-1], encoding="utf-8-sig", keep_default_na=False, na_values={"IV %": [""], "IV − HV": [""], "IV cùng mã %": [""]})
    for cot in ("KL niêm yết", "KL chào bán", "KL chờ mua", "Delta", "IV %", "IV − HV", "IV cùng mã %"):  # file quét bằng bản cũ chưa có các cột này -> hiện "—"
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
        nguon = {"khớp": ' <small class="phu">khớp</small>', "tham chiếu": ' <small class="phu">TC</small>'}.get(h["Nguồn giá mua"], "")
        iv, iv_hv = h["IV %"], h["IV − HV"]
        o_iv = f'<td class="so" data-v="{v(iv)}">{so(iv, 0) + "%" if math.isfinite(iv) else "—"}</td>'
        o_iv_hv = (f'<td class="so {"duong" if iv_hv < 0 else "am" if iv_hv > 0 else ""}" data-v="{iv_hv}">{so(iv_hv, 1, True)}</td>'
                   if math.isfinite(iv_hv) else f'<td class="so" data-v="{v(iv_hv)}" title="{ESC(h["Ghi chú IV"])}">—</td>')
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
            f'<td class="ly-do">{ESC(h["Lý do"])}</td></tr>')
    dau = "".join(f'<th class="{lop}"><button type="button" title="{ESC(giai_thich)} (Bấm để sắp xếp.)">{ten}</button></th>' for ten, lop, giai_thich in COT)
    return f'<table{f" id={id_bang}" if id_bang else ""}><thead><tr>{dau}</tr></thead><tbody>{"".join(dong)}</tbody></table>'


# ============ TRANG CHÍNH ============
def trang_chinh():
    df, ngay = doc_ket_qua()
    co_key = bool(cw_scanner.doc_env().get("VNSTOCK_API_KEY"))
    phan = [
        '<div class="dau-trang"><div><h1>Quét chứng quyền</h1>'
        f'<p class="phu">{f"Dữ liệu ngày {ngay:%d/%m/%Y} · {len(df)} CW · định giá bằng Black-Scholes" if ngay else "Chưa có dữ liệu"}'
        f' · API key vnstock: {"đã nhập ✓" if co_key else "<b>chưa nhập</b> (mở file .env để điền)"}</p></div>'
        '<form method="post" action="/quet" onsubmit="this.nut.disabled = true; this.nut.textContent = \'Đang quét... (1-3 phút)\';">'
        '<button class="nut" name="nut">Quét ngay</button></form></div>'
    ]
    if LOI:
        phan.append(f'<p class="loi" role="alert">{ESC(LOI)}</p>')
    if NHAT_KY:  # tự mở nhật ký nếu có cảnh báo [!]
        phan.append(f'<details class="the"{" open" if "[!]" in NHAT_KY else ""}><summary>Nhật ký lần quét gần nhất</summary><pre>{ESC(NHAT_KY)}</pre></details>')
    if df is None:
        phan.append('<div class="the"><h2>Chưa có kết quả</h2><p>Lần đầu dùng? Làm theo 3 bước:</p><ol>'
                    '<li>Bấm nút <b>Quét ngay</b> ở góc trên bên phải và chờ 1-3 phút.</li>'
                    '<li>Xem bảng <b>Nên xem xét</b> hiện ra - đó là những chứng quyền đạt cả 4 tiêu chí.</li>'
                    '<li>Bấm vào một mã để xem phân tích chi tiết trước khi quyết định.</li></ol>'
                    '<p>Chưa biết chứng quyền là gì? Đọc <a href="/huong-dan">Hướng dẫn sử dụng</a> (khoảng 5 phút).</p></div>')
        return trang("Quét chứng quyền", "".join(phan), "/")

    dem = df["Đánh giá"].value_counts()
    moi, tot = df[df["Mới"] == "MỚI"], df[df["Đánh giá"] == "NÊN XEM XÉT"]
    phan.append('<div class="luoi-o">' + "".join(o_so(huy_hieu(k), so(dem.get(k, 0))) for k in KET_LUAN)
                + o_so("CW mới phát hành", so(len(moi)), 'so với lần quét trước · <a href="/sap-ra-mat">xem CW sắp ra mắt →</a>') + "</div>")
    phan.append(
        f'<p class="phu">Tiêu chí (tính theo giá mua = giá chào bán thấp nhất): còn ≥ {cw_scanner.MIN_NGAY_CON_LAI} ngày · IV − HV ≤ {so(cw_scanner.MAX_IV_TRU_HV * 100, 0, True)} điểm'
        f' · cổ phiếu cơ sở tăng ≤ {cw_scanner.MAX_TANG_DE_HOA_VON:.0%} là hòa vốn · khớp ≥ {so(cw_scanner.MIN_KHOI_LUONG)} CW/phiên.'
        ' Bấm vào một mã để xem phân tích chi tiết, rê chuột lên tiêu đề cột để xem giải thích.'
        ' Chưa rõ cách dùng? Đọc <a href="/huong-dan">Hướng dẫn sử dụng</a>.</p>')
    if len(moi):
        phan.append(f'<section class="the"><h2>CW mới phát hành ({len(moi)})</h2><div class="cuon">{bang(moi)}</div></section>')
    phan.append(f'<section class="the"><h2>Nên xem xét ({len(tot)})</h2><p class="phu">Đạt cả 4 tiêu chí, xếp theo IV − HV (thấp nhất trước = rẻ nhất so với mức dao động 1 năm qua).</p>'
                + (f'<div class="cuon">{bang(tot)}</div>' if len(tot) else '<p>Hôm nay không có CW nào đạt cả 4 tiêu chí.</p>') + "</section>")
    phan.append(f'<section class="the"><h2>Tất cả {len(df)} CW</h2>'
                '<input type="search" data-loc="#bang-tat-ca" placeholder="Tìm theo mã CW, mã cổ phiếu hoặc TCPH (vd: VPB, SSI)" aria-label="Tìm chứng quyền">'
                f'<div class="cuon cao">{bang(df, id_bang="bang-tat-ca")}</div></section>')
    return trang("Quét chứng quyền", "".join(phan), "/")


# ============ TRANG CHI TIẾT ============
def bieu_do(lich_su, duong_ke, ten_cs):
    """SVG giá đóng cửa 1 năm + đường tham chiếu [(nhãn, giá, lớp)], kèm bảng dữ liệu cho người không xem được hình."""
    R, C, TRAI, PHAI, TREN, DUOI = 900, 320, 60, 150, 16, 30
    gia = [g for _, g in lich_su]
    thap, cao = min(gia + [v for _, v, _ in duong_ke]), max(gia + [v for _, v, _ in duong_ke])
    le = (cao - thap) * 0.06 or 1
    thap, cao = thap - le, cao + le
    x = lambda i: TRAI + i * (R - TRAI - PHAI) / max(len(gia) - 1, 1)
    y = lambda v: TREN + (cao - v) * (C - TREN - DUOI) / (cao - thap)
    # vạch trục tung tròn số: bước 1/2/2,5/5 x 10^n
    buoc_tho = (cao - thap) / 4
    mu = 10 ** math.floor(math.log10(buoc_tho))
    buoc = next(b * mu for b in (1, 2, 2.5, 5, 10) if b * mu >= buoc_tho)
    vach = [math.ceil(thap / buoc) * buoc + k * buoc for k in range(int((cao - math.ceil(thap / buoc) * buoc) // buoc) + 1)]
    phan = [f'<line class="luoi-ngang" x1="{TRAI}" x2="{R - PHAI}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
            f'<text class="nhan-truc" x="{TRAI - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{so(v)}</text>' for v in vach]
    phan.append(f'<line class="truc" x1="{TRAI}" x2="{R - PHAI}" y1="{C - DUOI}" y2="{C - DUOI}"/>')
    for i in sorted({0, len(gia) // 4, len(gia) // 2, 3 * len(gia) // 4, len(gia) - 1}):
        neo = "start" if i == 0 else ("end" if i == len(gia) - 1 else "middle")
        phan.append(f'<text class="nhan-truc" x="{x(i):.1f}" y="{C - 8}" text-anchor="{neo}">{lich_su[i][0][5:7]}/{lich_su[i][0][:4]}</text>')
    # đường tham chiếu + nhãn bên phải; nhãn gần nhau thì đẩy ra và nối bằng đường dẫn (không chồng chữ)
    vi_tri = sorted([(y(v), nhan, v, lop) for nhan, v, lop in duong_ke])
    for k in range(1, len(vi_tri)):
        if vi_tri[k][0] - vi_tri[k - 1][0] < 34:
            vi_tri[k] = (vi_tri[k - 1][0] + 34,) + vi_tri[k][1:]
    for (yn, nhan, v, lop) in vi_tri:
        phan.append(f'<line class="{lop}" x1="{TRAI}" x2="{R - PHAI}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                    f'<line class="dan" x1="{R - PHAI}" x2="{R - PHAI + 10}" y1="{y(v):.1f}" y2="{yn:.1f}"/>'
                    f'<line class="{lop}" x1="{R - PHAI + 12}" x2="{R - PHAI + 24}" y1="{yn:.1f}" y2="{yn:.1f}"/>'
                    f'<text class="nhan-tc" x="{R - PHAI + 30}" y="{yn - 2:.1f}">{nhan}</text>'
                    f'<text class="gia-tc" x="{R - PHAI + 30}" y="{yn + 13:.1f}">{so(v)}</text>')
    phan.append(f'<polyline class="duong-gia" points="{" ".join(f"{x(i):.1f},{y(g):.1f}" for i, g in enumerate(gia))}"/>')
    phan.append(f'<circle class="diem" r="4" cx="{x(len(gia) - 1):.1f}" cy="{y(gia[-1]):.1f}"/>')
    phan.append(f'<line class="tro" y1="{TREN}" y2="{C - DUOI}"/><circle class="diem diem-tro" r="5"/>')
    diem = json.dumps([[round(x(i), 1), round(y(g), 1), d, g] for i, (d, g) in enumerate(lich_su)]).replace("</", "<\\/")
    mo_ta = f"Giá {ten_cs} từ {lich_su[0][0]} đến {lich_su[-1][0]}, thấp nhất {so(min(gia))}, cao nhất {so(max(gia))}, hiện tại {so(gia[-1])} đồng"
    dong_bang = "".join(f'<tr><td>{d[8:]}/{d[5:7]}/{d[:4]}</td><td class="so">{so(g)}</td></tr>' for d, g in reversed(lich_su))
    return (f'<div class="cuon-bieu-do"><div class="bieu-do"><svg viewBox="0 0 {R} {C}" tabindex="0" role="img" aria-label="{ESC(mo_ta)}. Dùng phím mũi tên để xem từng ngày.">'
            f'{"".join(phan)}</svg><div class="o-tro" hidden><b></b><span></span></div>'
            f'<script type="application/json">{diem}</script></div></div>'
            f'<details style="margin-top:8px"><summary>Xem dữ liệu dạng bảng</summary><div class="cuon cao" style="max-width:360px">'
            f'<table><thead><tr><th>Ngày</th><th class="so">Giá đóng cửa (đ)</th></tr></thead><tbody>{dong_bang}</tbody></table></div></details>')


def trang_chi_tiet(ma, von=VON_MAC_DINH):
    df, ngay = doc_ket_qua()
    if df is None or ma not in set(df["Mã CW"]):
        return None
    h, C = df[df["Mã CW"] == ma].iloc[0].to_dict(), cw_scanner
    cs, sigma_ls, ket_luan_quet = h["Mã CS"], float(h["Biến động %/năm"]) / 100, h["Đánh giá"]
    r = float(h["r %"]) / 100 if "r %" in h else C.LAI_SUAT_PHI_RUI_RO  # đúng lãi suất của lần quét (file cũ: cấu hình hiện tại)
    # Định giá lại theo giá trực tiếp: CW + cổ phiếu cơ sở trong 1 lần gọi (chờ tối đa 5 giây); σ và r giữ như lúc quét
    try:
        bang_gia = C.lay_bang_gia([ma, cs], cho=5)
        niem_yet, khop, so_lenh = bang_gia[ma]
        S_truc_tiep = C.gia_hien_tai(*bang_gia[cs])
    except Exception as e:  # mất mạng / máy chủ lỗi / thiếu mã: dùng đúng số lúc quét và báo rõ trên trang
        so_lenh, ngay_tinh, truc_tiep = {}, ngay, False
        nguon = f"KHÔNG tải được giá trực tiếp ({ESC(str(e)[:120])}), đang dùng số liệu lúc quét ngày {ngay:%d/%m/%Y}"
    else:
        h.update(C.dinh_gia(niem_yet, khop, so_lenh, S_truc_tiep, sigma_ls, date.today(), r))
        ngay_tinh, truc_tiep = date.today(), True
        nguon = (f"bảng giá Vietcap lúc {datetime.now():%H:%M %d/%m/%Y} "
                 f"({'trạng thái cuối phiên gần nhất' if khop.get('session') == 'ENDED' else 'trong phiên'})")
    # P = giá mua (chào bán thấp nhất): giá người mua phải trả, dùng cho mọi chỉ số bên dưới
    S, K, ty_le, P = float(h["Giá CS"]), float(h["Giá thực hiện"]), float(h["Tỷ lệ CĐ"]), float(h["Giá mua"])
    P_khop, nguon_gia, ngay_con_lai = float(h["Giá CW"]), h["Nguồn giá mua"], int(h["Ngày còn lại"])
    T, hoa_von, tang = ngay_con_lai / 365, K + P * ty_le, float(h["CS tăng % để hòa vốn"])
    ngay_dao_han = ngay_tinh + timedelta(days=ngay_con_lai)
    iv = cw_scanner.bien_dong_ngam_dinh(P, S, K, T, r, ty_le)
    toi_thieu = cw_scanner.can_duoi(S, K, T, r)  # giá tối thiểu của quyền trên 1 cổ phiếu theo mô hình
    tv_cung_ma, canh_bao_iv = cw_scanner.so_iv_cung_ma(df, ma, cs, iv * 100 if iv else math.nan)  # IV so với CW khác cùng mã CS
    # IV − HV (điểm %): ưu tiên số trong CSV để khớp với kết luận lúc quét; file cũ chưa có cột này thì tính lại
    iv_hv = float(h["IV − HV"]) if math.isfinite(h["IV − HV"]) else ((iv - sigma_ls) * 100 if iv else math.nan)
    mo_ta_gia = (f"giá chào bán thấp nhất; giá khớp gần nhất {so(P_khop)} đ" if nguon_gia == "ask"
                 else f"sổ lệnh trống nên dùng giá {nguon_gia}")
    noi_tai = max(S - K, 0) / ty_le  # phần lãi nếu đáo hạn ngay hôm nay
    gia_tri_tg = P - noi_tai  # phần sẽ mất dần về 0 đến ngày đáo hạn
    if iv:  # mất giá theo thời gian tính theo mức biến động thị trường đang dùng
        mat_gia = (cw_scanner.black_scholes_call(S, K, T, r, iv)[0] - cw_scanner.black_scholes_call(S, K, T - 1 / 365, r, iv)[0]) / ty_le
    else:  # không giải được: chia đều phần giá trị thời gian còn lại cho số ngày
        mat_gia = max(gia_tri_tg, 0) / max(ngay_con_lai, 1)
    chu_dat_re, lop_dat_re = dat_re(h["Đắt/rẻ %"])

    phan = [f'<div class="dau-trang"><div><h1>{ESC(ma)}</h1><p class="phu">Chứng quyền mua <b>{ESC(cs)}</b> · TCPH {ESC(h["TCPH"])}'
            f' · đáo hạn {ngay_dao_han:%d/%m/%Y} (còn {ngay_con_lai} ngày)</p>'
            f'<p class="{"phu" if truc_tiep else "loi"}"{"" if truc_tiep else " role=alert"}>Định giá theo {nguon}. '
            f'σ lịch sử và lãi suất lấy từ lần quét ngày {ngay:%d/%m/%Y}.</p></div>'
            f'<div>{huy_hieu(h["Đánh giá"], True)}'
            + (f'<p class="phu">Lúc quét {ngay:%d/%m}: {ESC(KET_LUAN.get(ket_luan_quet, ("", "", ket_luan_quet))[2])}</p>'
               if h["Đánh giá"] != ket_luan_quet else "") + '</div></div>']

    # Tóm tắt + 4 tiêu chí
    if math.isfinite(iv_hv):
        dat_iv, noi_dung_iv = iv_hv <= C.MAX_IV_TRU_HV * 100, f"IV − HV = {so(iv_hv, 1, True)} điểm ({chu_dat_re} so với giá hợp lý)"
    elif P * ty_le < toi_thieu:  # không giải được IV vì giá quá thấp: rẻ hơn mọi mức dao động -> đạt (kèm cảnh báo ở trên)
        dat_iv, noi_dung_iv = True, "Giá mua dưới mức tối thiểu của mô hình, rẻ hơn mọi mức dao động (xem lưu ý ở trên)"
    else:
        dat_iv, noi_dung_iv = False, "Giá mua cao bất thường, không giải được IV"
    tieu_chi = [
        (ngay_con_lai >= C.MIN_NGAY_CON_LAI, f"Còn {ngay_con_lai} ngày đến đáo hạn", f"cần ≥ {C.MIN_NGAY_CON_LAI} ngày"),
        (dat_iv, noi_dung_iv, f"cần IV − HV ≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm"),
        (tang <= C.MAX_TANG_DE_HOA_VON * 100, f"{ESC(cs)} cần tăng {so(tang, 1, True)}% để hòa vốn", f"cần ≤ {C.MAX_TANG_DE_HOA_VON:.0%}"),
        (int(h["KL khớp"]) >= C.MIN_KHOI_LUONG, f"Khớp {so(h['KL khớp'])} CW trong phiên", f"cần ≥ {so(C.MIN_KHOI_LUONG)}"),
    ]
    dong_tc = "".join(f'<li><b class="{"duong" if dat else "am"}" aria-label="{"Đạt" if dat else "Không đạt"}">{"✓" if dat else "✕"}</b>'
                      f'<span>{noi_dung} <small>({yeu_cau})</small></span></li>' for dat, noi_dung, yeu_cau in tieu_chi)
    phan.append(
        f'<section class="the"><h2>Tóm tắt</h2><p class="tom-tat">Bạn trả <b>{so(P)} đ</b> cho 1 CW ({mo_ta_gia}; mô hình tính giá hợp lý là {so(h["Giá hợp lý"])} đ). '
        f'Nếu giữ đến ngày {ngay_dao_han:%d/%m/%Y}, giá {ESC(cs)} cần cao hơn <b>{so(hoa_von)} đ</b> ({so(tang, 1, True)}% so với hiện tại {so(S)} đ) thì mới có lãi. '
        f'Trong {so(P)} đ có {so(noi_tai)} đ <b>giá trị nội tại</b> (phần lãi nếu đáo hạn ngay hôm nay) và {so(gia_tri_tg)} đ <b>giá trị thời gian</b> '
        f'(mất dần về 0 đến ngày đáo hạn, khoảng {so(mat_gia, 1 if mat_gia < 10 else 0)} đ/ngày nếu giá {ESC(cs)} đứng yên).</p>'
        + (f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ Bất thường:</b> giá CW đang thấp hơn cả giá trị nội tại. Có thể do sắp điều chỉnh '
           f'điều khoản (cổ tức, chia tách…) hoặc thanh khoản kém. Hãy đọc thông báo mới nhất của {ESC(h["TCPH"])} về mã này trước khi mua.</p>' if gia_tri_tg < 0
           else f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ Lưu ý:</b> giá mua × tỷ lệ = {so(P * ty_le)} đ, thấp hơn mức tối thiểu theo mô hình '
           f'S − K × e<sup>−rT</sup> = {so(toi_thieu)} đ (lãi suất giả định {so(r * 100, 1)}%). Không có mức dao động nào cho ra giá này, nên chữ '
           f'“{chu_dat_re}” chủ yếu đến từ giả định (lãi suất, mức dao động 1 năm qua), không chắc là món hời. '
           f'Hãy so với các CW khác của {ESC(cs)} và đọc thông báo của {ESC(h["TCPH"])} trước khi mua.</p>' if P * ty_le < toi_thieu else "")
        + (f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ IV bất thường:</b> {ESC(canh_bao_iv)}.</p>' if canh_bao_iv else "")
        + f'<ul class="tieu-chi">{dong_tc}</ul>'
        '<p class="phu">Chưa hiểu các con số? Xem <a href="/huong-dan#trang-phan-tich">cách đọc trang phân tích</a> và '
        '<a href="/huong-dan#truoc-khi-mua">5 câu tự hỏi trước khi mua</a>.</p></section>')

    # Rủi ro với số tiền của bạn (đã tính phí mua, thuế khi nhận tiền; con số "xác suất" là của mô hình, không phải dự báo)
    rr = C.rui_ro_theo_tien(von * 1_000_000, P, S, K, ty_le, T, r, sigma_ls, float(h["Đòn bẩy"]))
    gd_cuoi = date.fromisoformat(h["Ngày GD cuối"]) if h.get("Ngày GD cuối") else None
    phi_chu, thue_chu = so(C.PHI_GIAO_DICH * 100, 2), so(C.THUE_BAN * 100, 1)
    phan.append(
        f'<section class="the" id="rui-ro"><h2>Rủi ro với số tiền của bạn</h2>'
        f'<form method="get" action="/cw/{ESC(ma)}#rui-ro" style="margin-top:8px"><label>Số tiền định đầu tư '
        f'<input type="number" name="von" min="1" max="10000" step="1" value="{von}" style="width:7em"> triệu đồng</label> '
        '<button class="nut" style="padding:6px 14px">Tính lại</button></form><div class="luoi-o">'
        + o_so("Mua được", f"{so(rr['so_cw'])} CW" if rr["so_cw"] else "Chưa đủ 1 lô",
               f"≈ {so(rr['tien_chi'])} đ, đã gồm phí mua {phi_chu}% (lô 100 CW)")
        + o_so("Tương đương nắm", f"{so(rr['tiep_xuc'] / 1e6, 1)} triệu đ {ESC(cs)}",
               f"≈ {so(rr['so_cp'])} cổ phiếu · gấp {so(rr['tiep_xuc'] / (von * 1e6), 1)} lần số tiền bỏ ra")
        + o_so("Mất toàn bộ tiền nếu", f"{ESC(cs)} ≤ {so(K)} đ",
               f"tức giảm {so(-rr['giam_ve_0'] * 100, 1)}% vào lúc đáo hạn · xác suất theo mô hình ≈ {so(rr['xs_ve_0'] * 100, 0)}% "
               "(σ lịch sử, không phải dự báo)" if rr["giam_ve_0"] < 0 else f"{ESC(cs)} đang thấp hơn giá thực hiện")
        + o_so(f"{ESC(cs)} giảm 1%", f"≈ −{so(rr['mat_khi_giam_1pct'])} đ",
               f"trước ngày đáo hạn, theo đòn bẩy {so(h['Đòn bẩy'], 1)}x; giảm sâu thì mất nhanh hơn")
        + o_so("Ngày giao dịch cuối", f"{gd_cuoi:%d/%m/%Y}" if gd_cuoi else "Không rõ",
               f"còn {(gd_cuoi - ngay_tinh).days} ngày để bán; sau đó chỉ chờ nhận tiền theo giá trung bình 5 phiên trước "
               f"ngày đáo hạn {ngay_dao_han:%d/%m/%Y}" if gd_cuoi else "bấm Quét ngay để lấy ngày này")
        + o_so("Hòa vốn có phí, thuế", f"{so(rr['hoa_von_phi'])} đ",
               f"{ESC(cs)} cần {so((rr['hoa_von_phi'] / S - 1) * 100, 1, True)}% (chưa tính phí: {so(hoa_von)} đ). "
               f"Phí {phi_chu}% + thuế {thue_chu}% khi nhận tiền là giả định - kiểm tra với công ty chứng khoán của bạn")
        + '</div></section>')

    # Các chỉ số chính
    delta = C.black_scholes_call(S, K, T, r, sigma_ls)[1]  # N(d1): giá trị quyền trên 1 cổ phiếu tăng bao nhiêu khi cổ phiếu tăng 1 đ
    so_sanh_bd = ((f"IV − HV = {so(iv_hv, 1, True)} điểm → thị trường đang định giá CW "
                   + ("rẻ hơn" if iv_hv < 0 else "đắt hơn") + " mức dao động 1 năm qua.") if math.isfinite(iv_hv)
                  else f"Không giải được: giá mua dưới mức tối thiểu S − K × e^(−rT) (lãi suất giả định {so(r * 100, 1)}%)." if P * ty_le < toi_thieu
                  else "Không giải được: giá mua cao bất thường so với mô hình.")
    phan.append('<div class="luoi-o">'
                + o_so("Giá mua / giá hợp lý", f"{so(P)} / {so(h['Giá hợp lý'])}",
                       '<a href="#cach-tinh" onclick="document.getElementById(\'cach-tinh\').open = true">Xem cách tính giá hợp lý ↓</a>')
                + o_so("So với giá hợp lý", f'<span class="{lop_dat_re}">{chu_dat_re}</span>', "Rẻ = giá mua thấp hơn mô hình")
                + o_so("Điểm hòa vốn", f"{so(hoa_von)} đ", f"{ESC(cs)} cần {so(tang, 1, True)}% đến ngày đáo hạn")
                + o_so("Đòn bẩy", f"{so(h['Đòn bẩy'], 1)}x", f"{ESC(cs)} tăng/giảm 1% → CW tăng/giảm khoảng {so(h['Đòn bẩy'], 1)}%")
                + o_so("Delta", so(delta, 2), f"{ESC(cs)} tăng/giảm 1.000 đ → 1 CW tăng/giảm khoảng {so(delta / ty_le * 1000)} đ")
                + o_so("Mất giá theo thời gian", f"{so(mat_gia, 1 if mat_gia < 10 else 0)} đ/ngày", f"≈ {so(mat_gia / P * 100, 2 if mat_gia / P < 0.001 else 1)}% giá CW mỗi ngày nếu {ESC(cs)} đứng yên")
                + o_so("Biến động ngầm định (IV)", f"{so(iv * 100, 0)}%" if iv else "—", f"Lịch sử 1 năm (HV): {so(sigma_ls * 100, 0)}%. {so_sanh_bd}"
                       + (f" Trung vị IV các CW {ESC(cs)} khác: {so(tv_cung_ma, 0)}%." if math.isfinite(tv_cung_ma) else ""))
                + "</div>")

    # Giá hợp lý được tính thế nào: từng bước bằng số thật của mã này, nói bằng lời thường
    if ngay_con_lai > 0:
        N, bdd, kc = C.phan_phoi_chuan, sigma_ls * math.sqrt(T), math.log(S / K)  # bdd: biên độ dao động đến ngày đáo hạn
        d1 = (kc + (r + sigma_ls**2 / 2) * T) / bdd
        d2, ck = d1 - bdd, math.exp(-r * T)
        nhan, tra = S * N(d1), K * ck * N(d2)
        gia_cw_tinh, mo_phong = (nhan - tra) / ty_le, C.mo_phong_gia(S, K, T, r, sigma_ls) / ty_le
        c = ESC(cs)
        buoc = [
            ("Thu thập 5 con số", f"Giá {c} hôm nay <b>S = {so(S)} đ</b> · giá thực hiện <b>K = {so(K)} đ</b> · còn <b>{ngay_con_lai} ngày = {so(T, 3)} năm</b>"
             f" · {c} dao động khoảng <b>σ = {so(sigma_ls * 100, 1)}%/năm</b> (đo từ giá 1 năm qua) · lãi suất <b>r = {so(r * 100, 1)}%/năm</b>."),
            ("Giá đang cách giá thực hiện bao xa?", f"ln(S ÷ K) = ln({so(S)} ÷ {so(K)}) = <b>{so(kc, 3)}</b> → giá {c} đang "
             f"{'cao' if kc >= 0 else 'thấp'} hơn giá thực hiện khoảng <b>{so(abs(kc) * 100, 1)}%</b>."),
            ("Từ nay đến ngày đáo hạn, giá thường dao động bao nhiêu?", f"σ × √T = {so(sigma_ls * 100, 1)}% × √{so(T, 3)} = <b>{so(bdd * 100, 1)}%</b>"
             f" → trong {ngay_con_lai} ngày tới, giá {c} thường lên/xuống trong khoảng <b>±{so(bdd * 100, 0)}%</b>."),
            ("Đổi khoảng cách thành “số bước dao động”", f"d1 = (khoảng cách + một chút cho lãi suất và dao động) ÷ biên độ = ({so(kc, 3)} + "
             f"{so((r + sigma_ls**2 / 2) * T, 3)}) ÷ {so(bdd, 3)} = <b>{so(d1, 2)}</b> · d2 = d1 − biên độ = <b>{so(d2, 2)}</b>."
             f" Hiểu đơn giản: giá đang {'trên' if d2 >= 0 else 'dưới'} giá thực hiện khoảng {so(abs(d2), 1)} bước dao động."),
            ("Đổi “số bước” thành xác suất", f"Tra bảng phân phối chuẩn (Excel: hàm NORM.S.DIST): <b>N(d2) = {so(N(d2) * 100, 0)}%</b> = khả năng tới ngày đáo hạn "
             f"giá {c} vẫn trên {so(K)} đ (theo mô hình) · <b>N(d1) = {so(N(d1) * 100, 0)}%</b> – đây chính là <b>delta = {so(N(d1), 2)}</b>."),
            ("Ráp vào công thức", f"Giá 1 quyền chọn = <b>phần nhận được − phần phải trả</b> = S × N(d1) − K × e<sup>−rT</sup> × N(d2) = "
             f"{so(S)} × {so(N(d1), 3)} − {so(K)} × {so(ck, 3)} × {so(N(d2), 3)} = {so(nhan)} − {so(tra)} = <b>{so(nhan - tra)} đ</b> (cho 1 cổ phiếu)."),
            ("Chia cho tỷ lệ chuyển đổi", f"{so(nhan - tra)} ÷ {so(ty_le, 4)} = <b>{so(gia_cw_tinh)} đ / 1 CW</b>. Giá mua là {so(P)} đ → <b>{chu_dat_re}</b> so với giá hợp lý."
             + (f" <small class='phu'>(Bảng ghi {so(h['Giá hợp lý'])} đ: chênh vài đồng do mức dao động hiển thị đã làm tròn.)</small>"
                if round(gia_cw_tinh) != int(h["Giá hợp lý"]) else "")),
        ]
        phan.append(
            f'<details class="the" id="cach-tinh"><summary><h2 style="display:inline">📐 Giá hợp lý {so(h["Giá hợp lý"])} đ được tính thế nào?</h2>'
            ' <span class="phu">(bấm để xem từng bước)</span></summary>'
            f'<p class="tom-tat"><b>Ý tưởng:</b> tưởng tượng hàng nghìn kịch bản giá {c} có thể xảy ra đến ngày đáo hạn, với mức dao động như 1 năm qua. '
            f'Mỗi kịch bản, CW trả một số tiền hoặc về 0. <b>Giá hợp lý = trung bình số tiền đó, quy về tiền hôm nay.</b> '
            'Công thức Black-Scholes tính ra con số trung bình này chỉ bằng 7 bước:</p><ol class="cac-buoc">'
            + "".join(f"<li><b>Bước {k} – {t}{'' if t.endswith('?') else '.'}</b><br>{nd}</li>" for k, (t, nd) in enumerate(buoc, 1))
            + f'</ol><p class="ghi-chu-canh-bao" style="border-left-color: var(--xanh); background: color-mix(in srgb, var(--xanh) 8%, transparent)">'
            f'<b>Kiểm chứng:</b> chương trình vừa thử <b>20.000 kịch bản</b> ngẫu nhiên cho giá {c} đến ngày đáo hạn. Trung bình CW trả '
            f'<b>≈ {so(mo_phong)} đ</b> (quy về hôm nay), gần bằng kết quả công thức {so(gia_cw_tinh)} đ.</p>'
            '<p class="phu">Nhớ: con số này dựa trên giả định cổ phiếu sẽ dao động như 1 năm qua. Nó là thước đo để so sánh, không phải dự báo giá.</p></details>')

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

    def goi_y_ben(ds, ten_gia, viec):  # vd: "ở giá thấp nhất 920 đ chỉ có 5.100 CW (≈ 4,7 triệu đ). Mua hết cả 3 mức ..."
        kl3, tien3 = sum(m.get("volume") or 0 for m in ds), sum(tien(m) for m in ds)
        return (f"Ở giá {ten_gia} {so(gia(ds[0]))} đ chỉ có <b>{so(ds[0].get('volume') or 0)} CW</b> (≈ {so(tien(ds[0]) / 1e6, 1)} triệu đ). "
                f"{viec} hết cả {len(ds)} mức ({so(gia(ds[0]))}–{so(gia(ds[-1]))} đ): ≈ {so(tien3 / 1e6, 1)} triệu đ, "
                f"giá trung bình ≈ {so(tien3 / kl3 if kl3 else math.nan)} đ")

    dong_sl = ("".join(f"<tr>{o_sl(mua, i)}{o_sl(ban, i)}</tr>" for i in range(3)) if (ban or mua)
               else '<tr><td colspan="6">Sổ lệnh đang trống (ngoài giờ giao dịch hoặc chưa có lệnh).</td></tr>')
    phan.append(
        '<section class="the" id="khoi-luong"><h2>Khối lượng CW</h2><div class="luoi-o">'
        + o_so("Khối lượng phát hành", f"{so(kl_ny)} CW", "tổng số CW được niêm yết (được phép bán ra)")
        + o_so("Đang chào bán (3 mức giá)", f"{so(kl_ban)} CW", goi_y_ben(ban, "thấp nhất", "Mua") if ban else "ở 3 mức giá bán thấp nhất")
        + o_so("Đang chờ mua (3 mức giá)", f"{so(kl_mua)} CW", goi_y_ben(mua, "cao nhất", "Bán") if mua else "ở 3 mức giá mua cao nhất")
        + o_so("Đã khớp trong phiên", f"{so(kl_khop)} CW",
               f"≈ {so(kl_khop / kl_ny * 100, 1)}% khối lượng phát hành" if kl_ny > 0 else "")
        + '</div><div class="cuon"><table style="max-width:820px"><thead><tr><th class="so">Giá chờ mua (đ)</th><th class="so">KL chờ mua</th>'
        '<th class="so">Thành tiền (triệu đ)</th><th class="so">Giá chào bán (đ)</th><th class="so">KL chào bán</th><th class="so">Thành tiền (triệu đ)</th>'
        f'</tr></thead><tbody>{dong_sl}</tbody></table></div>'
        '<p class="phu">Sổ lệnh 3 mức giá tốt nhất. Mua nhiều hơn khối lượng ở giá thấp nhất thì phần còn lại phải mua ở các mức giá cao hơn '
        f'(bán thì ngược lại). Nguồn: {nguon}.</p>'
        '<details><summary>Vì sao không có "số CW đã bán ra" và "số CW còn lại"?</summary>'
        '<p>Các nguồn dữ liệu miễn phí (bảng giá Vietcap, KBS, vnstock gói miễn phí) chỉ công bố <b>tổng khối lượng phát hành</b>, '
        'không công bố nhà đầu tư đang nắm bao nhiêu CW. Phần CW chưa bán thường nằm trong tay <b>tổ chức phát hành</b>: họ là bên tạo lập '
        'thị trường, đặt lệnh bán dần ra và đặt lệnh mua lại. Vì vậy con số <b>"có thể mua ngay"</b> trên thực tế là khối lượng '
        '<b>đang chào bán</b> trong sổ lệnh. Tổ chức phát hành có thể đặt thêm lệnh bán sau đó, nhưng không vượt quá khối lượng phát hành. '
        'Nếu cần con số chính xác, hãy xem thông báo của tổ chức phát hành hoặc ứng dụng của công ty chứng khoán bạn dùng (nếu có hiển thị).</p></details></section>')

    # Biểu đồ giá cổ phiếu cơ sở
    file_ls = C.THU_MUC_KET_QUA / f"lich_su_{ngay}.json"
    lich_su = json.loads(file_ls.read_text()).get(cs) if file_ls.exists() else None
    phan.append(f'<section class="the"><h2>Giá {ESC(cs)} 1 năm qua</h2>'
                f'<p class="phu">Muốn có lãi khi giữ đến đáo hạn, giá {ESC(cs)} phải nằm trên đường <b>hòa vốn</b>. Rê chuột lên biểu đồ để xem giá từng ngày.</p>'
                + (bieu_do(lich_su, [("Giá thực hiện", K, "tc-thuc-hien"), ("Hòa vốn", hoa_von, "tc-hoa-von")], cs) if lich_su
                   else '<p>Chưa có dữ liệu biểu đồ. Bấm <b>Quét ngay</b> ở trang chính để tải.</p>') + "</section>")

    # Kịch bản lãi/lỗ khi đáo hạn
    so_cw, gia_von = rr["so_cw"], P * (1 + C.PHI_GIAO_DICH)  # giá vốn 1 CW đã gồm phí mua
    dong = []
    for thay_doi in (-20, -10, -5, 0, 5, 10, 15, 20, 30):
        gia_cs = S * (1 + thay_doi / 100)
        nhan_ve = max(gia_cs - K, 0) / ty_le
        lai = nhan_ve * (1 - C.THUE_BAN) - gia_von  # đã trừ thuế khi nhận tiền
        lop = "duong" if lai > 0 else ("am" if lai < 0 else "")
        dong.append(f'<tr{" class=hang-goc" if thay_doi == 0 else ""}><td>{"Giữ nguyên" if thay_doi == 0 else f"{thay_doi:+d}%"}</td>'
                    f'<td class="so">{so(gia_cs)}</td><td class="so">{so(nhan_ve)}</td><td class="so {lop}">{so(lai, 0, True)}</td>'
                    f'<td class="so {lop}">{so(lai / gia_von * 100, 0, True)}%</td><td class="so {lop}">{so(lai * so_cw, 0, True)}</td></tr>')
    phan.append(f'<section class="the"><h2>Nếu giữ đến ngày đáo hạn ({ngay_dao_han:%d/%m/%Y})</h2>'
                f'<p class="phu">Lãi/lỗ theo giá {ESC(cs)} lúc đáo hạn (giá thanh toán thực tế là trung bình 5 phiên trước đáo hạn). '
                f'Đã trừ phí mua {phi_chu}% và thuế {thue_chu}% khi nhận tiền. Lỗ tối đa là toàn bộ tiền mua CW.</p><div class="cuon"><table><thead><tr><th>{ESC(cs)} thay đổi</th><th class="so">Giá {ESC(cs)} (đ)</th>'
                f'<th class="so">Nhận về / CW (đ)</th><th class="so">Lãi/lỗ / CW (đ)</th><th class="so">Lãi/lỗ</th>'
                f'<th class="so">Với {so(so_cw)} CW ≈ {von} triệu (đ)</th></tr></thead><tbody>{"".join(dong)}</tbody></table></div></section>')

    # So sánh các CW cùng mã cơ sở
    cung_cs = df[df["Mã CS"] == cs].sort_values("IV − HV", na_position="last")
    phan.append(f'<section class="the"><h2>Các CW khác của {ESC(cs)} ({len(cung_cs)})</h2>'
                f'<p class="phu">Cùng một cổ phiếu cơ sở nhưng khác TCPH, giá thực hiện và thời hạn. Xếp theo IV − HV (thấp nhất = rẻ nhất trước); dòng tô nền là CW đang xem.</p>'
                f'<div class="cuon">{bang(cung_cs, ma)}</div></section>')

    # Điều khoản
    dk = [("Mã cổ phiếu cơ sở", ESC(cs)), ("Tổ chức phát hành", ESC(h["TCPH"])), ("Giá thực hiện", f"{so(K)} đ"),
          ("Tỷ lệ chuyển đổi", f"{so(ty_le, 4)} CW : 1 cổ phiếu"), ("Ngày đáo hạn", f"{ngay_dao_han:%d/%m/%Y}"),
          ("Giá cổ phiếu cơ sở", f"{so(S)} đ"), ("Giá mua lúc quét", f"{so(P)} đ (giá {nguon_gia})"), ("Giá khớp gần nhất", f"{so(P_khop)} đ"),
          ("Khối lượng khớp", f"{so(h['KL khớp'])} CW"),
          ("Biến động lịch sử 1 năm", f"{so(sigma_ls * 100, 1)}%"), ("Lãi suất phi rủi ro (giả định)", f"{so(r * 100, 1)}%")]
    phan.append('<section class="the"><h2>Điều khoản &amp; số liệu</h2><dl class="dieu-khoan">'
                + "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in dk) + "</dl></section>")
    return trang(f"{ma} – phân tích chứng quyền", "".join(phan))


# ============ TRANG CW SẮP RA MẮT ============
def trang_sap_ra_mat(tai_moi=False):
    """CW đã được HOSE chấp thuận niêm yết nhưng chưa giao dịch, kèm giá hợp lý dự kiến để so sánh khi lên sàn."""
    C = cw_scanner
    df, ngay = doc_ket_qua()
    phan = ['<div class="dau-trang"><div><h1>Chứng quyền sắp ra mắt</h1><p class="phu">Các CW đã được HOSE chấp thuận niêm yết '
            'nhưng <b>chưa giao dịch</b>. Mã CW (ví dụ CVPB26xx) sẽ có khi lên sàn.</p></div></div>']
    luu = sorted(C.THU_MUC_KET_QUA.glob("sap_ra_mat_*.json"))
    tai_lai = ' · <a href="/sap-ra-mat?tai_moi=1">tải lại trực tiếp từ HOSE</a> (có thể mất 10-40 giây)'
    try:
        # đã quét hôm nay thì dùng ngay danh sách vừa lưu (máy chủ HOSE thường chậm); muốn mới nhất thì bấm "tải lại"
        if luu and luu[-1].stem[11:] == str(date.today()) and not tai_moi:
            ds, nguon = C.doc_cw_sap_ra_mat(json.loads(luu[-1].read_text())), "hsx.vn, danh sách lưu lúc quét hôm nay" + tai_lai
        else:
            ds, nguon = C.doc_cw_sap_ra_mat(C.tai_du_lieu_hose_cw(cho=12)), "hsx.vn (Niêm yết mới → DS CW được chấp thuận chính thức), tải trực tiếp lúc mở trang"
    except Exception as e:
        if not luu:
            phan.append(f'<p class="loi" role="alert">Không tải được danh sách từ HOSE ({ESC(str(e))}). Máy chủ HOSE có thể đang chậm, '
                        'hãy tải lại trang sau ít phút hoặc bấm Quét ngay ở trang chính.</p>')
            return trang("CW sắp ra mắt", "".join(phan), "/sap-ra-mat")
        ds = C.doc_cw_sap_ra_mat(json.loads(luu[-1].read_text()))
        nguon = f"không tải được trực tiếp từ HOSE ({ESC(str(e))}), dùng danh sách lưu lúc quét ngày {date.fromisoformat(luu[-1].stem[11:]):%d/%m/%Y}" + tai_lai

    # Bỏ mã đã hết hạn và mã đã lên sàn (cùng mã CS + giá thực hiện + ngày đáo hạn với một CW trong lần quét gần nhất)
    hom_nay, co_so, dang_gd = date.today(), {}, set()
    if df is not None:
        dang_gd = {(h["Mã CS"], round(h["Giá thực hiện"]), ngay + timedelta(days=int(h["Ngày còn lại"]))) for _, h in df.iterrows()}
        co_so = df.groupby("Mã CS")[["Giá CS", "Biến động %/năm"]].first().to_dict("index")
    sap = sorted((x for x in ds if x["ngay_dao_han"] and x["ngay_dao_han"] > hom_nay
                  and (x["ma_cs"], round(x["gia_thuc_hien"] or 0), x["ngay_dao_han"]) not in dang_gd),
                 key=lambda x: (x["ngay_chap_thuan"] or date.min, x["ten"]), reverse=True)

    dv = lambda v: v if isinstance(v, (int, float)) and math.isfinite(v) else -1  # giá trị để sắp xếp; thiếu số liệu xếp cuối
    dong = []
    for x in sap:
        K, cs, con = x["gia_thuc_hien"], co_so.get(x["ma_cs"]), (x["ngay_dao_han"] - hom_nay).days
        ngay_ct = f'{x["ngay_chap_thuan"]:%d/%m/%Y}' if x["ngay_chap_thuan"] else "—"
        S = cs["Giá CS"] if cs else math.nan
        try:  # giá hợp lý dự kiến nếu CW lên sàn hôm nay, dùng giá & mức dao động của cổ phiếu cơ sở ở lần quét gần nhất
            gia_hl = C.black_scholes_call(S, K, con / 365, C.LAI_SUAT_PHI_RUI_RO, cs["Biến động %/năm"] / 100)[0] / C.doc_ty_le(x["ty_le"])
        except Exception:
            gia_hl = math.nan
        lech = (K / S - 1) * 100 if K and S == S else math.nan
        dong.append(
            f'<tr><td data-v="{x["ngay_chap_thuan"] or ""}">{ngay_ct}</td><td>{ESC(x["ten"].replace("Chứng quyền ", ""))}</td>'
            f'<td class="so" data-v="{dv(gia_hl)}"><b>{so(gia_hl)}</b></td>'
            f'<td class="so" data-v="{dv(S)}">{so(S)}</td><td class="so" data-v="{dv(K)}">{so(K or math.nan)}</td>'
            f'<td class="so" data-v="{dv(lech)}">{so(lech, 1, True)}%</td><td class="so">{ESC(x["ty_le"])}</td>'
            f'<td data-v="{x["ngay_dao_han"]}">{x["ngay_dao_han"]:%d/%m/%Y}</td><td class="so" data-v="{con}">{so(con)}</td>'
            f'<td class="so" data-v="{dv(x["kl_niem_yet"])}">{so(x["kl_niem_yet"] or math.nan)}</td></tr>')
    cot = [("Ngày chấp thuận", ""), ("Chứng quyền", ""), ("Giá hợp lý dự kiến", "so"), ("Giá CS", "so"), ("Giá thực hiện", "so"),
           ("So với giá CS", "so"), ("Tỷ lệ CĐ", "so"), ("Đáo hạn", ""), ("Còn (ngày)", "so"), ("KL niêm yết", "so")]
    dau = "".join(f'<th class="{lop}"><button type="button" title="Bấm để sắp xếp">{ten}</button></th>' for ten, lop in cot)
    phan.append(
        f'<section class="the"><h2>{len(sap)} CW đang chờ lên sàn</h2>'
        + (f'<div class="cuon"><table><thead><tr>{dau}</tr></thead><tbody>{"".join(dong)}</tbody></table></div>' if sap
           else '<p>Hiện không có CW nào đang chờ lên sàn.</p>')
        + f'<p class="phu">Nguồn: {nguon}.</p></section>'
        '<section class="the"><h2>Đọc bảng này thế nào?</h2><ul>'
        '<li><b>Chứng quyền</b>: tên đầy đủ theo HOSE, dạng <i>Mã CS / Tổ chức phát hành / thời hạn / số thứ tự</i>. Ví dụ "VPB/MSVN/7M/0226" là CW của VPB do MSVN phát hành, thời hạn 7 tháng.</li>'
        '<li><b>So với giá CS</b>: giá thực hiện so với giá cổ phiếu hiện tại. Số dương = giá thực hiện cao hơn (cổ phiếu phải tăng thêm chừng đó mới có giá trị nội tại).</li>'
        '<li><b>Giá hợp lý dự kiến</b> (đồng/CW): tính bằng Black-Scholes như các CW đang giao dịch, dùng giá và mức dao động của cổ phiếu cơ sở ở lần quét gần nhất'
        f'{f" (ngày {ngay:%d/%m/%Y})" if ngay else ""}. Khi CW lên sàn, so giá giao dịch với con số này: <b>thấp hơn là rẻ</b>, cao hơn là đắt.</li>'
        '<li>Mã nào chưa có giá cổ phiếu cơ sở trong lần quét gần nhất thì giá hợp lý hiện "—".</li>'
        '<li>Khi CW đã lên sàn, nó sẽ tự biến mất khỏi trang này và xuất hiện trong <a href="/">danh sách chính</a> (được đánh dấu <span class="chip">Mới</span>).</li>'
        '</ul></section>')
    return trang("CW sắp ra mắt", "".join(phan), "/sap-ra-mat")


# ============ TRANG HƯỚNG DẪN ============
def trang_huong_dan():
    """Hướng dẫn cho người mới: CW là gì, cách dùng trang, ý nghĩa các con số, việc cần làm trước khi mua."""
    C = cw_scanner
    df, _ = doc_ket_qua()
    tot = df[df["Đánh giá"] == "NÊN XEM XÉT"] if df is not None else None
    vi_du = (f' Xem thử một ví dụ thật: <a href="/cw/{ESC(tot["Mã CW"].iloc[0])}">{ESC(tot["Mã CW"].iloc[0])}</a>.'
             if tot is not None and len(tot) else "")
    muc = [("cong-cu", "Công cụ này làm gì?"), ("cw-la-gi", "Chứng quyền là gì? (1 phút)"), ("5-buoc", "Dùng trang web trong 5 bước"),
           ("tieu-chi", "4 tiêu chí chấm điểm"), ("cac-cot", "Ý nghĩa từng cột trong bảng"), ("trang-phan-tich", "Đọc trang phân tích một mã"),
           ("gia-hop-ly", "Giá hợp lý được tính thế nào?"), ("truoc-khi-mua", "5 câu tự hỏi trước khi mua"), ("hoi-dap", "Câu hỏi thường gặp")]
    phan = ['<div class="huong-dan"><h1>Hướng dẫn sử dụng</h1><p class="phu">Đọc lần lượt từ trên xuống, khoảng 5 phút. '
            'Không cần biết lập trình hay công thức toán.</p>'
            '<nav class="the" aria-label="Mục lục"><h2>Mục lục</h2><ol class="muc-luc">'
            + "".join(f'<li><a href="#{a}">{t}</a></li>' for a, t in muc) + "</ol></nav>"]

    phan.append(
        '<section class="the" id="cong-cu"><h2>1. Công cụ này làm gì?</h2>'
        '<p>Mỗi lần bạn bấm <b>Quét ngay</b>, chương trình tải giá của <b>tất cả chứng quyền đang niêm yết trên HOSE</b>, '
        'tính <b>giá hợp lý</b> của từng mã bằng công thức Black-Scholes, rồi chấm điểm theo 4 tiêu chí để bạn biết '
        '<b>nên xem kỹ mã nào</b> và <b>nên bỏ qua mã nào</b>.</p>'
        '<p>Chương trình <b>không mua bán giúp bạn</b>, <b>không dự báo cổ phiếu sẽ tăng hay giảm</b>, và <b>không phải lời khuyên đầu tư</b>. '
        'Nó giúp bạn trả lời câu hỏi: <i>"Nếu tôi đã muốn đặt cược vào cổ phiếu X, thì chứng quyền nào của X đang có giá tốt?"</i></p></section>')

    phan.append(
        '<section class="the" id="cw-la-gi"><h2>2. Chứng quyền là gì? (1 phút)</h2><ul>'
        '<li>Mua chứng quyền (CW) = trả một khoản tiền nhỏ để được hưởng <b>phần tăng giá của một cổ phiếu</b> '
        '(gọi là <b>cổ phiếu cơ sở</b>) vượt trên một mức gọi là <b>giá thực hiện</b>, tính vào <b>ngày đáo hạn</b>.</li>'
        '<li><b>Ví dụ:</b> CW của VPB có giá thực hiện 22.605 đ, tỷ lệ chuyển đổi 1,5863 CW : 1 cổ phiếu. '
        'Nếu ngày đáo hạn VPB là 26.000 đ, mỗi CW nhận về (26.000 − 22.605) ÷ 1,5863 ≈ <b>2.140 đ</b>. '
        'Nếu VPB dưới 22.605 đ, CW <b>về 0 đ</b>.</li>'
        '<li><b>Lỗ tối đa</b> = toàn bộ tiền bạn bỏ ra mua CW. Không bao giờ lỗ nhiều hơn số đó.</li>'
        '<li><b>Lãi có thể gấp nhiều lần</b> nhờ <b>đòn bẩy</b>: cổ phiếu tăng 10% thì CW có thể tăng 50-100%.</li>'
        '<li><b>CW mất giá dần theo thời gian</b>: nếu cổ phiếu đứng yên, giá CW giảm dần mỗi ngày đến ngày đáo hạn.</li>'
        '<li>CW ngừng giao dịch <b>2 phiên trước ngày đáo hạn</b>. Nếu còn giữ đến đáo hạn, bạn nhận tiền mặt (không nhận cổ phiếu).</li>'
        '</ul></section>')

    phan.append(
        '<section class="the" id="5-buoc"><h2>3. Dùng trang web trong 5 bước</h2><ol>'
        '<li><b>Bấm "Quét ngay"</b> ở <a href="/">trang chính</a> và chờ 1-3 phút. Nên quét <b>sau 15:00</b> các ngày giao dịch để có giá đóng cửa.</li>'
        '<li><b>Xem 4 ô số</b> ở đầu trang: có bao nhiêu mã <i>Nên xem xét</i>, <i>Theo dõi</i>, <i>Bỏ qua</i> và bao nhiêu mã mới phát hành.</li>'
        '<li><b>Xem bảng "Nên xem xét"</b>: đây là các mã đạt cả 4 tiêu chí. '
        '<b>Bấm vào tiêu đề cột để sắp xếp</b> (ví dụ bấm "So với giá hợp lý" để mã rẻ nhất lên đầu). '
        'Muốn tìm CW của một cổ phiếu cụ thể, gõ mã (VPB, HPG…) vào <b>ô tìm kiếm</b> của bảng "Tất cả".</li>'
        f'<li><b>Bấm vào một mã CW</b> để mở trang phân tích chi tiết (xem mục 6).{vi_du}</li>'
        '<li><b>Tự trả lời 5 câu hỏi</b> ở mục 8 rồi mới quyết định mua hay không. Đặt lệnh qua ứng dụng của công ty chứng khoán bạn đang dùng.</li>'
        '</ol><p class="phu">Mẹo: rê chuột lên tiêu đề cột bất kỳ để xem giải thích ngắn của cột đó.</p></section>')

    phan.append(
        '<section class="the" id="tieu-chi"><h2>4. Bốn tiêu chí chấm điểm</h2><div class="cuon"><table class="bang-chu"><thead><tr>'
        '<th>Tiêu chí</th><th>Mức đang dùng</th><th>Vì sao quan trọng</th></tr></thead><tbody>'
        f'<tr><td>Thời gian còn lại</td><td>≥ {C.MIN_NGAY_CON_LAI} ngày</td><td>Gần ngày đáo hạn, CW mất giá rất nhanh và ít thời gian để cổ phiếu tăng.</td></tr>'
        f'<tr><td>Biến động ngầm định so với lịch sử (IV − HV)</td><td>≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm</td><td>Không trả cho mức dao động '
        'cao hơn hẳn 1 năm qua (tính theo giá mua = giá chào bán thấp nhất). Dùng IV thay cho "% đắt hơn giá hợp lý" vì cùng đắt 10% về giá, '
        'CW ngoài tiền chỉ tương đương khoảng +1,6 điểm IV còn CW sâu trong tiền tới khoảng +14 điểm; mức +3 điểm tương đương đắt 10% ở CW quanh tiền. '
        'CW có giá mua dưới mức tối thiểu của mô hình (không giải được IV) được tính là đạt, kèm cảnh báo.</td></tr>'
        f'<tr><td>Mức tăng cần để hòa vốn</td><td>≤ {C.MAX_TANG_DE_HOA_VON:.0%}</td><td>Mục tiêu phải thực tế: cổ phiếu tăng vài % dễ hơn nhiều so với tăng 30%.</td></tr>'
        f'<tr><td>Thanh khoản</td><td>≥ {so(C.MIN_KHOI_LUONG)} CW khớp/phiên</td><td>Đủ người mua bán thì bạn mới bán ra được đúng giá khi cần.</td></tr>'
        '</tbody></table></div><p>' + " · ".join(f"{huy_hieu(k)} {m}" for k, m in zip(KET_LUAN, ("đạt cả 4", "trượt 1 tiêu chí", "trượt từ 2 tiêu chí")))
        + '</p><p class="phu">Muốn đổi các mức trên: mở file <code>cw_scanner.py</code>, sửa phần <b>CẤU HÌNH</b> ở đầu file, lưu lại rồi bấm Quét ngay.</p></section>')

    phan.append(
        '<section class="the" id="cac-cot"><h2>5. Ý nghĩa từng cột trong bảng</h2><div class="cuon"><table class="bang-chu">'
        '<thead><tr><th>Cột</th><th>Ý nghĩa</th></tr></thead><tbody>'
        + "".join(f"<tr><td><b>{ten}</b></td><td>{ESC(gt)}</td></tr>" for ten, _, gt in COT) + "</tbody></table></div></section>")

    phan.append(
        '<section class="the" id="trang-phan-tich"><h2>6. Đọc trang phân tích một mã</h2><ul>'
        '<li><b>Tóm tắt</b>: đọc đoạn này trước. Nó nói bạn trả bao nhiêu, cổ phiếu phải lên mức nào mới có lãi, và mỗi ngày CW mất bao nhiêu tiền. '
        'Bên dưới là 4 tiêu chí với dấu ✓ (đạt) hoặc ✕ (không đạt).</li>'
        '<li><b>Giá trị nội tại và giá trị thời gian</b>: giá CW = phần lãi nếu đáo hạn ngay hôm nay (<i>nội tại</i>) + phần trả thêm cho thời gian còn lại '
        '(<i>thời gian</i>). Phần thời gian luôn giảm về 0 vào ngày đáo hạn. Phần này càng nhỏ, bạn càng ít mất tiền do thời gian.</li>'
        '<li><b>Điểm hòa vốn</b>: giá cổ phiếu cần đạt vào ngày đáo hạn để bạn không lỗ không lãi.</li>'
        '<li><b>📐 Giá hợp lý … được tính thế nào?</b>: bấm vào để xem 7 bước tính giá hợp lý bằng số thật của mã đó, '
        'kèm phần kiểm chứng bằng 20.000 kịch bản (xem thêm mục 7).</li>'
        '<li><b>Khối lượng CW</b>: tổng số CW phát hành, số CW <b>đang chào bán</b> (lượng bạn mua được ngay và giá thấp nhất), '
        'số CW đang chờ mua (lượng bán ra được ngay) và sổ lệnh 3 mức giá, tải trực tiếp lúc mở trang.</li>'
        '<li><b>Đòn bẩy</b>: ví dụ 9x nghĩa là cổ phiếu tăng 1% thì CW tăng khoảng 9%, cổ phiếu giảm 1% thì CW giảm khoảng 9%.</li>'
        '<li><b>Delta</b> (từ 0 đến 1): mức CW "chạy theo" cổ phiếu. Ô này ghi sẵn cổ phiếu tăng/giảm 1.000 đ thì 1 CW tăng/giảm khoảng bao nhiêu đồng. '
        'Delta gần 1: CW bám sát cổ phiếu; gần 0: CW gần như không phản ứng (thường do giá cổ phiếu còn xa dưới giá thực hiện).</li>'
        '<li><b>Biến động ngầm định (IV)</b>: mức dao động mà giá mua CW đang "giả định". So với mức dao động thật 1 năm qua (HV): '
        '<b>IV − HV</b> âm → CW đang rẻ, dương → đắt. Khác với "% so với giá hợp lý", con số này so sánh được giữa các CW ở gần và xa giá thực hiện, '
        f'nên bảng xếp theo nó và dùng nó làm tiêu chí (≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm). "—" nghĩa là không giải được, thường do giá mua thấp hơn <b>mức tối thiểu</b> S − K × e<sup>−rT</sup> của mô hình '
        '(có khung ⚠ Lưu ý): khi đó chữ "Rẻ" chủ yếu đến từ giả định lãi suất và mức dao động, không chắc là món hời.</li>'
        '<li><b>Biểu đồ</b>: đường xanh là giá cổ phiếu 1 năm qua; đường xám là giá thực hiện; đường cam là <b>điểm hòa vốn</b>. '
        'Muốn có lãi khi giữ đến đáo hạn, giá cổ phiếu phải <b>nằm trên đường cam</b>. Rê chuột (hoặc bấm vào biểu đồ rồi dùng phím ← →) để xem giá từng ngày.</li>'
        '<li><b>Bảng "Nếu giữ đến ngày đáo hạn"</b>: xem trước lãi/lỗ theo từng kịch bản cổ phiếu tăng/giảm. '
        'Nhìn dòng <b>−10%</b> và <b>−20%</b> để biết <b>kịch bản xấu</b>, cột cuối cho biết lãi/lỗ theo số tiền bạn nhập ở mục <b>Rủi ro với số tiền của bạn</b>.</li>'
        '<li><b>Rủi ro với số tiền của bạn</b>: nhập số tiền định bỏ ra để xem mua được bao nhiêu CW, tương đương nắm bao nhiêu tiền cổ phiếu '
        '(thường gấp 5-15 lần), cổ phiếu giảm đến đâu thì mất toàn bộ, ngày cuối cùng còn bán được và điểm hòa vốn sau phí, thuế.</li>'
        '<li>Mọi con số ở trang phân tích được <b>tính lại theo giá trực tiếp</b> lúc mở trang (dòng đầu trang ghi giờ lấy giá). '
        'Kết luận có thể khác bảng ở trang chính (bảng đó là số lúc quét).</li>'
        '<li><b>Các CW khác của cùng cổ phiếu</b>: cùng đặt cược vào một cổ phiếu, hãy so để chọn CW rẻ hơn, còn nhiều ngày hơn hoặc dễ hòa vốn hơn.</li>'
        '<li>Khung màu vàng <b>⚠ Bất thường</b> (nếu có): giá CW thấp hơn cả giá trị nội tại. Hãy đọc thông báo của tổ chức phát hành trước khi mua.</li>'
        '</ul></section>')

    phan.append(
        '<section class="the" id="gia-hop-ly"><h2>7. Giá hợp lý được tính thế nào? (nói đơn giản)</h2>'
        '<p><b>Ý tưởng:</b> tưởng tượng hàng nghìn kịch bản giá cổ phiếu có thể xảy ra đến ngày đáo hạn (cổ phiếu dao động mạnh hay yếu '
        'giống như 1 năm qua). Trong mỗi kịch bản, CW trả một số tiền hoặc về 0. <b>Giá hợp lý = trung bình số tiền đó, quy về tiền hôm nay.</b> '
        'Công thức Black-Scholes là cách tính nhanh ra con số trung bình này mà không cần thử từng kịch bản.</p>'
        '<p><b>Ví dụ dễ hình dung:</b> cổ phiếu giá 100 đ, giá thực hiện 100 đ, tỷ lệ 1 : 1.</p><ul>'
        '<li>Nếu đến ngày đáo hạn cổ phiếu chỉ có thể là <b>90 hoặc 110</b> (mỗi khả năng một nửa): CW trả 0 hoặc 10 → trung bình <b>5 đ</b>.</li>'
        '<li>Nếu cổ phiếu dao động mạnh hơn, là <b>70 hoặc 130</b>: CW trả 0 hoặc 30 → trung bình <b>15 đ</b>.</li></ul>'
        '<p>Cùng một cổ phiếu, dao động mạnh hơn thì CW đáng giá gấp 3. Lý do: lỗ tối đa chỉ là tiền mua CW, còn lãi thì không giới hạn.</p>'
        '<p><b>Công thức viết bằng lời:</b></p>'
        '<p class="cong-thuc">Giá hợp lý 1 CW = ( Giá cổ phiếu × A − Giá thực hiện × B ) ÷ Tỷ lệ chuyển đổi</p><ul>'
        '<li><b>Giá cổ phiếu × A</b> = phần bạn "nhận được"; <b>Giá thực hiện × B</b> = phần bạn "phải trả". Chênh lệch là giá trị của quyền.</li>'
        '<li><b>A</b> và <b>B</b> là hai hệ số từ 0 đến 1. <b>B</b> gần bằng <b>xác suất</b> đến ngày đáo hạn giá cổ phiếu vẫn trên giá thực hiện.</li>'
        '<li>A và B được tính từ 3 câu hỏi: giá đang cách giá thực hiện bao xa? còn bao nhiêu thời gian? cổ phiếu hay dao động cỡ nào?</li></ul>'
        '<p><b>3 quy luật dễ nhớ – CW đáng giá hơn khi:</b></p><ol>'
        '<li>Giá cổ phiếu <b>càng cao hơn</b> giá thực hiện.</li><li><b>Còn càng nhiều thời gian</b> đến ngày đáo hạn.</li>'
        '<li>Cổ phiếu <b>càng hay dao động mạnh</b> (như ví dụ trên).</li></ol>'
        f'<p>Muốn xem <b>từng bước tính bằng số thật</b>: mở trang phân tích một mã bất kỳ, bấm mục <b>"📐 Giá hợp lý … được tính thế nào?"</b>.{vi_du}</p></section>'
        '<section class="the" id="truoc-khi-mua"><h2>8. Năm câu tự hỏi trước khi mua</h2><ol>'
        '<li><b>Tôi có lý do tin cổ phiếu cơ sở sẽ lên trên điểm hòa vốn trước ngày đáo hạn không?</b> '
        'Công cụ chỉ cho biết CW đắt hay rẻ, không cho biết cổ phiếu sẽ tăng.</li>'
        '<li><b>Nếu cổ phiếu giảm 10-20%, tôi mất bao nhiêu?</b> Xem bảng kịch bản. Có thể mất gần hết tiền mua CW.</li>'
        f'<li><b>Còn đủ thời gian không?</b> Ưu tiên CW còn trên {C.MIN_NGAY_CON_LAI} ngày.</li>'
        '<li><b>Có CW nào khác của cùng cổ phiếu tốt hơn không?</b> Xem bảng so sánh ở cuối trang phân tích.</li>'
        '<li><b>Nếu mất hết số tiền này, tôi vẫn ổn chứ?</b> Chỉ dùng phần tiền bạn chấp nhận mất.</li></ol>'
        '<p><b>Khi đặt lệnh:</b> dùng <b>lệnh giới hạn (LO)</b> với mức giá bạn muốn thay vì mua bằng mọi giá; kiểm tra lại điều khoản CW '
        'trên website tổ chức phát hành / HOSE; ghi nhớ ngày giao dịch cuối cùng (2 phiên trước ngày đáo hạn).</p></section>')

    hoi_dap = [
        ("Vì sao quét mất 1-3 phút?", "Gói miễn phí của vnstock giới hạn số lượt lấy dữ liệu mỗi phút, chương trình tự chờ rồi chạy tiếp. Có API key hợp lệ thì nhanh hơn."),
        ("Nhật ký có dòng [!] … số thiết bị tối đa?", "Tài khoản vnstock của bạn đã dùng hết số máy được phép. Vào trang tài khoản trên vnstocks.com để gỡ thiết bị cũ. Trong lúc đó chương trình vẫn quét được, chỉ chậm hơn."),
        ("Dữ liệu được cập nhật khi nào?", "Mỗi lần bấm Quét ngay. Ngày của dữ liệu ghi ở đầu trang chính. Giá trong ngày thay đổi liên tục nên hãy quét lại trước khi đặt lệnh."),
        ("Chữ \"Mới\" cạnh mã CW là gì?", "CW chưa có ở lần quét trước, tức là mới niêm yết. Lần quét đầu tiên chưa đánh dấu mã nào."),
        ("Xem các chứng quyền sắp ra mắt ở đâu?", "Bấm \"🆕 CW sắp ra mắt\" ở đầu trang. Đó là các CW HOSE đã chấp thuận niêm yết nhưng chưa giao dịch, "
         "kèm giá hợp lý dự kiến để so sánh khi CW lên sàn. Danh sách tải trực tiếp từ HOSE; nếu HOSE chậm thì dùng danh sách lưu ở lần quét gần nhất."),
        ("Xem số CW đã bán ra và còn lại ở đâu?", "Các nguồn dữ liệu miễn phí chỉ công bố tổng khối lượng phát hành, không công bố nhà đầu tư đang nắm bao nhiêu. "
         "Trang phân tích mỗi mã có mục \"Khối lượng CW\": khối lượng phát hành, số CW đang chào bán (lượng mua được ngay), đang chờ mua và sổ lệnh 3 mức giá, "
         "tải trực tiếp lúc mở trang. Cột \"Đang chào bán\" trong bảng là số liệu lúc quét."),
        ("Vì sao dùng giá chào bán (giá mua) chứ không dùng giá khớp?", "Muốn mua ngay, bạn phải trả giá thấp nhất đang chào bán, thường cao hơn giá khớp gần nhất "
         "(có mã cao hơn hơn 10%). Định giá theo giá khớp có thể làm CW trông rẻ hơn thực tế. Khi sổ lệnh trống (trước giờ giao dịch), chương trình "
         "dùng giá khớp hoặc giá tham chiếu và ghi chữ nhỏ \"khớp\" / \"TC\" cạnh giá."),
        ("\"Đắt > 1.000%\" là sao?", "CW gần hết hạn và giá cổ phiếu còn quá xa giá thực hiện, nên giá hợp lý gần 0 đ. Gần như chắc chắn nên bỏ qua."),
        ("\"Giá hợp lý\" có chắc đúng không?", "Không. Nó dựa trên giả định mức dao động của cổ phiếu 1 năm qua sẽ lặp lại. Hãy coi nó là một ý kiến tham khảo, không phải sự thật."),
        ("Tắt chương trình thế nào?", "Đóng cửa sổ Terminal (Mac) hoặc cửa sổ đen (Windows), hoặc nhấn Ctrl + C trong cửa sổ đó."),
    ]
    phan.append('<section class="the" id="hoi-dap"><h2>9. Câu hỏi thường gặp</h2>'
                + "".join(f'<details style="margin-top:10px"><summary>{ESC(q)}</summary><p>{ESC(a)}</p></details>' for q, a in hoi_dap)
                + "</section></div>")
    return trang("Hướng dẫn sử dụng", "".join(phan), "/huong-dan")


class XuLy(BaseHTTPRequestHandler):
    def do_GET(self):
        duong_dan = self.path.split("?")[0]
        m = re.fullmatch(r"/cw/([A-Z0-9]{4,12})", duong_dan)  # chỉ nhận mã hợp lệ
        noi_dung = (trang_chinh() if duong_dan == "/" else trang_huong_dan() if duong_dan == "/huong-dan"
                    else trang_sap_ra_mat("tai_moi=1" in self.path) if duong_dan == "/sap-ra-mat"
                    else trang_chi_tiet(m.group(1), doc_von(self.path)) if m else None)
        self.send_response(200 if noi_dung else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write((noi_dung or trang("Không tìm thấy", '<h1>Không tìm thấy</h1><p><a href="/">← Về danh sách chứng quyền</a></p>')).encode("utf-8"))

    def do_POST(self):
        global LOI, NHAT_KY
        bo_dem = io.StringIO()
        try:
            with contextlib.redirect_stdout(bo_dem):  # gom lời nhắn của cw_scanner để hiện lên trang
                cw_scanner.main()
            LOI = ""
        except Exception as e:  # lỗi mạng/API: báo trên trang thay vì làm sập máy chủ
            LOI = f"Lỗi khi quét: {e}"
        NHAT_KY = bo_dem.getvalue()
        self.send_response(303)  # quay về trang chính để bấm F5 không bị quét lại
        self.send_header("Location", "/")
        self.end_headers()


if __name__ == "__main__":
    # Chỉ mở cho máy của bạn (127.0.0.1), người khác trong mạng không truy cập được
    may_chu = HTTPServer(("127.0.0.1", CONG), XuLy)
    print(f"Giao diện web: http://localhost:{CONG}  (Ctrl+C để tắt)")
    webbrowser.open(f"http://localhost:{CONG}")
    may_chu.serve_forever()
