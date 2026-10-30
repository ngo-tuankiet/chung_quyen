"""Phần dùng chung của giao diện web: CSS/JS, định dạng số, khung trang + menu, bảng CW, biểu đồ, đọc file kết quả, trạng thái lần quét."""

import html
import json
import math
import re
import time
from datetime import date
from urllib.parse import parse_qs, quote, urlsplit

import pandas as pd

import cw_scanner
import danh_muc

CONG = 8000
VON_MAC_DINH = 10  # triệu đồng: số tiền mặc định ở mục "Rủi ro với số tiền của bạn"
BO_NHO_NEN: dict[str, tuple] = (
    {}
)  # mã -> (lúc tải, nến H4): trang chi tiết mở lại trong vài phút không gọi vnstock lần nữa
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
main { margin: 0 auto; padding: 24px 24px 48px; }  /* trải hết chiều ngang; chữ dài tự giới hạn ở .tom-tat, .huong-dan */
a { color: var(--lien-ket); }
h1 { font-size: 26px; margin: 0; line-height: 1.25; }
h2 { font-size: 18px; margin: 0; }
.phu { color: var(--chu-phu); margin: 4px 0 0; font-size: 14px; }
.dau-trang { display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; align-items: flex-start; }
.nut { background: var(--nut); color: #fff; border: 0; border-radius: 8px; padding: 10px 22px; font: 600 15px system-ui, sans-serif; cursor: pointer; }
.nut:disabled { opacity: .6; cursor: wait; }
.the { background: var(--be-mat); border: 1px solid var(--vien); border-radius: 12px; padding: 20px; margin-top: 16px; }
.luoi-o { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-top: 16px; }
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
.nen-tang { fill: var(--tot); stroke: var(--tot); } .nen-giam { fill: var(--chu-am); stroke: var(--chu-am); }
.nen-le { opacity: .3; } tr.khop-le td { opacity: .45; }
.kl-tang { fill: var(--tot); opacity: .45; } .kl-giam { fill: var(--chu-am); opacity: .45; }
.kl-tang-dam { fill: var(--tot); } .kl-giam-dam { fill: var(--chu-am); }
.vach-phien { stroke: var(--luoi); stroke-width: 1; stroke-dasharray: 2 3; }
.gia-cuoi { stroke: var(--chu-mo); stroke-width: 1; stroke-dasharray: 4 3; }
.nhan-gia-cuoi { fill: #fff; font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
.bieu-do-nen line, .bieu-do-nen rect { vector-effect: non-scaling-stroke; } .bieu-do-nen { width: 100%; height: auto; display: block; }
.chon-khung { display: inline-flex; border: 1px solid var(--vien); border-radius: 8px; overflow: hidden; }
.chon-khung button { border: 0; background: transparent; color: var(--chu); padding: 6px 14px; font: inherit; font-weight: 600; cursor: pointer; }
.chon-khung button[aria-pressed="true"] { background: var(--nut); color: #fff; }
.nen-chu-giai { font-size: 13px; font-variant-numeric: tabular-nums; min-height: 1.5em; margin: 6px 0 2px; }
.nen-chu-giai b { font-weight: 600; } .nen-tuong-tac svg { cursor: crosshair; touch-action: none; user-select: none; }
@media (pointer: coarse) { .nen-tuong-tac svg { touch-action: pan-y; } }  /* điện thoại: vuốt dọc vẫn cuộn trang */
.vach-doc, .vach-ngang { stroke: var(--chu-mo); stroke-width: 1; stroke-dasharray: 3 3; pointer-events: none; }
.nhan-con-tro rect { fill: var(--chu-mo); } .nhan-con-tro text { fill: #fff; font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
.thuoc-do { pointer-events: none; } .vung-do { fill: var(--tot); fill-opacity: .14; stroke: var(--tot); stroke-width: 1; }
.thuoc-do.giam .vung-do { fill: var(--chu-am); stroke: var(--chu-am); } .duong-do { stroke: var(--tot); stroke-width: 1.5; }
.thuoc-do.giam .duong-do { stroke: var(--chu-am); }
.chu-do { font-size: 14px; font-weight: 700; fill: var(--chu-duong); paint-order: stroke; stroke: var(--be-mat); stroke-width: 4px; }
.thuoc-do.giam .chu-do { fill: var(--chu-am); }
.tom-nen { margin: 4px 0 0; font-size: 14px; font-variant-numeric: tabular-nums; }
.hang-doi { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; margin-top: 16px; }
.hang-doi > .the { margin-top: 0; }
.cot-doc { display: flex; flex-direction: column; gap: 16px; } .cot-doc > .the { margin-top: 0; }
.giai-thich { margin-top: 4px; } .giai-thich summary { cursor: pointer; color: var(--lien-ket); font-size: 14px; }
.giai-thich .phu { max-width: 900px; }
.hang-nen { display: grid; grid-template-columns: minmax(0, 1fr) 320px 360px; gap: 16px; align-items: start; margin-top: 8px; }
.hang-nen h4 { margin: 0 0 6px; font-size: 14px; } .hang-nen table { font-size: 13px; width: 100%; }
.hang-nen td, .hang-nen th { padding: 3px 6px; } .khop-cuon { max-height: 330px; overflow-y: auto; }
.ti-le { display: flex; height: 6px; border-radius: 3px; overflow: hidden; margin: 6px 0 2px; background: var(--chu-am); }
.ti-le span { background: var(--tot); } .du { display: flex; justify-content: space-between; font-size: 13px; }
.cot-mua { fill: var(--tot); opacity: .8; } .cot-ban { fill: var(--chu-am); opacity: .8; }
.gia-tang { color: var(--chu-duong); } .gia-giam { color: var(--chu-am); } .gia-dung { color: #b8860b; }
@media (max-width: 1100px) { .hang-nen { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 1100px) { .hang-doi { grid-template-columns: minmax(0, 1fr); } }
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
// biểu đồ nến: thanh dọc theo chuột / ngón tay (như TradingView) + dòng thông số của nến đang trỏ. Các biểu đồ cùng khung trong
// 1 mục (CW và CS, chung trục) chạy cùng nhau. Rời chuột thì về nến cuối. Phím ← → khi biểu đồ được chọn.
const nenCung = el => el.closest("section").querySelectorAll(`.khung-nen[data-khung="${el.closest(".khung-nen").dataset.khung}"] .nen-tuong-tac`);
const chiNen = (el, i) => nenCung(el).forEach(k => {
  const n = k.querySelectorAll(".nen-chu-giai > span"), cuoi = n.length - 1, j = i == null ? cuoi : Math.max(0, Math.min(cuoi, i));
  n.forEach((s, m) => { s.hidden = m !== j; });
  const v = k.querySelector(".vach-doc"), x = +k.dataset.x0 + (j + 0.5) * +k.dataset.rong;
  v.setAttribute("x1", x); v.setAttribute("x2", x); v.setAttribute("visibility", i == null ? "hidden" : "visible");
  k.dataset.i = i == null ? "" : j;
});
document.querySelectorAll(".nen-tuong-tac").forEach(k => {
  const svg = k.querySelector("svg");
  const viTri = e => { const r = svg.getBoundingClientRect(); return Math.floor(((e.clientX - r.left) / r.width * +k.dataset.r - +k.dataset.x0) / +k.dataset.rong); };
  svg.addEventListener("pointermove", e => chiNen(k, viTri(e)));
  svg.addEventListener("pointerdown", e => chiNen(k, viTri(e)));
  svg.addEventListener("pointerleave", () => chiNen(k, null));
  svg.addEventListener("keydown", e => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const n = k.querySelectorAll(".nen-chu-giai > span").length, i = k.dataset.i === "" || k.dataset.i == null ? n - 1 : +k.dataset.i;
    chiNen(k, i + (e.key === "ArrowLeft" ? -1 : 1));
  });
  svg.addEventListener("blur", () => chiNen(k, null));
});
// thanh ngang + thước đo: trong vùng giá, đường ngang và nhãn giá tại con trỏ (bên phải); giữ chuột / ngón tay kéo -> vùng đo
// từ điểm bắt đầu tới con trỏ: % thay đổi, chênh lệch giá (đ), số nến (như công cụ đo của TradingView). Thả ra vẫn giữ
// vùng đo; bấm (không kéo) hoặc Esc để xóa.
const soVN = (v, le = 0) => v.toLocaleString("vi-VN", { minimumFractionDigits: le, maximumFractionDigits: le });
document.querySelectorAll(".nen-tuong-tac").forEach(k => {
  const svg = k.querySelector("svg"), d = k.dataset, q = s => svg.querySelector(s), td = q(".thuoc-do");
  const toaDo = e => { const r = svg.getBoundingClientRect(); return [(e.clientX - r.left) / r.width * +d.r, (e.clientY - r.top) / r.height * +d.c]; };
  const kep = y => Math.max(+d.tren, Math.min(+d.tren + +d.nenCao, y));
  const giaTai = y => +d.giaCao - (kep(y) - +d.tren) / +d.nenCao * (+d.giaCao - +d.giaThap);
  const trongGia = y => y >= +d.tren && y <= +d.tren + +d.nenCao;
  const nenTai = x => Math.floor((x - +d.x0) / +d.rong);
  const dat = (el, o) => Object.entries(o).forEach(([a, v]) => el.setAttribute(a, v));
  let dau = null;
  const ngang = y => {
    const l = q(".vach-ngang"), n = q(".nhan-con-tro"), hien = trongGia(y) ? "visible" : "hidden";
    l.setAttribute("visibility", hien); n.setAttribute("visibility", hien);
    if (hien === "hidden") return;
    dat(l, { y1: y, y2: y }); n.querySelector("rect").setAttribute("y", y - 10);
    const ch = n.querySelector("text"); ch.setAttribute("y", y + 4); ch.textContent = soVN(giaTai(y), +d.soLe);
  };
  const doDen = (x, y) => {
    y = kep(y);
    const g0 = giaTai(dau.y), g1 = giaTai(y), pt = (g1 / g0 - 1) * 100, dau_ = pt >= 0 ? "+" : "−";
    td.classList.toggle("giam", pt < 0);
    dat(q(".vung-do"), { x: Math.min(dau.x, x), y: Math.min(dau.y, y), width: Math.abs(x - dau.x), height: Math.abs(y - dau.y) });
    dat(q(".duong-do"), { x1: dau.x, y1: dau.y, x2: x, y2: y });
    const ch = q(".chu-do"), xt = Math.min(x + 8, +d.r - 220);
    dat(ch, { x: xt, y: Math.max(+d.tren + 14, y + (y < dau.y ? -8 : 18)) });
    ch.textContent = `${dau_}${soVN(Math.abs(pt), 2)}% (${dau_}${soVN(Math.abs(g1 - g0), +d.soLe)} ${d.donVi}) · ${Math.abs(nenTai(x) - nenTai(dau.x))} nến`;
    td.setAttribute("visibility", "visible");
  };
  svg.addEventListener("pointerdown", e => {
    const [x, y] = toaDo(e);
    td.setAttribute("visibility", "hidden");
    if (!trongGia(y)) return;
    dau = { x, y, keo: false };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", e => {
    const [x, y] = toaDo(e);
    ngang(y);
    if (!dau) return;
    if (Math.abs(x - dau.x) + Math.abs(y - dau.y) > 4) dau.keo = true;
    if (dau.keo) doDen(x, y);
  });
  svg.addEventListener("pointerup", () => { dau = null; });
  svg.addEventListener("pointerleave", () => { if (!dau) ngang(-1); });
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") document.querySelectorAll(".thuoc-do").forEach(g => g.setAttribute("visibility", "hidden"));
});
// nút H1 / H4 / D1: hiện biểu đồ nến đúng khung trong cùng mục, các khung khác ẩn (đã vẽ sẵn, không tải lại trang)
document.querySelectorAll("[data-chon-khung]").forEach(n => n.addEventListener("click", () => {
  const muc = n.closest("section");
  muc.querySelectorAll(".khung-nen").forEach(k => { k.hidden = k.dataset.khung !== n.dataset.chonKhung; });
  muc.querySelectorAll("[data-chon-khung]").forEach(b => b.setAttribute("aria-pressed", b === n));
}));
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
    ("/etf", "📊", "ETF"),
    ("/phai-sinh", "📉", "Phái sinh"),
    ("/danh-muc", "💼", "Danh mục"),
    ("/huong-dan", "❓", "Hướng dẫn"),
)


GIAI_THICH_TOI_THIEU = (
    160  # ghi chú (p.phu) dài hơn số ký tự chữ này thì thu vào nút "ℹ Giải thích" (người dùng chọn 30/10/2026)
)
MAU_GHI_CHU = re.compile(
    r'<p class="phu"(?: [^>]*)?>.*?</p>', re.DOTALL
)  # p không lồng p nên khớp ngắn nhất là đúng 1 đoạn


def hang_doi(trai, phai):
    """2 mục cạnh nhau (mỗi mục 1 nửa chiều ngang); màn hình < 1.100 px tự xếp 1 cột. Thiếu 1 bên thì mục còn lại trải ngang."""
    if not trai or not phai:
        return trai + phai
    return f'<div class="hang-doi">{trai}{phai}</div>'


def thu_gon_giai_thich(html):
    """Ghi chú dài thu vào <details> "ℹ Giải thích" để trang trải ngang gọn hơn; ghi chú ngắn giữ nguyên."""
    dai = lambda m: len(re.sub(r"<[^>]+>", "", m.group(0))) > GIAI_THICH_TOI_THIEU
    return MAU_GHI_CHU.sub(
        lambda m: (
            f'<details class="giai-thich"><summary>ℹ Giải thích</summary>{m.group(0)}</details>'
            if dai(m)
            else m.group(0)
        ),
        html,
    )


def trang(tieu_de, than, duong_dan=""):
    """Khung chung của mọi trang: thanh điều hướng trên cùng + nội dung + lưu ý cuối trang.
    Ghi chú dài thu vào "ℹ Giải thích", trừ trang Hướng dẫn (trang để đọc)."""
    if duong_dan != "/huong-dan":
        than = thu_gon_giai_thich(than)
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


def bieu_do(lich_su, duong_ke, ten, don_vi="đ", ten_cot="Giá đóng cửa (đ)", duong_phu=(), so_le=0, truc_gio=False):
    """SVG một chuỗi số theo ngày [[ngày, giá trị]] + đường tham chiếu [(nhãn, giá trị, lớp)], kèm bảng dữ liệu cho người không xem được hình.
    duong_phu [(nhãn, [giá trị từng ngày hoặc None], lớp)]: đường vẽ cùng trục (vd MA50), nhãn ở mép phải. so_le: số lẻ khi hiện số.
    truc_gio: mốc là giờ "HH:MM" trong 1 phiên thay vì ngày "YYYY-MM-DD".
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
            f'<text class="nhan-truc" x="{x(i):.1f}" y="{C - 8}" text-anchor="{neo}">{lich_su[i][0][:5] if truc_gio else f"{lich_su[i][0][5:7]}/{lich_su[i][0][:4]}"}</text>'
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
        f'<tr><td>{d[:5] if truc_gio else f"{d[8:]}/{d[5:7]}/{d[:4]}"}</td><td class="so">{so(g, so_le)}</td></tr>'
        for d, g in reversed(lich_su)
    )
    return (
        f'<div class="cuon-bieu-do"><div class="bieu-do" data-don-vi="{ESC(don_vi)}"><svg viewBox="0 0 {R} {C}" tabindex="0" role="img" aria-label="{ESC(mo_ta)}. Dùng phím mũi tên để xem từng ngày.">'
        f'{"".join(phan)}</svg><div class="o-tro" hidden><b></b><span></span></div>'
        f'<script type="application/json">{diem}</script></div></div>'
        f'<details style="margin-top:8px"><summary>Xem dữ liệu dạng bảng</summary><div class="cuon cao" style="max-width:360px">'
        f'<table><thead><tr><th>Ngày</th><th class="so">{ESC(ten_cot)}</th></tr></thead><tbody>{dong_bang}</tbody></table></div></details>'
    )


# ============ NẾN H4 (gộp từ nến 1 giờ) ============
NEN_CAO, KL_CAO = 280, 110  # chiều cao vùng nến và vùng khối lượng (px trong viewBox)


def nen_tu_df(df, he_so):
    """DataFrame nến vnstock -> {'YYYY-MM-DD HH:MM': (mở, cao, thấp, đóng, KL)}, giá nhân he_so (vnstock trả nghìn đồng)."""
    return {
        str(t)[:16]: (o * he_so, h * he_so, l * he_so, c * he_so, float(v))
        for t, o, h, l, c, v in zip(df["time"], df["open"], df["high"], df["low"], df["close"], df["volume"])
    }


def gio_nen_chung(*cac_nen, so_nen):
    """Trục thời gian chung của nhiều mã (gộp mốc của tất cả), chỉ giữ `so_nen` mốc cuối: 2 biểu đồ cùng cột = cùng thời điểm."""
    return sorted(set().union(*cac_nen))[-so_nen:]


def nen_h4(nen):
    """Gộp nến 1 giờ thành nến 4 giờ mốc 09:00 và 13:00. HOSE chỉ khớp 9:15–11:30 và 13:00–14:45 nên mỗi phiên có đúng
    1 nến buổi sáng và 1 nến buổi chiều: mở = mở nến sớm nhất, đóng = đóng nến muộn nhất, cao/thấp = max/min, KL cộng dồn.
    """
    gop = {}
    for g in sorted(nen):
        k, (o, h, l, c, v) = g[:11] + ("09:00" if g[11:16] < "13:00" else "13:00"), nen[g]
        if k in gop:
            o0, h0, l0, _, v0 = gop[k]
            gop[k] = (o0, max(h0, h), min(l0, l), c, v0 + v)
        else:
            gop[k] = (o, h, l, c, v)
    return gop


def muc_so_lenh(so_lenh):
    """3 mức giá chờ mua / chào bán tốt nhất (Vietcap chỉ trả 3 mức), từ giá tốt nhất ra ngoài: ([(giá, KL)] mua, [(giá, KL)] bán).
    Giá dạng chữ (ATO/ATC) hoặc ≤ 0 bỏ qua."""
    lay = lambda khoa: [
        (float(m["price"]), float(m.get("volume") or 0))
        for m in (so_lenh or {}).get(khoa) or []
        if isinstance(m.get("price"), (int, float)) and m["price"] > 0
    ]
    return lay("bidPrices"), lay("askPrices")


TEN_KHUNG = {"h1": "1 giờ", "h4": "4 giờ", "d1": "ngày"}


def kl_gon(x):
    """Khối lượng ngắn gọn cho nhãn trục: 950 -> '950', 150.000 -> '150K', 1.250.000 -> '1,3M'."""
    return so(x / 1e6, 1) + "M" if x >= 1e6 else (so(x / 1e3) + "K" if x >= 1e3 else so(x))


def buoc_dep(tho):
    """Bước trục "đẹp" (1, 2, 2,5, 5 × 10^n) nhỏ nhất ≥ tho."""
    mu = 10 ** math.floor(math.log10(tho))
    return next(b * mu for b in (1, 2, 2.5, 5, 10) if b * mu >= tho)


MAX_NHAN_NGAY = 10  # trục ngang: tối đa bấy nhiêu nhãn ngày (D1 30 nến mà ghi đủ 30 ngày thì chồng chữ)


def bieu_do_nen(gio, nen, ten, khung="h4", don_vi="đ", so_le=0, he_so_nhan=1):
    """SVG nến khung `khung` (h1 | h4 | d1; xanh tăng, đỏ giảm) + cột khối lượng cùng màu theo trục `gio`; mốc không có trong `nen` (không khớp) để trống.
    Đường đứt + nhãn bên phải: giá đóng cửa nến cuối. Thanh dọc theo chuột/ngón tay (như TradingView, JS ở đầu trang) và dòng
    thông số của nến đang trỏ: thời điểm, mở/cao/thấp/đóng, % so với đóng cửa nến trước, KL (mặc định là nến cuối).
    Kèm dòng tóm tắt (đóng cuối, thay đổi cả khoảng, cao/thấp) và bảng dữ liệu cho người không xem được hình."""
    co = [nen[g] for g in gio if g in nen]
    if not co:
        return f"<p>{ESC(ten)}: không có giao dịch trong khoảng này.</p>"
    R, TRAI, PHAI, TREN = 900, 56, 76, 10  # PHAI chừa chỗ nhãn giá cuối
    day_nen, day_kl = TREN + NEN_CAO, TREN + NEN_CAO + 24 + KL_CAO
    C = day_kl + 4
    thap, cao = min(n[2] for n in co), max(n[1] for n in co)
    le = (cao - thap) * 0.06 or 1
    thap, cao = thap - le, cao + le
    rong = (R - TRAI - PHAI) / len(gio)
    x = lambda i: TRAI + (i + 0.5) * rong
    y = lambda v: TREN + (cao - v) * NEN_CAO / (cao - thap)
    # trục KL: 2 vạch "đẹp", đỉnh trục là vạch trên cùng nên chiều cao cột đọc được bằng vạch
    buoc_kl = buoc_dep((max(n[4] for n in co) or 1) / 2)
    kl_max = math.ceil((max(n[4] for n in co) or 1) / buoc_kl) * buoc_kl
    buoi = lambda g: {"h1": g[11:16], "h4": "buổi " + ("sáng" if g[11:16] < "13:00" else "chiều"), "d1": ""}[khung]
    dau_phien = [i for i, g in enumerate(gio) if i == 0 or g[:10] != gio[i - 1][:10]]
    co_nhan = set(dau_phien[:: math.ceil(len(dau_phien) / MAX_NHAN_NGAY)])
    phan, chu_giai, dong_truoc = [], [], None
    buoc = buoc_dep((cao - thap) / 4)
    v = math.ceil(thap / buoc) * buoc
    while v <= cao:
        phan.append(
            f'<line class="luoi-ngang" x1="{TRAI}" x2="{R - PHAI}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
            f'<text class="nhan-truc" x="{TRAI - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{so(v)}</text>'
        )
        v += buoc
    phan.append(f'<line class="truc" x1="{TRAI}" x2="{R - PHAI}" y1="{day_nen + 24:.1f}" y2="{day_nen + 24:.1f}"/>')
    for k in (buoc_kl, kl_max):
        yk = day_kl - k / kl_max * KL_CAO
        phan.append(
            f'<line class="luoi-ngang" x1="{TRAI}" x2="{R - PHAI}" y1="{yk:.1f}" y2="{yk:.1f}"/>'
            f'<text class="nhan-truc" x="{TRAI - 8}" y="{yk + 4:.1f}" text-anchor="end">{kl_gon(k)}</text>'
        )
    for i, g in enumerate(gio):
        if i in co_nhan:  # vạch mờ + nhãn ngày, thưa bớt khi nhiều ngày
            xg = TRAI + i * rong
            phan.append(
                f'<line class="vach-phien" x1="{xg:.1f}" x2="{xg:.1f}" y1="{TREN}" y2="{day_kl}"/>'
                f'<text class="nhan-truc" x="{xg + 3:.1f}" y="{day_nen + 16}">{g[8:10]}/{g[5:7]}</text>'
            )
        nhan = f"{g[8:10]}/{g[5:7]}{' ' + buoi(g) if buoi(g) else ''}"
        an = "" if i == len(gio) - 1 else " hidden"
        if g not in nen:
            chu_giai.append(f'<span data-i="{i}"{an}><b>{nhan}</b> không khớp lệnh</span>')
            continue
        o, h, l, c, kl = nen[g]
        doi = c / (dong_truoc or o) - 1
        lop_doi = "gia-tang" if doi > 0 else ("gia-giam" if doi < 0 else "")
        chu_giai.append(
            f'<span data-i="{i}"{an}><b>{nhan}</b> Mở <b>{so(o, so_le)}</b> Cao <b>{so(h, so_le)}</b> Thấp <b>{so(l, so_le)}</b> '
            f'Đóng <b class="{lop_doi}">{so(c, so_le)}</b> <span class="{lop_doi}">{so(doi * 100, 1, True)}%</span> KL <b>{so(kl)}</b>'
            + (
                " · <i>khớp lẻ dưới 5 triệu đồng, giá không đáng tin</i>"
                if c * kl * he_so_nhan < cw_scanner.GIA_TRI_KHOP_TOI_THIEU
                else ""
            )
            + "</span>"
        )
        dong_truoc = c
        lop = "tang" if c >= o else "giam"
        tren, duoi = y(max(o, c)), y(min(o, c))
        le = c * kl * he_so_nhan < cw_scanner.GIA_TRI_KHOP_TOI_THIEU  # khớp lẻ: giá không đáng tin, vẽ mờ
        lop_le = ' class="nen-le"' if le else ""
        phan.append(
            f"<g{lop_le}>"
            f'<line class="nen-{lop}" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{y(h):.1f}" y2="{y(l):.1f}"/>'
            f'<rect class="nen-{lop}" x="{x(i) - rong * 0.35:.1f}" y="{tren:.1f}" height="{max(duoi - tren, 1):.1f}" '
            f'width="{rong * 0.7:.1f}" rx="1"/>'
            f'<rect class="kl-{lop}" x="{x(i) - rong * 0.35:.1f}" y="{day_kl - kl / kl_max * KL_CAO:.1f}" '
            f'height="{kl / kl_max * KL_CAO:.1f}" width="{rong * 0.7:.1f}"/></g>'
        )
    g_cuoi = max(g for g in gio if g in nen)
    o_dau, dong = nen[min(g for g in gio if g in nen)][0], nen[g_cuoi][3]
    lop_cuoi = "tang" if dong >= nen[g_cuoi][0] else "giam"
    phan.append(
        f'<line class="gia-cuoi" x1="{TRAI}" x2="{R - PHAI}" y1="{y(dong):.1f}" y2="{y(dong):.1f}"/>'
        f'<rect class="nen-{lop_cuoi}" x="{R - PHAI + 4}" y="{y(dong) - 10:.1f}" width="{PHAI - 6}" height="20" rx="3"/>'
        f'<text class="nhan-gia-cuoi" x="{R - PHAI / 2 + 1:.1f}" y="{y(dong) + 4:.1f}" text-anchor="middle">{so(dong, so_le)}</text>'
    )
    kl_cuoi = nen[g_cuoi][4]
    phan.append(
        f'<rect class="kl-{lop_cuoi}-dam" x="{R - PHAI + 4}" y="{day_kl - kl_cuoi / kl_max * KL_CAO - 10:.1f}" width="{PHAI - 6}" '
        f'height="20" rx="3"/><text class="nhan-gia-cuoi" x="{R - PHAI / 2 + 1:.1f}" '
        f'y="{day_kl - kl_cuoi / kl_max * KL_CAO + 4:.1f}" text-anchor="middle">{kl_gon(kl_cuoi)}</text>'
    )
    thay_doi = dong / o_dau - 1 if o_dau else 0.0
    tom_tat = (
        f'<p class="tom-nen">Đóng cuối <b>{so(dong, so_le)} {don_vi}</b> · <b class="{"gia-tang" if thay_doi >= 0 else "gia-giam"}">'
        f"{so(thay_doi * 100, 1, True)}%</b> trong {len(gio)} nến · KL nến cuối {so(kl_cuoi)} · cao nhất {so(max(n[1] for n in co))} · thấp nhất {so(min(n[2] for n in co))}</p>"
    )
    mo_ta = (
        f"{ten}: nến {TEN_KHUNG[khung]} từ {gio[0][:10]} đến {gio[-1][:10]}, {len(co)} nến có khớp lệnh, đóng cuối {so(dong, so_le)} {don_vi}, "
        f"thấp nhất {so(min(n[2] for n in co))} đ, cao nhất {so(max(n[1] for n in co))} đ"
    )
    dong_bang = "".join(
        f"<tr><td>{g[8:10]}/{g[5:7]} {buoi(g)}</td>"
        + "".join(f'<td class="so">{so(x, so_le if j < 4 else 0)}</td>' for j, x in enumerate(nen[g]))
        + "</tr>"
        for g in reversed(gio)
        if g in nen
    )
    return (
        f'{tom_tat}<div class="cuon-bieu-do nen-tuong-tac" data-x0="{TRAI}" data-rong="{rong:.3f}" data-r="{R}" data-c="{C}" '
        f'data-tren="{TREN}" data-nen-cao="{NEN_CAO}" data-gia-cao="{round(cao, 6):g}" data-gia-thap="{round(thap, 6):g}" '
        f'data-so-le="{so_le}" data-don-vi="{ESC(don_vi)}">'
        f'<div class="nen-chu-giai">{"".join(chu_giai)}</div>'
        f'<svg class="bieu-do-nen" viewBox="0 0 {R} {C}" tabindex="0" role="img" '
        f'aria-label="{ESC(mo_ta)}. Dùng phím mũi tên để xem từng nến.">{"".join(phan)}'
        f'<g class="thuoc-do" visibility="hidden"><rect class="vung-do"/><line class="duong-do"/><text class="chu-do"/></g>'
        f'<line class="vach-doc" x1="0" x2="0" y1="{TREN}" y2="{day_kl}" visibility="hidden"/>'
        f'<line class="vach-ngang" x1="{TRAI}" x2="{R - PHAI}" y1="0" y2="0" visibility="hidden"/>'
        f'<g class="nhan-con-tro" visibility="hidden"><rect x="{R - PHAI + 4}" y="0" width="{PHAI - 6}" height="20" rx="3"/>'
        f'<text x="{R - PHAI / 2 + 1:.1f}" y="0" text-anchor="middle"></text></g></svg></div>'
        f'<details style="margin-top:8px"><summary>Xem dữ liệu {ESC(ten)} dạng bảng</summary><div class="cuon cao">'
        '<table><thead><tr><th>Thời điểm</th><th class="so">Mở</th><th class="so">Cao</th><th class="so">Thấp</th><th class="so">Đóng</th>'
        f'<th class="so">KL</th></tr></thead><tbody>{dong_bang}</tbody></table></div></details>'
    )


# ============ ĐỘ SÂU THỊ TRƯỜNG, KHỚP LỆNH ============
DO_SAU_CAO = 150  # chiều cao vùng cột của biểu đồ độ sâu


def do_sau_thi_truong(so_lenh, so_le=0):
    """Bảng 3 mức giá mua/bán, dư mua/dư bán + thanh tỷ lệ, và biểu đồ bậc độ sâu (KL cộng dồn từ giá tốt nhất ra ngoài:
    cột cao nhất mỗi bên là tổng chờ ở 3 mức; bậc nhảy lớn = nơi có "tường")."""
    mua, ban = muc_so_lenh(so_lenh)
    if not mua and not ban:
        return '<p class="phu">Chưa có sổ lệnh.</p>'
    du_mua, du_ban = sum(kl for _, kl in mua), sum(kl for _, kl in ban)
    hang = "".join(
        "<tr>"
        + (
            f'<td class="so">{so(mua[i][1])}</td><td class="so gia-tang">{so(mua[i][0], so_le)}</td>'
            if i < len(mua)
            else "<td></td><td></td>"
        )
        + (
            f'<td class="so gia-giam">{so(ban[i][0], so_le)}</td><td class="so">{so(ban[i][1])}</td>'
            if i < len(ban)
            else "<td></td><td></td>"
        )
        + "</tr>"
        for i in range(max(len(mua), len(ban)))
    )
    # biểu đồ bậc: trục ngang là các mức giá tăng dần (mua xa nhất ... mua tốt nhất | bán tốt nhất ... bán xa nhất)
    cot = [(g, sum(k for _, k in mua[: i + 1]), "mua") for i, (g, _) in enumerate(mua)][::-1] + [
        (g, sum(k for _, k in ban[: i + 1]), "ban") for i, (g, _) in enumerate(ban)
    ]
    R, TREN, rong = 320, 6, 320 / len(cot)
    cao_max = max(c for _, c, _ in cot) or 1
    hinh = "".join(
        f'<rect class="cot-{b}" x="{i * rong:.1f}" y="{TREN + DO_SAU_CAO - c / cao_max * DO_SAU_CAO:.1f}" width="{rong:.1f}" '
        f'height="{c / cao_max * DO_SAU_CAO:.1f}"><title>{"Mua" if b == "mua" else "Bán"} {so(g, so_le)}: cộng dồn {so(c)}</title></rect>'
        f'<text class="nhan-truc" x="{(i + 0.5) * rong:.1f}" y="{TREN + DO_SAU_CAO + 14}" text-anchor="middle">{so(g, so_le)}</text>'
        for i, (g, c, b) in enumerate(cot)
    )
    ty_le = du_mua / (du_mua + du_ban) * 100 if du_mua + du_ban else 50
    return (
        '<table><thead><tr><th class="so">KL</th><th class="so">Giá mua</th><th class="so">Giá bán</th><th class="so">KL</th></tr></thead>'
        f"<tbody>{hang}</tbody></table>"
        f'<div class="ti-le" aria-hidden="true"><span style="width:{ty_le:.1f}%"></span></div>'
        f'<div class="du"><span>Dư mua: {so(du_mua)}</span><span>Dư bán: {so(du_ban)}</span></div>'
        f'<svg viewBox="0 0 {R} {TREN + DO_SAU_CAO + 20}" role="img" aria-label="Độ sâu: dư mua {so(du_mua)}, dư bán {so(du_ban)}">{hinh}</svg>'
    )


def dong_khop_lenh(df, ref, he_so):
    """DataFrame intraday vnstock (cũ -> mới, giá nghìn đồng) -> [(giờ, KL, giá đ, +/− đ, +/−%, M|B|"")] mới nhất trước.
    +/− so với giá tham chiếu `ref` (đ). M = mua chủ động (Buy), B = bán chủ động (Sell), còn lại (ATO/ATC) để trống."""
    mb = {"Buy": "M", "Sell": "B"}
    return [
        (
            f"{t:%H:%M:%S}",
            int(v),
            float(g) * he_so,
            float(g) * he_so - ref,
            (float(g) * he_so - ref) / ref if ref else 0.0,
            mb.get(m, ""),
        )
        for t, g, v, m in zip(df["time"], df["price"], df["volume"], df["match_type"])
    ][::-1]


def bang_khop_lenh(dong, kl_phien, so_le=0, nhan=1):
    """Bảng khớp lệnh kiểu bảng điện: giá xanh/đỏ/vàng theo tham chiếu; dòng tổng KL phiên, M/B cộng trên các lệnh đang hiện.
    nhan: đồng cho 1 đơn vị giá (HĐ tương lai: 100.000 đ/điểm) để xét khớp lẻ theo giá trị."""
    if not dong:
        return '<p class="phu">Chưa có lệnh khớp.</p>'
    lop = lambda c: "gia-tang" if c > 0 else ("gia-giam" if c < 0 else "gia-dung")
    le = lambda g, kl: ' class="khop-le"' if g * kl * nhan < cw_scanner.GIA_TRI_KHOP_TOI_THIEU else ""  # khớp lẻ: vẽ mờ
    hang = "".join(
        f'<tr{le(g, kl)}><td>{gio}</td><td class="so">{so(kl)}</td><td class="so {lop(c)}">{so(g, so_le)}</td><td class="so {lop(c)}">{so(c, so_le, True)}</td>'
        f'<td class="so {lop(c)}">{so(pt * 100, 1, True)}</td><td class="{"gia-tang" if m == "M" else "gia-giam"}">{m}</td></tr>'
        for gio, kl, g, c, pt, m in dong
    )
    m, b = sum(d[1] for d in dong if d[5] == "M"), sum(d[1] for d in dong if d[5] == "B")
    return (
        f'<div class="du"><span>KL: {so(kl_phien)}</span><span class="gia-tang">M: {so(m)}</span><span class="gia-giam">B: {so(b)}</span></div>'
        f'<p class="phu" style="margin:2px 0 4px">M/B cộng trên {len(dong)} lệnh gần nhất</p>'
        '<div class="khop-cuon"><table><thead><tr><th>Thời gian</th><th class="so">KL</th><th class="so">Giá</th><th class="so">+/−</th>'
        f'<th class="so">%</th><th>M/B</th></tr></thead><tbody>{hang}</tbody></table></div>'
    )


# ============ MỤC NẾN DÙNG CHUNG (trang CW và trang ETF) ============
SO_NEN = 50  # trang chi tiết: 50 nến gần nhất mỗi khung H1 / H4 / D1 của CW và CS (người dùng chọn 30/10/2026)
SO_NGAY_NEN_1H = 45  # ngày lịch nến 1 giờ cần tải để đủ 50 nến H4 (25 phiên); thử 30/10/2026: 45 ngày -> 34 phiên
SO_NGAY_NEN_D1 = 80  # ngày lịch nến ngày cần tải để đủ 50 phiên (cuối tuần, nghỉ lễ); thử: 80 ngày -> 56 phiên
KHUNG_MAC_DINH = "h4"
GIAY_NHO_NEN = 300  # nến đã tải dùng lại trong 5 phút
SO_LENH_KHOP = 100  # bảng khớp lệnh: số lệnh gần nhất


def nen_cac_khung(ma, gia_hien_tai, chi_so=None):
    """{'h1', 'h4', 'd1': nến (giá đồng / điểm)} của 1 mã: H1 và D1 từ vnstock (2 lượt gọi), H4 gộp từ H1; nhớ GIAY_NHO_NEN giây.
    Đơn vị (vnstock trả nghìn đồng; chỉ số, HĐ tương lai chia 1.000) suy từ giá hiện tại. chi_so = tên trong vnstock (vd VNMIDCAP):
    lấy floating=6, vì mặc định làm tròn 2 số lẻ sau khi chia 1.000 làm sai giá (VN30 1.892,98 -> 1,89)."""
    luc, nen = BO_NHO_NEN.get(ma, (0.0, None))
    if nen is None or time.time() - luc > GIAY_NHO_NEN:
        doc = lambda df: nen_tu_df(
            df, 10 ** round(math.log10(gia_hien_tai / float(df["close"].iloc[-1]))) if len(df) else 1
        )
        them = {"floating": 6} if chi_so else {}
        ten = chi_so or ma
        h1 = doc(cw_scanner.lay_gia_dong_cua(ten, SO_NGAY_NEN_1H, cw_scanner.NGUON_GIA_CW, interval="1H", **them))
        d1 = doc(cw_scanner.lay_gia_dong_cua(ten, SO_NGAY_NEN_D1, cw_scanner.NGUON_GIA_CW, **them))
        nen = {"h1": h1, "h4": nen_h4(h1), "d1": d1}
        BO_NHO_NEN[ma] = (time.time(), nen)
    return nen


def khop_lenh(ma, ref, gia_hien_tai):
    """SO_LENH_KHOP lệnh khớp gần nhất (vnstock intraday, không nhớ tạm để luôn là số mới) -> dong_khop_lenh."""
    df = cw_scanner.Quote(source=cw_scanner.NGUON_GIA_CW, symbol=ma).intraday(page_size=SO_LENH_KHOP)
    if not len(df):
        return []
    return dong_khop_lenh(df, ref, 10 ** round(math.log10(gia_hien_tai / float(df["price"].iloc[-1]))))


def hang_nen(
    ma, cac_gio, nen, bg, nhan=None
):  # bg == "chi_so": nến bằng điểm, 2 số lẻ; nhan: HĐ tương lai (điểm, 1 số lẻ)
    """1 hàng: nến (đủ 3 khung, chỉ hiện 1) | độ sâu thị trường | khớp lệnh. bg = (niêm yết, khớp lệnh, sổ lệnh) Vietcap,
    None (mất mạng) hoặc "chi_so" (chỉ số không giao dịch: không có sổ lệnh, khớp lệnh)."""
    if bg == "chi_so":
        do_sau = khop_html = '<p class="phu">Chỉ số không giao dịch trực tiếp nên không có sổ lệnh, khớp lệnh.</p>'
    elif bg:
        ny, khop, so_lenh = bg
        try:
            khop_html = bang_khop_lenh(
                khop_lenh(ma, ny["refPrice"], cw_scanner.gia_hien_tai(ny, khop) or ny["refPrice"]),
                khop.get("accumulatedVolume") or 0,
                *((1, nhan) if nhan else ()),
            )
        # lỗi mạng / hết lượt gọi: chỉ ô này trống
        except Exception as e:  # noqa: BLE001
            khop_html = f'<p class="phu">Chưa tải được khớp lệnh ({ESC(str(e)[:100])}).</p>'
        do_sau = do_sau_thi_truong(so_lenh, 1 if nhan else 0)
    else:
        do_sau = khop_html = '<p class="phu">Không lấy được bảng giá trực tiếp.</p>'
    return (
        f'<div class="hang-nen"><div><h3 style="margin:0">{ESC(ma)}</h3>'
        + "".join(
            f'<div class="khung-nen" data-khung="{k}"{"" if k == KHUNG_MAC_DINH else " hidden"}>'
            f"{bieu_do_nen(gio, nen[k], ma, k, *(('điểm', 2) if bg == 'chi_so' else ('điểm', 1, nhan) if nhan else ()))}</div>"
            for k, gio in cac_gio.items()
        )
        + "</div>"
        f"<div><h4>Độ sâu thị trường</h4>{do_sau}</div><div><h4>Khớp lệnh</h4>{khop_html}</div></div>"
    )


def muc_nen(ma, cs, P, S, bg_cw=None, bg_cs=None, chi_so=None, nhan=None):
    """Mục nến trải hết chiều ngang: mỗi mã (CW/ETF/HĐ tương lai trên, cổ phiếu cơ sở / chỉ số dưới) 1 hàng nến | độ sâu |
    khớp lệnh; nến chung trục. chi_so = tên chỉ số trong vnstock khi `cs` là chỉ số (trang ETF, phái sinh): hàng dưới không có
    sổ lệnh. nhan = hệ số nhân khi `ma` là HĐ tương lai (giá bằng điểm: vnstock floating=6, 1 số lẻ, khớp lẻ theo giá trị).
    """
    try:
        cw, nen_cs = nen_cac_khung(ma, P, ma if nhan else None), nen_cac_khung(cs, S, chi_so)
    # lỗi mạng / hết lượt gọi: chỉ mục này trống, phần còn lại của trang vẫn dùng được
    except Exception as e:  # noqa: BLE001
        return (
            f'<section class="the"><h2>Nến: {ESC(ma)} và {ESC(cs)}</h2>'
            f"<p>Chưa tải được nến ({ESC(str(e)[:120])}). Mở lại trang sau ít phút.</p></section>"
        )
    cac_gio = {k: gio_nen_chung(cw[k], nen_cs[k], so_nen=SO_NEN) for k in TEN_KHUNG}
    nut = "".join(
        f'<button type="button" data-chon-khung="{k}" aria-pressed="{str(k == KHUNG_MAC_DINH).lower()}">{k.upper()}</button>'
        for k in TEN_KHUNG
    )
    return (
        f'<section class="the" id="nen-1h"><div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">'
        f'<div class="chon-khung" role="group" aria-label="Khung nến">{nut}</div>'
        f'<h2 style="margin:0">Nến: {ESC(ma)} và {ESC(cs)} ({SO_NEN} nến)</h2></div>'
        f'<p class="phu">Bấm H1 / H4 / D1 để đổi khung nến ({SO_NEN} nến gần nhất). H4: mỗi phiên 2 nến, buổi sáng (9:15–11:30) và buổi '
        f"chiều (13:00–14:45), gộp từ nến 1 giờ. Hai biểu đồ chung trục: cùng cột là cùng thời điểm; lúc {ESC(ma)} không khớp lệnh thì "
        "để trống. Đường đứt và nhãn bên phải là giá đóng cửa nến cuối. Cột khối lượng (KL) có vạch chia và số bên trái; "
        "nhãn bên phải là KL nến cuối; rê chuột lên nến để xem KL chính xác. "
        "Độ sâu thị trường: 3 mức giá chờ mua / chào bán (Vietcap chỉ cho 3 mức) lúc mở trang; biểu đồ bậc cộng dồn KL từ giá tốt nhất "
        "ra ngoài, bậc nhảy lớn là nơi có tường (có thể bị rút bất cứ lúc nào). Khớp lệnh: M = mua chủ động, B = bán chủ động. "
        "Tải lại trang để có số mới. Nến: vnstock (VCI), cập nhật mỗi 5 phút; giá chưa điều chỉnh cổ tức"
        + (", chỉ số tính bằng điểm" if chi_so else "")
        + ".</p>"
        f'{hang_nen(ma, cac_gio, cw, bg_cw, nhan)}{hang_nen(cs, cac_gio, nen_cs, "chi_so" if chi_so else bg_cs)}</section>'
    )
