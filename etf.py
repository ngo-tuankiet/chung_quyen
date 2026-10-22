"""
etf.py - Theo dõi các quỹ ETF niêm yết trên HOSE. Giai đoạn 1: lợi nhuận, xu hướng, RSI, rủi ro, thanh khoản, dòng tiền.
Chưa có: P/E–P/B chỉ số, NAV/premium, chấm điểm (các giai đoạn sau, xem KE_HOACH.md Phần 8).

Chạy:   python etf.py               lưu ket_qua/etf_YYYY-MM-DD.csv rồi gửi báo cáo lên Discord (DISCORD_WEBHOOK_URL trong .env)
        python etf.py --no-discord  chỉ in báo cáo ra màn hình
        python etf.py --bao-loi     gửi tin "báo cáo ETF lỗi" (chay_etf_tu_dong.sh gọi khi lỗi cả 3 lần, lý do trong QUET_LOI)
Nguồn:  danh sách ETF, giá ngày của quỹ (vnstock, KBS) và chỉ số (vnstock, VCI); giá, khối ngoại, số CCQ hôm nay (bảng giá Vietcap).
"""

import math
import os
import sys
from datetime import date, datetime

import pandas as pd
from vnstock import Listing

import cw_scanner as C
import danh_muc as D

# ============ CẤU HÌNH ============
# Chỉ số mà từng quỹ mô phỏng. Quỹ không có ở đây (vd FUEVN50G chưa tra được chỉ số, quỹ mới niêm yết): báo cáo cảnh báo,
# so tạm với VNINDEX. Quỹ mới -> thêm vào đúng nhóm.
QUY_THEO_CHI_SO = {
    "VN30": ["E1VFVN30", "FUESSV30", "FUEKIV30", "FUEMAV30"],
    "VN100": ["FUEVN100", "FUEIP100"],
    "VNX50": ["FUESSV50", "FUETCC50", "FUEFCV50"],
    "VNDIAMOND": ["FUEVFVND", "FUEKIVND", "FUEMAVND", "FUEABVND", "FUEBFVND", "FUETPVND"],
    "VNFINLEAD": ["FUESSVFL"],
    "VNFINSELECT": ["FUEKIVFS"],
    "VNMID": ["FUEDCMID"],
    "VNMITECH": ["FUEMITEC"],
    "VNSHINE": ["FUEPHVNS"],
}
TEN_TRONG_VNSTOCK = {"VNMID": "VNMIDCAP"}  # vnstock đặt tên khác HOSE
THI_TRUONG = "VNINDEX"
HE_SO_CHI_SO = 1000  # vnstock (VCI) trả điểm chỉ số chia 1.000 (VN30 1.892,98 điểm -> 1.89298)
PHI_QUAN_LY = {}  # %/năm theo bản cáo bạch từng quỹ, vd {"E1VFVN30": 0.65}. Chưa điền -> "—" (không đoán số)
SO_NGAY_LICH_SU = 730  # 2 năm: đủ MA200 và lợi nhuận 1 năm
KY_LOI_NHUAN = {"1T": 1, "3T": 3, "6T": 6, "1N": 12}  # tên kỳ -> số tháng lịch
MA_NGAN, MA_DAI = 50, 200
SO_PHIEN_RSI = 14
SO_PHIEN_GTGD = 20
MIN_PHIEN_KHOP = 200  # < 200 phiên có khớp lệnh trong 1 năm (mới niêm yết / ít giao dịch): chỉ số kỹ thuật kém tin cậy
SO_QUY_NOI_BAT = 5  # báo cáo: số quỹ thanh khoản cao nhất
SO_DONG_DONG_TIEN = 5  # báo cáo: số quỹ đổi số CCQ lưu hành / khối ngoại mua-bán ròng liệt kê

COT_CHU = ["Loại", "Mã", "Chỉ số", "Xu hướng", "Cảnh báo", "Ngày giá cuối"]
COT = (
    COT_CHU[:3]
    + ["Giá"]
    + [f"{k} %" for k in KY_LOI_NHUAN]
    + [
        "Xu hướng",
        "MA50",
        "MA200",
        "RSI14",
        "Biến động năm %",
        "Giảm sâu nhất 1N %",
        "Cách đỉnh 1N %",
        "GTGD TB20 (tỷ)",
        "GTGD hôm nay (tỷ)",
        "Khối ngoại ròng (tỷ)",
        "CCQ lưu hành",
        "Phiên khớp 1N",
        "Phí quản lý %",
        "Cảnh báo",
        "Ngày giá cuối",
    ]
)
MUI_TEN = {"Tăng": "↑", "Giảm": "↓", "Đi ngang": "→"}


# ============ CÔNG THỨC (chuỗi giá: pandas Series, chỉ mục = ngày, tăng dần) ============
def loi_nhuan(gia, ngay, so_thang):
    """Lợi nhuận từ giá đóng cửa phiên gần nhất trước/đúng mốc (ngày − so_thang tháng lịch) tới giá cuối.
    Chưa có giá ở mốc (quỹ niêm yết sau mốc) -> NaN."""
    truoc = gia[gia.index <= pd.Timestamp(ngay) - pd.DateOffset(months=so_thang)]
    return gia.iloc[-1] / truoc.iloc[-1] - 1 if len(truoc) else math.nan


def rsi(gia, n=SO_PHIEN_RSI):
    """RSI của Wilder: trung bình tăng/giảm của n phiên đầu là trung bình cộng, sau đó (TB cũ × (n − 1) + phiên mới) / n."""
    thay_doi = gia.diff().dropna().tolist()
    if len(thay_doi) < n:
        return math.nan
    tang = sum(max(x, 0) for x in thay_doi[:n]) / n
    giam = sum(max(-x, 0) for x in thay_doi[:n]) / n
    for x in thay_doi[n:]:
        tang, giam = (tang * (n - 1) + max(x, 0)) / n, (giam * (n - 1) + max(-x, 0)) / n
    if giam == 0:
        return 100.0 if tang > 0 else math.nan
    return 100 - 100 / (1 + tang / giam)


def xu_huong(gia):
    """'Tăng' khi giá và MA50 cùng trên MA200, 'Giảm' khi cùng dưới, còn lại 'Đi ngang'. Chưa đủ 200 phiên -> ''."""
    if len(gia) < MA_DAI:
        return ""
    p, ngan, dai = gia.iloc[-1], gia.tail(MA_NGAN).mean(), gia.tail(MA_DAI).mean()
    return "Tăng" if p > dai and ngan > dai else "Giảm" if p < dai and ngan < dai else "Đi ngang"


def bien_dong_nam(gia):
    """Độ lệch chuẩn lợi suất log ngày (tối đa 250 phiên gần nhất) × √250, như HV của CW."""
    lr = (gia / gia.shift(1)).apply(math.log).dropna().tail(C.SO_PHIEN_DO_BIEN_DONG)
    return lr.std() * math.sqrt(C.SO_PHIEN_MOT_NAM) if len(lr) > 1 else math.nan


def giam_tu_dinh(gia, ngay):
    """(mức giảm sâu nhất từ đỉnh, mức cách đỉnh hiện tại) trong 1 năm tới `ngay`, đều ≤ 0. Không có giá -> NaN."""
    g = gia[gia.index > pd.Timestamp(ngay) - pd.DateOffset(years=1)]
    if g.empty:
        return math.nan, math.nan
    sut = g / g.cummax() - 1
    return sut.min(), sut.iloc[-1]


def gtgd_trung_binh(gia, kl, lich):
    """Giá trị giao dịch TB (đồng/phiên) của SO_PHIEN_GTGD phiên gần nhất theo lịch thị trường; phiên không khớp tính 0."""
    phien = lich[-SO_PHIEN_GTGD:]
    return (gia * kl).reindex(phien, fill_value=0).sum() / len(phien)


def chuoi_gia(df, he_so=1.0):
    """DataFrame giá ngày của vnstock -> (giá đóng cửa × he_so, khối lượng), chỉ mục = ngày; bỏ phiên không khớp lệnh."""
    df = df[df["volume"] > 0]
    ngay = pd.DatetimeIndex(df["time"]).tz_localize(None).normalize()
    return pd.Series(df["close"].to_numpy(float) * he_so, ngay), pd.Series(df["volume"].to_numpy(float), ngay)


def chi_so_gia(gia, ngay):
    """Các chỉ số tính từ chuỗi giá (dùng cho cả quỹ và chỉ số), phần trăm làm tròn 2 số lẻ."""
    p = lambda x: round(x * 100, 2) if math.isfinite(x) else math.nan
    sut, cach_dinh = giam_tu_dinh(gia, ngay)
    return {
        **{f"{k} %": p(loi_nhuan(gia, ngay, m)) for k, m in KY_LOI_NHUAN.items()},
        "Giá": gia.iloc[-1],
        "Xu hướng": xu_huong(gia),
        "MA50": gia.tail(MA_NGAN).mean() if len(gia) >= MA_NGAN else math.nan,
        "MA200": gia.tail(MA_DAI).mean() if len(gia) >= MA_DAI else math.nan,
        "RSI14": round(rsi(gia), 1),
        "Biến động năm %": p(bien_dong_nam(gia)),
        "Giảm sâu nhất 1N %": p(sut),
        "Cách đỉnh 1N %": p(cach_dinh),
    }


# ============ LẬP BẢNG ============
def chi_so_cua(ma):
    return next((cs for cs, ds in QUY_THEO_CHI_SO.items() if ma in ds), "")


def lap_bang(ds_quy, ls_quy, ls_cs, bang_gia, hom_nay):
    """Bảng kết quả (mỗi dòng 1 chỉ số hoặc 1 quỹ) + ngày của giá cuối.
    ls_quy / ls_cs: {mã: DataFrame vnstock hoặc chuỗi lý do lỗi}; bang_gia: kết quả cw_scanner.lay_bang_gia.
    Một mã lỗi chỉ thành dòng cảnh báo, không dừng cả bảng."""
    lich = chuoi_gia(ls_cs[THI_TRUONG])[0].index
    ngay = lich[-1]
    dong, gia_cs = [], {}
    for cs, df in ls_cs.items():
        if isinstance(df, str):
            dong.append({"Loại": "Chỉ số", "Mã": cs, "Cảnh báo": f"không lấy được lịch sử chỉ số: {df}"})
            continue
        gia_cs[cs] = chuoi_gia(df, HE_SO_CHI_SO)[0]
        dong.append(
            {"Loại": "Chỉ số", "Mã": cs, "Chỉ số": cs, **chi_so_gia(gia_cs[cs].loc[:ngay], ngay), "Cảnh báo": ""}
        )
    for ma in ds_quy:
        cs, canh_bao = chi_so_cua(ma), []
        if not cs:
            canh_bao.append(f"chưa có trong danh sách chỉ số mô phỏng (QUY_THEO_CHI_SO), so tạm với {THI_TRUONG}")
        h = {"Loại": "ETF", "Mã": ma, "Chỉ số": cs or THI_TRUONG}
        df = ls_quy.get(ma, "không có dữ liệu")
        if isinstance(df, str) or ma not in bang_gia:
            ly_do = df if isinstance(df, str) else "không có trên bảng giá Vietcap"
            dong.append({**h, "Cảnh báo": "; ".join(canh_bao + [f"không lấy được dữ liệu: {ly_do}"])})
            continue
        ny, khop, _ = bang_gia[ma]
        gia_nay = C.gia_hien_tai(ny, khop)
        he_so = 10 ** round(math.log10(gia_nay / float(df["close"].iloc[-1])))  # vnstock trả nghìn đồng -> đồng
        gia, kl = chuoi_gia(df, he_so)
        gia, kl = gia.loc[:ngay], kl.loc[:ngay]
        hom_nay_co_khop = ny.get("tradingDate") == str(hom_nay) and khop.get("matchPrice")
        if hom_nay_co_khop and ngay.date() == hom_nay and gia.index[-1] < ngay:  # lịch sử chưa có phiên hôm nay
            gia = pd.concat([gia, pd.Series([float(khop["matchPrice"])], [ngay])])
            kl = pd.concat([kl, pd.Series([float(khop.get("accumulatedVolume") or 0)], [ngay])])
        so_phien = int((gia.index > ngay - pd.DateOffset(years=1)).sum())
        if so_phien < MIN_PHIEN_KHOP:
            canh_bao.append(f"chỉ {so_phien} phiên có khớp lệnh trong 1 năm: chỉ số kỹ thuật kém tin cậy")
        dong.append(
            {
                **h,
                **chi_so_gia(gia, ngay),
                "GTGD TB20 (tỷ)": round(gtgd_trung_binh(gia, kl, lich) / 1e9, 3),
                # Vietcap: accumulatedValue theo triệu đồng; khối ngoại theo đồng
                "GTGD hôm nay (tỷ)": round(khop.get("accumulatedValue", 0) / 1e3, 3) if hom_nay_co_khop else 0.0,
                "Khối ngoại ròng (tỷ)": (
                    round(((khop.get("foreignBuyValue") or 0) - (khop.get("foreignSellValue") or 0)) / 1e9, 3)
                    if ny.get("tradingDate") == str(hom_nay)
                    else math.nan
                ),
                "CCQ lưu hành": ny.get("listedShare", math.nan),
                "Phiên khớp 1N": so_phien,
                "Phí quản lý %": PHI_QUAN_LY.get(ma, math.nan),
                "Cảnh báo": "; ".join(canh_bao),
                "Ngày giá cuối": str(gia.index[-1].date()),
            }
        )
    df = pd.DataFrame(dong).reindex(columns=COT)  # dòng lỗi thiếu cột số -> NaN
    df[COT_CHU] = df[COT_CHU].fillna("")
    return df, ngay.date()


# ============ LƯU / ĐỌC ============
def doc_ket_qua(truoc=None):
    """(bảng, ngày) của file ket_qua/etf_*.csv mới nhất (truoc: mới nhất có ngày < truoc). Chưa có -> (None, None)."""
    tep = [f for f in sorted(C.THU_MUC_KET_QUA.glob("etf_*.csv")) if truoc is None or f.stem[4:] < str(truoc)]
    if not tep:
        return None, None
    df = pd.read_csv(tep[-1], encoding="utf-8-sig")
    df[COT_CHU] = df[COT_CHU].fillna("")
    return df, date.fromisoformat(tep[-1].stem[4:])


# ============ BÁO CÁO ============
_p = lambda x: D.pt(x / 100, 1) if math.isfinite(x) else "—"  # 2.51 (%) -> '+2,5%'
_d = lambda x: f"{x:+.1f}".replace(".", ",") if math.isfinite(x) else "—"  # chênh lệch, điểm %
_ty = lambda x: (f"{x:.2f}" if abs(x) < 1 else f"{x:.1f}").replace(".", ",") if math.isfinite(x) else "—"
GHI_CHU = (
    "_GTGD = giá trị giao dịch TB 20 phiên (tỷ đ) · XH = xu hướng: ↑ giá và MA50 trên MA200, ↓ cùng dưới, → còn lại · "
    "so CS = lợi nhuận 1 năm của quỹ − của chỉ số (điểm %; chỉ số giá chưa gồm cổ tức nên quỹ thường cao hơn một chút)_"
)


def bao_cao(df, df_truoc, luc, ngay_gia):
    """Nội dung báo cáo ETF (markdown Discord, bảng chữ đều cột; chia tin bằng danh_muc.chia_tin)."""
    cs, quy = df[df["Loại"] == "Chỉ số"], df[df["Loại"] == "ETF"]
    ln_cs = dict(zip(cs["Mã"], cs["1N %"]))
    phan = [f"**📊 Báo cáo ETF** ({luc:%H:%M %d/%m}) · giá đến phiên {ngay_gia:%d/%m}"]
    phan.append(
        "**Chỉ số**\n"
        + D.bang(
            ["Chỉ số", *KY_LOI_NHUAN, "XH"],
            [
                [h["Mã"], *(_p(h[f"{k} %"]) for k in KY_LOI_NHUAN), MUI_TEN.get(h["Xu hướng"], "—")]
                for _, h in cs.iterrows()
            ],
        )
    )
    top = quy.sort_values("GTGD TB20 (tỷ)", ascending=False).head(SO_QUY_NOI_BAT)
    phan.append(
        f"**Top {len(top)} quỹ thanh khoản**\n"
        + D.bang(
            ["Mã", "GTGD", "1T", "3T", "1N", "RSI", "XH"],
            [
                [h["Mã"], _ty(h["GTGD TB20 (tỷ)"]), _p(h["1T %"]), _p(h["3T %"]), _p(h["1N %"])]
                + [f"{h['RSI14']:.0f}" if math.isfinite(h["RSI14"]) else "—", MUI_TEN.get(h["Xu hướng"], "—")]
                for _, h in top.iterrows()
            ],
        )
    )
    if df_truoc is not None:
        xh_truoc = dict(zip(df_truoc["Mã"], df_truoc["Xu hướng"]))
        doi = [
            f"{h['Mã']}: {xh_truoc[h['Mã']]} → **{h['Xu hướng']}**"
            for _, h in df.iterrows()
            if h["Xu hướng"] and xh_truoc.get(h["Mã"]) and xh_truoc[h["Mã"]] != h["Xu hướng"]
        ]
        phan.append("**🔄 Đổi xu hướng so với phiên trước**\n" + ("\n".join(doi) if doi else "Không có."))
        ccq = quy.merge(df_truoc[["Mã", "CCQ lưu hành"]], on="Mã", suffixes=("", " trước"))
        ccq["Đổi"] = ccq["CCQ lưu hành"] - ccq["CCQ lưu hành trước"]
        ccq = ccq[ccq["Đổi"].fillna(0) != 0]
        ccq = ccq.reindex((ccq["Đổi"] / ccq["CCQ lưu hành trước"]).abs().sort_values(ascending=False).index)
        if len(ccq):
            phan.append(
                "**🏦 Số chứng chỉ quỹ lưu hành thay đổi** (tăng = nhà đầu tư lớn góp thêm tiền vào quỹ, giảm = rút ra)\n"
                + "\n".join(
                    f"{h['Mã']}: {'+' if h['Đổi'] > 0 else '−'}{D.so(abs(h['Đổi']))} CCQ "
                    f"({D.pt(h['Đổi'] / h['CCQ lưu hành trước'], 1)}, ≈ {_ty(h['Đổi'] * h['Giá'] / 1e9)} tỷ)"
                    for _, h in ccq.head(SO_DONG_DONG_TIEN).iterrows()
                )
            )
    kn = quy[quy["Khối ngoại ròng (tỷ)"].fillna(0) != 0].sort_values("Khối ngoại ròng (tỷ)")
    if len(kn):
        dong = lambda d: ", ".join(f"{h['Mã']} {_ty(h['Khối ngoại ròng (tỷ)'])}" for _, h in d.iterrows()) or "—"
        mua, ban = kn[kn["Khối ngoại ròng (tỷ)"] > 0], kn[kn["Khối ngoại ròng (tỷ)"] < 0]
        phan.append(
            "**🌏 Khối ngoại hôm nay (tỷ đ)**\n"
            f"Mua ròng: {dong(mua.iloc[::-1].head(SO_DONG_DONG_TIEN))}\nBán ròng: {dong(ban.head(SO_DONG_DONG_TIEN))}"
        )
    for ten, nhom in quy[quy["Chỉ số"].map(lambda c: len(QUY_THEO_CHI_SO.get(c, [])) > 1)].groupby(
        "Chỉ số", sort=False
    ):
        nhom = nhom.sort_values("GTGD TB20 (tỷ)", ascending=False)
        phan.append(
            f"**Cùng mô phỏng {ten}: chọn quỹ nào?**\n"
            + D.bang(
                ["Quỹ", "GTGD", "Phiên", "1N", "so CS"],
                [
                    [
                        h["Mã"],
                        _ty(h["GTGD TB20 (tỷ)"]),
                        D.so(h["Phiên khớp 1N"]) if math.isfinite(h["Phiên khớp 1N"]) else "—",
                    ]
                    + [_p(h["1N %"]), _d(h["1N %"] - ln_cs.get(ten, math.nan))]
                    for _, h in nhom.iterrows()
                ],
            )
        )
    canh_bao = [f"⚠ **{h['Mã']}**: {h['Cảnh báo']}" for _, h in df.iterrows() if h["Cảnh báo"]]
    if canh_bao:
        phan.append("**Cảnh báo dữ liệu**\n" + "\n".join(canh_bao))
    phan.append(GHI_CHU)
    return "\n\n".join(phan)


# ============ CHẠY ============
def lay_du_lieu(ds_quy):
    """Lịch sử giá các quỹ và chỉ số cần so: {mã: DataFrame} hoặc {mã: lý do lỗi}. Lỗi 1 mã không dừng các mã khác."""
    # VNINDEX là lịch phiên của mọi phép tính: lỗi thì dừng hẳn (lỗi nổi lên, chay_etf_tu_dong.sh thử lại / báo lỗi)
    ls_quy, ls_cs = {}, {THI_TRUONG: C.lay_gia_dong_cua(THI_TRUONG, SO_NGAY_LICH_SU, "VCI", floating=6)}
    for cs in [cs for cs, ds in QUY_THEO_CHI_SO.items() if set(ds) & set(ds_quy)]:
        try:
            ls_cs[cs] = C.lay_gia_dong_cua(TEN_TRONG_VNSTOCK.get(cs, cs), SO_NGAY_LICH_SU, "VCI", floating=6)
        except Exception as e:  # ranh giới gọi vnstock: lỗi được ghi vào báo cáo, không nuốt  # noqa: BLE001
            ls_cs[cs] = f"{type(e).__name__}: {e}"[:150]
    for ma in ds_quy:
        try:
            ls_quy[ma] = C.lay_gia_dong_cua(ma, SO_NGAY_LICH_SU)
        except Exception as e:  # noqa: BLE001
            ls_quy[ma] = f"{type(e).__name__}: {e}"[:150]
    return ls_quy, ls_cs


def chay(gui=True, luc=None):
    luc = luc or datetime.now()
    C.dang_nhap()
    ds_quy = sorted(Listing(source="VCI").symbols_by_group("ETF"))
    print(f"Tìm thấy {len(ds_quy)} ETF đang niêm yết.")
    bang_gia = C.lay_bang_gia(ds_quy)
    ls_quy, ls_cs = lay_du_lieu(ds_quy)
    df, ngay_gia = lap_bang(ds_quy, ls_quy, ls_cs, bang_gia, luc.date())
    C.THU_MUC_KET_QUA.mkdir(exist_ok=True)
    tep = C.THU_MUC_KET_QUA / f"etf_{luc.date()}.csv"
    df.to_csv(tep, index=False, encoding="utf-8-sig")  # chạy lại trong ngày: ghi đè đúng file của ngày đó
    noi_dung = bao_cao(df, doc_ket_qua(truoc=luc.date())[0], luc, ngay_gia)
    print(f"Đã lưu {tep}\n\n{noi_dung}")
    if gui:
        url = C.doc_env().get("DISCORD_WEBHOOK_URL", "")
        if not url:
            print("[!] Chưa có DISCORD_WEBHOOK_URL trong .env, không gửi báo cáo")
            return
        tin = D.chia_tin(noi_dung)
        for t in tin:
            D.gui_discord(t, url)
        print(f"Đã gửi báo cáo ETF ({len(tin)} tin)")


def gui_loi(ly_do, luc=None):
    """Báo lên Discord khi cả lần chạy lỗi (chay_etf_tu_dong.sh gọi sau khi đã thử lại)."""
    luc = luc or datetime.now()
    url = C.doc_env().get("DISCORD_WEBHOOK_URL", "")
    if url:
        D.gui_discord(f"⚠ **Báo cáo ETF hôm nay lỗi** ({luc:%H:%M %d/%m}): {ly_do[:300] or 'không rõ lý do'}", url)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--bao-loi" in sys.argv:
        gui_loi(os.environ.get("QUET_LOI", ""))
    else:
        chay(gui="--no-discord" not in sys.argv)
