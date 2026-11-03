"""
canh_bao_gia.py - Trang 🔔 Cảnh báo giá (/canh-bao): giá lệch bất thường ĐANG mua được lúc xem, và các mức giá người dùng
tự đặt. Người dùng yêu cầu 31/10/2026: theo dõi mã có giá đột biến lệch khỏi thị trường làm định giá rẻ ngay lúc đó (CW,
ETF, VN30F, VN100F) mà vẫn an toàn; ETF lệch giá thì phòng hộ bằng hợp đồng tương lai (HĐTL).

Mọi giá đem so là giá MUA ĐƯỢC trong sổ lệnh, không phải giá khớp: nến giật do khớp lẻ không mua lại được (CVNM2616 30/10/2026).
- CW: giá chào bán thấp hơn giá "lẽ ra" theo cổ phiếu cơ sở (CS) ≥ NGUONG_LECH_CW. IV mốc = IV của giá chào bán lúc quét gần
  nhất (giá tổ chức phát hành tự yết), tính lại theo giá CS bây giờ (cw_scanner.lech_theo_cs). Phải có ≥ MIN_GIA_TRI_MUA đồng
  chào bán ở các mức rẻ đó, và IV ở giá chào bán bây giờ không cao hơn trung vị IV các CW cùng CS (rẻ so với chính nó chưa đủ).
  Không phòng hộ được (Việt Nam chưa cho bán khống cổ phiếu).
- ETF: đúng ngưỡng 🟢 của trang ETF (≥ MIN_GIA_TRI_CHAO_BAN đồng chào bán ở giá đủ lãi ròng ≥ NGUONG_LAI_RONG nếu về iNAV), trừ
  quỹ lúc nào cũng rẻ như vậy (như cảnh báo trong phiên). Quỹ VN30 / VN100 kèm số HĐTL cần bán để phòng hộ (Hull ch. 3).
- HĐTL: giá hợp lý cost-of-carry F = S·e^((r − q)T) (Hull ch. 5) với q = 0, tức cận trên thận trọng. Bán HĐTL + mua ETF cùng chỉ
  số khóa được lãi khi giá chờ mua HĐTL vẫn cao hơn sau chi phí cả 2 chân; cổ tức ETF nhận thêm không tính (thận trọng).
  HĐTL rẻ hơn chỉ số quá chi phí chỉ ghi nhận: chỉ người đang giữ ETF cùng chỉ số mới tận dụng được.
Chưa tín hiệu nào ở đây được kiểm chứng là có lãi sau phí (KE_HOACH.md): đây là sàng lọc, không phải khuyến nghị.
Trang web chỉ đọc (không ghi file, không gửi Discord); lịch 5 phút (danh_muc.py) gọi kiem_tra_muc_gia để ghi mức đã chạm.
"""

import csv
import json
import math
import re
import shutil
import time
from datetime import date, datetime
from datetime import time as gio

import pandas as pd
from vnstock import Listing

import chiet_khau as CK
import cw_scanner as C
import danh_muc as D
import etf as E
import phai_sinh as P

# ============ CẤU HÌNH ============
NGUONG_LECH_CW = D.NGUONG_LECH_GIAM_MANH  # 15%: cùng ngưỡng lệch của cảnh báo CW giảm mạnh (người dùng chốt 30/10/2026)
# CW trong ngần này dòng đầu danh sách Chứng quyền (thứ tự file quét) không cần điều kiện IV ≤ trung vị cùng mã (người dùng chốt
# 03/11/2026: "top 30 hoặc IV rẻ"; đo 03/11 13:27 chưa thêm mã nào vì không CW top 30 nào lệch tới −15%)
SO_TOP_CW_RE = 30
MIN_GIA_TRI_MUA = (
    C.GIA_TRI_KHOP_TOI_THIEU
)  # 5 triệu đồng: ít hơn là lô lẻ, không phải cơ hội thật (người dùng chốt 30/10/2026)
GIA_TRI_LENH_ETF = CK.GIA_TRI_LENH  # lệnh ETF 50 triệu: dùng để tính số HĐTL phòng hộ
CHI_SO_HD = {"41I1": "VN30", "41I2": "VN100"}  # đầu mã KRX của HĐTL chỉ số -> chỉ số cơ sở
MAU_MA_HD_KRX = re.compile(r"41I[12][A-Z0-9]{2}000")
MAU_MA_HD_BI_DANH = re.compile(r"VN(30|100)F[12][MQ]")  # tháng gần, tháng sau, 2 quý gần nhất
# mã đặt mức giá: CW, cổ phiếu 3 chữ, ETF, HĐTL (bí danh hoặc mã KRX). Chỉ số (VN30...) không có giá trên bảng giá Vietcap.
MAU_MA_MUC = re.compile(
    r"C[A-Z]{3}\d{4}|[A-Z]{3}|E1VFVN30|FUE[A-Z0-9]{3,8}|" + MAU_MA_HD_BI_DANH.pattern + "|" + MAU_MA_HD_KRX.pattern
)
GIAY_NHO_MA_HD = 3600  # danh sách mã KRX chỉ đổi khi đáo hạn
GIAY_NHO_CHI_SO = 30  # giá chỉ số dùng lại 30 giây (bấm tải lại liên tục không gọi lặp vnstock)
BO_NHO: dict[str, tuple[float, object]] = {}  # khóa -> (lúc tải, dữ liệu)

FILE_MUC_GIA = C.THU_MUC / "muc_gia.csv"
COT_MUC_GIA = ["id", "ma", "chieu", "muc", "ghi_chu", "ngay_tao"]
CHIEU = {"duoi": "≤", "tren": "≥"}  # giá xuống tới mức (muốn mua) / lên tới mức (muốn bán, chốt lời)
SO_MUC_TOI_DA = 50
# mức gấp hoặc chỉ bằng 1/10 giá hiện tại: nghi gõ sai đơn vị (120 nghìn gõ thành 120 đ lệch ×1.000); CW đòn bẩy cao nên
# mức chốt lời +70% hay mua lại −50% vẫn hợp lệ (rà soát 31/10/2026: ngưỡng 50% cũ chặn nhầm)
HE_SO_SAI_DON_VI = 10
THU_MUC_CHAM = (
    C.THU_MUC_KET_QUA
)  # muc_gia_cham_<ngày>.json: các mức đã chạm trong ngày (lịch 5 phút ghi, trang web đọc)
GUI_DISCORD_MUC_GIA = False  # chờ người dùng cho phép gửi Discord (AGENTS.md mục 4.7)
GIO_XET_ATC = gio(14, 50)  # lịch 5 phút xét mức giá tới 14:50 để có giá đóng cửa ATC (khớp lúc 14:45)
SO_PHIEN_TOI_THIEU_KHOA = 2  # ETF mua phiên T sớm nhất chiều T+2 mới bán: HĐ còn < 2 phiên thì không khóa được lãi


# ============ CÔNG THỨC ============
def doc_ngay(chuoi):
    """'20270217' (CW trên bảng giá Vietcap) hoặc '19/11/2026' (HĐTL) -> date; rỗng hoặc sai dạng -> None."""
    s = str(chuoi or "")
    if re.fullmatch(r"\d{8}", s):
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
        return date(int(s[6:]), int(s[3:5]), int(s[:2]))
    return None


def gia_tri_chao_ban_den(so_lenh, gia_toi_da, he_so=1):
    """Tổng giá trị (đồng) đang chào bán ở các mức giá ≤ gia_toi_da. he_so: hệ số nhân của HĐTL (giá tính bằng điểm)."""
    return float(sum(g * v * he_so for g, v in C.muc_so_lenh(so_lenh, "askPrices") if g <= gia_toi_da))


def so_hd_phong_ho(gia_tri, F, beta=1.0):
    """Số HĐTL tối ưu để phòng hộ vị thế gia_tri đồng: N* = β·V_A / V_F, V_F = F × hệ số nhân (Hull ch. 3, phòng hộ danh mục
    cổ phiếu bằng HĐTL chỉ số). ETF bám đúng chỉ số của HĐTL: β = 1. Chưa làm tròn (HĐ chỉ giao dịch số nguyên)."""
    return beta * gia_tri / (F * P.HE_SO_NHAN)


def chi_phi_hd_den_dao_han(F, so_phien_giu, chi_so):
    """Chi phí (đồng) của 1 HĐ mở ở giá F rồi giữ đến đáo hạn, đúng cách tính của phai_sinh.lai_lo_dao_han (phí công ty, Sở,
    bù trừ VSDC, thuế 2 lần): lãi gộp − lãi ròng khi chỉ số lúc đáo hạn = F."""
    gop, rong = P.lai_lo_dao_han(F, F, -1, so_phien_giu, chi_so)
    return gop - rong


def chi_phi_ra_etf(A, B, inav):
    """Phần giá trị mất khi bán ETF lúc đáo hạn, theo tỷ lệ iNAV (thận trọng): ETF đang rẻ hơn iNAV thì coi như vẫn rẻ như vậy
    (1 − B/iNAV: không tính chiết khấu đóng lại là lãi); đang cao hơn iNAV thì coi phần cao hơn biến mất, chỉ còn chênh lệch
    mua–bán (A − B)/iNAV. Rà soát 31/10/2026: tính (A − B)/iNAV cho mọi quỹ thì FUEIP100 (thường rẻ hơn NAV 4,6%) cho 'lãi khóa'
    +80 điểm giả."""
    return max(1 - B / inav, (A - B) / inav)


def lai_khoa_ban_hd_mua_etf(F_ban, S, A, B, inav, ngay_con_lai, chi_phi_hd, r=C.LAI_SUAT_PHI_RUI_RO):
    """Lãi khóa được (điểm chỉ số, cho 1 HĐ) khi bán HĐTL ở F_ban và mua ETF cùng chỉ số ở giá A (giá bình quân đủ 1 HĐ), giữ đến
    đáo hạn. Mua ETF ở A khi iNAV là inav tương đương mua chỉ số ở S·A/inav; vốn đó mất lãi suất r (giá hợp lý S·e^(rT), q = 0).
    Trừ phí mua + phí bán + thuế bán ETF, phần mất khi bán ETF ra (chi_phi_ra_etf) và chi phí HĐTL (đồng) quy ra điểm.
    Không tính: cổ tức ETF nhận được (có lợi), lãi suất bỏ lỡ của tiền ký quỹ HĐ (khoảng 17% × F × (e^(rT) − 1), bất lợi).
    """
    T = ngay_con_lai / C.NGAY_MOT_NAM
    chi_phi_etf = S * (2 * C.PHI_GIAO_DICH + C.THUE_BAN + chi_phi_ra_etf(A, B, inav))
    return F_ban - S * A / inav * math.exp(r * T) - chi_phi_etf - chi_phi_hd / P.HE_SO_NHAN


# ============ LẤY DỮ LIỆU ============
def nho(khoa, giay, ham):
    """Kết quả ham() dùng lại trong `giay` giây."""
    luc, kq = BO_NHO.get(khoa, (0.0, None))
    if kq is None or time.time() - luc > giay:
        kq = ham()
        BO_NHO[khoa] = (time.time(), kq)
    return kq


def ma_hdtl():
    """Mã KRX các HĐTL chỉ số đang niêm yết (vnstock, nhóm FU_INDEX của VCI); nhớ GIAY_NHO_MA_HD giây."""
    return nho(
        "ma_hd",
        GIAY_NHO_MA_HD,
        lambda: sorted(
            m for m in Listing(source="VCI").symbols_by_group("FU_INDEX") if MAU_MA_HD_KRX.fullmatch(str(m))
        ),
    )


def gia_chi_so(chi_so):
    """(giá chỉ số bằng điểm, ngày 'YYYY-MM-DD') từ nến ngày VCI (nến hôm nay chạy trong phiên); nhớ GIAY_NHO_CHI_SO giây.
    vnstock VCI trả điểm chia 1.000, phải floating=6 (như phai_sinh.chuoi_dong_cua)."""

    def lay():
        df = C.lay_gia_dong_cua(chi_so, 10, "VCI", floating=6)
        return float(df["close"].iloc[-1]) * 1000, str(df["time"].iloc[-1])[:10]

    return nho(f"chi_so_{chi_so}", GIAY_NHO_CHI_SO, lay)


def he_so_cua(ma):
    """Đồng trên 1 đơn vị giá: HĐTL tính bằng điểm (× hệ số nhân), còn lại tính bằng đồng."""
    return P.HE_SO_NHAN if MAU_MA_HD_KRX.fullmatch(ma) or MAU_MA_HD_BI_DANH.fullmatch(ma) else 1


def ban_ghi_cua(ma, bang_gia):
    """Bản ghi bảng giá của 1 mã đặt mức. Bí danh HĐTL (VN30F1M...) trên Vietcap không có giá và sổ lệnh: dùng mã KRX có
    listingInfo.mappingSymbol trùng bí danh. Trả về (mã thật, bản ghi) hoặc (ma, None)."""
    if MAU_MA_HD_BI_DANH.fullmatch(ma):
        for that, bg in bang_gia.items():
            if MAU_MA_HD_KRX.fullmatch(that) and bg[0].get("mappingSymbol") == ma:
                return that, bg
        return ma, None
    return ma, bang_gia.get(ma)


# ============ CW, ETF, HĐTL LỆCH ============
def cw_lech_re(df, bang_gia, ngay_quet, hom_nay):
    """CW có giá chào bán thấp hơn giá lẽ ra theo CS ≥ NGUONG_LECH_CW và ≥ MIN_GIA_TRI_MUA đồng chào bán ở các mức rẻ đó.
    Bỏ CW còn < MIN_NGAY_GD_CUOI_LUOT ngày tới ngày GD cuối (sắp hết đường bán), CW lúc quét không có giá chào bán thật
    (IV mốc phải từ giá tổ chức phát hành yết) và CW mà IV ở giá chào bán bây giờ vẫn cao hơn trung vị IV các CW cùng CS lúc quét
    (cột "IV cùng mã %"; không có trung vị hoặc giá dưới mức tối thiểu, không giải được IV, thì vẫn báo). CW trong SO_TOP_CW_RE
    dòng đầu df (thứ tự file quét = trang Chứng quyền: Nên xem xét trước, IV − HV thấp trước) không cần điều kiện IV đó.
    Trả về [dict] xếp lệch sâu nhất trước; iv, iv_tv tính bằng %; top: CW thuộc SO_TOP_CW_RE dòng đầu."""
    if df is None or df.empty:
        return []
    top = set(df["Mã CW"].head(SO_TOP_CW_RE))
    kq = []
    for _, h in df.iterrows():
        ma = h["Mã CW"]
        if ma not in bang_gia or h.get("Nguồn giá mua") != "ask" or pd.isna(h.get("IV %")):
            continue
        # mốc phải là giá yết thật: lúc quét có ≥ MIN_GIA_TRI_MUA đồng chào bán (lô lẻ 500 CW giá cao thổi IV mốc lên, hôm sau
        # TCPH yết bình thường cũng bị báo 'rẻ' — rà soát 31/10/2026; 28–30/10 có 17–62 CW/ngày như vậy)
        if not float(h["Giá mua"]) * float(h.get("KL chào bán") or 0) >= MIN_GIA_TRI_MUA:
            continue
        ny, _, so_lenh = bang_gia[ma]
        ban, cs = C.muc_so_lenh(so_lenh, "askPrices"), ny.get("underlyingSymbol") or h["Mã CS"]
        gd_cuoi, dao_han = doc_ngay(ny.get("lastTradingDate")), doc_ngay(ny.get("maturityDate"))
        if not ban or cs not in bang_gia or not gd_cuoi or not dao_han:
            continue
        if (gd_cuoi - hom_nay).days < C.MIN_NGAY_GD_CUOI_LUOT:
            continue
        S, gia = C.gia_hien_tai(*bang_gia[cs]), min(g for g, _ in ban)
        r = float(h["r %"]) / 100 if not pd.isna(h.get("r %")) else C.LAI_SUAT_PHI_RUI_RO
        K, ty_le = ny["exercisePrice"], C.doc_ty_le(ny["exerciseRatio"])
        lech = C.lech_theo_cs(
            float(h["Giá mua"]), float(h["Giá CS"]), ngay_quet, gia, S, hom_nay, K, ty_le, dao_han, r
        )[0]
        if not round(lech, 9) <= -NGUONG_LECH_CW:  # NaN: không tính được giá lẽ ra -> bỏ
            continue
        # rẻ so với chính nó chưa đủ: TCPH hạ một IV quá cao thì CW vẫn đắt (CFPT2638 02/11/2026: lệch −72% mà IV còn 61%,
        # HV 31%, trung vị 29 CW FPT khác 52%) -> chỉ báo khi IV không cao hơn trung vị cùng mã (người dùng chốt 02/11/2026)
        iv, iv_tv = C.bien_dong_ngam_dinh(gia, S, K, (dao_han - hom_nay).days / C.NGAY_MOT_NAM, r, ty_le), h.get(
            "IV cùng mã %"
        )
        if ma not in top and iv is not None and pd.notna(iv_tv) and iv * 100 > iv_tv:
            continue
        le_ra = gia / (1 + lech)
        mua_duoc = gia_tri_chao_ban_den(so_lenh, le_ra * (1 - NGUONG_LECH_CW))
        if mua_duoc < MIN_GIA_TRI_MUA:
            continue
        cho_mua = C.gia_cho_mua(so_lenh)
        kq.append(
            {
                "ma": ma,
                "cs": cs,
                "tcph": h.get("TCPH", ""),
                "gia": gia,
                "le_ra": le_ra,
                "lech": lech,
                "mua_duoc": mua_duoc,
                "cho_mua": cho_mua,
                "spread": (gia - cho_mua) / ((gia + cho_mua) / 2) if cho_mua else math.nan,
                "con_ngay": (gd_cuoi - hom_nay).days,
                "cs_pt": S / float(h["Giá CS"]) - 1,
                "iv": iv * 100 if iv is not None else math.nan,
                "iv_tv": float(iv_tv) if pd.notna(iv_tv) else math.nan,
                "top": ma in top,
            }
        )
    return sorted(kq, key=lambda x: x["lech"])


def etf_mua_duoc(ssi, chi_so, gia_tri=0, thuong_lech=None):
    """ETF cùng chỉ số tốn ít nhất để mua rồi bán ra (giá mua / iNAV + chi_phi_ra_etf nhỏ nhất): (mã, A, B, iNAV) hoặc None.
    A = giá bình quân mua đủ gia_tri đồng qua 3 mức chào bán (không đủ hàng thì bỏ quỹ; gia_tri 0 -> giá chào bán tốt nhất).
    Bỏ quỹ có mức thường lệch 1 năm ≤ −NGUONG_GIAM_SO_INAV (lúc nào cũng rẻ, như etf_duoi_inav)."""
    ung_vien = []
    for ma in E.QUY_THEO_CHI_SO.get(chi_so, []):
        bg = ssi.get(ma) or {}
        ban, inav, B = CK.muc_chao_ban(bg), bg.get("iNAV") or 0, bg.get("best1Bid") or 0
        if not ban or inav <= 0 or B <= 0 or (thuong_lech or {}).get(ma, math.nan) <= -CK.NGUONG_GIAM_SO_INAV * 100:
            continue
        A = CK.gia_mua_lenh(bg, gia_tri) if gia_tri > 0 else ban[0][0]
        if math.isfinite(A):
            ung_vien.append((A / inav + chi_phi_ra_etf(A, B, inav), ma, A, B, inav))
    if not ung_vien:
        return None
    _, ma, A, B, inav = min(ung_vien)
    return ma, A, B, inav


def etf_duoi_inav(ssi, thuong_lech, hd_thang_gan):
    """ETF đạt ngưỡng 🟢 (mua được ≥ MIN_GIA_TRI_CHAO_BAN đồng ở giá đủ lãi ròng ≥ NGUONG_LAI_RONG nếu về iNAV), trừ quỹ có
    mức thường lệch 1 năm ≤ −NGUONG_GIAM_SO_INAV (quỹ lúc nào cũng rẻ như vậy; chưa rõ mức thường thì vẫn hiện).
    thuong_lech: {mã: trung vị giá/NAV − 1 của 1 năm, %}; hd_thang_gan: {chỉ số: (mã HĐ, giá chờ mua)} để tính phòng hộ.
    """
    kq = []
    for ma, bg in sorted(ssi.items()):
        d = CK.danh_gia_quy(bg)
        if d["Mua được đạt ngưỡng (đ)"] < CK.MIN_GIA_TRI_CHAO_BAN:
            continue
        if thuong_lech.get(ma, math.nan) <= -CK.NGUONG_GIAM_SO_INAV * 100:
            continue
        chi_so = next((cs for cs, ds in E.QUY_THEO_CHI_SO.items() if ma in ds), "")
        hd = hd_thang_gan.get(chi_so)
        kq.append(
            {
                "ma": ma,
                "chi_so": chi_so,
                "inav": d["iNAV"],
                "gia": d["Giá chào bán"],
                "ck": d["Chiết khấu mua được %"],
                "lai_rong": d["Lãi ròng nếu về NAV %"],
                "mua_duoc": d["Mua được đạt ngưỡng (đ)"],
                "thuong": thuong_lech.get(ma, math.nan),
                "hd": hd[0] if hd else "",
                "so_hd": so_hd_phong_ho(GIA_TRI_LENH_ETF, hd[1]) if hd and math.isfinite(hd[1]) else math.nan,
                "etf_1_hd": hd[1] * P.HE_SO_NHAN if hd and math.isfinite(hd[1]) else math.nan,
            }
        )
    return sorted(kq, key=lambda x: -x["lai_rong"])


def hdtl_lech(bang_gia, chi_so, ssi, hom_nay, r=C.LAI_SUAT_PHI_RUI_RO, trong_phien=True, thuong_lech=None):
    """Mỗi HĐTL chỉ số trong bang_gia: giá, basis, giá hợp lý S·e^(rT), lệch, chi phí (điểm), và tín hiệu
    'dat' (bán HĐTL + mua ETF cùng chỉ số khóa được lãi sau chi phí cả 2 chân) / 're' (giá chào bán HĐTL thấp hơn số tiền
    bán ETF cùng chỉ số đem lại, sau chi phí: chỉ dùng được khi đang giữ ETF đó). chi_so: {chỉ số: (giá điểm, ngày)}.
    Chỉ cho tín hiệu trong giờ khớp lệnh (trong_phien) và khi chỉ số và HĐTL cùng ngày giao dịch: ngoài giờ, sổ lệnh còn lại
    và iNAV không cùng thời điểm (30/10/2026 sau 15h: E1VFVN30 chờ mua 33.600 trong khi iNAV 33.254, báo 'rẻ' giả cả 4 HĐ VN30).
    """
    kq = []
    for ma, (ny, khop, so_lenh) in sorted(bang_gia.items()):
        cs = CHI_SO_HD.get(ma[:4])
        gd_cuoi = doc_ngay(ny.get("lastTradingDate"))
        if not MAU_MA_HD_KRX.fullmatch(ma) or not cs or not gd_cuoi or gd_cuoi < hom_nay:
            continue
        S, ngay_cs = chi_so.get(cs, (math.nan, ""))
        ban, mua = C.muc_so_lenh(so_lenh, "askPrices"), C.muc_so_lenh(so_lenh, "bidPrices")
        A_hd, B_hd = (min(g for g, _ in ban) if ban else math.nan), (max(g for g, _ in mua) if mua else math.nan)
        gia = khop.get("matchPrice") or math.nan
        ngay_con_lai = (gd_cuoi - hom_nay).days
        so_phien = P.so_phien(hom_nay, gd_cuoi)
        hop_ly = S * math.exp(r * ngay_con_lai / C.NGAY_MOT_NAM)
        chi_phi = chi_phi_hd_den_dao_han(S if math.isnan(gia) else gia, so_phien, cs)
        cung_ngay = ny.get("tradingDate") == ngay_cs and trong_phien
        # 1 HĐ phòng hộ khoảng S × 100.000 đồng ETF: giá ETF là giá bình quân mua đủ lượng đó (rà soát 31/10/2026)
        gia_tri_1_hd = S * P.HE_SO_NHAN if not math.isnan(S) else 0
        tin_hieu, lai_khoa, etf = "", math.nan, etf_mua_duoc(ssi, cs, gia_tri_1_hd, thuong_lech)
        if cung_ngay and not math.isnan(S) and etf:
            _, A, B, inav = etf
            if not math.isnan(B_hd):
                lai_khoa = lai_khoa_ban_hd_mua_etf(B_hd, S, A, B, inav, ngay_con_lai, chi_phi, r)
                tin_hieu = "dat" if lai_khoa > 0 and so_phien >= SO_PHIEN_TOI_THIEU_KHOA else ""
            # người đang giữ ETF: bán ETF ở giá chờ mua B (tương đương chỉ số S·B/iNAV, trừ phí + thuế bán, phí mua lại) rồi
            # mua HĐTL ở A_hd. Lãi tiền nhàn rỗi không tính (thận trọng); cổ tức ETF bỏ lỡ cũng chưa trừ (ghi trên trang)
            if not tin_hieu and not math.isnan(A_hd):
                ban_etf = S * B / inav * (1 - 2 * C.PHI_GIAO_DICH - C.THUE_BAN)
                tin_hieu = "re" if A_hd < ban_etf - chi_phi / P.HE_SO_NHAN else ""
        kq.append(
            {
                "ma": ma,
                "bi_danh": ny.get("mappingSymbol") or "",
                "chi_so": cs,
                "S": S,
                "ngay_cs": ngay_cs,
                "cung_ngay": cung_ngay,
                "gia": gia,
                "mua": B_hd,
                "ban": A_hd,
                "kl": khop.get("accumulatedVolume") or 0,
                "oi": khop.get("openInterest") or 0,
                "gd_cuoi": gd_cuoi,
                "basis": gia - S,
                "hop_ly": hop_ly,
                "lech": gia - hop_ly,
                "chi_phi": chi_phi / P.HE_SO_NHAN,
                "lai_khoa": lai_khoa,
                "etf": etf[0] if etf else "",
                "tin_hieu": tin_hieu,
            }
        )
    return kq


# ============ MỨC GIÁ TỰ ĐẶT ============
def doc_muc_gia(file=None):
    """Danh sách mức giá trong muc_gia.csv (chưa có file -> []). Sai dòng tiêu đề thì báo lỗi, không coi là rỗng."""
    file = file or FILE_MUC_GIA
    if not file.exists():
        return []
    with open(file, encoding="utf-8-sig", newline="") as f:
        doc = csv.DictReader(f)
        if doc.fieldnames != COT_MUC_GIA:  # coi là rỗng thì lần lưu sau ghi đè mất hết mức đã đặt
            raise ValueError(f"dòng tiêu đề muc_gia.csv phải là {','.join(COT_MUC_GIA)}")
        ds = [{**d, "id": int(d["id"]), "muc": float(d["muc"] or "nan")} for d in doc]
    for d in ds:  # file sửa tay sai thì báo rõ dòng nào, không để trang sập vì KeyError/None
        if None in d.values() or d["chieu"] not in CHIEU or not MAU_MA_MUC.fullmatch(d["ma"]) or not d["muc"] > 0:
            raise ValueError(f"muc_gia.csv dòng số {d['id']}: mã, chiều (duoi/tren) hoặc mức giá sai hay thiếu ô")
    return ds


def ghi_muc_gia(ds, file=None):
    """Ghi tạm rồi đổi tên (không để lại file ghi dở); bản trước giữ ở .csv.bak để hoàn tác 1 bước."""
    file = file or FILE_MUC_GIA
    tam = file.with_suffix(".tmp")
    with open(tam, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, COT_MUC_GIA)
        w.writeheader()
        w.writerows({k: d[k] for k in COT_MUC_GIA} for d in ds)
    if file.exists():
        shutil.copy2(file, file.with_suffix(".csv.bak"))
    tam.replace(file)


def doc_form_muc(form):
    """Form web {tên: [giá trị]} -> (mức, lỗi). Giá như ô nhập giá ở Danh mục: dưới 100 là nghìn đồng ('0,87' = 870 đ); HĐTL
    nhập điểm (1.858,5 hoặc 1858.5)."""
    lay = lambda k: (form.get(k) or [""])[0].strip()
    ma, chieu = lay("ma").upper(), lay("chieu")
    loi = []
    if not MAU_MA_MUC.fullmatch(ma):
        loi.append("mã phải là CW (CVPB2615), cổ phiếu (VPB), ETF (E1VFVN30, FUE...) hoặc HĐTL (VN30F1M, 41I1GB000)")
    if chieu not in CHIEU:
        loi.append("chiều phải là 'xuống tới' hoặc 'lên tới'")
    chuoi = lay("muc").replace(" ", "")
    try:
        if he_so_cua(ma) > 1:  # HĐTL: điểm; dấu chấm hàng nghìn kiểu Việt Nam (1.858,5) -> 1858.5
            muc = float(chuoi.replace(".", "").replace(",", ".") if "," in chuoi else chuoi)
        else:
            muc = D.doc_gia(chuoi)
    except ValueError:
        return None, loi + ["mức giá phải là số (vd 0,87 hoặc 870 cho CW; 1858,5 cho HĐTL)"]
    if not math.isfinite(muc) or muc <= 0:
        loi.append("mức giá phải lớn hơn 0")
    return {"ma": ma, "chieu": chieu, "muc": muc, "ghi_chu": lay("ghi_chu")[:100]}, loi


def gia_xet(ban_ghi, chieu, he_so=1):
    """Giá dùng để xét 1 mức: giá khớp gần nhất nếu lệnh khớp đó ≥ MIN_GIA_TRI_MUA đồng; khớp lẻ (hoặc chưa khớp) thì giá
    giao dịch được ngay: chiều 'duoi' lấy giá chào bán thấp nhất (mua được), chiều 'tren' lấy giá chờ mua cao nhất (bán
    được) — cùng quy tắc khớp lẻ người dùng chốt 30/10/2026. Không có giá nào -> None."""
    _, khop, so_lenh = ban_ghi
    gia = khop.get("matchPrice") or 0
    if gia and gia * (khop.get("matchVol") or 0) * he_so >= MIN_GIA_TRI_MUA:
        return gia
    if chieu == "duoi":
        ban = C.muc_so_lenh(so_lenh, "askPrices")
        return min(g for g, _ in ban) if ban else None
    mua = C.muc_so_lenh(so_lenh, "bidPrices")
    return max(g for g, _ in mua) if mua else None


def da_cham(gia, chieu, muc):
    return gia is not None and (gia <= muc if chieu == "duoi" else gia >= muc)


def trang_thai_muc(ds, bang_gia):
    """Mỗi mức: {**mức, ma_that, gia, cham, cach (giá / mức − 1)}; mã không có trên bảng giá -> gia None."""
    kq = []
    for m in ds:
        that, bg = ban_ghi_cua(m["ma"], bang_gia)
        gia = gia_xet(bg, m["chieu"], he_so_cua(that)) if bg else None
        kq.append(
            {
                **m,
                "ma_that": that,
                "gia": gia,
                "cham": da_cham(gia, m["chieu"], m["muc"]),
                "cach": gia / m["muc"] - 1 if gia else math.nan,
            }
        )
    return kq


def bang_gia_muc(ds, cho=15):
    """Bảng giá Vietcap cho danh sách mức. Bí danh HĐTL hỏi 2 bước: bản ghi bí danh cho mã KRX (listingInfo.ticker, như
    phai_sinh.bang_gia_krx), rồi hỏi mã KRX; không cần vnstock (lỗi vnstock không làm hỏng việc xét các mức khác)."""
    bg = C.lay_bang_gia(sorted({m["ma"] for m in ds}), cho=cho)
    krx = sorted(
        {
            str(ny.get("ticker"))
            for ma, (ny, *_) in bg.items()
            if MAU_MA_HD_BI_DANH.fullmatch(ma) and MAU_MA_HD_KRX.fullmatch(str(ny.get("ticker") or ""))
        }
    )
    return {**bg, **C.lay_bang_gia(krx, cho=cho)} if krx else bg


def them_muc_gia(form, hom_nay):
    """Thêm 1 mức từ form web. Kiểm mã có trên bảng giá và mức không gấp / chỉ bằng dưới 1/HE_SO_SAI_DON_VI giá hiện tại
    (nghi sai đơn vị). Trả về danh sách lỗi ([] = đã lưu)."""
    muc, loi = doc_form_muc(form)
    ds = doc_muc_gia()
    if not loi and len(ds) >= SO_MUC_TOI_DA:
        loi.append(f"tối đa {SO_MUC_TOI_DA} mức, xóa bớt mức cũ trước")
    if loi or muc is None:
        return loi
    bang_gia = bang_gia_muc([muc], cho=10)
    that, bg = ban_ghi_cua(muc["ma"], bang_gia)
    if bg is None:
        return [f"{muc['ma']} không có trên bảng giá (mã sai hoặc đã hủy niêm yết)"]
    ny, khop, so_lenh = bg
    hien_tai = khop.get("matchPrice") or C.gia_cho_mua(so_lenh) or ny.get("refPrice") or 0
    if hien_tai and not 1 / HE_SO_SAI_DON_VI <= muc["muc"] / hien_tai <= HE_SO_SAI_DON_VI:
        don_vi = "điểm" if he_so_cua(that) > 1 else "đ"
        return [
            f"mức {D.so(muc['muc'])} {don_vi} gấp hoặc chỉ bằng dưới 1/{HE_SO_SAI_DON_VI} giá hiện tại {D.so(hien_tai)} "
            + f"{don_vi}: kiểm tra đơn vị (cổ phiếu 24,5 hoặc 24500; CW 0,87 hoặc 870)"
        ]
    # không cấp lại id đã chạm hôm nay (xóa mức rồi thêm mức mới: mức mới nhận nhầm 'đã chạm' của mức cũ — rà soát 31/10/2026)
    id_cu = [d["id"] for d in ds] + [int(k) for k in doc_da_cham(hom_nay.isoformat())]
    ghi_muc_gia(ds + [{**muc, "id": max(id_cu, default=0) + 1, "ngay_tao": hom_nay.isoformat()}])
    return []


def xoa_muc_gia(id_muc):
    """Xóa 1 mức. Trả về lỗi hoặc ""."""
    ds = doc_muc_gia()
    con_lai = [d for d in ds if d["id"] != id_muc]
    if len(con_lai) == len(ds):
        return f"không có mức số {id_muc}"
    ghi_muc_gia(con_lai)
    return ""


def doc_da_cham(ngay):
    """{id mức (chuỗi): {ma, chieu, muc, gia, luc lần đầu chạm, da_gui}} trong ngày `ngay`; chưa có -> {}."""
    file = THU_MUC_CHAM / f"muc_gia_cham_{ngay}.json"
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}


def ghi_da_cham(ngay, cu):
    tam = THU_MUC_CHAM / f"muc_gia_cham_{ngay}.tmp"
    tam.write_text(json.dumps(cu, ensure_ascii=False), encoding="utf-8")
    tam.replace(THU_MUC_CHAM / f"muc_gia_cham_{ngay}.json")


def noi_dung_cham(m):
    don_vi = "điểm" if he_so_cua(m["ma"]) > 1 else "đ"
    ghi_chu = f" ({m['ghi_chu']})" if m.get("ghi_chu") else ""
    return f"giá {D.so(m['gia'])} {don_vi} đã {CHIEU[m['chieu']]} mức {D.so(m['muc'])} {don_vi}{ghi_chu}"


def kiem_tra_muc_gia(luon=False, luc=None):
    """Lần chạy 5 phút (danh_muc.py gọi): ghi các mức vừa chạm vào muc_gia_cham_<ngày>.json (giữ giờ chạm đầu tiên) và, nếu
    GUI_DISCORD_MUC_GIA, gửi Discord mỗi mức tối đa 1 tin/ngày (gửi lỗi thì lần sau gửi lại). Trả về id các mức mới chạm.
    """
    luc = luc or datetime.now()
    sau_atc = luc.weekday() < 5 and D.GIO_KHOP_LENH[-1][1] < luc.time() <= GIO_XET_ATC
    if not luon and not D.trong_gio_khop_lenh(luc) and not sau_atc:
        return []
    ds = doc_muc_gia()
    if not ds:
        return []
    bang_gia = bang_gia_muc(ds)
    hom_nay = str(luc.date())
    if not any(ny.get("tradingDate") == hom_nay for ny, *_ in bang_gia.values()):
        return []  # ngày nghỉ lễ: bảng giá vẫn là phiên trước
    cu = doc_da_cham(hom_nay)
    moi = [m for m in trang_thai_muc(ds, bang_gia) if m["cham"] and str(m["id"]) not in cu]
    for m in moi:
        cu[str(m["id"])] = {k: m[k] for k in ("ma", "chieu", "muc", "gia", "ghi_chu")} | {"luc": f"{luc:%H:%M}"}
    if moi:
        ghi_da_cham(hom_nay, cu)
        print(f"{luc:%d/%m %H:%M} Giá chạm {len(moi)} mức đã đặt: " + ", ".join(m["ma"] for m in moi))
    chua_gui = {k: m for k, m in cu.items() if not m.get("da_gui")}
    if GUI_DISCORD_MUC_GIA and chua_gui:
        url = C.doc_env().get("DISCORD_WEBHOOK_URL", "")
        if not url:
            print(
                f"{luc:%d/%m %H:%M} [!] Có {len(chua_gui)} mức giá đã chạm nhưng chưa có DISCORD_WEBHOOK_URL trong .env"
            )
            return [m["id"] for m in moi]
        tin = f"**🔔 Giá chạm mức bạn đặt** ({luc:%H:%M %d/%m})\n" + "\n".join(
            f"🔔 **{m['ma']}** lúc {m['luc']}: {noi_dung_cham(m)}" for m in chua_gui.values()
        )
        for doan in D.chia_tin(tin):
            D.gui_discord(doan, url)  # lỗi mạng -> báo lỗi; chưa đánh dấu da_gui nên lần sau gửi lại
        for k in chua_gui:
            cu[k]["da_gui"] = True
        ghi_da_cham(hom_nay, cu)
    return [m["id"] for m in moi]
