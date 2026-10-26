"""Phần dùng chung của giao diện web: CSS/JS, định dạng số, khung trang + menu, bảng CW, biểu đồ, đọc file kết quả, trạng thái lần quét."""

import html
import json
import math
from datetime import date
from urllib.parse import parse_qs, quote, urlsplit

import pandas as pd

import cw_scanner
import danh_muc

CONG = 8000
VON_MAC_DINH = 10  # triệu đồng: số tiền mặc định ở mục "Rủi ro với số tiền của bạn"
BO_NHO_IV: dict[tuple, dict] = {}  # (mã CW, ngày) -> [[ngày, IV %]]: lịch sử giá CW chỉ tải 1 lần mỗi ngày
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
GIAI_THICH_LECH = "Giá CW thực tế so với giá “lẽ ra” nếu CW giữ nguyên mức IV của ngày mốc và chỉ chạy theo giá cổ phiếu cơ sở (đã gồm đòn bẩy và mất giá theo thời gian), qua 20 phiên gần nhất. Âm: CW không theo kịp cổ phiếu; dương: CW chạy nhanh hơn, dễ bị kéo về. Trong khoảng ±15% là bình thường. Chi tiết và biểu đồ ở trang của từng CW."
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
    ("Lệch 20 phiên", "so", GIAI_THICH_LECH),
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
.thanh-tren .bt { margin-right: 4px; }
/* Điện thoại: menu thành thanh cố định dưới cùng (biểu tượng trên chữ), bảng gọn hơn, cột mã đứng yên khi vuốt ngang */
@media (max-width: 640px) {
  main { padding: 16px 12px calc(84px + env(safe-area-inset-bottom)); }
  h1 { font-size: 22px; }
  .the { padding: 14px; }
  .thanh-tren { position: fixed; left: 0; right: 0; bottom: 0; z-index: 10; margin: 0; gap: 0; flex-wrap: nowrap;
    background: var(--be-mat); border-top: 1px solid var(--vien); padding: 4px 4px calc(4px + env(safe-area-inset-bottom)); }
  .thanh-tren a { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 0;
    font-size: 11px; color: var(--chu-phu); }
  .thanh-tren .bt { font-size: 22px; line-height: 1; margin: 0; }
  .thanh-tren a[aria-current] { color: var(--nut); border-bottom: 0; }
  table { font-size: 13px; }
  th, td { padding: 6px 8px; }
  .cuon th:first-child, .cuon td:first-child { position: sticky; left: 0; z-index: 1; background: var(--be-mat); }
  .cuon th:first-child { z-index: 2; }
}
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


# thanh menu: trên đầu trang ở máy tính, dưới cùng màn hình ở điện thoại (như app). Trang "Sắp ra mắt" (/sap-ra-mat) vẫn còn
# nhưng bỏ khỏi menu theo yêu cầu người dùng 24/10/2026
MENU = (
    ("/", "📈", "Chứng quyền"),
    ("/luot-cw", "⚡", "Lướt CW"),
    ("/etf", "📊", "ETF"),
    ("/danh-muc", "💼", "Danh mục"),
    ("/huong-dan", "❓", "Hướng dẫn"),
)


def trang(tieu_de, than, duong_dan=""):
    """Khung chung của mọi trang: thanh điều hướng trên cùng + nội dung + lưu ý cuối trang."""
    menu = "".join(
        f'<a href="{dd}"{" aria-current=page" if dd == duong_dan else ""}><span class="bt" aria-hidden="true">{bt}</span>'
        f"<span>{ten}</span></a>"
        for dd, bt, ten in MENU
    )
    # biểu tượng trên tab trình duyệt: emoji của mục menu (trang khác, vd chi tiết CW: 📈), vẽ bằng SVG nên không cần file ảnh
    bieu_tuong = {dd: bt for dd, bt, _ in MENU}.get(duong_dan, "📈")
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>{bieu_tuong}</text></svg>"
    return (
        f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f'<title>{ESC(tieu_de)}</title><link rel="icon" href="data:image/svg+xml,{quote(svg)}"><style>{CSS}</style></head><body><main>'
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
    "Lệch 20 phiên %",
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
        lech = h["Lệch 20 phiên %"]
        o_lech = (
            f'<td class="so" data-v="{lech}" title="mốc {ESC(str(h.get("Mốc lệch", "")))}">'
            + (f"<b>{so(lech, 1, True)}%</b>" if abs(lech) >= danh_muc.CANH_BAO_LECH * 100 else f"{so(lech, 1, True)}%")
            + "</td>"
            if math.isfinite(lech)
            else f'<td class="so" data-v="{v(lech)}">—</td>'
        )  # đậm khi vượt ngưỡng cảnh báo ±15% của danh mục
        dong.append(
            f'<tr data-href="/cw/{ma}"{" class=dang-xem" if h["Mã CW"] == ma_dang_xem else ""}>'
            f'<td><a href="/cw/{ma}">{ma}</a>{moi}</td><td>{ESC(h["Mã CS"])}</td><td>{ESC(h["TCPH"])}</td>'
            f'<td class="so" data-v="{h["Ngày còn lại"]}">{so(h["Ngày còn lại"])}</td>'
            f'<td class="so" data-v="{h["Giá mua"]}">{so(h["Giá mua"])}{nguon}</td><td class="so" data-v="{h["Giá hợp lý"]}">{so(h["Giá hợp lý"])}</td>'
            f'<td class="so {lop}" data-v="{v(h["Đắt/rẻ %"])}">{chu_dat_re}</td>{o_iv}{o_iv_hv}{o_lech}'
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
