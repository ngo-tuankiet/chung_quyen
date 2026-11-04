"""Phần dùng chung của giao diện web: CSS/JS, định dạng số, khung trang + menu, bảng CW, biểu đồ, đọc file kết quả, trạng thái lần quét."""

import html
import io
import json
import math
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import pandas as pd

import cw_scanner
import danh_muc

CONG = int(os.environ.get("PORT", "8000"))
VON_MAC_DINH = 10  # triệu đồng: số tiền mặc định ở mục "Rủi ro với số tiền của bạn"
BO_NHO_NEN: dict[str, tuple] = (
    {}
)  # mã -> (lúc tải, nến H4): trang chi tiết mở lại trong vài phút không gọi vnstock lần nữa
BO_NHO_IV: dict[tuple, dict] = {}  # (mã CW, ngày) -> [[ngày, IV %]]: lịch sử giá CW chỉ tải 1 lần mỗi ngày
# nút 🔄 Quét đầu mỗi tab (đường dẫn menu -> loại quét, tên, giải thích khi rê chuột); trang Cảnh báo quét tất cả. Các bước: web.VIEC_QUET
NUT_QUET = {
    "/canh-bao": (
        "tat-ca",
        "tất cả",
        "Quét chứng quyền rồi ETF, lấy lại giá phái sinh và giá trên trang này (2–4 phút)",
    ),
    "/": ("cw", "chứng quyền", "Quét lại toàn bộ chứng quyền (1–3 phút)"),
    "/etf": ("etf", "ETF", "Quét lại các quỹ ETF, không gửi Discord (khoảng 30 giây)"),
    "/phai-sinh": ("phai-sinh", "giá phái sinh", "Lấy giá hợp đồng tương lai mới ngay, không chờ hết 5 phút nhớ tạm"),
    "/danh-muc": (
        "danh-muc",
        "giá danh mục",
        "Lấy lại giá trực tiếp; IV, giá hợp lý vẫn theo lần quét chứng quyền gần nhất",
    ),
}
GIAY_TAI_LAI = 5  # màn hình chờ lúc đang quét tự tải lại sau ngần này giây
GIAY_HOI_CANH_BAO = 60  # mọi trang đang mở hỏi /canh-bao/tin ngần này giây 1 lần (nhiều tab: chỉ 1 tab hỏi)
SO_THONG_BAO_TOI_DA = 5  # mỗi lượt hiện tối đa ngần này thông báo hệ thống (còn lại xem trong khung đỏ trên trang)
# lần quét gần nhất (chỉ 1 người dùng trên máy mình nên dùng biến toàn cục là đủ); tab: trang hiện kết quả
QUET = {
    "dang": False,
    "loai": "",
    "tab": "",
    "buoc": "",
    "bat_dau": None,
    "xong": None,
    "loi": "",
    "nhat_ky": io.StringIO(),
}
LOI_DANH_MUC = ""  # lỗi của lần thêm/xóa lệnh gần nhất (hiện 1 lần ở trang Danh mục)
ESC = html.escape
# kết luận -> (lớp màu, biểu tượng, nhãn). Màu luôn đi kèm biểu tượng + chữ, không dùng màu một mình
KET_LUAN = {
    "NÊN XEM XÉT": ("tot", "✓", "Nên xem xét"),
    "THEO DÕI": ("canh-bao", "!", "Theo dõi"),
    "BỎ QUA": ("bo-qua", "✕", "Bỏ qua"),
}
# Các cột của bảng danh sách: (tiêu đề, căn lề, giải thích cho người mới - hiện khi rê chuột lên tiêu đề và ở trang Hướng dẫn)
GIAI_THICH_LECH = "Giá CW thực tế so với giá “lẽ ra” nếu CW giữ nguyên mức IV của ngày mốc và chỉ chạy theo giá cổ phiếu cơ sở (đã gồm đòn bẩy và mất giá theo thời gian), qua 20 phiên gần nhất. Âm: CW không theo kịp cổ phiếu; dương: CW chạy nhanh hơn, dễ bị kéo về. Trong khoảng ±15% là bình thường. Âm sâu mà đường lệch đi ngang thường là tổ chức phát hành đã hạ IV một lần (trang của từng CW ghi IV ngày mốc → phiên gần nhất). Chi tiết và biểu đồ ở trang của từng CW."
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
        (
            "Cổ phiếu tăng (hoặc giảm) 1% thì CW tăng (hoặc giảm) khoảng bấy nhiêu % (giữ IV của giá mua; không giải được IV thì "
            "theo biến động lịch sử). Đòn bẩy cao: lãi nhanh nhưng lỗ cũng nhanh."
        ),
    ),
    (
        "Delta",
        "so",
        (
            "Từ 0 đến 1: cổ phiếu tăng 1 đ thì giá trị quyền trên 1 cổ phiếu tăng bấy nhiêu đ (tính ở IV của giá mua). Gần 1: CW bám "
            "sát cổ phiếu; gần 0: gần như không phản ứng."
        ),
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

# CSS (màu theo bảng màu đã kiểm định cho người mù màu, sáng/tối) và JS viết ở file riêng trong giao_dien/ để có tô màu cú pháp,
# kiểm được; đọc 1 lần lúc chạy rồi nhúng vào mọi trang như trước (không thêm đường dẫn file tĩnh nào cho máy chủ)
THU_MUC_GIAO_DIEN = Path(__file__).parent / "giao_dien"
CSS = (THU_MUC_GIAO_DIEN / "trang.css").read_text(encoding="utf-8")
JS = (THU_MUC_GIAO_DIEN / "trang.js").read_text(encoding="utf-8")


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
    # trang Cảnh báo giá (31/10/2026): giá lệch bất thường đang mua được + mức giá tự đặt
    ("/canh-bao", "🔔", "Cảnh báo"),
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


def thoi_luong(giay):
    """125 -> '2 phút 5 giây', 35 -> '35 giây'."""
    phut, giay = divmod(int(giay), 60)
    return f"{phut} phút {giay} giây" if phut else f"{giay} giây"


def muc_quet(duong_dan):
    """Nút 🔄 Quét của tab + kết quả lần quét gần nhất bấm từ tab này (đầu trang); tab không có loại quét -> ""."""
    if duong_dan not in NUT_QUET or QUET["dang"]:
        return ""
    loai, _, giai_thich = NUT_QUET[duong_dan]
    phan = [
        (
            '<form class="nut-quet" method="post" action="/quet" onsubmit="this.nut.disabled = true;">'
            f'<input type="hidden" name="loai" value="{loai}"><button class="nut" name="nut" title="{ESC(giai_thich)}">'
            f'🔄 Quét{" tất cả" if loai == "tat-ca" else ""}</button></form>'
        )
    ]
    q = QUET
    if q["tab"] == duong_dan and q["xong"]:
        ten, luc = (
            NUT_QUET[duong_dan][1],
            f'{q["xong"]:%H:%M} ({thoi_luong((q["xong"] - q["bat_dau"]).total_seconds())})',
        )
        nhat_ky = q["nhat_ky"].getvalue()
        canh_bao = nhat_ky.count("[!]")
        # 1 dòng kết quả, bấm mở nhật ký; chỉ tự mở khi có lỗi (để không đẩy nội dung trang xuống)
        phan.append(
            f'<p class="phu ket-qua-quet" role="status">✓ Quét {ten} xong lúc {luc}.</p>'
            if not (nhat_ky or q["loi"])  # phái sinh, danh mục: chỉ bỏ giá đã nhớ, không có nhật ký
            else f'<details class="ket-qua-quet"{" open" if q["loi"] else ""}>'
            + (
                f'<summary class="loi" role="alert">Quét {ten} lúc {luc} có lỗi: {ESC(q["loi"])}</summary>'
                if q["loi"]
                else f'<summary class="phu" role="status">✓ Quét {ten} xong lúc {luc}'
                + (f" · {canh_bao} dòng cảnh báo [!]" if canh_bao else "")
                + " · xem nhật ký</summary>"
            )
            + f"<pre>{ESC(nhat_ky or '(không có dòng nào)')}</pre></details>"
        )
    return "".join(phan)


def trang_cho():
    """Màn hình chờ lúc đang quét (thay cho mọi trang, để không đọc file kết quả đang ghi dở): bước đang chạy + nhật ký, tự tải lại."""
    q = QUET
    nhat_ky = "\n".join(q["nhat_ky"].getvalue().splitlines()[-30:])
    than = (
        f'<section class="the" role="status"><h1>⏳ Đang quét {ESC(q["buoc"] or NUT_QUET.get(q["tab"], ("", ""))[1])}</h1>'
        f'<p>Bắt đầu lúc {q["bat_dau"]:%H:%M:%S}, đã chạy {thoi_luong((datetime.now() - q["bat_dau"]).total_seconds())}. '
        f"Trang tự tải lại mỗi {GIAY_TAI_LAI} giây; quét xong sẽ hiện dữ liệu mới.</p>"
        + (f"<pre>{ESC(nhat_ky)}</pre>" if nhat_ky else "")
        + f"</section><script>setTimeout(() => location.reload(), {GIAY_TAI_LAI * 1000});</script>"
    )
    return trang("Đang quét…", than, q["tab"])


def trang(tieu_de, than, duong_dan=""):
    """Khung chung của mọi trang: thanh điều hướng trên cùng + nút 🔄 Quét của tab + nội dung + lưu ý cuối trang.
    Ghi chú dài thu vào "ℹ Giải thích", trừ trang Hướng dẫn (trang để đọc)."""
    if duong_dan != "/huong-dan":
        than = thu_gon_giai_thich(than)
    than = muc_quet(duong_dan) + than
    menu = "".join(
        f'<a href="{dd}"{" aria-current=page" if dd == duong_dan else ""}><span class="bt" aria-hidden="true">{bt}</span>'
        f"<span>{ten}</span></a>"
        for dd, bt, ten in MENU
    ) + (
        f'<button type="button" id="nut-bao" class="nut-bao" data-giay="{GIAY_HOI_CANH_BAO}" data-toi-da="{SO_THONG_BAO_TOI_DA}" '
        'title="Kêu + thông báo khi có cảnh báo mới (trong giờ khớp lệnh, khi còn mở ít nhất 1 trang cw_scanner). '
        'Bấm để bật/tắt và nghe thử."><span class="bt" aria-hidden="true">🔊</span><span class="chu">Báo: bật</span></button>'
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
    buoc = buoc_dep((cao - thap) / 4)  # vạch trục tung tròn số: bước 1/2/2,5/5 x 10^n
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
        for t, o, h, l, c, v in zip(
            df["time"], df["open"], df["high"], df["low"], df["close"], df["volume"], strict=True
        )
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
        for t, g, v, m in zip(df["time"], df["price"], df["volume"], df["match_type"], strict=True)
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
            df, cw_scanner.he_so_don_vi(gia_hien_tai, float(df["close"].iloc[-1])) if len(df) else 1
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
    return dong_khop_lenh(df, ref, cw_scanner.he_so_don_vi(gia_hien_tai, float(df["price"].iloc[-1])))


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
                # mã trên bảng giá: HĐ tương lai là mã KRX (bí danh VN30F1M không có lệnh khớp)
                khop_lenh(ny["symbol"], ny["refPrice"], cw_scanner.gia_hien_tai(ny, khop) or ny["refPrice"]),
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
