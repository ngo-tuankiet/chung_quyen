"""
kiem_chung_truyen_dan.py - Tổ chức phát hành (TCPH) đổi IV theo hướng cổ phiếu cơ sở bao nhiêu trong 5 phiên (KE_HOACH.md Phần 7b),
để hiệu chỉnh "Lướt: lãi kịch bản" của trang ⚡ (vốn giả định IV giữ nguyên 5 phiên).

Chạy:   python kiem_chung_truyen_dan.py   lưu ket_qua/he_so_iv_tcph_YYYY-MM-DD.csv (bảng hệ số, ngày = phiên cuối của dữ liệu;
                                          trang ⚡ đọc file mới nhất) và ket_qua/kiem_chung_truyen_dan_YYYY-MM-DD.md (báo cáo)
Chỉ đọc dữ liệu, không gửi Discord. Dữ liệu = bộ mới nhất của kiem_chung_luot.py (ket_qua/kiem_chung_luot_du_lieu_*.pkl) cộng các
CW đã hết hạn mà nó bỏ vì CS có sự kiện quyền sau ngày GD cuối: thang giá CS của các CW này được đưa về lúc hết hạn bằng
f = giá CS đã điều chỉnh (vnstock) / giá đóng cửa thô (HOSE) ngày GD cuối, tải 1 lần cho mỗi bộ dữ liệu.
Mỗi cửa sổ = 1 CW từ phiên a tới a + SO_PHIEN phiên, đo bằng giá đóng cửa (≈ giá giữa):
- truyền dẫn = CW thực đổi / CW mô hình đổi, mô hình = Black-Scholes ở giá CS phiên b với IV phiên a giữ nguyên;
- β = ΔIV / CS đổi (tỷ lệ / tỷ lệ = số điểm IV đổi khi CS đổi 1%). IV kịch bản = IV + β × CS đổi.
Bảng hệ số = trung vị theo (TCPH, chiều CS).
"""

import functools
import math
import sys

import numpy as np
import pandas as pd

import cw_scanner as C
import kiem_chung_luot as L

# ============ CẤU HÌNH ============
SO_PHIEN = C.SO_PHIEN_GIU  # cửa sổ 5 phiên như bảng ⚡; ngày đầu cửa sổ cách nhau SO_PHIEN phiên (không chồng nhau)
DELTA_DO = (
    0.15,
    0.85,
)  # delta (theo IV phiên a) ngoài khoảng này: CW quá sâu trong / ngoài tiền, IV từ giá đóng cửa rất nhiễu
NGUONG_MO_HINH = 0.05  # truyền dẫn: mô hình dự tính CW đổi < 5% thì tỷ số thực / mô hình không có nghĩa
NGUONG_CS_BETA = 0.02  # β: CS đổi < 2% thì ΔIV / CS đổi bị nhiễu giá đóng cửa chi phối
BIEN_DELTA, NHAN_DELTA = (0.35, 0.65), ["ngoài tiền", "quanh giá", "trong tiền"]  # nhóm tiền để kiểm hiệu chỉnh
URL_KET_QUA_HOSE = (  # cùng máy chủ api.hsx.vn với cw_scanner.URL_HOSE_CW_MOI
    "https://api.hsx.vn/mk/api/v1/market/securities/tradingresult/{ma}?pageSize=5&pageIndex=1&fromDate={ngay}&toDate={ngay}"
)
SO_CW_KIEM_F, LECH_F_TOI_DA = (
    8,
    0.005,
)  # CW hết hạn không có sự kiện sau GD cuối: f phải ≈ 1 (giá HOSE cùng đơn vị đồng)


# ============ LẤY DỮ LIỆU ============
@functools.cache
def gia_tho_hose(cs, ngay):
    """Giá đóng cửa thô (chưa điều chỉnh, đồng) của cs ngày `ngay` (date) từ HOSE; None nếu HOSE không có."""
    ds = (C.tai_json(URL_KET_QUA_HOSE.format(ma=cs, ngay=ngay), C.HEADERS_HOSE).get("data") or {}).get("list") or []
    return float(ds[0]["closePrice"]) if ds and ds[0].get("closePrice") else None


def gia_luc(s, ngay):
    return s.asof(pd.Timestamp(ngay, tz=s.index.tz))


def lay_bo_sung(lich, gia_cs, cw, su_kien):
    """([(dk + "f", giá CW đồng, KL CW)], [cảnh báo]): CW hết hạn mà CS có sự kiện quyền sau ngày GD cuối."""
    C.dang_nhap()
    for dk in [dk for dk, *_ in cw if dk["gd_cuoi"] < lich[-1].date()][:SO_CW_KIEM_F]:
        tho = gia_tho_hose(dk["cs"], dk["gd_cuoi"])
        if tho and abs(gia_luc(gia_cs[dk["cs"]], dk["gd_cuoi"]) / tho - 1) > LECH_F_TOI_DA:
            raise ValueError(
                f"{dk['ma']}: giá CS vnstock / giá thô HOSE ngày GD cuối ≠ 1 dù không có sự kiện quyền (đơn vị?)"
            )
    # đơn vị giá CW vnstock: so 1 CW còn sống (dữ liệu kiem_chung_luot đã đổi ra đồng) với giá vnstock chưa đổi
    dk, gia, _ = next(x for x in cw if x[0]["gd_cuoi"] >= lich[-1].date())
    tho = L.chuoi(C.lay_gia_dong_cua(dk["ma"], L.SO_NGAY_LICH_SU), 1.0)[0]
    d = gia.index.intersection(tho.index)[-1]
    he_so = 10 ** round(math.log10(gia[d] / tho[d]))
    ung_vien = [f"C{cs}{nam}{so:02d}" for cs in gia_cs for nam in L.NAM_DO_MA for so in L.SO_DO_MA]
    bang = {}
    for i in range(0, len(ung_vien), 400):
        bang.update(C.lay_bang_gia(ung_vien[i : i + 400]))
    da_co, ket_qua, canh_bao = {dk["ma"] for dk, *_ in cw}, [], []
    for ma, (ny, _, _) in sorted(bang.items()):
        cs = ny.get("underlyingSymbol")
        if ma in da_co or cs not in gia_cs or not ny.get("lastTradingDate") or not ny.get("exercisePrice"):
            continue
        dk = L.dieu_khoan(ma, ny)
        if not lich[0].date() < dk["gd_cuoi"] < lich[-1].date() or not any(e > dk["gd_cuoi"] for e in su_kien[cs]):
            continue
        tho = gia_tho_hose(cs, dk["gd_cuoi"])
        if not tho:
            canh_bao.append(f"{ma}: HOSE không có giá đóng cửa thô của {cs} ngày {dk['gd_cuoi']:%d/%m/%Y}")
            continue
        dk["f"] = gia_luc(gia_cs[cs], dk["gd_cuoi"]) / tho
        try:
            df = C.lay_gia_dong_cua(ma, L.SO_NGAY_LICH_SU)
            df["close"].iloc[-1]  # vnstock trả bảng rỗng (không lỗi) cho mã không có giá trong kỳ
        # ranh giới gọi vnstock: mã không có giá thì bỏ mã đó và ghi vào cảnh báo, không dừng cả lần chạy
        except Exception as e:  # noqa: BLE001
            canh_bao.append(f"{ma}: không lấy được giá ({str(e)[:80]})")
            continue
        gia, kl = L.chuoi(df, he_so)
        ti = (dk["K"] * dk["f"] / gia_cs[cs].reindex(gia.index)).median()
        if not L.K_TREN_S[0] <= ti <= L.K_TREN_S[1]:
            canh_bao.append(f"{ma}: bỏ, trung vị K/giá CS = {ti:.2f} (điều khoản lỗi?)")
            continue
        ket_qua.append((dk, gia, kl))
    return ket_qua, canh_bao


# ============ ĐO ============
def cua_so(dk, gia, kl, gia_cs, lich, r=C.LAI_SUAT_PHI_RUI_RO, so_phien=SO_PHIEN):
    """Các cửa sổ so_phien phiên của 1 CW, bắt đầu ở lich[0], lich[so_phien]… (cùng lưới ngày cho mọi CW: CW cùng ngày tương
    quan, t tính theo ngày). gia_cs: giá CS cùng thang với điều khoản. Bỏ cửa sổ: CW không khớp ở 1 trong 2 đầu, còn
    < MIN_NGAY_GD_CUOI_LUOT ngày tới GD cuối ở phiên a (trang ⚡ cũng loại), quá ngày GD cuối ở phiên b, không giải được IV,
    delta ngoài DELTA_DO."""
    dong = []
    for i in range(0, len(lich) - so_phien, so_phien):
        a, b = lich[i], lich[i + so_phien]
        if kl.get(a, 0) <= 0 or kl.get(b, 0) <= 0 or a not in gia_cs.index or b not in gia_cs.index:
            continue
        if (dk["gd_cuoi"] - a.date()).days < C.MIN_NGAY_GD_CUOI_LUOT or b.date() > dk["gd_cuoi"]:
            continue
        K, ty_le, Sa, Sb = dk["K"], dk["ty_le"], gia_cs[a], gia_cs[b]
        Ta, Tb = ((dk["dao_han"] - d.date()).days / 365 for d in (a, b))
        iva = C.bien_dong_ngam_dinh(gia[a], Sa, K, Ta, r, ty_le)
        ivb = C.bien_dong_ngam_dinh(gia[b], Sb, K, Tb, r, ty_le)
        if not iva or not ivb:
            continue
        delta = C.black_scholes_call(Sa, K, Ta, r, iva)[1]
        if not DELTA_DO[0] <= delta <= DELTA_DO[1]:
            continue
        dong.append(
            {"Mã CW": dk["ma"], "TCPH": dk["tcph"], "Ngày": a, "Delta": delta, "CS %": Sb / Sa - 1, "ΔIV": ivb - iva}
            | {
                "Mô hình %": C.black_scholes_call(Sb, K, Tb, r, iva)[0] / ty_le / gia[a] - 1,
                "Thực %": gia[b] / gia[a] - 1,
            }
            | {
                "S b": Sb,
                "K": K,
                "T b": Tb,
                "IV a": iva,
                "Tỷ lệ": ty_le,
                "Giá a": gia[a],
            }  # để tính lại mô hình hiệu chỉnh
        )
    return pd.DataFrame(dong)


def chieu(cs_pt):
    return np.where(cs_pt > 0, "tăng", "giảm")


def bang_he_so(w):
    """Bảng hệ số theo (TCPH, chiều CS) từ các cửa sổ w: "Cửa sổ β" / "Số CW" / "Số ngày" = mẫu đo β (|CS| ≥ NGUONG_CS_BETA),
    β = trung vị ΔIV / CS đổi, "t β" = t của trung bình theo ngày (L.t_theo_ngay), "Truyền dẫn" = trung vị thực / mô hình
    trên "Cửa sổ truyền dẫn" (|mô hình| ≥ NGUONG_MO_HINH)."""
    dong = []
    for (tcph, c), g in w.assign(c=chieu(w["CS %"])).groupby(["TCPH", "c"]):
        b, td = g[g["CS %"].abs() >= NGUONG_CS_BETA], g[g["Mô hình %"].abs() >= NGUONG_MO_HINH]
        ti = b["ΔIV"] / b["CS %"]
        dong.append(
            {"TCPH": tcph, "Chiều CS": c, "Cửa sổ β": len(b), "Số CW": b["Mã CW"].nunique()}
            | {"Số ngày": b["Ngày"].nunique(), "β": ti.median(), "t β": L.t_theo_ngay(ti, b["Ngày"])}
            | {"Cửa sổ truyền dẫn": len(td), "Truyền dẫn": (td["Thực %"] / td["Mô hình %"]).median()}
        )
    return pd.DataFrame(dong)


def mo_hinh_hieu_chinh(w, bang, r=C.LAI_SUAT_PHI_RUI_RO):
    """CW mô hình đổi (tỷ lệ) khi IV phiên b = IV a + β × CS đổi, β của (TCPH, chiều CS) có ≥ MIN_MAU_HE_SO_IV cửa sổ (còn lại
    β = 0: như mô hình gốc). Cùng công thức với cột hiệu chỉnh của trang ⚡ (cw_scanner.luot_ngan_han, d_iv)."""
    b = bang[bang["Cửa sổ β"] >= C.MIN_MAU_HE_SO_IV].set_index(["TCPH", "Chiều CS"])["β"]
    beta = [b.get((t, c), 0.0) for t, c in zip(w["TCPH"], chieu(w["CS %"]))]
    return pd.Series(
        [
            C.black_scholes_call(S, K, T, r, iv + be * x)[0] / tl / g - 1
            for S, K, T, iv, be, x, tl, g in zip(
                w["S b"], w["K"], w["T b"], w["IV a"], beta, w["CS %"], w["Tỷ lệ"], w["Giá a"]
            )
        ],
        w.index,
        dtype=float,
    )


# ============ BÁO CÁO ============
def bang_he_so_md(bang):
    dong = [
        [
            h["TCPH"],
            h["Chiều CS"],
            str(h["Cửa sổ β"]),
            str(h["Số CW"]),
            str(h["Số ngày"]),
            L._s(h["β"]),
            L._s(h["t β"], 1),
        ]
        + [str(h["Cửa sổ truyền dẫn"]), f"{h['Truyền dẫn']:.2f}".replace(".", ",") if h["Cửa sổ truyền dẫn"] else "—"]
        + ["✓" if h["Cửa sổ β"] >= C.MIN_MAU_HE_SO_IV else ""]
        for _, h in bang.sort_values(["TCPH", "Chiều CS"], ascending=[True, False]).iterrows()
    ]
    cot = [
        "TCPH",
        "Chiều CS",
        "Cửa sổ β",
        "Số CW",
        "Số ngày",
        "β (điểm IV / 1% CS)",
        "t β",
        "Cửa sổ truyền dẫn",
        "Truyền dẫn TV",
    ]
    return L.bang_md(cot + [f"Hiệu chỉnh (≥ {C.MIN_MAU_HE_SO_IV})"], dong)


def bang_kiem_md(w, hc, ds_tcph):
    """Truyền dẫn trung vị trước / sau hiệu chỉnh theo nhóm tiền (cửa sổ |mô hình gốc| ≥ NGUONG_MO_HINH) và |thực − mô hình|
    trung vị (mọi cửa sổ), cho các TCPH được hiệu chỉnh."""
    x = w.assign(c=chieu(w["CS %"]), hc=hc, nhom=pd.cut(w["Delta"], [0, *BIEN_DELTA, 1], labels=NHAN_DELTA))
    dong = []
    for (t, c), g in x[x["TCPH"].isin(ds_tcph)].groupby(["TCPH", "c"]):
        td = g[g["Mô hình %"].abs() >= NGUONG_MO_HINH]
        o = []
        for nh in NHAN_DELTA:
            y = td[td["nhom"] == nh]
            truoc, sau = (y["Thực %"] / y["Mô hình %"]).median(), (y["Thực %"] / y["hc"]).median()
            o.append(f"{truoc:.2f} → {sau:.2f} ({len(y)})".replace(".", ",") if len(y) else "—")
        sai = [_p((g["Thực %"] - g[cot]).abs().median()) for cot in ("Mô hình %", "hc")]
        dong.append([t, c, *o, f"{sai[0]} → {sai[1]}"])
    return L.bang_md(["TCPH", "Chiều CS", *NHAN_DELTA, "|Thực − mô hình| TV"], dong)


def _p(x):
    return L._p(x, 1).lstrip("+")


def chay():
    tep = max(C.THU_MUC_KET_QUA.glob("kiem_chung_luot_du_lieu_*.pkl"), default=None)
    if tep is None:
        raise SystemExit("Chưa có dữ liệu: chạy python kiem_chung_luot.py trước (tải giá ngày + điều khoản CW).")
    lich, gia_cs, cw, su_kien, _ = pd.read_pickle(tep)
    ngay = lich[-1].date()
    tep_bs = C.THU_MUC_KET_QUA / f"kiem_chung_truyen_dan_du_lieu_{ngay}.pkl"  # chạy lại không tải lại ~500 mã
    if not tep_bs.exists():
        pd.to_pickle(lay_bo_sung(lich, gia_cs, cw, su_kien), tep_bs)
    bo_sung, canh_bao = pd.read_pickle(tep_bs)
    w = pd.concat(
        [cua_so(dk, gia, kl, gia_cs[dk["cs"]] / dk.get("f", 1.0), lich) for dk, gia, kl in cw + bo_sung],
        ignore_index=True,
    )
    tu = lich[-1] - pd.DateOffset(months=C.SO_THANG_HE_SO_IV)
    gan = w[w["Ngày"] >= tu]  # bảng hệ số cho trang ⚡: chỉ SO_THANG_HE_SO_IV tháng gần nhất
    bang = bang_he_so(gan)
    bang.round({"β": 4, "t β": 2, "Truyền dẫn": 4}).to_csv(
        C.THU_MUC_KET_QUA / f"he_so_iv_tcph_{ngay}.csv", index=False, encoding="utf-8-sig"
    )
    ds = sorted(bang.loc[bang["Cửa sổ β"] >= C.MIN_MAU_HE_SO_IV, "TCPH"].unique())
    # ngoài mẫu: hệ số từ SO_THANG_HE_SO_IV tháng trước mốc (giữa các ngày đầu cửa sổ), kiểm trên phần sau mốc
    ngay_dau = sorted(w["Ngày"].unique())
    moc = ngay_dau[len(ngay_dau) // 2]
    dau = w[(w["Ngày"] < moc) & (w["Ngày"] >= moc - pd.DateOffset(months=C.SO_THANG_HE_SO_IV))]
    sau = w[w["Ngày"] >= moc].copy()
    bang_dau = bang_he_so(dau)
    nua_nam = w.assign(
        c=chieu(w["CS %"]), ky=w["Ngày"].dt.year.astype(str) + "-H" + ((w["Ngày"].dt.month > 6) + 1).astype(str)
    )
    ky = sorted(nua_nam["ky"].unique())
    dong_ky = []
    for (t, c), g in nua_nam[nua_nam["TCPH"].isin(ds)].groupby(["TCPH", "c"]):
        b = g[g["CS %"].abs() >= NGUONG_CS_BETA]
        tv = (b["ΔIV"] / b["CS %"]).groupby(b["ky"]).agg(["median", "size"])
        dong_ky.append(
            [t, c] + [f"{L._s(tv.loc[k, 'median'])} ({tv.loc[k, 'size']})" if k in tv.index else "—" for k in ky]
        )
    phan = [
        f"# Tổ chức phát hành đổi IV theo hướng CS ({ngay:%d/%m/%Y})",
        (
            f"Giá ngày {lich[0]:%d/%m/%Y} – {ngay:%d/%m/%Y}, {len(cw)} CW từ `{tep.name}` + {len(bo_sung)} CW hết hạn có sự kiện"
            f" quyền sau ngày GD cuối (thang giá CS hiệu chỉnh bằng giá thô HOSE). {len(w)} cửa sổ {SO_PHIEN} phiên của"
            f" {w['Mã CW'].nunique()} CW, {w['Ngày'].nunique()} ngày đầu cửa sổ. Bảng hệ số: `he_so_iv_tcph_{ngay}.csv`"
            f" (trang ⚡ đọc file mới nhất) chỉ dùng {len(gan)} cửa sổ bắt đầu từ {tu:%d/%m/%Y} ({C.SO_THANG_HE_SO_IV} tháng gần nhất)."
        ),
        f"""**Cách đo và giới hạn (đọc trước khi tin số)**
- **Giá đóng cửa ≠ giá yết của TCPH.** Không có lịch sử sổ lệnh: IV giải từ giá đóng cửa (≈ giá giữa), lệch ± nửa spread ở cả 2 đầu;
  cột hiệu chỉnh của trang ⚡ áp cùng β vào giá chờ mua (giả định spread tương đối không đổi).
- **Mẫu theo thời kỳ.** Hệ số là hành vi của TCPH trong {C.SO_THANG_HE_SO_IV} tháng tới {ngay:%d/%m/%Y}; TCPH đổi cách yết thì hệ số cũ sai
  (xem bảng theo nửa năm và kiểm ngoài mẫu). Chạy lại định kỳ.
- Cửa sổ: CW có khớp ở cả 2 đầu, còn ≥ {C.MIN_NGAY_GD_CUOI_LUOT} ngày tới GD cuối, delta {DELTA_DO[0]:g}–{DELTA_DO[1]:g} (theo IV phiên đầu).
  β chỉ đo trên cửa sổ |CS| ≥ {NGUONG_CS_BETA:.0%}, truyền dẫn trên cửa sổ |mô hình| ≥ {NGUONG_MO_HINH:.0%}. r = {L._p(C.LAI_SUAT_PHI_RUI_RO, 0)}.
- CW cùng ngày tương quan mạnh: số quan sát độc lập ≈ số ngày; t β = t của trung bình ΔIV / CS đổi từng ngày.
- β là trung vị, không phải hồi quy: không tách phần IV trôi theo thời gian (ΔIV khi CS đứng yên) khỏi phần theo CS.""",
        f"## 1. Bảng hệ số ({C.SO_THANG_HE_SO_IV} tháng từ {tu:%d/%m/%Y})\nβ = trung vị (ΔIV / CS đổi): CS +1% thì IV TCPH yết đổi β điểm. Truyền dẫn = trung vị (CW thực đổi / CW mô hình"
        " đổi khi IV giữ nguyên): 1 = đúng mô hình, < 1 = CW chạy ít hơn mô hình.\n" + bang_he_so_md(bang),
        f"## 2. Kiểm hiệu chỉnh trong mẫu ({C.SO_THANG_HE_SO_IV} tháng, TCPH ≥ {C.MIN_MAU_HE_SO_IV} cửa sổ)\nMỗi ô nhóm tiền: truyền dẫn TV gốc → sau hiệu chỉnh"
        " (IV b = IV a + β × CS đổi), (số cửa sổ). Hiệu chỉnh đúng thì sau ≈ 1 ở mọi nhóm tiền.\n"
        + bang_kiem_md(gan, mo_hinh_hieu_chinh(gan, bang), ds),
        f"## 3. Ngoài mẫu: hệ số đo {C.SO_THANG_HE_SO_IV} tháng trước {moc:%d/%m/%Y}, kiểm từ {moc:%d/%m/%Y}\nTCPH có < {C.MIN_MAU_HE_SO_IV} cửa sổ trong"
        " các tháng đo thì không được hiệu chỉnh (trước = sau).\n"
        + bang_kiem_md(sau, mo_hinh_hieu_chinh(sau, bang_dau), ds),
        "## 4. β theo nửa năm (trung vị, số cửa sổ)\n" + L.bang_md(["TCPH", "Chiều CS", *ky], dong_ky),
    ]
    if canh_bao:
        phan.append(f"## Cảnh báo dữ liệu ({len(canh_bao)} CW bổ sung bị bỏ)\n" + "\n".join(f"- {c}" for c in canh_bao))
    noi_dung = "\n\n".join(phan) + "\n"
    (C.THU_MUC_KET_QUA / f"kiem_chung_truyen_dan_{ngay}.md").write_text(noi_dung, encoding="utf-8")
    print(noi_dung)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    chay()
