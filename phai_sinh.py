"""
phai_sinh.py - Hợp đồng tương lai chỉ số VN30 và VN100 (VN30F1M…F2Q, VN100F1M…F2Q): basis so với chỉ số, basis năm hóa so với lãi suất
phi rủi ro, ký quỹ, lãi/lỗ nếu giữ đến đáo hạn sau phí và thuế. Chỉ đọc dữ liệu, dùng cho trang web /phai-sinh.

Giá trị hợp lý của HĐ chỉ số theo cost-of-carry (Hull ch. 5): F = S·e^((r − q)T), q = tỷ suất cổ tức của VN30. Chưa có q
chắc chắn nên không tính "giá hợp lý": hiện basis và basis năm hóa ln(F/S)/T (= r − q ngầm định) đặt cạnh r để người dùng
tự so (người dùng chọn 30/10/2026). HĐ thanh toán bằng tiền theo VN30 đóng cửa ngày giao dịch cuối, nên basis về 0 lúc đó.
"""

import math
import re
import time
from datetime import date

import numpy as np

import cw_scanner as C

# ============ CẤU HÌNH ============
CHI_SO_HD = ("VN30", "VN100")  # VN100 thêm 31/10/2026 theo yêu cầu người dùng
# mã liên tục của vnstock / bảng giá: tháng gần, tháng sau, 2 quý gần nhất
HOP_DONG = tuple(f"{cs}F{k}" for cs in CHI_SO_HD for k in ("1M", "2M", "1Q", "2Q"))
MAU_MA_HD = re.compile(r"VN(30|100)F[12][MQ]")  # chỉ nhận mã đúng dạng (mã từ URL)
HE_SO_NHAN = 100_000  # đồng / 1 điểm chỉ số (quy chuẩn HĐTL chỉ số VN30 và VN100 của HNX)
# Phí, thuế, ký quỹ: người dùng chọn lấy 1 công ty lớn làm chuẩn (30/10/2026). Nguồn: biểu giá SSI cho TKGD phái sinh, hiệu lực
# 01/01/2022 (khách có môi giới tư vấn, < 100 HĐ/ngày); VSDC; ví dụ thuế của Pinetree 11/07/2024. Kiểm tra lại với CTCK của bạn.
PHI_CTCK_HD = 3_000  # đồng / HĐ / lần giao dịch (SSI thu cả khi đáo hạn)
PHI_SO_HD = 2_700  # đồng / HĐ / giao dịch, trả HNX
PHI_VI_THE_HD_NGAY = 2_550  # đồng / HĐ / ngày giữ vị thế, trả VSDC (tính theo phiên, chưa trừ ngày lễ)
# Tỷ lệ ký quỹ ban đầu theo chỉ số. VN30: VSDC hiệu lực 22/11/2024. VSDC công bố hằng tháng cho VN30 và VN100 (mới nhất
# hiệu lực 16/10/2026) nhưng chưa đọc được số; chưa thấy số riêng cho VN100 nên tạm dùng như VN30 (trang ghi rõ chưa xác nhận).
TY_LE_KY_QUY_BAN_DAU = {"VN30": 0.17, "VN100": 0.17}
KY_QUY_CHUA_XAC_NHAN = {"VN100"}
THUE_TNCN = 0.001  # 0,1% × giá trị chuyển nhượng = giá × HE_SO_NHAN × tỷ lệ ký quỹ ban đầu / 2 mỗi lần (chưa đối chiếu văn bản BTC)
SO_NGAY_GIA = 80  # ngày lịch giá đóng cửa cần tải: giá hiện tại (nến hôm nay) + basis ~50 phiên gần nhất
GIAY_NHO = 300  # dữ liệu đã tải dùng lại trong 5 phút
BO_NHO: dict = {}  # "du_lieu" -> (lúc tải, kết quả)


# ============ TÍNH TOÁN ============
def basis(F, S):
    """(F − S điểm, F / S − 1 %)."""
    return F - S, (F / S - 1) * 100


def basis_nam_hoa(F, S, ngay_con_lai):
    """ln(F/S) / T (%/năm), T = số ngày lịch tới ngày giao dịch cuối / 365: bằng r − q ngầm định theo cost-of-carry."""
    return math.log(F / S) / (ngay_con_lai / C.NGAY_MOT_NAM) * 100 if ngay_con_lai > 0 else math.nan


def chi_so_cua(ma):
    """'VN100F1Q' -> 'VN100' (chỉ số cơ sở của hợp đồng)."""
    return ma.split("F")[0]


def ky_quy_ban_dau(F, chi_so="VN30"):
    """Tiền ký quỹ ban đầu cho 1 HĐ (đồng)."""
    return F * HE_SO_NHAN * TY_LE_KY_QUY_BAN_DAU[chi_so]


def thue_mot_lan(gia, chi_so="VN30"):
    """Thuế TNCN 1 lần chuyển nhượng 1 HĐ: 0,1% × giá × hệ số nhân × tỷ lệ ký quỹ ban đầu / 2."""
    return THUE_TNCN * gia * HE_SO_NHAN * TY_LE_KY_QUY_BAN_DAU[chi_so] / 2


def lai_lo_dao_han(F, S_T, chieu, so_phien_giu, chi_so="VN30"):
    """(lãi/lỗ gộp, lãi/lỗ ròng) đồng của 1 HĐ mở ở giá F, giữ đến đáo hạn (thanh toán theo chỉ số ngày GD cuối S_T);
    chieu = +1 Long, −1 Short. Ròng trừ phí CTCK lúc mở và lúc đáo hạn, phí Sở lúc mở, phí vị thế mỗi phiên, thuế 2 lần.
    """
    gop = chieu * (S_T - F) * HE_SO_NHAN
    phi = 2 * PHI_CTCK_HD + PHI_SO_HD + PHI_VI_THE_HD_NGAY * so_phien_giu
    phi += thue_mot_lan(F, chi_so) + thue_mot_lan(S_T, chi_so)
    return gop, gop - phi


def so_phien(tu, den):
    """Số phiên từ `tu` (tính) tới `den` (không tính), bỏ thứ Bảy, Chủ nhật. shortcut: chưa trừ ngày lễ."""
    return int(np.busday_count(np.datetime64(tu), np.datetime64(den)))


def doc_ngay(chuoi):
    """'19/11/2026' (bảng giá Vietcap, khác dạng YYYYMMDD của CW) -> date; rỗng -> None."""
    return date(int(chuoi[6:10]), int(chuoi[3:5]), int(chuoi[:2])) if chuoi else None


# ============ LẤY DỮ LIỆU ============
def chuoi_dong_cua(ma):
    """({ngày: giá đóng cửa (điểm)}, {ngày: KL}) SO_NGAY_GIA ngày lịch từ vnstock VCI, gồm nến hôm nay đang chạy trong phiên.
    floating=6: vnstock trả điểm chia 1.000, mặc định làm tròn 2 số lẻ (1.880,8 -> 1,88) làm sai giá."""
    df = C.lay_gia_dong_cua(ma, SO_NGAY_GIA, "VCI", floating=6)
    ngay = [str(t)[:10] for t in df["time"]]
    return dict(zip(ngay, (float(g) * 1000 for g in df["close"]))), dict(zip(ngay, (float(v) for v in df["volume"])))


def lay_du_lieu():
    """(danh sách HĐ [dict], giá chỉ số {chỉ số: {ngày: điểm}}, [cảnh báo]); nhớ GIAY_NHO giây. Mỗi HĐ: mã, chỉ số, tên, giá
    (nến ngày mới nhất), ngày giá, KL phiên đó, lịch sử giá, ngày GD cuối / đáo hạn (bảng giá Vietcap), bản ghi bảng giá (sổ lệnh).
    """
    luc, kq = BO_NHO.get("du_lieu", (0.0, None))
    if kq is not None and time.time() - luc <= GIAY_NHO:
        return kq
    canh_bao = []
    gia_cs = {cs: chuoi_dong_cua(cs)[0] for cs in CHI_SO_HD}
    try:
        bang_gia = C.lay_bang_gia(list(HOP_DONG))
    # lỗi mạng: vẫn có giá từ vnstock, chỉ thiếu ngày đáo hạn và sổ lệnh
    except Exception as e:  # noqa: BLE001
        bang_gia = {}
        canh_bao.append(f"không lấy được bảng giá Vietcap ({type(e).__name__}): thiếu ngày đáo hạn và sổ lệnh")
    ds = []
    for ma in HOP_DONG:
        gia, kl = chuoi_dong_cua(ma)
        cs = chi_so_cua(ma)
        if not gia:
            canh_bao.append(f"{ma}: vnstock không có giá")
            continue
        ngay_gia = max(gia)
        ny = bang_gia.get(ma, ({},))[0]
        ds.append(
            {
                "ma": ma,
                "chi_so": cs,
                "ten": ny.get("organName") or ma,
                "gia": gia[ngay_gia],
                "ngay_gia": ngay_gia,
                "kl": kl.get(ngay_gia, 0.0),
                "lich_su": gia,
                "gd_cuoi": doc_ngay(ny.get("lastTradingDate") or ""),
                "dao_han": doc_ngay(ny.get("maturityDate") or ""),
                "bang_gia": bang_gia.get(ma),
            }
        )
        if ngay_gia != max(gia_cs[cs]):
            canh_bao.append(f"{ma}: giá ngày {ngay_gia} khác ngày {cs} {max(gia_cs[cs])}, basis không cùng thời điểm")
    kq = (ds, gia_cs, canh_bao)
    BO_NHO["du_lieu"] = (time.time(), kq)
    return kq
