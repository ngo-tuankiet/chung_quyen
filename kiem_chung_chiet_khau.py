"""
kiem_chung_chiet_khau.py - Kiểm chứng ngưỡng chiết khấu NAV của ETF (KE_HOACH.md Phần 8) bằng lịch sử từ 09/2024:
những phiên giá đóng cửa đủ dưới NAV để lãi ròng nếu về NAV ≥ chiet_khau.NGUONG_LAI_RONG, sau 1/5/10/20 phiên chênh lệch
giá/NAV có thu hẹp không, lãi thực tế sau phí và thuế nếu mua rồi bán ở giá thị trường; so với mua ở phiên bất kỳ.

Chạy:   python kiem_chung_chiet_khau.py   lưu ket_qua/kiem_chung_chiet_khau_YYYY-MM-DD.md (bảng kết quả) và
                                          ket_qua/kiem_chung_chiet_khau_su_kien_YYYY-MM-DD.csv (từng lệnh độc lập)
Chỉ đọc dữ liệu (giá và chỉ số vnstock VCI, NAV Vietcap IQ qua etf.lay_nav), không gửi Discord, không đổi ngưỡng đang chạy.
Giả định (ghi lại trong báo cáo):
- Tín hiệu phiên T: phiên T có khớp, có NAV(T) và lai_rong_neu_ve_nav(giá đóng cửa T, NAV T) ≥ ngưỡng.
- Kịch bản A "cùng phiên": coi iNAV lúc ATC ≈ NAV(T), mua ở giá đóng cửa T (lạc quan: quỹ mỏng giá đóng cửa thường là 1 lô 100 CCQ).
- Kịch bản B "trễ 1 phiên": không cần iNAV (sáng T+1 đã có NAV(T) = NAV T-1 của SSI), mua ở giá đóng cửa phiên có khớp kế tiếp.
- Bán ở giá đóng cửa phiên có khớp đầu tiên cách phiên mua ≥ N phiên của lịch thị trường (quỹ không khớp: giá cũ không bán được).
"""

import math
import sys
from datetime import date

import pandas as pd
from vnstock import Listing

import chiet_khau as CK
import cw_scanner as C
import danh_muc as D
import etf as E

# ============ CẤU HÌNH ============
SO_PHIEN_GIU = (1, 5, 10, 20)
SO_NGAY_LICH_SU = (
    800  # NAV Vietcap IQ bắt đầu 24/09/2024: lấy giá và chỉ số dư từ trước đó (bo_nav_loi cần chỉ số cùng ngày)
)
KICH_BAN = {"A": 0, "B": 1}  # số phiên có khớp giữa phiên tín hiệu và phiên mua
TEN_KICH_BAN = {"A": "A cùng phiên (giả định có iNAV)", "B": "B trễ 1 phiên (không cần iNAV)"}
# Nhóm theo giá trị giao dịch TB/phiên trong kỳ có NAV (phiên không khớp tính 0), đồng; phân nhóm để mô tả, không phải tín hiệu
NHOM_THANH_KHOAN = ((1e9, "cao ≥ 1 tỷ"), (1e8, "vừa 0,1–1 tỷ"), (0.0, "mỏng < 0,1 tỷ"))
MIN_SU_KIEN = 10  # dưới số sự kiện độc lập này: ghi "không đủ kết luận" (mẫu nhỏ dễ ra kết quả đẹp do ngẫu nhiên)


# ============ MÔ PHỎNG ============
def phien_tin_hieu(gia, nav, nguong=CK.NGUONG_LAI_RONG):
    """Các phiên có khớp, có NAV và lãi ròng nếu mua ở giá đóng cửa rồi bán đúng NAV cùng ngày ≥ nguong."""
    g, n = gia.align(nav, join="inner")
    return g.index[CK.lai_rong_neu_ve_nav(g, n) >= nguong]


def mo_phong(gia, nav, lich, ngay_vao, so_phien, tre=0):
    """Mỗi phiên trong ngay_vao -> 1 lệnh: mua ở giá đóng cửa phiên có khớp thứ `tre` tính từ phiên đó (0 = chính phiên đó),
    bán ở giá đóng cửa phiên có khớp đầu tiên cách phiên mua ≥ so_phien phiên của `lich`.
    gia: giá đóng cửa chỉ các phiên có khớp; nav: NAV đã làm sạch; lich: mọi phiên của thị trường.
    Lệnh chưa có phiên mua/bán trước cuối dữ liệu: bỏ. Lãi = lai_rong_neu_ve_nav với "NAV" là giá bán (cùng phí và thuế).
    Vượt NAV = (1 + lãi) / (1 + lợi nhuận NAV cùng kỳ) − 1: phần lãi nhờ chênh lệch giá/NAV thu hẹp, sau phí và thuế
    (tách khỏi phần thị trường lên/xuống mà quỹ nào cũng có)."""
    if not gia.index.isin(lich).all():
        raise ValueError(f"giá có phiên ngoài lịch thị trường: {list(gia.index[~gia.index.isin(lich)][:3])}")
    khop = gia.index
    thu_tu = pd.Index(lich.get_indexer(khop))  # phiên có khớp là phiên thứ mấy của lịch
    dong = []
    for t in ngay_vao:
        i = khop.get_loc(t) + tre
        if i >= len(khop):
            continue
        j = thu_tu.searchsorted(thu_tu[i] + so_phien)
        if j >= len(khop):
            continue
        mua, ban = khop[i], khop[j]
        dong.append(
            {
                "Ngày tín hiệu": t,
                "Ngày mua": mua,
                "Ngày bán": ban,
                "Giá mua": gia[mua],
                "Giá bán": gia[ban],
                "Phiên giữ": thu_tu[j] - thu_tu[i],
                "CL tín hiệu": gia[t] / nav.get(t, math.nan) - 1,
                "CL mua": gia[mua] / nav.get(mua, math.nan) - 1,
                "CL bán": gia[ban] / nav.get(ban, math.nan) - 1,
                "Lãi": CK.lai_rong_neu_ve_nav(gia[mua], gia[ban]),
                "Vượt NAV": CK.lai_rong_neu_ve_nav(
                    gia[mua], gia[ban] * nav.get(mua, math.nan) / nav.get(ban, math.nan)
                ),
            }
        )
    return pd.DataFrame(
        dong,
        columns=["Ngày tín hiệu", "Ngày mua", "Ngày bán", "Giá mua", "Giá bán", "Phiên giữ"]
        + ["CL tín hiệu", "CL mua", "CL bán", "Lãi", "Vượt NAV"],
    )


def doc_lap(lenh):
    """Giữ 1 vị thế mỗi lúc: bỏ lệnh có ngày tín hiệu ≤ ngày bán của lệnh đang giữ (các lệnh không chồng nhau)."""
    giu, ban_cuoi = [], pd.Timestamp.min
    for i, h in lenh.iterrows():
        if h["Ngày tín hiệu"] > ban_cuoi:
            giu.append(i)
            ban_cuoi = h["Ngày bán"]
    return lenh.loc[giu]


def tom_tat(lenh):
    """Số lệnh, lãi trung vị / trung bình / tệ nhất, % lệnh lãi; % lệnh chênh lệch giá/NAV thu hẹp (CL bán > CL mua)
    và trung vị Vượt NAV (chỉ lệnh có NAV cả ngày mua lẫn ngày bán)."""
    cl = lenh.dropna(subset=["CL mua", "CL bán"])
    return {
        "n": len(lenh),
        "Lãi TV": lenh["Lãi"].median(),
        "Lãi TB": lenh["Lãi"].mean(),
        "Tệ nhất": lenh["Lãi"].min(),
        "% lãi": (lenh["Lãi"] > 0).mean() if len(lenh) else math.nan,
        "% CL hẹp": (cl["CL bán"] > cl["CL mua"]).mean() if len(cl) else math.nan,
        "Vượt NAV TV": cl["Vượt NAV"].median(),
    }


def nhom_thanh_khoan(gtgd_tb):
    return next(ten for moc, ten in NHOM_THANH_KHOAN if gtgd_tb >= moc)


# ============ LẤY DỮ LIỆU ============
def lay_du_lieu():
    """(lịch phiên, {mã: (giá đóng cửa đồng, khối lượng, NAV)}, [cảnh báo]). Chỉ quỹ có lịch sử NAV."""
    C.dang_nhap()
    ds_quy = sorted(m for m in Listing(source="VCI").symbols_by_group("ETF") if CK.MAU_MA_QUY.fullmatch(str(m)))
    ls_quy, ls_cs = E.lay_du_lieu(ds_quy, SO_NGAY_LICH_SU)
    _, ls_nav, canh_bao = E.lay_nav(ds_quy, ls_cs)
    canh_bao += [
        f"chỉ số {cs}: {df} (NAV quỹ mô phỏng nó chưa qua bo_nav_loi)"
        for cs, df in ls_cs.items()
        if isinstance(df, str)
    ]
    lich = E.chuoi_gia(ls_cs[E.THI_TRUONG])[0].index
    du_lieu = {}
    for ma in ds_quy:
        nav, df = ls_nav.get(ma, "không có"), ls_quy.get(ma)
        if isinstance(nav, str) or isinstance(df, str) or nav.empty:
            canh_bao.append(
                f"{ma}: bỏ, " + (nav if isinstance(nav, str) else df if isinstance(df, str) else "NAV rỗng")
            )
            continue
        gia, kl = E.chuoi_gia(df)
        he_so = 10 ** round(math.log10(nav.median() / gia.median()))  # vnstock trả nghìn đồng -> đồng
        du_lieu[ma] = (gia * he_so, kl, nav)
    return lich, du_lieu, canh_bao


# ============ BÁO CÁO ============
_p = lambda x, so_le=1: D.pt(x, so_le) if math.isfinite(x) else "—"  # 0.0251 -> '+2,5%'
_t = lambda x: f"{x:.0%}" if math.isfinite(x) else "—"  # tỷ lệ 0.62 -> '62%'


def chay(hom_nay=None):
    hom_nay = hom_nay or date.today()
    lich, du_lieu, canh_bao = lay_du_lieu()
    thong_tin, tong, su_kien = [], [], []
    for ma, (gia, kl, nav) in du_lieu.items():
        ky = lich[(lich >= nav.index[0]) & (lich <= nav.index[-1])]
        gtgd = (gia * kl).reindex(ky, fill_value=0).mean()
        g, n = gia.align(nav, join="inner")
        tin_hieu, nen = phien_tin_hieu(gia, nav), g.index
        thong_tin.append(
            {"Mã": ma, "Nhóm": nhom_thanh_khoan(gtgd), "GTGD TB (tỷ)": gtgd / 1e9, "Phiên có giá và NAV": len(nen)}
            | {
                "Phiên tín hiệu": len(tin_hieu),
                "CL TV kỳ": (g / n - 1).median(),
                "Từ": nav.index[0],
                "Đến": nav.index[-1],
            }
        )
        for kb, tre in KICH_BAN.items():
            for so_phien in SO_PHIEN_GIU:
                lenh = doc_lap(mo_phong(gia, nav, lich, tin_hieu, so_phien, tre))
                nen_lenh = mo_phong(
                    gia, nav, lich, nen, so_phien, tre
                )  # nền: mọi phiên, chồng nhau (chỉ để lấy mức TB)
                nen_tt = {f"Nền {k}": v for k, v in tom_tat(nen_lenh).items()}
                tong.append({"Mã": ma, "KB": kb, "N": so_phien} | tom_tat(lenh) | nen_tt)
                su_kien.append(lenh.assign(**{"Mã": ma, "Kịch bản": kb, "N": so_phien}))
    tt, tg = pd.DataFrame(thong_tin), pd.DataFrame(tong)
    sk = pd.concat([x for x in su_kien if len(x)], ignore_index=True)  # bảng rỗng làm cột ngày thành object
    sk = sk.merge(tt[["Mã", "Nhóm"]], on="Mã")
    C.THU_MUC_KET_QUA.mkdir(exist_ok=True)
    sk.to_csv(C.THU_MUC_KET_QUA / f"kiem_chung_chiet_khau_su_kien_{hom_nay}.csv", index=False, encoding="utf-8-sig")
    noi_dung = bao_cao(tt, tg, sk, canh_bao, hom_nay)
    (C.THU_MUC_KET_QUA / f"kiem_chung_chiet_khau_{hom_nay}.md").write_text(noi_dung, encoding="utf-8")
    print(noi_dung)


GIOI_HAN = """**Giả định và giới hạn (đọc trước khi tin số)**
- Chống lookahead: tín hiệu phiên T dùng NAV(T). Kịch bản A coi iNAV lúc ATC ≈ NAV(T) và mua ngay ở giá đóng cửa T (cận lạc quan).
  Kịch bản B mua ở phiên có khớp kế tiếp: lúc đó NAV(T) đã công bố (NAV T-1 trên SSI), không cần iNAV — đây là kịch bản chính.
  NAV Vietcap IQ trễ ~2 phiên nhưng chỉ là nguồn lưu trữ; NAV(T) chính thức có từ sáng T+1.
- Giá đóng cửa của quỹ mỏng thường là 1 lô 100 CCQ và hay bằng giá chào bán (lệch lên): mua ở đó chỉ được vài lô;
  bán ở giá đóng cửa là lạc quan (thực tế khớp giá chờ mua, thấp hơn). Quỹ không khớp: giá cũ không mua/bán được,
  lệnh chờ tới phiên có khớp kế tiếp (cột Phiên giữ trong file sự kiện).
- Không có lịch sử sổ lệnh / iNAV trong phiên (ket_qua/inav_*.csv mới lưu từ 22/10/2026): không kiểm được điều kiện
  "chào bán đạt ngưỡng ≥ 5 triệu" và không biết giá chào bán thật trong phiên.
- bo_nav_loi lọc lỗi NAV bằng cửa sổ 5 phiên ở giữa (có nhìn NAV 2 phiên sau): chỉ để bỏ ngày NAV gắn sai, không dùng cho tín hiệu.
- Danh sách quỹ là các quỹ đang niêm yết hôm nay (quỹ đã hủy niêm yết không có trong mẫu). Nhóm thanh khoản xếp theo GTGD TB
  của cả kỳ (để mô tả, không phải tín hiệu)."""


def bang_md(cot, dong):
    return "\n".join(
        ["| " + " | ".join(cot) + " |", "|" + "---|" * len(cot)] + ["| " + " | ".join(d) + " |" for d in dong]
    )


def bao_cao(tt, tg, sk, canh_bao, hom_nay):
    """Báo cáo markdown: giả định, bảng theo nhóm thanh khoản, bảng theo quỹ, cảnh báo dữ liệu."""
    nhom_cua = dict(zip(tt["Mã"], tt["Nhóm"]))
    phan = [
        f"# Kiểm chứng ngưỡng chiết khấu NAV ETF ({hom_nay:%d/%m/%Y})",
        (
            f"Dữ liệu NAV {min(tt['Từ']):%d/%m/%Y} – {max(tt['Đến']):%d/%m/%Y}, {len(tt)} quỹ. Tín hiệu: lãi ròng nếu mua ở giá đóng cửa"
            f" rồi bán đúng NAV cùng ngày ≥ {CK.NGUONG_LAI_RONG:.0%} (phí {_p(C.PHI_GIAO_DICH, 2)} × 2, thuế bán {_p(C.THUE_BAN)})."
            " Lãi = mua ở giá đóng cửa, bán ở giá đóng cửa sau N phiên, sau phí và thuế. **Vượt NAV** = (1 + lãi) / (1 + lợi nhuận"
            " NAV cùng kỳ) − 1: phần lãi nhờ chênh lệch giá/NAV thu hẹp (bỏ phần thị trường lên/xuống), sau phí và thuế."
            " Nền = mua ở mọi phiên có khớp và có NAV của chính quỹ (cùng cách mua/bán)."
            " n = số lệnh độc lập (mỗi quỹ giữ 1 vị thế mỗi lúc); Tháng = số tháng khác nhau có lệnh (lệnh cùng đợt thị trường"
            " không độc lập với nhau)."
        ),
        GIOI_HAN,
    ]
    for kb in KICH_BAN:
        dong = []
        for nhom in [ten for _, ten in NHOM_THANH_KHOAN] + ["Tất cả"]:
            for so_phien in SO_PHIEN_GIU:
                ma = [m for m, nh in nhom_cua.items() if nhom in (nh, "Tất cả")]
                lenh = sk[(sk["Kịch bản"] == kb) & (sk["N"] == so_phien) & sk["Mã"].isin(ma)]
                nen = tg[(tg["KB"] == kb) & (tg["N"] == so_phien) & tg["Mã"].isin(ma)]
                t = tom_tat(lenh)
                dong.append(
                    [nhom, str(so_phien), str(t["n"]), str(lenh["Mã"].nunique())]
                    + [str(lenh["Ngày tín hiệu"].dt.to_period("M").nunique()), _p(t["Lãi TV"]), _p(t["Lãi TB"])]
                    + [_p(t["Tệ nhất"]), _t(t["% lãi"]), _t(t["% CL hẹp"]), _p(t["Vượt NAV TV"])]
                    + [_p(nen["Nền Lãi TV"].median()), _p(nen["Nền Vượt NAV TV"].median())]
                )
        phan.append(
            f"## Theo nhóm thanh khoản — {TEN_KICH_BAN[kb]}\n"
            + bang_md(
                ["Nhóm", "N", "n", "Số quỹ", "Tháng", "Lãi TV", "Lãi TB", "Tệ nhất", "% lãi", "% CL hẹp"]
                + ["Vượt NAV TV", "Nền lãi TV*", "Nền vượt NAV TV*"],
                dong,
            )
            + "\n\n_TV = trung vị. * Nền của nhóm = trung vị các mức nền của từng quỹ trong nhóm (kể cả quỹ không có tín hiệu)._"
        )
    for kb in KICH_BAN:
        dong = []
        for _, h in tt.sort_values("GTGD TB (tỷ)", ascending=False).iterrows():
            o = []
            for so_phien in SO_PHIEN_GIU:
                r = tg[(tg["Mã"] == h["Mã"]) & (tg["KB"] == kb) & (tg["N"] == so_phien)].iloc[0]
                nen = f"nền {_p(r['Nền Lãi TV'])}"
                o.append(f"{r['n']} · {_p(r['Lãi TV'])} · {_p(r['Vượt NAV TV'])} · {nen}" if r["n"] else f"0 · {nen}")
            it = tg[(tg["Mã"] == h["Mã"]) & (tg["KB"] == kb)]["n"].max() < MIN_SU_KIEN
            dong.append(
                [h["Mã"] + (" ⚠" if it else ""), h["Nhóm"], f"{h['GTGD TB (tỷ)']:.3f}".replace(".", ",")]
                + [f"{h['Phiên tín hiệu']}/{h['Phiên có giá và NAV']}", _p(h["CL TV kỳ"]), *o]
            )
        phan.append(
            f"## Theo quỹ — {TEN_KICH_BAN[kb]}\nMỗi ô N phiên: n lệnh độc lập · lãi TV · vượt NAV TV · lãi TV nền. "
            f"⚠ = dưới {MIN_SU_KIEN} lệnh độc lập ở mọi N: không đủ kết luận.\n"
            + bang_md(
                ["Quỹ", "Nhóm", "GTGD TB (tỷ)", "Phiên tín hiệu", "CL TV kỳ", *(f"N={n}" for n in SO_PHIEN_GIU)], dong
            )
        )
    if canh_bao:
        phan.append("## Cảnh báo dữ liệu\n" + "\n".join(f"- {c}" for c in canh_bao))
    return "\n\n".join(phan) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    chay()
