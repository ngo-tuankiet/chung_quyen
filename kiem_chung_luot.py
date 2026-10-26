"""
kiem_chung_luot.py - Backtest cách xếp CW để lướt 2–5 phiên (KE_HOACH.md Phần 7b, cw_scanner.luot_ngan_han / chon_luot):
với cùng một biến động của cổ phiếu cơ sở, CW xếp đầu theo "Lướt: CS cần tăng %" (thấp) có lãi/lỗ tốt hơn CW xếp cuối không,
và giả định "IV giữ nguyên 5 phiên" sai bao nhiêu. So sánh CÓ ĐIỀU KIỆN theo biến động CS thực tế: không đoán hướng CS,
không đánh giá "tín hiệu".

Chạy:   python kiem_chung_luot.py   lưu ket_qua/kiem_chung_luot_YYYY-MM-DD.md (bảng kết quả) và
                                    ket_qua/kiem_chung_luot_lenh_YYYY-MM-DD.csv (từng lệnh)
Chỉ đọc dữ liệu (điều khoản Vietcap, giá ngày + sự kiện quyền vnstock), không gửi Discord, không đổi ngưỡng đang chạy.
Giả định (ghi lại trong báo cáo):
- Mẫu: CW còn sống + CW đã hết hạn mà CS KHÔNG có sự kiện quyền (DIV/ISS của VCI) sau ngày GD cuối của CW. Giá CS của vnstock
  đã điều chỉnh theo mọi sự kiện tới hôm nay, còn điều khoản CW hết hạn dừng ở lúc hết hạn -> sự kiện sau đó làm lệch thang K/S.
- Không có lịch sử sổ lệnh: giá đóng cửa ≈ giá giữa, giá chào bán / chờ mua = giá đóng cửa ± nửa spread giả định (bước giá).
- Ngày vào T: mỗi KICH_BAN[0][0] phiên một lần (lệnh không chồng nhau); điểm xếp hạng chỉ dùng dữ liệu tới T.
- Bán ở giá đóng cửa − nửa spread của phiên CW có khớp đầu tiên cách T ≥ N phiên (CW không khớp: giá cũ không bán được).
"""

import math
import sys
from datetime import date

import numpy as np
import pandas as pd
from vnstock import Company

import cw_scanner as C
import danh_muc as D

# ============ CẤU HÌNH ============
SO_NGAY_LICH_SU = 800  # gói vnstock golden: ~546 phiên từ 08/2024
BUOC_GIA = 10  # đồng: bước giá CW trên HOSE
# (phiên giữ, spread giả định số bước giá, mua trễ mấy phiên sau ngày xếp hạng); dòng đầu = kịch bản chính.
# 5 phiên = như bảng ⚡ (C.SO_PHIEN_GIU), 2 = sớm nhất bán được (mua T, chiều T+2 mới có CW). Spread 1 bước = trung vị sổ lệnh
# 23/10/2026 (200/322 CW đúng 1 bước), 2 bước = phân vị 75%. Trễ 1 phiên: điểm và giá mua không cùng dùng giá đóng cửa T.
KICH_BAN = ((5, 1, 0), (5, 2, 0), (2, 1, 0), (2, 2, 0), (5, 1, 1))
NAM_DO_MA, SO_DO_MA = (24, 25, 26), range(1, 80)  # dò mã CW dạng C{CS}{năm}{số thứ tự}: Vietcap trả cả CW đã hết hạn
SU_KIEN_DIEU_CHINH = ("DIV", "ISS")  # event_code VCI: cổ tức tiền; phát hành cổ phiếu (cổ tức CP, thưởng, quyền mua...)
K_TREN_S = (0.3, 3.0)  # trung vị K / giá CS ngoài khoảng này: điều khoản lỗi (vd CACB2401 K = 210.030 khi ACB ~25.000)
BIEN_CS = (-0.05, -0.02, 0.0, 0.02, 0.05)  # nhóm biến động CS thực tế trong thời gian giữ
NHAN_CS = ["≤ −5%", "−5…−2%", "−2…0%", "0…+2%", "+2…+5%", "> +5%"]
BIEN_NGAY = (60, 120)  # nhóm số ngày lịch còn lại tới đáo hạn ở ngày vào
NHAN_NGAY = ["20–60 ngày", "60–120 ngày", "> 120 ngày"]  # dưới 20 ngày tới GD cuối đã bị chon_luot loại
MIN_CW_NHOM = 3  # so CW cùng CS cùng ngày: cần ≥ 3 CW
MIN_NGAY_VAO = 10  # dưới số ngày vào độc lập này: "không đủ kết luận"
SO_NHOM_HANG = 5  # ngũ phân vị


# ============ MÔ PHỎNG ============
def lai_lenh(mua, ban, phi=C.PHI_GIAO_DICH, thue=C.THUE_BAN):
    """Lãi 1 lệnh: mua ở `mua` + phí, bán ở `ban` − phí − thuế (cùng cách tính với cw_scanner.luot_ngan_han)."""
    return ban * (1 - phi - thue) / (mua * (1 + phi)) - 1


def mo_phong(dk, gia, kl, gia_cs, lich, ngay_vao, so_phien, spread, r=C.LAI_SUAT_PHI_RUI_RO, tre=0):
    """Lệnh lướt của 1 CW ở mỗi ngày vào. dk: {"ma", "cs", "tcph", "K", "ty_le", "dao_han", "gd_cuoi"} (ngày: date);
    gia, kl: giá đóng cửa (đồng) / khối lượng của CW theo phiên; gia_cs: giá CS đã điều chỉnh (đồng); lich: mọi phiên.
    Vào lệnh ở T khi (giống chon_luot, phần có dữ liệu): CW khớp ≥ MIN_KHOI_LUONG ở T (thay cho độ sâu bên mua), spread giả định
    ≤ MAX_SPREAD_LUOT, còn ≥ MIN_NGAY_GD_CUOI_LUOT ngày tới GD cuối, tính được hòa vốn. Điểm xếp hạng = luot_ngan_han y như bảng ⚡
    với chào bán / chờ mua = đóng cửa T ± spread/2, chỉ dùng giá T. Mua = đóng cửa + spread/2 ở phiên thứ `tre` sau T (CW phải
    khớp phiên đó; tre = 1 tách nhiễu giá đóng cửa T khỏi cả điểm lẫn giá mua). Bán = đóng cửa − spread/2 ở phiên CW có khớp đầu
    tiên cách phiên mua ≥ so_phien phiên. Lãi mô hình = giá Black-Scholes ở giá CS thật lúc bán, IV giải từ giá chờ mua lúc mua
    (giả định IV giữ nguyên)."""
    khop = kl.index[kl > 0]
    dong = []
    for t in ngay_vao:
        i = lich.get_loc(t)
        if kl.get(t, 0) < C.MIN_KHOI_LUONG or i + tre + so_phien >= len(lich) or t not in gia_cs.index:
            continue
        v = lich[i + tre]  # phiên mua
        if (dk["gd_cuoi"] - t.date()).days < C.MIN_NGAY_GD_CUOI_LUOT or kl.get(v, 0) <= 0 or v not in gia_cs.index:
            continue
        j = khop.searchsorted(lich[i + tre + so_phien])
        if j >= len(khop) or khop[j].date() > dk["gd_cuoi"] or khop[j] not in gia_cs.index:
            continue
        b, K, ty_le = khop[j], dk["K"], dk["ty_le"]
        if gia[t] - spread / 2 <= 0 or spread / gia[t] > C.MAX_SPREAD_LUOT:
            continue
        hoa_von, _ = C.luot_ngan_han(
            gia[t] + spread / 2,
            gia[t] - spread / 2,
            gia_cs[t],
            K,
            ty_le,
            (dk["dao_han"] - t.date()).days,
            r,
            C.so_ngay_lich(t.date(), C.SO_PHIEN_GIU),
        )
        if not math.isfinite(hoa_von):
            continue
        giua, S, S2 = gia[v], gia_cs[v], gia_cs[b]
        mua, cho = giua + spread / 2, giua - spread / 2
        if cho <= 0:
            continue
        con, giu = (dk["dao_han"] - v.date()).days, (b - v).days
        iv_cho = C.bien_dong_ngam_dinh(cho, S, K, con / C.NGAY_MOT_NAM, r, ty_le)
        du_bao = C.black_scholes_call(S2, K, (con - giu) / C.NGAY_MOT_NAM, r, iv_cho)[0] / ty_le if iv_cho else math.nan
        iv0 = C.bien_dong_ngam_dinh(giua, S, K, con / C.NGAY_MOT_NAM, r, ty_le)
        iv1 = C.bien_dong_ngam_dinh(gia[b], S2, K, (con - giu) / C.NGAY_MOT_NAM, r, ty_le)
        dong.append(
            {
                "Ngày vào": t,
                "Ngày mua": v,
                "Ngày bán": b,
                "Phiên giữ": lich.get_loc(b) - i - tre,
                "Mã CW": dk["ma"],
                "Mã CS": dk["cs"],
                "TCPH": dk["tcph"],
                "Ngày còn lại": con,
                "Giá giữa": giua,
                "Hòa vốn": hoa_von,  # = "Lướt: CS cần tăng %" / 100 ở ngày T
                "Đòn bẩy": (
                    C.black_scholes_call(S, K, con / C.NGAY_MOT_NAM, r, iv0)[1] * S / (giua * ty_le)
                    if iv0
                    else math.nan
                ),
                "CS %": S2 / S - 1,
                "Lãi": lai_lenh(mua, max(gia[b] - spread / 2, 0.0)),
                "Lãi mô hình": lai_lenh(mua, du_bao),
                "IV vào": iv0 if iv0 else math.nan,
                "ΔIV": iv1 - iv0 if iv0 and iv1 else math.nan,  # theo giá giữa ở cả 2 đầu
            }
        )
    return pd.DataFrame(dong)


def nhom_cs(cs_pt):
    return pd.cut(cs_pt, [-np.inf, *BIEN_CS, np.inf], labels=NHAN_CS)


def tuong_quan_hang(x, y):
    """Tương quan hạng Spearman (không cần scipy): Pearson của 2 dãy hạng."""
    return x.rank().corr(y.rank())


def cung_cs(lenh, so_phien):
    """Mỗi nhóm (ngày vào, mã CS) có ≥ MIN_CW_NHOM CW bán đúng hạn (cùng ngày bán -> cùng một biến động CS): CW hòa vốn thấp
    nhất ("đầu") so với cao nhất ("cuối") và tương quan hạng giữa hòa vốn với lãi (âm = hòa vốn thấp thì lãi cao hơn).
    """
    x = lenh[lenh["Phiên giữ"] == so_phien]
    dong = []
    for (t, cs), g in x.groupby(["Ngày vào", "Mã CS"]):
        if len(g) < MIN_CW_NHOM:
            continue
        g = g.sort_values("Hòa vốn")
        dau, cuoi = g.iloc[0], g.iloc[-1]
        dong.append(
            {"Ngày vào": t, "Mã CS": cs, "CS %": dau["CS %"], "Số CW": len(g), "Lãi đầu": dau["Lãi"]}
            | {"Lãi cuối": cuoi["Lãi"], "Chênh": dau["Lãi"] - cuoi["Lãi"], "ρ": tuong_quan_hang(g["Hòa vốn"], g["Lãi"])}
            | {"Đòn bẩy đầu": dau["Đòn bẩy"], "Đòn bẩy cuối": cuoi["Đòn bẩy"]}
        )
    return pd.DataFrame(dong)


def t_theo_ngay(x, ngay):
    """Thống kê t của trung bình, coi mỗi ngày vào là 1 quan sát độc lập (CW cùng ngày tương quan mạnh với nhau)."""
    m = x.groupby(ngay).mean()
    return m.mean() / (m.std() / math.sqrt(len(m))) if len(m) > 1 and m.std() > 0 else math.nan


def hang_nhom(lenh):
    """Thêm cột "Nhóm hạng" 1…SO_NHOM_HANG: ngũ phân vị hòa vốn trong các CW vào lệnh cùng ngày (1 = hòa vốn thấp nhất,
    tương ứng đầu bảng ⚡). Ngày có ít CW hơn số nhóm: bỏ."""
    x = lenh.groupby("Ngày vào").filter(lambda g: len(g) >= SO_NHOM_HANG).copy()
    x["Nhóm hạng"] = x.groupby("Ngày vào")["Hòa vốn"].transform(
        lambda h: pd.qcut(h.rank(method="first"), SO_NHOM_HANG, labels=False) + 1
    )
    return x


def dung_hoa_von(lenh):
    """Tỷ lệ lệnh mà "CS tăng ≥ mức hòa vốn" trùng với "lãi ≥ 0" (mức hòa vốn đúng chiều)."""
    return ((lenh["CS %"] >= lenh["Hòa vốn"]) == (lenh["Lãi"] >= 0)).mean() if len(lenh) else math.nan


# ============ LẤY DỮ LIỆU ============
def ngay_su_kien(cs):
    """Các ngày GDKHQ (date) của cổ tức tiền / phát hành cổ phiếu của mã cs (vnstock VCI events)."""
    e = Company(source="VCI", symbol=cs).events()
    e = e[e["event_code"].isin(SU_KIEN_DIEU_CHINH) & e["exright_date"].notna()]
    return sorted({x.date() for x in e["exright_date"]})


def chuoi(df, he_so):
    """(giá đồng, khối lượng) theo phiên từ DataFrame vnstock."""
    idx = pd.DatetimeIndex(pd.to_datetime(df["time"]).dt.normalize())
    return pd.Series(df["close"].to_numpy(float) * he_so, idx), pd.Series(df["volume"].to_numpy(float), idx)


def dieu_khoan(ma, ny):
    """Điều khoản 1 CW từ bảng giá Vietcap: {"ma", "cs", "tcph", "K", "ty_le", "dao_han", "gd_cuoi"} (ngày: date)."""
    ngay = lambda s: date(int(s[:4]), int(s[4:6]), int(s[6:]))
    dk = {
        "ma": ma,
        "cs": ny.get("underlyingSymbol"),
        "tcph": ny.get("issuerName") or "",
        "K": float(ny["exercisePrice"]),
    }
    return dk | {
        "ty_le": C.doc_ty_le(ny["exerciseRatio"]),
        "dao_han": ngay(ny["maturityDate"]),
        "gd_cuoi": ngay(ny["lastTradingDate"]),
    }


def lay_du_lieu(hom_nay, ds_cs):
    """(lịch phiên, {mã CS: giá}, [(dk, giá CW, KL CW)], {mã CS: [ngày GDKHQ]}, [cảnh báo]) cho mẫu A."""
    C.dang_nhap()
    canh_bao = []
    ung_vien = [f"C{cs}{nam}{so:02d}" for cs in ds_cs for nam in NAM_DO_MA for so in SO_DO_MA]
    bang = {}
    for i in range(0, len(ung_vien), 400):
        bang.update(C.lay_bang_gia(ung_vien[i : i + 400]))
    bang_cs = C.lay_bang_gia(list(ds_cs))
    gia_cs, su_kien = {}, {}
    for cs in ds_cs:
        df = C.lay_gia_dong_cua(cs, SO_NGAY_LICH_SU)
        he_so = 10 ** round(math.log10(C.gia_hien_tai(*bang_cs[cs]) / float(df["close"].iloc[-1])))
        gia_cs[cs], su_kien[cs] = chuoi(df, he_so)[0], ngay_su_kien(cs)
    lich = pd.DatetimeIndex(sorted(set().union(*(s.index for s in gia_cs.values()))))
    cw, he_so_cw, dem = [], set(), {"hết hạn trước dữ liệu": 0, "sự kiện sau GD cuối": 0}
    for ma, (ny, kl, _) in sorted(bang.items()):
        cs = ny.get("underlyingSymbol")
        if cs not in gia_cs or not ny.get("lastTradingDate") or not ny.get("exercisePrice"):
            continue
        dk = dieu_khoan(ma, ny)
        con_song = dk["gd_cuoi"] >= hom_nay
        if dk["gd_cuoi"] <= lich[0].date():
            dem["hết hạn trước dữ liệu"] += 1
            continue
        if not con_song and any(e > dk["gd_cuoi"] for e in su_kien[cs]):
            dem["sự kiện sau GD cuối"] += 1
            continue
        try:
            df = C.lay_gia_dong_cua(ma, SO_NGAY_LICH_SU, C.NGUON_GIA_CW)
            df["close"].iloc[-1]  # vnstock trả bảng rỗng (không lỗi) cho mã không có giá trong kỳ
        # ranh giới gọi vnstock: mã không có giá thì bỏ mã đó và ghi vào cảnh báo, không dừng cả lần chạy
        except Exception as e:  # noqa: BLE001
            canh_bao.append(f"{ma}: không lấy được giá ({str(e)[:80]})")
            continue
        if con_song and C.gia_hien_tai(ny, kl):
            he_so_cw.add(10 ** round(math.log10(C.gia_hien_tai(ny, kl) / float(df["close"].iloc[-1]))))
        cw.append((dk, df))
    if len(he_so_cw) != 1:  # đơn vị giá CW của vnstock phải nhất quán thì mới dùng chung cho CW đã hết hạn
        raise ValueError(f"hệ số đơn vị giá CW vnstock không nhất quán: {sorted(he_so_cw)}")
    he_so = he_so_cw.pop()
    ket_qua = []
    for dk, df in cw:
        gia, kl = chuoi(df, he_so)
        ti = (dk["K"] / gia_cs[dk["cs"]].reindex(gia.index)).median()
        if not K_TREN_S[0] <= ti <= K_TREN_S[1]:
            canh_bao.append(f"{dk['ma']}: bỏ, trung vị K/giá CS = {ti:.2f} (điều khoản lỗi?)")
            continue
        ket_qua.append((dk, gia, kl))
    canh_bao.append(
        f"Đơn vị giá CW vnstock × {he_so:g}. Bỏ {dem['hết hạn trước dữ liệu']} CW hết hạn trước {lich[0]:%d/%m/%Y},"
        f" {dem['sự kiện sau GD cuối']} CW hết hạn có sự kiện quyền của CS sau ngày GD cuối (lệch thang K/giá CS)."
    )
    return lich, gia_cs, ket_qua, su_kien, canh_bao


def kiem_tra_gdkhq(cw, gia_cs, su_kien, lich, r=C.LAI_SUAT_PHI_RUI_RO):
    """Điều khoản CW và giá CS đã điều chỉnh có cùng thang quanh ngày GDKHQ không: ΔIV 1 phiên (theo giá đóng cửa) của CW ở ngày
    GDKHQ so với các phiên thường. Nếu K/tỷ lệ không được điều chỉnh như giá CS thì IV nhảy vọt đúng ngày GDKHQ.
    Trả về DataFrame (Mã CW, Ngày, GDKHQ, ΔIV) cho mọi cặp 2 phiên liền nhau CW đều có khớp."""
    dong = []
    for dk, gia, kl in cw:
        g = gia[kl > 0]
        s = gia_cs[dk["cs"]]
        for a, b in zip(g.index[:-1], g.index[1:]):
            if lich.get_loc(b) - lich.get_loc(a) != 1 or a not in s.index or b not in s.index:
                continue
            iv = [
                C.bien_dong_ngam_dinh(
                    g[d], s[d], dk["K"], (dk["dao_han"] - d.date()).days / C.NGAY_MOT_NAM, r, dk["ty_le"]
                )
                for d in (a, b)
            ]
            if iv[0] and iv[1]:
                dong.append(
                    {"Mã CW": dk["ma"], "Ngày": b, "GDKHQ": b.date() in su_kien[dk["cs"]], "ΔIV": iv[1] - iv[0]}
                )
    return pd.DataFrame(dong)


# ============ BÁO CÁO ============
def _p(x, le=1):
    return D.pt(x, le) if pd.notna(x) and math.isfinite(x) else "—"  # 0.0251 -> '+2,5%'


def _s(x, le=2):
    return f"{x:+.{le}f}".replace(".", ",").replace("-", "−") if pd.notna(x) and math.isfinite(x) else "—"


def _t(x):
    return f"{x:.0%}" if pd.notna(x) and math.isfinite(x) else "—"  # tỷ lệ 0.62 -> '62%'


def theo_nhom_cs(x, nhan):
    return x if nhan == "Tất cả" else x[nhom_cs(x["CS %"]) == nhan]


def bang_cung_cs(n):
    dong = []
    for nhan in NHAN_CS + ["Tất cả"]:
        x, it = theo_nhom_cs(n, nhan), theo_nhom_cs(n, nhan)["Ngày vào"].nunique() < MIN_NGAY_VAO
        dong.append(
            [nhan + (" ⚠" if it else ""), str(len(x)), str(x["Ngày vào"].nunique())]
            + [
                _p(x["Lãi đầu"].median()),
                _p(x["Lãi cuối"].median()),
                _p(x["Chênh"].mean()),
                _t((x["Chênh"] > 0).mean()),
            ]
            + [
                _s(t_theo_ngay(x["Chênh"], x["Ngày vào"]), 1),
                _s(x["ρ"].mean()),
                _s(t_theo_ngay(x["ρ"], x["Ngày vào"]), 1),
            ]
            + [f"{x['Đòn bẩy đầu'].median():.1f} / {x['Đòn bẩy cuối'].median():.1f}".replace(".", ",")]
        )
    return bang_md(
        [
            "Biến động CS",
            "Số nhóm",
            "Ngày vào",
            "Lãi TV đầu",
            "Lãi TV cuối",
            "Chênh TB",
            "% đầu > cuối",
            "t chênh",
            "ρ TB",
            "t ρ",
        ]
        + ["Đòn bẩy TV đầu / cuối"],
        dong,
    )


def bang_hang(x):
    dong = []
    for nhan in NHAN_CS + ["Tất cả"]:
        y = theo_nhom_cs(x, nhan)
        o = [
            f"{_p(z.median())} · {len(z)}"
            for z in (y.loc[y["Nhóm hạng"] == q, "Lãi"] for q in range(1, SO_NHOM_HANG + 1))
        ]
        dong.append([nhan, str(y["Ngày vào"].nunique()), *o])
    tv = x.groupby("Nhóm hạng")[["Hòa vốn", "Đòn bẩy", "Ngày còn lại", "Giá giữa"]].median()
    dong += [
        ["_Hòa vốn TV_", "", *(_p(v, 2) for v in tv["Hòa vốn"])],
        ["_Đòn bẩy TV_", "", *(f"{v:.1f}".replace(".", ",") for v in tv["Đòn bẩy"])],
        ["_Ngày còn lại TV_", "", *(f"{v:.0f}" for v in tv["Ngày còn lại"])],
        ["_Giá CW TV (đồng)_", "", *(D.so(v) for v in tv["Giá giữa"])],
    ]
    return bang_md(["Biến động CS", "Ngày vào", *(f"Q{q}" for q in range(1, SO_NHOM_HANG + 1))], dong)


def bang_iv(lenh, cot, thu_tu, so_phien):
    dong = []
    for ten in list(thu_tu) + ["Tất cả"]:
        x = lenh if ten == "Tất cả" else lenh[lenh[cot] == ten]
        ss, n, div = x["Lãi"] - x["Lãi mô hình"], cung_cs(x, so_phien), x["ΔIV"] * 100
        dong.append(
            [str(ten), str(len(x)), str(x["Ngày vào"].nunique()), _s(div.median(), 1)]
            + [f"{_s(div.quantile(0.1), 1)} … {_s(div.quantile(0.9), 1)}", _p(ss.median()), _p(ss.abs().median())]
            + [_t(dung_hoa_von(x)), f"{_s(n['ρ'].mean())} ({len(n)})" if len(n) else "—"]
        )
    return bang_md(
        [cot, "Lệnh", "Ngày vào", "ΔIV TV (điểm)", "ΔIV P10 … P90", "Thực − mô hình TV", "|Thực − mô hình| TV"]
        + ["% đúng hòa vốn", "ρ cùng CS (số nhóm)"],
        dong,
    )


def bang_do_nhay(ket_qua):
    dong = []
    for (so_phien, buoc, tre), lenh in ket_qua.items():
        n, x = cung_cs(lenh, so_phien), hang_nhom(lenh)
        q = x.groupby("Nhóm hạng")["Lãi"].median()
        dong.append(
            [
                f"{so_phien} phiên, spread {buoc} bước" + (f", mua trễ {tre} phiên" if tre else ""),
                str(len(lenh)),
                str(lenh["Ngày vào"].nunique()),
                str(len(n)),
            ]
            + [_p(n["Chênh"].mean()), _s(t_theo_ngay(n["Chênh"], n["Ngày vào"]), 1), _s(n["ρ"].mean())]
            + [_s(t_theo_ngay(n["ρ"], n["Ngày vào"]), 1)]
            + [_p(q.get(1, math.nan)), _p(q.get(SO_NHOM_HANG, math.nan)), _t(dung_hoa_von(lenh))]
        )
    return bang_md(
        [
            "Kịch bản",
            "Lệnh",
            "Ngày vào",
            "Nhóm cùng CS",
            "Chênh TB",
            "t chênh",
            "ρ TB",
            "t ρ",
            "Lãi TV Q1",
            "Lãi TV Q5",
            "% đúng hòa vốn",
        ],
        dong,
    )


def bang_gdkhq(kt):
    dong = []
    for co, ten in ((True, "ngày GDKHQ của CS"), (False, "phiên thường")):
        x = kt.loc[kt["GDKHQ"] == co, "ΔIV"] * 100
        dong.append([ten, str(len(x)), _s(x.median(), 1), _s(x.abs().median(), 1), _s(x.abs().quantile(0.9), 1)])
    return bang_md(["1 phiên", "Số cặp", "ΔIV TV (điểm)", "|ΔIV| TV", "|ΔIV| P90"], dong)


def bang_md(cot, dong):
    return "\n".join(
        ["| " + " | ".join(cot) + " |", "|" + "---|" * len(cot)] + ["| " + " | ".join(d) + " |" for d in dong]
    )


GIOI_HAN = f"""**Giả định và giới hạn (đọc trước khi tin số)**
- **Lớn nhất: không có lịch sử sổ lệnh.** Coi giá đóng cửa ≈ giá giữa; chào bán / chờ mua = đóng cửa ± nửa spread giả định
  ({KICH_BAN[0][1]} bước giá {BUOC_GIA} đ = trung vị sổ lệnh 23/10/2026; {KICH_BAN[1][1]} bước = phân vị 75%). Giá đóng cửa ATC có thể nằm
  sát bên mua hoặc bên bán: sai số ± nửa spread ở cả 2 đầu, lớn với CW giá thấp (1 bước = 3,3% của CW 300 đ).
- Không kiểm được "bên mua 3 bước ≥ {D.so(C.MIN_BEN_MUA_LUOT)} đ": thay bằng khối lượng khớp ngày vào ≥ {D.so(C.MIN_KHOI_LUONG)} CW.
  Spread lọc theo spread giả định (CW giá giữa < {BUOC_GIA * KICH_BAN[0][1] / C.MAX_SPREAD_LUOT:.0f} đ bị loại ở kịch bản 1 bước).
- Điểm và giá mua cùng dùng giá đóng cửa T: giá đóng cửa lệch lên (khớp ở giá chào bán) làm hòa vốn cao VÀ giá mua cao, nên
  thứ tự có thể trông đúng chỉ vì nhiễu đó (bid-ask bounce). Kịch bản "mua trễ 1 phiên" tách 2 thứ ra; ở bảng ⚡ thật bạn mua
  đúng giá chào bán lúc xem nên không bị nhiễu này.
- Điểm xếp hạng ngày T = cw_scanner.luot_ngan_han như bảng ⚡ (giữ {C.SO_PHIEN_GIU} phiên = so_ngay_lich, r = {_p(C.LAI_SUAT_PHI_RUI_RO, 0)}),
  chỉ dùng giá tới T. Điều khoản (K, tỷ lệ) là bản đã điều chỉnh của Vietcap, giá CS đã điều chỉnh của vnstock: cùng nhân 1 hệ số
  thì giá trị 1 CW không đổi (xem phần kiểm tra GDKHQ).
- Lệnh bán ở phiên CW có khớp đầu tiên cách T ≥ N phiên (giá cũ không bán được); so cùng CS chỉ lấy lệnh bán đúng N phiên.
- Mẫu chọn theo ngày đáo hạn (biết trước tại T, không theo lãi lỗ): CW còn sống + CW hết hạn không có sự kiện quyền của CS sau
  ngày GD cuối. Ở các ngày vào xa, mẫu nghiêng về CW kỳ hạn dài -> xem thêm bảng theo số ngày còn lại.
- CW cùng ngày tương quan mạnh (cùng thị trường, cùng CS): số quan sát độc lập ≈ số **ngày vào** (cách nhau {KICH_BAN[0][0]} phiên),
  t tính theo ngày (trung bình từng ngày rồi lấy t của các trung bình). ⚠ = dưới {MIN_NGAY_VAO} ngày vào: không đủ kết luận."""


def chay(hom_nay=None):
    hom_nay = hom_nay or date.today()
    ds_cs = sorted(pd.read_csv(max(C.THU_MUC_KET_QUA.glob("cw_*.csv")))["Mã CS"].unique())  # các CS đang có CW
    tep = C.THU_MUC_KET_QUA / f"kiem_chung_luot_du_lieu_{hom_nay}.pkl"  # chạy lại trong ngày không tải lại ~500 mã
    if not tep.exists():
        pd.to_pickle(lay_du_lieu(hom_nay, ds_cs), tep)
    lich, gia_cs, cw, su_kien, canh_bao = pd.read_pickle(tep)
    N, B, _ = KICH_BAN[0]
    ngay_vao = lich[::N]
    ket_qua = {
        (so_phien, buoc, tre): pd.concat(
            [
                mo_phong(dk, gia, kl, gia_cs[dk["cs"]], lich, ngay_vao, so_phien, buoc * BUOC_GIA, tre=tre)
                for dk, gia, kl in cw
            ],
            ignore_index=True,
        )
        for so_phien, buoc, tre in KICH_BAN
    }
    for (so_phien, buoc, tre), lenh in ket_qua.items():
        lenh["Nhóm ngày"] = pd.cut(lenh["Ngày còn lại"], [-np.inf, *BIEN_NGAY, np.inf], labels=NHAN_NGAY).astype(str)
        lenh[["N", "Spread (bước)", "Mua trễ (phiên)"]] = so_phien, buoc, tre
    chinh = ket_qua[KICH_BAN[0]]
    con_song = sum(dk["gd_cuoi"] >= hom_nay for dk, *_ in cw)
    pd.concat(ket_qua.values()).to_csv(
        C.THU_MUC_KET_QUA / f"kiem_chung_luot_lenh_{hom_nay}.csv", index=False, encoding="utf-8-sig"
    )
    tcph = chinh["TCPH"].value_counts().index
    kt = kiem_tra_gdkhq(cw, gia_cs, su_kien, lich)
    phan = [
        f"# Backtest xếp hạng CW lướt 2–5 phiên ({hom_nay:%d/%m/%Y})",
        (
            f"Giá ngày {lich[0]:%d/%m/%Y} – {lich[-1]:%d/%m/%Y} ({len(lich)} phiên), {len(cw)} CW của {len(gia_cs)} CS"
            f" ({con_song} còn sống, {len(cw) - con_song} đã hết hạn), {len(ngay_vao)} ngày vào cách nhau {N} phiên."
            f" Kịch bản chính: giữ {N} phiên, spread {B} bước: {len(chinh)} lệnh, {chinh['Mã CW'].nunique()} CW,"
            f" {chinh['Ngày vào'].nunique()} ngày vào có lệnh. Lãi = sau phí {_p(C.PHI_GIAO_DICH, 2)} × 2 và thuế bán"
            f' {_p(C.THUE_BAN)}. **Hòa vốn** = "Lướt: CS cần tăng %" ở ngày vào. Python không đoán hướng CS: mọi bảng chia theo'
            " biến động CS **thực tế** trong thời gian giữ."
        ),
        GIOI_HAN,
        "## Kiểm tra dữ liệu: điều khoản và giá CS cùng thang quanh ngày GDKHQ\nΔIV 1 phiên theo giá đóng cửa, mọi CW trong"
        " mẫu. Nếu K/tỷ lệ không được điều chỉnh như giá CS, IV nhảy đúng ngày GDKHQ (vd cổ tức 3% làm IV CW ngang giá 60 ngày"
        " đổi hơn 10 điểm).\n" + bang_gdkhq(kt),
        f"## 1. Cùng CS, cùng ngày vào (cùng một biến động CS) — giữ {N} phiên, spread {B} bước\n"
        f"Mỗi nhóm = các CW cùng CS vào cùng ngày, bán cùng ngày (≥ {MIN_CW_NHOM} CW). Đầu = CW hòa vốn thấp nhất (đầu bảng ⚡),"
        " cuối = cao nhất. Chênh = lãi đầu − lãi cuối. ρ = tương quan hạng giữa hòa vốn và lãi trong nhóm (âm = hòa vốn thấp"
        " thì lãi cao hơn, tức thứ tự xếp hạng đúng). t theo ngày vào (|t| ≥ 2 ≈ khó do ngẫu nhiên); t ρ ít bị vài lệnh lãi rất"
        " lớn chi phối hơn t chênh.\n" + bang_cung_cs(cung_cs(chinh, N)),
        f"## 2. Ngũ phân vị hòa vốn trong cả bảng mỗi ngày (giống bảng ⚡) — giữ {N} phiên, spread {B} bước\n"
        "Q1 = 20% CW hòa vốn thấp nhất ngày đó. Mỗi ô: lãi TV · số lệnh. CW khác CS nên biến động CS chỉ gần bằng nhau"
        " trong cùng hàng.\n" + bang_hang(hang_nhom(chinh)),
        "## 3. Độ nhạy theo thời gian giữ và spread giả định\n" + bang_do_nhay(ket_qua),
        f'## 4. Giả định "IV giữ nguyên" sai bao nhiêu — giữ {N} phiên, spread {B} bước\n'
        "ΔIV = IV(giá đóng cửa lúc bán) − IV(giá đóng cửa lúc mua), điểm %. Thực − mô hình = lãi thực tế − lãi nếu CW bán đúng"
        " giá Black-Scholes ở giá CS thật lúc bán với IV giải từ giá chờ mua ngày vào (giả định của bảng ⚡). % đúng hòa vốn ="
        ' tỷ lệ lệnh mà "CS tăng ≥ hòa vốn" trùng "lãi ≥ 0".\n### Theo tổ chức phát hành\n'
        + bang_iv(chinh, "TCPH", tcph, N)
        + "\n\n### Theo số ngày còn lại\n"
        + bang_iv(chinh, "Nhóm ngày", NHAN_NGAY, N)
        + f"\n\nTương quan (thực − mô hình, ΔIV) = {_s(chinh['Lãi'].sub(chinh['Lãi mô hình']).corr(chinh['ΔIV']))}.",
    ]
    if canh_bao:
        phan.append("## Cảnh báo dữ liệu\n" + "\n".join(f"- {c}" for c in canh_bao))
    noi_dung = "\n\n".join(phan) + "\n"
    (C.THU_MUC_KET_QUA / f"kiem_chung_luot_{hom_nay}.md").write_text(noi_dung, encoding="utf-8")
    print(noi_dung)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]  # stdout luôn là TextIOWrapper
    chay()
