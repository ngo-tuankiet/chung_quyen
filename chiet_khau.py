"""
chiet_khau.py - ETF đang giao dịch dưới NAV (chiết khấu): so giá chào bán tốt nhất với iNAV (NAV ước tính trong phiên),
chênh lệch giá/NAV trong quá khứ của chính quỹ, mức bám chỉ số tính bằng NAV.

Chạy:   python chiet_khau.py --trong-phien   launchd gọi mỗi 5 phút (kiem_tra_chiet_khau.sh): giữ máy thức 9:00–14:45, ghi iNAV vào
                                             ket_qua/inav_YYYY-MM-DD.csv, báo Discord khi có quỹ đạt ngưỡng.
                                             Ngoài giờ khớp lệnh hoặc ngày nghỉ: thoát ngay.
        Bảng chiết khấu nằm trong báo cáo ETF 9:40 (etf.py dùng các hàm ở đây).
Nguồn:  SSI iBoard: iNAV, NAV T-1 chính thức, 3 bước giá mua/bán của cả rổ ETF trong 1 lần gọi.
        Vietcap IQ: NAV/CCQ hằng ngày từ 09/2024 (trễ ~2 phiên, nhãn ngày lỗi -> lam_sach_nav).
"""

import csv
import json
import math
import re
import subprocess
import sys
from datetime import datetime, time

import pandas as pd

import cw_scanner as C
import danh_muc as D

# ============ CẤU HÌNH ============
URL_SSI_ETF = "https://iboard-query.ssi.com.vn/stock/type/e/hose"
HEADERS_SSI = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://iboard.ssi.com.vn",
    "Referer": "https://iboard.ssi.com.vn/",
}
URL_IQ_QUY = "https://iq.vietcap.com.vn/api/iq-insight-service/v1/funds"  # danh sách quỹ -> organCode
URL_IQ_NAV = URL_IQ_QUY + "/{ma_to_chuc}/nav-history?lengthReport=40"  # lengthReport bị bỏ qua: luôn trả ~2 năm
HEADERS_IQ = {"User-Agent": "Mozilla/5.0", "Referer": "https://trading.vietcap.com.vn/"}
# Báo khi mua ở giá chào bán rồi bán được đúng bằng NAV thì lãi ≥ 2% sau phí mua, phí bán, thuế bán (PHI_GIAO_DICH, THUE_BAN
# ở cw_scanner.py) VÀ lượng chào bán ở các mức giá đạt ngưỡng đó ≥ 5 triệu đồng (lô 100 CCQ lẻ tẻ không đáng công)
NGUONG_LAI_RONG = 0.02
MIN_GIA_TRI_CHAO_BAN = 5_000_000
# Cỡ lệnh của người dùng (< 50 triệu, KE_HOACH Phần 8): xếp hạng ETF tính giá mua bình quân của đúng 1 lệnh cỡ này qua 3 mức
# chào bán — giá chào bán tốt nhất thường chỉ có 1 lô 100 CCQ nên không phải giá trả cho cả lệnh
GIA_TRI_LENH = 50_000_000
# NAV Vietcap gắn sai ngày (vd FUESSVFL 07/04/2026 thật ra là NAV 08/04; E1VFVN30 dòng Chủ nhật 16/11/2025 là NAV thứ Hai):
# tỷ lệ NAV / chỉ số ngày đó lệch trung vị 5 phiên quanh nó > 0,5% -> bỏ. Đo trên NAV thật 09/2024–10/2026 của 19 quỹ:
# ngưỡng 0,5% bắt đủ các lỗi đã biết (lệch 1,2–10,9%) và chỉ bỏ ~20/9.000 ngày (8 ở FUEFCV50, quỹ bám chỉ số nhiễu nhất)
SAI_LECH_NAV_TOI_DA = 0.005
SO_PHIEN_SO_GAI = 5
MAU_MA_QUY = re.compile(r"[A-Z0-9]{3,12}")  # mã do API trả về / URL đưa vào phải đúng dạng này mới dùng
# Cảnh báo trong phiên: chỉ bật khi iNAV của SSI cập nhật trong phiên (iNAV đứng yên mà giá chạy thì "chiết khấu" là ảo).
# Đo phiên 23/10/2026 (ket_qua/inav_2026-10-23.csv): 16 lần ghi 10:09–11:25, iNAV cả 21 quỹ đổi ở mọi lần ghi -> bật.
BAT_CANH_BAO_TRONG_PHIEN = True
# Từ 23/10/2026 (người dùng chốt, thay cảnh báo "lãi ròng nếu về NAV ≥ 2%"): báo khi có ≥ MIN_GIA_TRI_CHAO_BAN đang chào bán
# ở giá ≤ iNAV × (1 − NGUONG_GIAM_SO_INAV), trừ quỹ mà trung vị giá/NAV 1 năm đã ≤ −ngưỡng (FUEIP100 ~−4,6%, FUEFCV50 ~−7,6%:
# rẻ như vậy là bình thường của chúng, không phải bất thường). Mỗi quỹ tối đa 1 tin/ngày.
NGUONG_GIAM_SO_INAV = 0.02
# Máy Mac tự ngủ (chạy pin, ngủ sau 1 phút) làm lỡ lần quét: 23/10/2026 ngủ 08:10–10:06, 13:07–13:53. Người dùng chọn để lịch
# 5 phút giữ máy thức trong khung này (cả nghỉ trưa), mỗi lần thêm GIU_THUC_GIAY > 5 phút để nối liền lần sau
GIU_MAY_THUC = (time(9, 0), time(14, 45))
GIU_THUC_GIAY = 360
FILE_DA_BAO = C.THU_MUC / "canh_bao_chiet_khau.json"
SO_QUY_TUT = 5  # báo cáo: số quỹ tụt sâu nhất so với chỉ số liệt kê


# ============ CÔNG THỨC ============
def lai_rong_neu_ve_nav(gia_mua: float, nav: float, phi: float = C.PHI_GIAO_DICH, thue: float = C.THUE_BAN) -> float:
    """Lãi nếu mua ở gia_mua (trả thêm phí) rồi bán đúng bằng NAV (trừ phí và thuế bán)."""
    return nav * (1 - phi - thue) / (gia_mua * (1 + phi)) - 1


def muc_chao_ban(bg):
    """3 mức chào bán tốt nhất của bản ghi SSI: [(giá, khối lượng)], bỏ mức trống."""
    muc = [(bg.get(f"best{i}Offer") or 0, bg.get(f"best{i}OfferVol") or 0) for i in (1, 2, 3)]
    return [(g, v) for g, v in muc if g > 0 and v > 0]


def gia_mua_lenh(bg, gia_tri=GIA_TRI_LENH):
    """Giá mua bình quân của 1 lệnh gia_tri đồng ăn dần 3 mức chào bán tốt nhất; 3 mức không đủ hàng -> NaN.
    shortcut: không làm tròn lô 100 CCQ (lệch ≤ 1 lô, ~1–3 triệu/50 triệu), đủ cho xếp hạng; cần số chính xác thì làm tròn lô.
    """
    con, ccq = gia_tri, 0.0
    for g, v in muc_chao_ban(bg):
        mua = min(con, g * v)
        con, ccq = con - mua, ccq + mua / g
        if con <= 0:
            return gia_tri / ccq
    return math.nan


def danh_gia_quy(bg):
    """Chiết khấu mua được của 1 quỹ từ bản ghi SSI: so giá chào bán (mua được ngay) với iNAV, không dùng giá khớp cuối
    (quỹ ít giao dịch: giá khớp có thể cũ nhiều tuần). Không có iNAV hoặc không có người bán -> NaN."""
    inav, ban = bg.get("iNAV") or 0, muc_chao_ban(bg)
    kq = {
        "iNAV": inav or math.nan,
        "NAV T-1": bg.get("prevINAV") or math.nan,
        "Giá chào bán": math.nan,
        "KL chào bán": math.nan,
        "Chiết khấu mua được %": math.nan,
        "Lãi ròng nếu về NAV %": math.nan,
        "Mua được đạt ngưỡng (đ)": 0.0,
        "CK 1 lệnh %": math.nan,
    }
    if inav <= 0 or not ban:
        return kq
    gia, kl = ban[0]
    return {
        **kq,
        "Giá chào bán": gia,
        "KL chào bán": kl,
        "Chiết khấu mua được %": round((gia / inav - 1) * 100, 2),
        "Lãi ròng nếu về NAV %": round(lai_rong_neu_ve_nav(gia, inav) * 100, 2),
        "Mua được đạt ngưỡng (đ)": float(sum(g * v for g, v in ban if lai_rong_neu_ve_nav(g, inav) >= NGUONG_LAI_RONG)),
        "CK 1 lệnh %": round((gia_mua_lenh(bg) / inav - 1) * 100, 2),  # NaN nếu 3 mức không đủ 1 lệnh
    }


def gia_tri_duoi_inav(bg, nguong=NGUONG_GIAM_SO_INAV):
    """Tổng giá trị (đồng) đang chào bán ở các mức giá ≤ iNAV × (1 − nguong) trong 3 mức tốt nhất. Không có iNAV -> 0."""
    inav = bg.get("iNAV") or 0
    return float(sum(g * v for g, v in muc_chao_ban(bg) if inav > 0 and g <= inav * (1 - nguong)))


def lam_sach_nav(dong):
    """[{tradingDate, navPerShare}] của Vietcap IQ -> NAV theo ngày giao dịch.
    - Một ngày có 2 số khác nhau: không biết số nào đúng (dữ liệu thật: số sau thường là NAV phiên kế tiếp) -> bỏ ngày đó.
    - Vietcap ghi NAV thứ Sáu vào Chủ nhật và để dòng thứ Sáu lặp số thứ Năm -> dòng Chủ nhật thay dòng thứ Sáu.
    - Bỏ ngày cuối tuần còn lại. Không phụ thuộc thứ tự dòng trả về."""
    theo_ngay = {}
    for x in dong:
        if x.get("navPerShare"):
            theo_ngay.setdefault(pd.Timestamp(x["tradingDate"]), set()).add(float(x["navPerShare"]))
    s = pd.Series({n: v.pop() for n, v in sorted(theo_ngay.items()) if len(v) == 1}, dtype=float)
    s.index = pd.DatetimeIndex(s.index)
    s.index = s.index.where(s.index.dayofweek != 6, s.index - pd.Timedelta(days=2))
    s = s[~s.index.duplicated(keep="last")].sort_index()  # sau khi sắp theo ngày gốc, dòng Chủ nhật đứng sau thứ Sáu
    return s[s.index.dayofweek < 5]


def bo_nav_loi(nav, chi_so):
    """Bỏ ngày NAV gắn sai ngày / nhập sai: tỷ lệ NAV / chỉ số (cùng ngày) lệch trung vị SO_PHIEN_SO_GAI phiên quanh nó
    > SAI_LECH_NAV_TOI_DA. Tỷ lệ đổi hẳn từ 1 ngày (vd quỹ chia lợi tức) thì trung vị đi theo nên giữ; riêng ngày cuối chuỗi
    chưa có phiên sau để xác nhận nên bị bỏ tạm. Ngày không có chỉ số: giữ nguyên."""
    ty_le = (nav / chi_so.reindex(nav.index)).dropna()
    trung_vi = ty_le.rolling(SO_PHIEN_SO_GAI, center=True, min_periods=SO_PHIEN_SO_GAI // 2 + 1).median()
    lech = (ty_le / trung_vi - 1).abs()
    return nav.drop(lech[lech > SAI_LECH_NAV_TOI_DA].index)


def thong_ke_nav(gia, nav, chi_so, ngay, inav=math.nan):
    """gia: giá đóng cửa (đồng, chỉ phiên có khớp: giá cũ không phải giá thật); nav: NAV đã làm sạch; chi_so: chỉ số mô phỏng
    (None nếu chưa rõ); ngay: phiên cuối của lịch thị trường; inav: iNAV hôm nay lúc chạy (SSI) nếu có.
    - Chênh lệch giá/NAV − 1: trung vị, thấp nhất trong 1 năm tới ngày NAV cuối.
    - "CL NAV 1N trước": ở đúng mốc của lợi nhuận giá 1 năm (ngay − 12 tháng) để phép tách mục quỹ tụt khớp nhau.
    - "NAV so CS 1N": lợi nhuận NAV − lợi nhuận chỉ số trên CÙNG 2 ngày; tới hôm nay bằng iNAV (NAV Vietcap trễ ~2 phiên),
      không có iNAV thì tới ngày NAV cuối."""
    kq = {k: math.nan for k in ("CL NAV trung vị 1N %", "CL NAV thấp nhất 1N %", "CL NAV 1N trước %", "NAV so CS 1N")}
    if nav is None or nav.empty:
        return {**kq, "Ngày NAV cuối": ""}
    cuoi, ngay = nav.index[-1], pd.Timestamp(ngay)
    cl = (gia / nav).dropna() - 1  # chỉ ngày có cả giá khớp lẫn NAV
    nam = cl[(cl.index > cuoi - pd.DateOffset(years=1)) & (cl.index <= cuoi)]
    truoc = cl[cl.index <= ngay - pd.DateOffset(months=12)]
    p = lambda x: round(x * 100, 2)
    if len(nam):
        kq["CL NAV trung vị 1N %"], kq["CL NAV thấp nhất 1N %"] = p(nam.median()), p(nam.min())
    if len(truoc):
        kq["CL NAV 1N trước %"] = p(truoc.iloc[-1])
    if chi_so is not None:
        if math.isfinite(inav) and ngay in chi_so.index:
            den, nav_den, cs_den = ngay, inav, chi_so[ngay]
        elif cuoi in chi_so.index:
            den, nav_den, cs_den = cuoi, nav[cuoi], chi_so[cuoi]
        else:
            den = None
        if den is not None:
            goc = pd.concat([nav, chi_so], axis=1, keys=["nav", "cs"], join="inner").dropna()
            goc = goc[goc.index <= den - pd.DateOffset(months=12)]
            if len(goc):
                n0, c0 = goc.iloc[-1]
                kq["NAV so CS 1N"] = p((nav_den / n0 - 1) - (cs_den / c0 - 1))  # điểm %
    return {**kq, "Ngày NAV cuối": str(cuoi.date())}


# ============ LẤY DỮ LIỆU ============
def lay_ssi():
    """{mã: bản ghi SSI iBoard} của cả rổ ETF HOSE (1 lần gọi)."""
    du_lieu = C.tai_json(URL_SSI_ETF, HEADERS_SSI)["data"]
    return {x["stockSymbol"]: x for x in du_lieu if MAU_MA_QUY.fullmatch(x.get("stockSymbol") or "")}


def lay_nav_lich_su(ds_quy):
    """{mã: DataFrame NAV thô [{tradingDate, navPerShare}] hoặc chuỗi lý do lỗi}. Lỗi 1 quỹ không dừng các quỹ khác."""
    ma_to_chuc = {(q.get("ticker") or "").strip(): q["organCode"] for q in C.tai_json(URL_IQ_QUY, HEADERS_IQ)["data"]}
    kq = {}
    for ma in ds_quy:
        if ma not in ma_to_chuc:
            kq[ma] = "Vietcap IQ không có quỹ này"
            continue
        try:
            kq[ma] = C.tai_json(URL_IQ_NAV.format(ma_to_chuc=ma_to_chuc[ma]), HEADERS_IQ)["data"] or []
        except Exception as e:  # ranh giới gọi mạng: lỗi ghi vào báo cáo, không nuốt  # noqa: BLE001
            kq[ma] = f"{type(e).__name__}: {e}"[:150]
    return kq


# ============ BÁO CÁO ============
_p = lambda x: D.pt(x / 100, 1) if math.isfinite(x) else "—"  # 2.51 (%) -> '+2,5%'
_d = lambda x: f"{x:+.1f}".replace(".", ",") if math.isfinite(x) else "—"  # điểm %
_ty = lambda x: f"{x:.2f}".replace(".", ",") if math.isfinite(x) else "—"  # tỷ đồng


def _chua_khop(h, ngay_khop=True):
    """' · 4 phiên chưa khớp (khớp cuối 16/10)' nếu giá khớp của quỹ đã cũ, không thì ''."""
    if not h["Phiên chưa khớp"] > 0:
        return ""
    ngay = (
        f" (khớp cuối {h['Ngày giá cuối'][8:10]}/{h['Ngày giá cuối'][5:7]})" if ngay_khop and h["Ngày giá cuối"] else ""
    )
    return f" · {h['Phiên chưa khớp']:.0f} phiên chưa khớp{ngay}"


def muc_bao_cao(df):
    """Các mục chiết khấu (a) và tụt so với chỉ số (d) cho báo cáo ETF (df: bảng của etf.lap_bang)."""
    quy, cs = df[df["Loại"] == "ETF"], df[df["Loại"] == "Chỉ số"]
    ln_cs = dict(zip(cs["Mã"], cs["1N %"]))
    dat = quy[quy["Mua được đạt ngưỡng (đ)"].fillna(0) >= MIN_GIA_TRI_CHAO_BAN].sort_values(
        "Lãi ròng nếu về NAV %", ascending=False
    )
    tieu_de = (
        f"**💰 Chiết khấu so với NAV** (giá chào bán so với iNAV lúc lập báo cáo; báo khi lãi ròng nếu về NAV "
        f"≥ {NGUONG_LAI_RONG:.0%} và mua được ≥ {D.so(MIN_GIA_TRI_CHAO_BAN / 1e6)} triệu)"
    )
    dong = [
        f"🟢 **{h['Mã']}**: chào bán {D.so(h['Giá chào bán'])} ({_p(h['Chiết khấu mua được %'])} so iNAV {D.so(h['iNAV'])}) · "
        f"lãi ròng {_p(h['Lãi ròng nếu về NAV %'])} · mua được {D.so(h['Mua được đạt ngưỡng (đ)'] / 1e6)} triệu · "
        f"GTGD TB20 {_ty(h['GTGD TB20 (tỷ)'])} tỷ"
        + f" · thường lệch NAV {_p(h['CL NAV trung vị 1N %'])} (trung vị 1 năm)"
        + _chua_khop(h, ngay_khop=False)
        for _, h in dat.iterrows()
    ]
    top = quy.dropna(subset=["Lãi ròng nếu về NAV %"]).sort_values("Lãi ròng nếu về NAV %", ascending=False).head(5)
    bang = D.bang(
        ["Mã", "Chào bán", "iNAV", "CK", "Ròng", "TV 1N"],
        [
            [h["Mã"], D.so(h["Giá chào bán"]), D.so(h["iNAV"]), _p(h["Chiết khấu mua được %"])]
            + [_p(h["Lãi ròng nếu về NAV %"]), _p(h["CL NAV trung vị 1N %"])]
            for _, h in top.iterrows()
        ],
    )
    tut = quy.assign(so_cs=quy["1N %"] - quy["Chỉ số"].map(ln_cs)).dropna(subset=["so_cs"]).sort_values("so_cs")
    tut = tut[tut["so_cs"] < 0].head(SO_QUY_TUT)
    muc_tut = "**📉 Quỹ tụt so với chỉ số 1 năm: do quỹ bám kém hay do giá rời NAV?**\n" + (
        "\n".join(
            f"**{h['Mã']}**: giá {_d(h['so_cs'])} điểm so {h['Chỉ số']} · NAV {_d(h['NAV so CS 1N'])} điểm (bám chỉ số) · "
            f"giá/NAV {_p(h['CL NAV 1N trước %'])} → "
            # giá khớp cũ nhiều phiên so với iNAV hôm nay là "chênh lệch" ảo -> không in
            + (_p((h["Giá"] / h["iNAV"] - 1) * 100) if h["Phiên chưa khớp"] == 0 else "—") + _chua_khop(h)
            for _, h in tut.iterrows()
        )
        or "Không có."
    )
    return [
        tieu_de + "\n" + ("\n".join(dong) if dong else "Không quỹ nào đạt ngưỡng.") + "\n" + bang + "\n" + GHI_CHU,
        muc_tut + "\n" + GHI_CHU_TUT,
    ]


GHI_CHU = (
    "_CK = giá chào bán / iNAV − 1 · Ròng = lãi nếu mua ở giá chào bán rồi bán đúng NAV, sau phí và thuế · "
    "TV 1N = trung vị (giá đóng cửa / NAV − 1) 1 năm của chính quỹ: quỹ luôn chiết khấu thì CK âm chưa chắc là rẻ bất thường_"
)
GHI_CHU_TUT = (
    "_NAV âm nhiều = quỹ bám chỉ số kém (điểm xấu của quỹ, không phải cơ hội). Giá/NAV giảm = giá từng cao hơn NAV nay về gần NAV "
    "hoặc xuống dưới: chỉ phần dưới NAV mới là cơ hội. Mức tụt của giá ≈ phần NAV + phần đổi giá/NAV (lệch thêm khi giá/NAV "
    "từng cao vì 2 phần nhân với nhau, vd FUEVN100 22/10/2026 dư ~1,4 điểm)_"
)


# ============ CẢNH BÁO TRONG PHIÊN ============
def ghi_inav(ssi, luc):
    """Ghi thêm 1 dòng/quỹ vào ket_qua/inav_YYYY-MM-DD.csv (lịch sử iNAV trong phiên: không nguồn nào lưu sẵn)."""
    C.THU_MUC_KET_QUA.mkdir(exist_ok=True)
    tep = C.THU_MUC_KET_QUA / f"inav_{luc.date()}.csv"
    cot = ["Giờ", "Mã", "iNAV", "Giá chào bán", "KL chào bán", "Giá chờ mua", "Giá khớp", "KL khớp"]
    moi = not tep.exists()
    with open(tep, "a", encoding="utf-8-sig" if moi else "utf-8", newline="") as f:
        w = csv.writer(f)
        if moi:
            w.writerow(cot)
        for ma, bg in sorted(ssi.items()):
            w.writerow(
                [f"{luc:%H:%M:%S}", ma, bg.get("iNAV"), bg.get("best1Offer"), bg.get("best1OfferVol")]
                + [bg.get("best1Bid"), bg.get("matchedPrice"), bg.get("nmTotalTradedQty")]
            )


def noi_dung_canh_bao(dat, luc, tham_khao=None):
    """dat: [(mã, danh_gia_quy, giá trị chào bán dưới ngưỡng đ)]; tham_khao: {mã: (trung vị chênh lệch giá/NAV 1 năm %,
    GTGD TB20 tỷ)} từ báo cáo ETF gần nhất."""
    tham_khao = tham_khao or {}
    return f"**🔻 ETF giảm bất thường so với iNAV** ({luc:%H:%M %d/%m})\n" + "\n".join(
        f"🔻 **{ma}**: chào bán {D.so(dg['Giá chào bán'])} × {D.so(dg['KL chào bán'])} CCQ, iNAV {D.so(dg['iNAV'])} "
        f"({_p(dg['Chiết khấu mua được %'])}) · có {D.so(gia_tri / 1e6)} triệu chào bán ở giá ≤ iNAV −{NGUONG_GIAM_SO_INAV:.0%}"
        + (
            f" · thường lệch NAV {_p(tham_khao[ma][0])} (trung vị 1 năm) · GTGD TB20 {_ty(tham_khao[ma][1])} tỷ"
            if ma in tham_khao
            else " · chưa rõ mức thường lệch NAV"
        )
        for ma, dg, gia_tri in dat
    )


def giu_may_thuc(luc=None):
    """Trong GIU_MAY_THUC thứ Hai–Sáu: chặn máy tự ngủ GIU_THUC_GIAY giây (lần chạy 5 phút sau gia hạn tiếp).
    Phiên riêng (start_new_session): launchd giết cả nhóm tiến trình khi lần chạy kết thúc. Không đánh thức được máy đã ngủ;
    gập nắp máy vẫn ngủ. shortcut: ngày lễ trong tuần vẫn giữ thức, cần thì kiểm tra la_ngay_giao_dich trước."""
    luc = luc or datetime.now()
    if luc.weekday() < 5 and GIU_MAY_THUC[0] <= luc.time() <= GIU_MAY_THUC[1]:
        subprocess.Popen(["/usr/bin/caffeinate", "-i", "-t", str(GIU_THUC_GIAY)], start_new_session=True)


def kiem_tra_trong_phien(luon=False, luc=None):
    """Lần chạy 5 phút: ghi iNAV; nếu đã bật cảnh báo thì báo Discord quỹ giảm bất thường so với iNAV (mỗi quỹ tối đa 1 tin/ngày).
    Trả về danh sách mã đã báo."""
    luc = luc or datetime.now()
    if not luon and not D.trong_gio_khop_lenh(luc):
        return []
    ssi = lay_ssi()
    if not any(bg.get("tradingDate") == f"{luc:%Y%m%d}" for bg in ssi.values()):
        return []  # ngày nghỉ lễ / Tết: SSI vẫn trả dữ liệu phiên trước
    ghi_inav(ssi, luc)
    if not BAT_CANH_BAO_TRONG_PHIEN:
        return []
    hom_nay = str(luc.date())
    da_bao = json.loads(FILE_DA_BAO.read_text(encoding="utf-8")) if FILE_DA_BAO.exists() else {}
    da_bao = {ma: ngay for ma, ngay in da_bao.items() if ngay == hom_nay}
    gia_tri = {ma: gia_tri_duoi_inav(bg) for ma, bg in sorted(ssi.items()) if ma not in da_bao}
    gia_tri = {ma: g for ma, g in gia_tri.items() if g >= MIN_GIA_TRI_CHAO_BAN}
    if not gia_tri:
        return []
    from etf import doc_ket_qua  # nhập ở đây để tránh vòng lặp import (etf.py dùng chiet_khau.py)

    df, _ = doc_ket_qua()
    tham_khao = (
        {h["Mã"]: (h["CL NAV trung vị 1N %"], h["GTGD TB20 (tỷ)"]) for _, h in df.iterrows()} if df is not None else {}
    )
    # quỹ thường đã rẻ hơn NAV từ ngưỡng trở lên: không phải bất thường. Chưa rõ mức thường (NaN, chưa có báo cáo) -> vẫn báo
    dat = [
        (ma, danh_gia_quy(ssi[ma]), g)
        for ma, g in gia_tri.items()
        if not tham_khao.get(ma, (math.nan,))[0] <= -NGUONG_GIAM_SO_INAV * 100
    ]
    if dat:
        url = C.doc_env().get("DISCORD_WEBHOOK_URL", "")
        if not url:
            print(
                f"{luc:%d/%m %H:%M} [!] Có {len(dat)} quỹ giảm bất thường nhưng chưa có DISCORD_WEBHOOK_URL trong .env"
            )
            return []  # không lưu trạng thái: có webhook rồi thì lần sau vẫn báo
        for tin in D.chia_tin(noi_dung_canh_bao(dat, luc, tham_khao)):
            D.gui_discord(tin, url)
        print(f"{luc:%d/%m %H:%M} Đã báo {len(dat)} quỹ giảm bất thường: " + ", ".join(ma for ma, *_ in dat))
        FILE_DA_BAO.write_text(
            json.dumps({**da_bao, **{ma: hom_nay for ma, *_ in dat}}), encoding="utf-8"
        )  # lưu sau khi gửi được: gửi lỗi thì lần sau gửi lại
    return [ma for ma, *_ in dat]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]  # stdout luôn là TextIOWrapper
    if "--trong-phien" in sys.argv:
        giu_may_thuc()
        kiem_tra_trong_phien(luon="--luon" in sys.argv)
