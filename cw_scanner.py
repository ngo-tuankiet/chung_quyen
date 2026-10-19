"""
cw_scanner.py - Quét và định giá chứng quyền (CW) bằng Black-Scholes.

Cách chạy:   python cw_scanner.py        (hoặc giao diện web: python web.py)
API key:     điền vào file .env:  VNSTOCK_API_KEY=khoa_cua_ban
Kết quả:     in bảng tóm tắt ra màn hình và lưu file ket_qua/cw_YYYY-MM-DD.csv (mở bằng Excel).

Các bước (xem KE_HOACH.md để hiểu chi tiết):
  1. Lấy danh sách tất cả CW đang giao dịch (vnstock).
  2. Lấy điều khoản + giá của từng CW và cổ phiếu cơ sở (bảng giá VCI).
  3. Đo độ biến động lịch sử của cổ phiếu cơ sở (vnstock).
  4. Tính giá hợp lý bằng Black-Scholes.
  5. Chấm điểm theo 4 tiêu chí -> NÊN XEM XÉT / THEO DÕI / BỎ QUA.
  6. Đánh dấu CW mới phát hành (chưa thấy ở lần chạy trước) và lưu kết quả.
"""

import gzip
import importlib.metadata
import json
import math
import random
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from vnstock import Listing, Quote, login

# ============ CẤU HÌNH: chỉnh các con số dưới đây theo khẩu vị của bạn ============
LAI_SUAT_PHI_RUI_RO = 0.04  # r: lợi suất TPCP / lãi tiết kiệm 12 tháng (%/năm). Nên cập nhật định kỳ.
SO_PHIEN_DO_BIEN_DONG = 250  # số phiên dùng để đo biến động (~1 năm giao dịch)
SO_PHIEN_MOT_NAM = 250  # hệ số năm hóa biến động: ~250 phiên giao dịch/năm ở Việt Nam

# 4 tiêu chí "có thể đầu tư"
MIN_NGAY_CON_LAI = 60  # CW mất giá trị thời gian rất nhanh khi gần đáo hạn
# IV không cao hơn biến động lịch sử quá 3 điểm %. Dùng IV thay cho "% đắt hơn giá hợp lý" vì cùng đắt 10% về giá,
# CW ngoài tiền chỉ ≈ +1,6 điểm IV còn CW sâu trong tiền tới ≈ +14 điểm; +3 điểm ≈ đắt 10% ở CW quanh tiền (KE_HOACH Phần 4)
MAX_IV_TRU_HV = 0.03
# Cảnh báo (không đổi kết luận) khi IV < 50% trung vị IV các CW khác cùng mã CS (cần ≥ 3 CW để so). Ngày 18/10/2026:
# 99% CW có tỷ số ≥ 0,6, chỉ CVPB2608 (ACBS) là 0,12 - giá do tổ chức phát hành tự bán ra, không phải món hời chắc chắn
MIN_IV_SO_VOI_CUNG_MA = 0.5
MIN_SO_CW_CUNG_MA = 3

# Chi phí khi mua/bán (chỉ dùng cho phần "rủi ro theo tiền thật" ở trang chi tiết, không đổi 4 tiêu chí).
# Phí tùy công ty chứng khoán; thuế TNCN 0,1% khi bán và (giả định) khi nhận tiền thanh toán đáo hạn - kiểm tra với CTCK của bạn
PHI_GIAO_DICH = 0.0015
THUE_BAN = 0.001
MAX_TANG_DE_HOA_VON = 0.15  # cổ phiếu cơ sở chỉ cần tăng tối đa 15% là hòa vốn lúc đáo hạn
MIN_KHOI_LUONG = 10_000  # khối lượng khớp trong phiên >= 10.000 CW (dễ mua, dễ bán)
KET_LUAN = ["NÊN XEM XÉT", "THEO DÕI", "BỎ QUA"]  # trượt 0 / 1 / từ 2 tiêu chí trở lên

THU_MUC = Path(
    __file__
).parent  # dùng đường dẫn tuyệt đối để chạy tự động (launchd/cron/Task Scheduler) không bị lạc thư mục
FILE_CW_DA_BIET = THU_MUC / "cw_da_biet.txt"
THU_MUC_KET_QUA = THU_MUC / "ket_qua"

# vnstock bỏ các cột giá thực hiện / tỷ lệ chuyển đổi / ngày đáo hạn khỏi price_board,
# nên ta gọi thẳng API bảng giá VCI (chính API mà vnstock dùng bên trong).
URL_BANG_GIA = "https://trading.vietcap.com.vn/api/price/symbols/getList"
HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn",
    "User-Agent": "Mozilla/5.0",
}
# HOSE > Niêm yết mới > "DS CW được chấp thuận chính thức" (API mà trang hsx.vn dùng; số 1 sau v1 = tiếng Việt)
URL_HOSE_CW_MOI = "https://api.hsx.vn/l/api/v1/1/securities?pageIndex=1&pageSize=200&newListingStatusId=1"
HEADERS_HOSE = {"Referer": "https://www.hsx.vn/", "Origin": "https://www.hsx.vn", "User-Agent": "Mozilla/5.0"}


# ============ PHẦN 1: CÔNG THỨC ============
def phan_phoi_chuan(x):
    """N(x): xác suất một biến chuẩn tắc nhỏ hơn x."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def black_scholes_call(S, K, T, r, sigma):
    """Giá quyền chọn mua kiểu châu Âu cho 1 cổ phiếu. Trả về (giá, delta)."""
    if T <= 0 or sigma <= 0:  # hết hạn: chỉ còn giá trị nội tại
        return max(S - K, 0.0), float(S > K)
    d1 = (math.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    gia = S * phan_phoi_chuan(d1) - K * math.exp(-r * T) * phan_phoi_chuan(d2)
    return gia, phan_phoi_chuan(d1)


def bien_dong_ngam_dinh(gia_cw, S, K, T, r, ty_le):
    """Mức biến động mà giá CW trên thị trường đang 'ngầm định' (giải ngược Black-Scholes). None nếu không giải được."""
    muc_tieu, thap, cao = gia_cw * ty_le, 0.001, 5.0
    if not black_scholes_call(S, K, T, r, thap)[0] <= muc_tieu <= black_scholes_call(S, K, T, r, cao)[0]:
        return None  # giá CW thấp hơn giá trị nội tại hoặc cao vô lý
    for _ in range(60):  # chia đôi khoảng: giá quyền chọn luôn tăng khi sigma tăng
        giua = (thap + cao) / 2
        thap, cao = (giua, cao) if black_scholes_call(S, K, T, r, giua)[0] < muc_tieu else (thap, giua)
    return (thap + cao) / 2


def can_duoi(S, K, T, r):
    """Giá tối thiểu của quyền chọn mua châu Âu (không cổ tức) cho 1 cổ phiếu: max(S − K·e^(−rT), 0).
    Giá CW × tỷ lệ thấp hơn mức này thì không có mức biến động nào khớp -> không giải được biến động ngầm định."""
    return max(S - K * math.exp(-r * max(T, 0)), 0.0)


def mo_phong_gia(S, K, T, r, sigma, so_kich_ban=20000):
    """Kiểm chứng Black-Scholes bằng cách thử thật: tạo nhiều kịch bản giá cổ phiếu lúc đáo hạn,
    lấy trung bình số tiền quyền chọn trả, quy về tiền hôm nay. Kết quả gần bằng công thức."""
    ngau_nhien = random.Random(0)  # cố định để mỗi lần mở trang ra cùng một con số
    tong = sum(
        max(S * math.exp((r - sigma**2 / 2) * T + sigma * math.sqrt(T) * ngau_nhien.gauss(0, 1)) - K, 0)
        for _ in range(so_kich_ban)
    )
    return tong / so_kich_ban * math.exp(-r * T)


def doc_ty_le(chuoi):
    """'1.7245:1' -> 1.7245 (cần 1.7245 CW để đổi lấy 1 cổ phiếu)."""
    so_cw, so_cp = chuoi.split(":")
    return float(so_cw) / float(so_cp)


# ============ PHẦN 2: LẤY DỮ LIỆU ============
def doc_env(file_env=THU_MUC / ".env"):
    """Đọc file .env (mỗi dòng KHOA=gia_tri, dòng bắt đầu bằng # là ghi chú) thành dict."""
    if not file_env.exists():
        return {}
    cap = [
        d.split("=", 1)
        for d in file_env.read_text(encoding="utf-8-sig").splitlines()
        if "=" in d and not d.lstrip().startswith("#")
    ]
    return {k.strip(): v.strip().strip("\"'") for k, v in cap}


def lay_bang_gia(danh_sach_ma, cho=30):
    """Giá + điều khoản + sổ lệnh của nhiều mã trong 1 lần gọi.
    Trả về {mã: (thông tin niêm yết, thông tin khớp lệnh, sổ lệnh 3 giá mua/bán tốt nhất)}."""
    yeu_cau = urllib.request.Request(URL_BANG_GIA, data=json.dumps({"symbols": danh_sach_ma}).encode(), headers=HEADERS)
    with urllib.request.urlopen(yeu_cau, timeout=cho) as r:  # máy chủ trả lỗi (4xx/5xx) -> tự báo lỗi
        du_lieu = json.load(r)
    # mã không tồn tại / đã hủy niêm yết: Vietcap trả listingInfo rỗng -> không có trong kết quả (nơi dùng tự xử lý mã thiếu)
    return {
        x["listingInfo"]["symbol"]: (x["listingInfo"], x["matchPrice"], x.get("bidAsk") or {})
        for x in du_lieu
        if x.get("listingInfo")
    }


def doc_cw_sap_ra_mat(du_lieu):
    """Đổi dữ liệu HOSE thành danh sách CW đã được chấp thuận: [{ngày chấp thuận, tên, mã CS, K, tỷ lệ, đáo hạn, ...}]."""
    ngay = lambda ts: datetime.fromtimestamp(ts, timezone.utc).date() if ts else None  # HOSE trả ngày dạng giây Unix
    ket_qua = []
    for x in (du_lieu.get("data") or {}).get("list") or []:
        cw = x.get("listingdbSecuritiesCoveredWarrant") or {}
        ket_qua.append(
            {
                "ngay_chap_thuan": ngay(x.get("acceptDate")),
                "ten": cw.get("cwname") or x.get("name") or "",
                "ma_cs": cw.get("underlyingSymbol") or "",
                "gia_thuc_hien": cw.get("exPrice"),
                "ty_le": cw.get("exRatio") or "",
                "ngay_dao_han": ngay(cw.get("maturityDate")),
                "thoi_han_thang": cw.get("deadline"),
                "kl_niem_yet": x.get("listingVolume"),
            }
        )
    return ket_qua


def tai_du_lieu_hose_cw(cho=20, so_lan=2):
    """Dữ liệu thô "CW được chấp thuận" từ HOSE (gồm cả mã đã lên sàn/hết hạn - nơi dùng tự lọc).
    Máy chủ HOSE đôi khi chậm hoặc ngắt giữa chừng nên thử lại 1 lần."""
    yeu_cau = urllib.request.Request(
        URL_HOSE_CW_MOI, headers={**HEADERS_HOSE, "Accept-Encoding": "gzip"}
    )  # nén: nhỏ ~10 lần
    for lan in range(so_lan):
        try:
            with urllib.request.urlopen(yeu_cau, timeout=cho) as r:
                du_lieu = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    du_lieu = gzip.decompress(du_lieu)
            return json.loads(du_lieu)
        except Exception:
            if lan == so_lan - 1:
                raise


def tong_kl(so_lenh, ben):
    """Tổng khối lượng ở 3 mức giá tốt nhất của một bên sổ lệnh ('askPrices' = đang chào bán, 'bidPrices' = đang chờ mua)."""
    return sum(muc.get("volume") or 0 for muc in so_lenh.get(ben) or [])


def gia_hien_tai(niem_yet, khop_lenh, *_):
    """Giá khớp gần nhất; nếu chưa có giao dịch trong phiên thì lấy giá tham chiếu."""
    return khop_lenh["matchPrice"] or niem_yet["refPrice"]


def gia_mua(niem_yet, khop_lenh, so_lenh):
    """Giá người mua phải trả: giá chào bán thấp nhất trong sổ lệnh; sổ lệnh trống thì giá khớp, chưa khớp thì giá tham chiếu.
    Trả về (giá, nguồn)."""
    gia_ban = [m.get("price") for m in so_lenh.get("askPrices") or []]
    gia_ban = [g for g in gia_ban if isinstance(g, (int, float)) and g > 0]  # phiên ATO/ATC có thể ghi chữ thay cho giá
    if gia_ban:
        return min(gia_ban), "ask"
    if khop_lenh.get("matchPrice"):
        return khop_lenh["matchPrice"], "khớp"
    return niem_yet["refPrice"], "tham chiếu"


def lay_gia_dong_cua(ma):
    """DataFrame (time, close) giá đóng cửa ngày 1 năm qua của một mã (cổ phiếu hoặc CW) từ vnstock.
    Giá cổ phiếu đã điều chỉnh theo sự kiện quyền; đơn vị có thể là nghìn đồng."""
    hom_nay = date.today()
    # KBS: nguồn mặc định của vnstock, ổn định hơn API lịch sử của VCI. 365 ngày: mức tối đa của gói Khách.
    lay = lambda: Quote(source="KBS", symbol=ma).history(
        start=str(hom_nay - timedelta(days=365)), end=str(hom_nay), interval="1D"
    )
    try:
        return lay()
    except Exception as e:
        if getattr(e, "code", "") != "VNSTOCK_AUTH_MINUTE_LIMIT":
            raise
        print("  Hết lượt gọi vnstock trong phút này, chờ 60 giây rồi chạy tiếp...")
        time.sleep(61)
        return lay()


def lech_theo_cs(P0, S0, ngay0, P, S, ngay, K, ty_le, dao_han, r):
    """CW đi lệch bao nhiêu so với cổ phiếu cơ sở kể từ ngày mốc: lấy IV tại mốc (giá CW P0, giá CS S0), tính giá CW lẽ ra
    với giá CS và thời gian hôm nay; lệch = P / giá lẽ ra − 1 (âm: CW không theo kịp CS). Đã gồm đòn bẩy và mất giá theo thời gian.
    Giá mốc dưới mức tối thiểu (không giải được IV) thì tính bằng r = 0 cho cả hai đầu. Trả về (lệch, r đã dùng); không tính được -> (NaN, None).
    """
    T0, T = (dao_han - ngay0).days / 365, (dao_han - ngay).days / 365
    for r_dung in (r, 0.0):
        iv0 = bien_dong_ngam_dinh(P0, S0, K, T0, r_dung, ty_le)
        if iv0 is not None:
            le_ra = black_scholes_call(S, K, T, r_dung, iv0)[0] / ty_le
            return (P / le_ra - 1 if le_ra > 0 else math.nan), r_dung
    return math.nan, None


def lich_su_iv(gia_cw, gia_cs, K, ty_le, dao_han, r):
    """IV (%) từng ngày từ {ngày 'YYYY-MM-DD': giá VND} của CW và cổ phiếu cơ sở. Trả về [[ngày, IV %], ...].
    Giá CS phải là giá đã điều chỉnh quyền: khi đó dùng điều khoản HIỆN TẠI (K, tỷ lệ đã điều chỉnh) cho cả các ngày trước sự kiện
    (giá trị 1 CW không đổi khi S, K, tỷ lệ cùng nhân một hệ số). Ngày giá CW dưới mức tối thiểu ghi 0; giá cao bất thường thì bỏ.
    """
    kq = []
    for ngay in sorted(gia_cw.keys() & gia_cs.keys()):
        S, P = gia_cs[ngay], gia_cw[ngay]
        T = (dao_han - date.fromisoformat(ngay)).days / 365
        iv = bien_dong_ngam_dinh(P, S, K, T, r, ty_le)
        if iv is not None:
            kq.append([ngay, round(iv * 100, 1)])
        elif P * ty_le < can_duoi(S, K, T, r):  # rẻ hơn mọi mức biến động
            kq.append([ngay, 0.0])
    return kq


def bien_dong_lich_su(ma):
    """Trả về (sigma năm hóa, số phiên đã dùng, [[ngày, giá đóng cửa], ...]) từ giá đóng cửa ngày 1 năm của cổ phiếu cơ sở."""
    df = lay_gia_dong_cua(ma)
    loi_suat = (df["close"] / df["close"].shift(1)).apply(math.log).dropna().tail(SO_PHIEN_DO_BIEN_DONG)
    lich_su = [[str(t)[:10], float(c)] for t, c in zip(df["time"], df["close"])]
    return loi_suat.std() * math.sqrt(SO_PHIEN_MOT_NAM), len(loi_suat), lich_su


# ============ PHẦN 3: ĐÁNH GIÁ ============
def danh_gia(ngay_con_lai, iv_tru_hv, tang_de_hoa_von, khoi_luong):
    """Trả về (kết luận, lý do). Đạt cả 4 tiêu chí -> NÊN XEM XÉT, trượt 1 -> THEO DÕI, còn lại -> BỎ QUA.
    iv_tru_hv: IV − HV (0.03 = 3 điểm %); -inf = giá dưới mức tối thiểu, +inf = giá cao bất thường (không giải được IV).
    """
    loi = []
    if ngay_con_lai < MIN_NGAY_CON_LAI:
        loi.append(f"chỉ còn {ngay_con_lai} ngày")
    if iv_tru_hv > MAX_IV_TRU_HV:
        loi.append(
            f"IV cao hơn lịch sử {iv_tru_hv * 100:+.1f} điểm".replace(".", ",")
            if math.isfinite(iv_tru_hv)
            else "giá mua cao bất thường"
        )
    if tang_de_hoa_von > MAX_TANG_DE_HOA_VON:
        loi.append(f"CP cơ sở phải tăng {tang_de_hoa_von:.0%} mới hòa vốn")
    if khoi_luong < MIN_KHOI_LUONG:
        loi.append(f"ít giao dịch ({khoi_luong:,} CW)".replace(",", "."))  # số kiểu Việt Nam: 5.700
    return KET_LUAN[min(len(loi), 2)], "; ".join(loi) or "đạt cả 4 tiêu chí"


def dinh_gia(ny, kl, so_lenh, S, sigma, hom_nay, r=None):
    """Định giá + chấm điểm 1 CW từ dữ liệu bảng giá (niêm yết, khớp lệnh, sổ lệnh), giá CS và sigma.
    Trả về dict đúng tên cột CSV, để main() ghi file và trang chi tiết định giá lại theo giá trực tiếp."""
    r = LAI_SUAT_PHI_RUI_RO if r is None else r
    K = ny["exercisePrice"]  # giá thực hiện (VND)
    P = gia_hien_tai(ny, kl)  # giá khớp gần nhất của CW (VND)
    P_mua, nguon_gia = gia_mua(ny, kl, so_lenh)  # giá phải trả nếu mua ngay: dùng cho mọi chỉ số định giá bên dưới
    ty_le = doc_ty_le(ny["exerciseRatio"])
    ngay_con_lai = (datetime.strptime(ny["maturityDate"], "%Y%m%d").date() - hom_nay).days
    T = ngay_con_lai / 365

    gia_quyen_chon, delta = black_scholes_call(S, K, T, r, sigma)
    gia_hop_ly = gia_quyen_chon / ty_le  # 1 CW chỉ bằng 1/tỷ lệ của 1 quyền chọn trên 1 cổ phiếu
    chenh_lech = P_mua / gia_hop_ly - 1 if gia_hop_ly > 0 else math.inf
    tang_de_hoa_von = (K + P_mua * ty_le) / S - 1
    iv = bien_dong_ngam_dinh(P_mua, S, K, T, r, ty_le)
    duoi_toi_thieu = P_mua * ty_le < can_duoi(S, K, T, r)
    ghi_chu_iv = (
        ""
        if iv is not None
        else ("giá mua dưới mức tối thiểu S − K·e^(−rT)" if duoi_toi_thieu else "giá mua cao bất thường")
    )
    # làm tròn 0,1 điểm như cột CSV để kết luận khớp số hiển thị; không giải được IV: dưới mức tối thiểu = rẻ hơn mọi mức biến động
    iv_tru_hv = round(iv - sigma, 3) if iv is not None else (-math.inf if duoi_toi_thieu else math.inf)
    ket_luan, ly_do = danh_gia(ngay_con_lai, iv_tru_hv, tang_de_hoa_von, kl["accumulatedVolume"])
    gd_cuoi = ny.get("lastTradingDate") or ""  # dạng YYYYMMDD
    return {
        "Mã CS": ny["underlyingSymbol"],
        "TCPH": ny["issuerName"],
        "Ngày còn lại": ngay_con_lai,
        "Ngày GD cuối": (
            f"{gd_cuoi[:4]}-{gd_cuoi[4:6]}-{gd_cuoi[6:]}" if gd_cuoi else ""
        ),  # sau ngày này không bán được nữa
        "Giá CS": S,
        "Giá thực hiện": K,
        "Tỷ lệ CĐ": ty_le,
        "Giá CW": P,
        "Giá mua": P_mua,
        "Nguồn giá mua": nguon_gia,
        "Giá hợp lý": round(gia_hop_ly),
        "Đắt/rẻ %": round(chenh_lech * 100, 1),
        "CS tăng % để hòa vốn": round(tang_de_hoa_von * 100, 1),
        "Đòn bẩy": round(delta * S / (P_mua * ty_le), 1),
        "Delta": round(delta, 2),
        "Biến động %/năm": round(sigma * 100, 1),
        "IV %": round(iv * 100, 1) if iv is not None else math.nan,
        "IV − HV": (
            round(iv_tru_hv * 100, 1) if iv is not None else math.nan
        ),  # điểm %: âm = thị trường định giá thấp hơn lịch sử
        "Ghi chú IV": ghi_chu_iv,
        "KL khớp": kl["accumulatedVolume"],
        "KL niêm yết": ny.get("listedShare")
        or 0,  # tổng số CW được phép bán (nguồn miễn phí không có số nhà đầu tư đang nắm)
        "KL chào bán": tong_kl(so_lenh, "askPrices"),  # lượng có thể mua ngay ở 3 giá bán thấp nhất
        "KL chờ mua": tong_kl(so_lenh, "bidPrices"),  # lượng có thể bán ra ngay ở 3 giá mua cao nhất
        "Đánh giá": ket_luan,
        "Lý do": ly_do,
        "r %": round(r * 100, 2),  # để tự tính lại từng dòng trong Excel
    }


def so_iv_cung_ma(df, ma, cs, iv):
    """So IV (%) của 1 CW với trung vị IV các CW khác cùng mã CS trong bảng df (cột "Mã CW", "Mã CS", "IV %").
    Trả về (trung vị %, cảnh báo): trung vị NaN nếu không đủ CW để so; cảnh báo "" nếu không bất thường."""
    khac = df.loc[(df["Mã CS"] == cs) & (df["Mã CW"] != ma), "IV %"].dropna()
    if len(khac) < MIN_SO_CW_CUNG_MA:
        return math.nan, ""
    tv = khac.median()
    if math.isfinite(iv) and iv < MIN_IV_SO_VOI_CUNG_MA * tv:
        return tv, (
            f"IV {iv:.0f}% chỉ bằng {iv / tv:.0%} trung vị {tv:.0f}% của {len(khac)} CW {cs} khác: giá có thể do tổ chức "
            "phát hành tự bán ra hoặc sắp có thay đổi, không chắc là món hời - đọc thông báo của TCPH trước khi mua"
        )
    return tv, ""


def rui_ro_theo_tien(von, P, S, K, ty_le, T, r, sigma, don_bay):
    """Rủi ro khi bỏ `von` đồng mua CW ở giá P (đã tính phí mua, thuế khi nhận tiền). Trả về dict:
    số CW (lô 100), tiền chi, số cổ phiếu tương đương, giá trị cổ phiếu cơ sở đang "nắm", hòa vốn có phí,
    % CS giảm thì về 0, xác suất về 0 theo mô hình (σ lịch sử, không phải dự báo), tiền mất khi CS giảm 1% (theo đòn bẩy).
    """
    so_cw = int(von / (P * (1 + PHI_GIAO_DICH)) // 100 * 100)
    if T > 0 and sigma > 0:
        xs_ve_0 = phan_phoi_chuan(-(math.log(S / K) + (r - sigma**2 / 2) * T) / (sigma * math.sqrt(T)))  # N(−d2)
    else:
        xs_ve_0 = float(S <= K)
    return {
        "so_cw": so_cw,
        "tien_chi": so_cw * P * (1 + PHI_GIAO_DICH),
        "so_cp": so_cw / ty_le,
        "tiep_xuc": so_cw / ty_le * S,
        "hoa_von_phi": K + ty_le * P * (1 + PHI_GIAO_DICH) / (1 - THUE_BAN),
        "giam_ve_0": K / S - 1,
        "xs_ve_0": xs_ve_0,
        "mat_khi_giam_1pct": so_cw * P * don_bay / 100,
    }


# ============ PHẦN 4: CHƯƠNG TRÌNH CHÍNH ============
def main():
    hom_nay = date.today()

    # Bước 0: đăng nhập vnstock bằng key trong file .env (không có key = gói Khách: 10 lượt gọi/phút, quét chậm hơn)
    api_key = doc_env().get("VNSTOCK_API_KEY", "")
    if api_key:
        try:
            print(f"Đăng nhập vnstock: gói {login(api_key).get('tier')}")
        except Exception as e:  # key sai, hết hạn, quá số thiết bị...: vẫn quét tiếp ở gói Khách  # noqa: BLE001
            print(f"  [!] Không đăng nhập được vnstock: {e}\n  -> quét tiếp bằng gói Khách.")
    else:
        print("Chưa có VNSTOCK_API_KEY trong file .env -> dùng gói Khách (10 lượt gọi/phút).")

    # Bước 1: danh sách CW
    ma_cw = list(Listing(source="KBS").all_covered_warrant())
    print(f"Tìm thấy {len(ma_cw)} chứng quyền đang niêm yết.")

    # Bước 2: điều khoản + giá của CW, sau đó giá cổ phiếu cơ sở
    bang_cw = lay_bang_gia(ma_cw)
    ma_co_so = sorted({ny["underlyingSymbol"] for ny, *_ in bang_cw.values()})
    bang_cs = lay_bang_gia(ma_co_so)

    # Bước 3: biến động của từng cổ phiếu cơ sở (lỗi 1 mã thì bỏ qua mã đó, không dừng cả chương trình)
    sigma, so_phien, lich_su = {}, {}, {}
    for ma in ma_co_so:
        try:
            s, n, ls = bien_dong_lich_su(ma)
            # vnstock có thể trả giá theo nghìn đồng: đưa về cùng đơn vị VND với bảng giá để vẽ biểu đồ
            he_so = 10 ** round(math.log10(gia_hien_tai(*bang_cs[ma]) / ls[-1][1]))
            lich_su[ma] = [[ngay, round(gia * he_so)] for ngay, gia in ls]
            # chỉ ghi nhận sigma khi mọi bước trên đã xong: mã lỗi thật sự bị bỏ qua (trước đây sigma NaN vẫn được dùng -> sập cả lần quét)
            sigma[ma], so_phien[ma] = s, n
        # ranh giới gọi vnstock/mạng: lỗi được báo ra (nhật ký hoặc trên trang), không nuốt
        except Exception as e:  # noqa: BLE001
            print(f"  [!] Không lấy được lịch sử giá {ma} (các CW của mã này bị bỏ qua): {e}")

    # Bước 6a: CW mới = chưa có trong danh sách đã lưu (lần chạy đầu tiên chỉ lưu, không đánh dấu)
    da_biet = set(FILE_CW_DA_BIET.read_text(encoding="utf-8").split()) if FILE_CW_DA_BIET.exists() else set(ma_cw)

    # Bước 4 + 5: định giá và chấm điểm từng CW
    dong = []
    for ma, (ny, kl, so_lenh) in bang_cw.items():
        cs = ny["underlyingSymbol"]
        if cs not in sigma or cs not in bang_cs:
            continue
        S = gia_hien_tai(*bang_cs[cs])  # giá cổ phiếu cơ sở (VND)
        dong.append(
            {
                "Mã CW": ma,
                "Mới": "MỚI" if ma not in da_biet else "",
                **dinh_gia(ny, kl, so_lenh, S, sigma[cs], hom_nay),
                "Số phiên σ": so_phien[cs],
            }
        )

    if not dong:  # mọi lần lấy lịch sử giá đều lỗi -> không có gì để lưu
        raise RuntimeError("Không định giá được CW nào (máy chủ dữ liệu đang lỗi?). Hãy thử lại sau ít phút.")
    df = pd.DataFrame(dong)
    so_sanh = [so_iv_cung_ma(df, ma, cs, iv) for ma, cs, iv in zip(df["Mã CW"], df["Mã CS"], df["IV %"])]
    df["IV cùng mã %"] = [round(tv, 1) for tv, _ in so_sanh]  # trung vị IV các CW khác cùng mã CS
    df["Cảnh báo"] = [cb for _, cb in so_sanh]
    df["Đánh giá"] = pd.Categorical(df["Đánh giá"], KET_LUAN, ordered=True)  # để sắp xếp theo thứ tự tốt -> xấu
    # trong mỗi nhóm: IV − HV thấp nhất trước (so sánh được giữa CW gần và xa giá thực hiện); không giải được IV xếp cuối
    df = df.sort_values(["Đánh giá", "IV − HV"], na_position="last")

    # Bước 6b: lưu kết quả + danh sách CW đã biết
    THU_MUC_KET_QUA.mkdir(exist_ok=True)
    file_ket_qua = THU_MUC_KET_QUA / f"cw_{hom_nay}.csv"
    df.to_csv(file_ket_qua, index=False, encoding="utf-8-sig")  # utf-8-sig để Excel hiển thị đúng tiếng Việt
    (THU_MUC_KET_QUA / f"lich_su_{hom_nay}.json").write_text(
        json.dumps(lich_su), encoding="utf-8"
    )  # cho biểu đồ ở trang chi tiết
    # Giả định đã dùng cho lần quét này: đổi cấu hình về sau vẫn truy lại được vì sao ra các con số trong file CSV
    gia_dinh = {
        "thoi_diem_quet": datetime.now().astimezone().isoformat(timespec="seconds"),
        "lai_suat_phi_rui_ro": LAI_SUAT_PHI_RUI_RO,
        "so_phien_do_bien_dong": SO_PHIEN_DO_BIEN_DONG,
        "so_phien_mot_nam": SO_PHIEN_MOT_NAM,
        "thoi_gian_T": "số ngày lịch còn lại / 365",
        "gia_mua": "giá chào bán thấp nhất trong sổ lệnh; sổ lệnh trống thì giá khớp; chưa khớp thì giá tham chiếu",
        "tieu_chi": {
            "MIN_NGAY_CON_LAI": MIN_NGAY_CON_LAI,
            "MAX_IV_TRU_HV": MAX_IV_TRU_HV,
            "MAX_TANG_DE_HOA_VON": MAX_TANG_DE_HOA_VON,
            "MIN_KHOI_LUONG": MIN_KHOI_LUONG,
        },
        "chi_phi": {"PHI_GIAO_DICH": PHI_GIAO_DICH, "THUE_BAN": THUE_BAN},
        "canh_bao_iv_cung_ma": {"MIN_IV_SO_VOI_CUNG_MA": MIN_IV_SO_VOI_CUNG_MA, "MIN_SO_CW_CUNG_MA": MIN_SO_CW_CUNG_MA},
        "nguon": {
            "danh_sach_cw": "vnstock Listing(KBS)",
            "bang_gia": URL_BANG_GIA,
            "lich_su_gia": "vnstock Quote(KBS), 1D",
        },
        "vnstock": importlib.metadata.version("vnstock"),
    }
    (THU_MUC_KET_QUA / f"gia_dinh_{hom_nay}.json").write_text(
        json.dumps(gia_dinh, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Bước 6c: lưu danh sách CW sắp ra mắt từ HOSE (để trang "CW sắp ra mắt" vẫn có dữ liệu khi HOSE chậm); lỗi thì bỏ qua
    try:
        du_lieu_hose = tai_du_lieu_hose_cw()
        (THU_MUC_KET_QUA / f"sap_ra_mat_{hom_nay}.json").write_text(
            json.dumps(du_lieu_hose, ensure_ascii=False), encoding="utf-8"
        )
        print(
            f"Đã lưu danh sách {len(doc_cw_sap_ra_mat(du_lieu_hose))} CW được HOSE chấp thuận (để xem CW sắp ra mắt)."
        )
    # ranh giới gọi vnstock/mạng: lỗi được báo ra (nhật ký hoặc trên trang), không nuốt
    except Exception as e:  # noqa: BLE001
        print(f"  [!] Không tải được danh sách CW sắp ra mắt từ HOSE (không ảnh hưởng kết quả quét): {e}")
    FILE_CW_DA_BIET.write_text("\n".join(sorted(da_biet | set(ma_cw))), encoding="utf-8")

    # In tóm tắt
    cot = [
        "Mã CW",
        "Mã CS",
        "Ngày còn lại",
        "Giá mua",
        "Giá hợp lý",
        "Đắt/rẻ %",
        "IV − HV",
        "CS tăng % để hòa vốn",
        "Đòn bẩy",
        "Lý do",
    ]
    print(f"\nĐã định giá {len(df)} CW: " + ", ".join(f"{k} {v}" for k, v in df["Đánh giá"].value_counts().items()))
    print(
        "Giá dùng để định giá: "
        + ", ".join(f"{v} CW giá {k}" for k, v in df["Nguồn giá mua"].value_counts().items())
        + f"; {(df['Ghi chú IV'] != '').sum()} CW không giải được biến động ngầm định (xem cột Ghi chú IV)"
    )
    for _, h in df[df["Cảnh báo"] != ""].iterrows():
        print(f"  ⚠ {h['Mã CW']}: {h['Cảnh báo']}")
    moi = df[df["Mới"] == "MỚI"]
    if len(moi):
        print(f"\n=== {len(moi)} CW MỚI PHÁT HÀNH ===")
        print(moi[cot + ["Đánh giá"]].to_string(index=False))
    tot = df[df["Đánh giá"] == "NÊN XEM XÉT"]
    print("\n=== NÊN XEM XÉT ===")
    print(tot[cot].to_string(index=False) if len(tot) else "(không có CW nào đạt cả 4 tiêu chí hôm nay)")
    print(f"\nChi tiết đầy đủ: {file_ket_qua}")


if __name__ == "__main__":
    # chạy nền không có cửa sổ (Task Scheduler) Windows dùng bảng mã cũ -> in tiếng Việt bị lỗi và dừng chương trình
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
