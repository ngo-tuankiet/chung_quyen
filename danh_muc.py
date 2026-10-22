"""
danh_muc.py - Theo dõi danh mục CW đang nắm: lưu lệnh, tính vị thế (giá vốn bình quân), lãi/lỗ nếu bán ngay,
cảnh báo (gần ngày GD cuối, cổ phiếu cơ sở gần giá thực hiện, chạm chốt lời/cắt lỗ, bất thường) và gửi Discord.

Kiểm tra:  python danh_muc.py          (launchd gọi mỗi 5 phút; ngoài giờ khớp lệnh thì thoát ngay, không gọi mạng)
           python danh_muc.py --luon   (kiểm tra bất kể giờ: dùng sau lần quét 14:00)
           python danh_muc.py --bao-cao (báo cáo tổng hợp ngày lên Discord)
Lệnh lưu trong danh_muc.csv (không đưa lên git). Webhook Discord: DISCORD_WEBHOOK_URL trong .env.
Chỉ gửi Discord khi một cảnh báo VỪA xuất hiện; cùng cảnh báo không gửi lại cho tới khi nó hết rồi xảy ra lần nữa.
"""

import csv
import json
import math
import os
import re
import shutil
import sys
import urllib.request
from datetime import date, datetime, timedelta
from datetime import time as gio

import pandas as pd

import cw_scanner as C

# ============ CẤU HÌNH ============
CHOT_LOI_MAC_DINH = 0.50  # báo khi lãi nếu bán ngay ≥ +50% (đặt riêng được cho từng lệnh mua)
CAT_LO_MAC_DINH = 0.30  # báo khi lỗ nếu bán ngay ≥ 30%
CANH_BAO_NGAY_GD_CUOI = 20  # báo khi còn ≤ 20 ngày (lịch) tới ngày giao dịch cuối
CANH_BAO_CACH_GIA_TH = 0.03  # báo khi cổ phiếu cơ sở cao hơn giá thực hiện ≤ 3% (hoặc đã xuống dưới)
GIO_KHOP_LENH = [(gio(9, 15), gio(11, 30)), (gio(13, 0), gio(14, 45))]  # HOSE: khớp liên tục sáng, chiều + ATC
GAN_NGUONG = 0.10  # báo cáo ngày: liệt kê vị thế còn cách ngưỡng chốt lời/cắt lỗ ≤ 10 điểm %
NGUONG_CW_DAT = 0.15  # báo khi bán ngay ≥ giá trị theo mô hình × 1,15 VÀ IV (theo giá chờ mua) > trung vị IV CW cùng mã
CANH_BAO_LECH = 0.15  # báo khi CW lệch ≥ 15% so với mức lẽ ra theo cổ phiếu cơ sở (từ lệnh mua gần nhất), cả hai chiều
SO_MA_NOI_BAT = 5
MAX_MA_MOI_VAO = 10  # báo cáo ngày: tối đa số mã "mới vào nhóm Nên xem xét" liệt kê (mỗi mã tốn 1 lượt vnstock để tính độ lệch)  # báo cáo ngày: số mã "Nên xem xét" đưa vào
URL_DISCORD_HOP_LE = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")

FILE_DANH_MUC = C.THU_MUC / "danh_muc.csv"
FILE_TRANG_THAI = C.THU_MUC / "canh_bao_da_gui.json"
COT = ["id", "ngay", "ma_cw", "loai", "so_luong", "gia", "chot_loi", "cat_lo", "ghi_chu"]
MAU_MA_CW = re.compile(r"C[A-Z]{3}\d{4}")


def so(x):
    """1234567.8 -> '1.234.568' (số kiểu Việt Nam)."""
    return f"{x:,.0f}".replace(",", ".")


def pt(x, le=0, dau=True):
    """0.0251 -> '+2,5%' (phần trăm kiểu Việt Nam)."""
    return f"{x:{'+' if dau else ''}.{le}%}".replace(".", ",")


# ============ LƯU LỆNH ============
def doc_lenh(file=None):
    """Danh sách lệnh trong danh_muc.csv (file chưa có -> []). File hỏng thì báo lỗi, không bỏ qua."""
    file = file or FILE_DANH_MUC
    if not file.exists():
        return []
    with open(file, encoding="utf-8-sig", newline="") as f:
        doc = csv.DictReader(f)
        # sai dòng tiêu đề mà coi như danh sách rỗng thì lần lưu kế tiếp sẽ ghi đè mất toàn bộ lịch sử lệnh -> phải báo lỗi
        if doc.fieldnames != COT:
            raise ValueError(f"dòng tiêu đề phải là {','.join(COT)}")
        so_hay_rong = lambda x: float(x) if x else None
        return [
            {
                **d,
                "id": int(d["id"]),
                "so_luong": int(d["so_luong"]),
                "gia": float(d["gia"]),
                "chot_loi": so_hay_rong(d["chot_loi"]),
                "cat_lo": so_hay_rong(d["cat_lo"]),
            }
            for d in doc
        ]


def ghi_lenh(ds, file=None):
    """Ghi an toàn: ghi file tạm rồi đổi tên (không bao giờ để lại file ghi dở); bản trước giữ ở .bak để hoàn tác 1 bước."""
    file = file or FILE_DANH_MUC
    tam = file.with_suffix(".tmp")
    with open(tam, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, COT)
        w.writeheader()
        w.writerows({k: "" if d.get(k) is None else d[k] for k in COT} for d in ds)
    if file.exists():
        shutil.copy2(file, file.with_suffix(".csv.bak"))
    tam.replace(file)


def doc_gia(chuoi):
    """Giá khớp theo cách app chứng khoán hiển thị (nghìn đồng: '0.87', '0,87') hoặc theo đồng ('870') -> đồng.
    Giá CW thấp nhất 10 đ = 0,01 nghìn đồng và hiếm khi quá 100.000 đ, nên số dưới 100 được hiểu là nghìn đồng."""
    gia = float(chuoi.replace(",", "."))
    return round(gia * 1000, 6) if gia < 100 else gia


def doc_form(form):
    """Form web {tên: [giá trị]} -> (lệnh, lỗi). Chốt lời / cắt lỗ nhập theo % (50 -> 0.5), để trống = mặc định."""
    lay = lambda k: (form.get(k) or [""])[0].strip()
    try:
        lenh = {
            "ngay": date.fromisoformat(lay("ngay")).isoformat(),
            "ma_cw": lay("ma_cw").upper(),
            "loai": lay("loai"),
            "so_luong": int(lay("so_luong")),
            "gia": doc_gia(lay("gia")),
            "ghi_chu": lay("ghi_chu")[:200],
        }
        for k in ("chot_loi", "cat_lo"):
            lenh[k] = float(lay(k)) / 100 if lay(k) else None
    except ValueError:
        return None, ["ngày, số lượng, giá, chốt lời/cắt lỗ phải là số (ngày dạng 2026-10-19)"]
    return lenh, []


def kiem_tra_lenh(lenh, ds, ma_hop_le, hom_nay):
    """Danh sách lỗi của 1 lệnh định thêm vào ds ([] = hợp lệ)."""
    loi, ma = [], lenh["ma_cw"]
    if not MAU_MA_CW.fullmatch(ma):
        loi.append("mã CW phải dạng C + 3 chữ + 4 số, ví dụ CVPB2615")
    elif ma not in ma_hop_le:
        loi.append(f"{ma} không có trong lần quét gần nhất")
    if lenh["loai"] not in ("MUA", "BAN"):
        loi.append("loại lệnh phải là MUA hoặc BAN")
    if lenh["so_luong"] <= 0 or lenh["so_luong"] % 100:
        loi.append("số lượng phải là bội số của 100 (lô chẵn CW)")
    if not lenh["gia"] > 0:
        loi.append("giá phải lớn hơn 0")
    elif round(lenh["gia"]) % 10 or lenh["gia"] != round(lenh["gia"]):
        loi.append(f"giá {so(lenh['gia'])} đ không đúng bước giá 10 đ (nhập 0,87 hoặc 870)")
    if lenh["ngay"] > hom_nay.isoformat():
        loi.append("ngày không được ở tương lai")
    for k, ten in (("chot_loi", "chốt lời"), ("cat_lo", "cắt lỗ")):
        if lenh[k] is not None and not 0 < lenh[k] <= 10:
            loi.append(f"{ten} phải từ 1% đến 1.000%")
    if lenh["loai"] == "BAN" and not loi:
        dang_nam = tinh_vi_the(ds).get(ma, {}).get("so_luong", 0)
        if lenh["so_luong"] > dang_nam:
            loi.append(f"chỉ đang nắm {so(dang_nam)} {ma}, không bán được {so(lenh['so_luong'])}")
    return loi


def them_lenh(form, ma_hop_le, hom_nay):
    """Thêm 1 lệnh từ form web. Trả về danh sách lỗi ([] = đã lưu)."""
    lenh, loi = doc_form(form)
    ds = doc_lenh()
    loi = loi or kiem_tra_lenh(lenh, ds, ma_hop_le, hom_nay)
    if not loi:
        ghi_lenh(ds + [{**lenh, "id": max((d["id"] for d in ds), default=0) + 1}])
    return loi


def xoa_lenh(id_lenh):
    """Xóa 1 lệnh. Không cho xóa nếu làm số đang nắm bị âm (vd xóa lệnh mua đã có lệnh bán sau đó). Trả về lỗi hoặc ""."""
    ds = doc_lenh()
    con_lai = [d for d in ds if d["id"] != id_lenh]
    if len(con_lai) == len(ds):
        return f"không có lệnh số {id_lenh}"
    try:
        tinh_vi_the(con_lai)
    except ValueError as e:
        return f"không xóa được: {e}"
    ghi_lenh(con_lai)
    return ""


# ============ VỊ THẾ ============
def tinh_vi_the(ds):
    """{mã: {so_luong, gia_von (1 CW, đã gồm phí mua), lai_da_chot (đ), chot_loi, cat_lo}} theo giá vốn bình quân
    như app công ty chứng khoán. Lệnh bán vượt số đang nắm -> ValueError (dữ liệu sai phải nổi lên)."""
    vt = {}
    for l in sorted(ds, key=lambda l: (l["ngay"], l["id"])):
        v = vt.setdefault(
            l["ma_cw"],
            {"so_luong": 0, "von": 0.0, "lai_da_chot": 0.0, "chot_loi": None, "cat_lo": None, "ngay_mua": None},
        )
        if l["loai"] == "MUA":
            v["von"] += l["so_luong"] * l["gia"] * (1 + C.PHI_GIAO_DICH)
            v["so_luong"] += l["so_luong"]
            v["ngay_mua"] = l["ngay"]  # mốc đo độ lệch so với CS: lệnh mua gần nhất
            v["chot_loi"] = (
                l["chot_loi"] if l["chot_loi"] is not None else v["chot_loi"]
            )  # ngưỡng của lệnh mua gần nhất có đặt
            v["cat_lo"] = l["cat_lo"] if l["cat_lo"] is not None else v["cat_lo"]
        else:
            if l["so_luong"] > v["so_luong"]:
                raise ValueError(
                    f"lệnh {l['id']} bán {so(l['so_luong'])} {l['ma_cw']} nhưng lúc đó chỉ nắm {so(v['so_luong'])}"
                )
            gia_von = v["von"] / v["so_luong"]
            v["lai_da_chot"] += l["so_luong"] * (l["gia"] * (1 - C.PHI_GIAO_DICH - C.THUE_BAN) - gia_von)
            v["von"] -= l["so_luong"] * gia_von
            v["so_luong"] -= l["so_luong"]
    for v in vt.values():
        v["gia_von"] = v.pop("von") / v["so_luong"] if v["so_luong"] else 0.0
    return vt


def giu_hay_ban(S, K, ty_le, T, r, sigma, gia_ban):
    """So bán ngay với giữ đến đáo hạn cho 1 CW (giá VND):
    ban_ngay = giá chờ mua sau phí + thuế; giu_mh = giá trị nếu giữ theo mô hình (sigma lịch sử, trừ thuế khi nhận tiền);
    cs_can = giá CS (bình quân 5 phiên trước đáo hạn) để tiền nhận về bằng bán ngay; cach = cs_can / S − 1; ve_0 = K / S − 1.
    """
    ban_ngay = gia_ban * (1 - C.PHI_GIAO_DICH - C.THUE_BAN)
    giu_mh = (
        C.black_scholes_call(S, K, T, r, sigma)[0] / ty_le * (1 - C.THUE_BAN) if not math.isnan(sigma) else float("nan")
    )
    cs_can = K + ty_le * ban_ngay / (1 - C.THUE_BAN)
    return {"ban_ngay": ban_ngay, "giu_mh": giu_mh, "cs_can": cs_can, "cach": cs_can / S - 1, "ve_0": K / S - 1}


def lo_100(x):
    """Làm tròn số cổ phiếu theo lô 100 (làm tròn lên từ 50: 450 -> 500)."""
    return int(x / 100 + 0.5) * 100


def canh_bao_cw_dat(so_luong, gia_bid, S, K, ty_le, dao_han, hom_nay, r, sigma, df, ma, cs):
    """Nội dung cảnh báo "CW đắt, cân nhắc chuyển sang cổ phiếu" hoặc "" nếu không đủ điều kiện:
    (1) bán ngay ≥ giá trị theo mô hình × (1 + NGUONG_CW_DAT); (2) IV theo giá chờ mua > trung vị IV các CW cùng mã.
    Có ghi số tiền (người dùng yêu cầu): tiền thu về, vốn mua cổ phiếu đủ số và theo delta (lô 100)."""
    if not gia_bid or not dao_han or math.isnan(sigma):
        return ""
    T = (dao_han - hom_nay).days / 365
    g = giu_hay_ban(S, K, ty_le, T, r, sigma, gia_bid)
    iv = C.bien_dong_ngam_dinh(gia_bid, S, K, T, r, ty_le)
    if iv is None or round(g["ban_ngay"], 9) < round(g["giu_mh"] * (1 + NGUONG_CW_DAT), 9):
        return ""
    tv = C.so_iv_cung_ma(df, ma, cs, iv * 100)[0]
    if math.isnan(tv) or iv * 100 <= tv:
        return ""
    so_cw_khac = int(((df["Mã CS"] == cs) & (df["Mã CW"] != ma) & df["IV %"].notna()).sum())
    thu_ve = so_luong * g["ban_ngay"]
    du_so, theo_delta = lo_100(so_luong / ty_le), lo_100(so_luong / ty_le * C.black_scholes_call(S, K, T, r, sigma)[1])
    return (
        f"CW đắt hơn mô hình {pt(g['ban_ngay'] / g['giu_mh'] - 1)} (bán ngay {so(g['ban_ngay'])} đ/CW, giữ theo mô hình "
        f"{so(g['giu_mh'])} đ); IV khi bán {iv * 100:.0f}% > trung vị {tv:.0f}% của {so_cw_khac} CW {cs}. "
        f"Bán hết thu ≈ {so(thu_ve)} đ. Chuyển sang {cs}: đủ số {so(du_so)} cp ≈ {so(du_so * S)} đ "
        f"(cần thêm ≈ {so(max(du_so * S - thu_ve, 0))} đ) · theo delta {so(theo_delta)} cp ≈ {so(theo_delta * S)} đ. "
        "Lưu ý: cổ phiếu không có giới hạn lỗ như CW; 3 lần giao dịch chịu phí, thuế; cổ phiếu về tài khoản sau T+2"
    )


def danh_gia_danh_muc(vt, bang_gia, df, hom_nay, kl_truoc, lich_su=None):
    """Chỉ số theo giá trực tiếp + cảnh báo cho các vị thế còn nắm.
    bang_gia: kết quả lay_bang_gia (CW + cổ phiếu cơ sở); df: bảng lần quét gần nhất (sigma, r, IV cùng mã);
    kl_truoc: {mã: khối lượng niêm yết lần kiểm tra trước} để phát hiện phát hành thêm;
    lich_su: {mã CS: [[ngày, giá đã điều chỉnh quyền]]} của lần quét (giá CS ngày mua, để đo độ lệch so với CS).
    Trả về (dòng, cảnh báo [(mã, loại, nội dung)], khối lượng niêm yết mới)."""
    dong, canh_bao, kl_moi = [], [], {}
    for ma, v in sorted(vt.items()):
        if v["so_luong"] <= 0:
            continue
        if ma not in bang_gia:
            canh_bao.append((ma, "khong_co_gia", "không có trên bảng giá (đã hết giao dịch?)"))
            dong.append({"ma": ma, **v, "co_gia": False})
            continue
        ny, kl, so_lenh = bang_gia[ma]
        cs = ny["underlyingSymbol"]
        gia_bid = [m.get("price") for m in so_lenh.get("bidPrices") or []]
        gia_bid = max((g for g in gia_bid if isinstance(g, (int, float)) and g > 0), default=None)
        gia_ban = gia_bid or C.gia_hien_tai(ny, kl)  # không ai đặt mua thì tạm dùng giá khớp (có cảnh báo riêng)
        lai_pct = gia_ban * (1 - C.PHI_GIAO_DICH - C.THUE_BAN) / v["gia_von"] - 1
        S, K = C.gia_hien_tai(*bang_gia[cs]), ny["exercisePrice"]
        gd = ny.get("lastTradingDate") or ""
        ngay_gd_cuoi = date(int(gd[:4]), int(gd[4:6]), int(gd[6:])) if gd else None
        con_ngay = (ngay_gd_cuoi - hom_nay).days if ngay_gd_cuoi else None
        quet = df[df["Mã CS"] == cs]
        md = ny.get("maturityDate") or ""
        dao_han = date(int(md[:4]), int(md[4:6]), int(md[6:])) if md else None
        r_dg = float(quet["r %"].iloc[0]) / 100 if len(quet) and "r %" in quet else C.LAI_SUAT_PHI_RUI_RO
        iv, don_bay, canh_bao_iv, sigma = float("nan"), float("nan"), "", float("nan")
        if len(quet):  # IV, đòn bẩy theo giá trực tiếp; sigma và r như lúc quét
            dg = C.dinh_gia(
                ny,
                kl,
                so_lenh,
                S,
                float(quet["Biến động %/năm"].iloc[0]) / 100,
                hom_nay,
                float(quet["r %"].iloc[0]) / 100 if "r %" in quet else None,
            )
            iv, don_bay, sigma = dg["IV %"], dg["Đòn bẩy"], dg["Biến động %/năm"] / 100
            canh_bao_iv = C.so_iv_cung_ma(df, ma, cs, iv)[1]
        chot_loi, cat_lo = v["chot_loi"] or CHOT_LOI_MAC_DINH, v["cat_lo"] or CAT_LO_MAC_DINH
        # Lệch so với CS từ lệnh mua gần nhất: mốc = giá vốn bình quân (bỏ phí) và giá CS đóng cửa ngày mua
        lech, r_lech = float("nan"), None
        S0 = [g for d, g in (lich_su or {}).get(cs, []) if d <= (v["ngay_mua"] or "")]
        if S0 and dao_han:
            lech, r_lech = C.lech_theo_cs(
                v["gia_von"] / (1 + C.PHI_GIAO_DICH),
                S0[-1],
                date.fromisoformat(v["ngay_mua"]),
                C.gia_hien_tai(ny, kl),
                S,
                hom_nay,
                K,
                C.doc_ty_le(ny["exerciseRatio"]),
                dao_han,
                r_dg,
            )
        kl_moi[ma] = ny.get("listedShare") or 0
        dong.append(
            {
                "ma": ma,
                **v,
                "co_gia": True,
                "cs": cs,
                "gia_ban": gia_ban,
                "co_nguoi_mua": gia_bid is not None,
                "lai_pct": lai_pct,
                "lai": (gia_ban * (1 - C.PHI_GIAO_DICH - C.THUE_BAN) - v["gia_von"]) * v["so_luong"],
                "S": S,
                "K": K,
                "cach_K": S / K - 1,
                "ngay_gd_cuoi": ngay_gd_cuoi,
                "con_ngay": con_ngay,
                "iv": iv,
                "don_bay": don_bay,
                "chot_loi": chot_loi,
                "cat_lo": cat_lo,
                "tiep_xuc": v["so_luong"] / C.doc_ty_le(ny["exerciseRatio"]) * S,
                "lech": lech,
                "lech_r0": r_lech == 0.0,
                # còn ≤ CANH_BAO_NGAY_GD_CUOI ngày tới ngày GD cuối: so giữ đến đáo hạn với bán ngay (mục ⏳ của báo cáo)
                "giu_hay_ban": (
                    giu_hay_ban(
                        S, K, C.doc_ty_le(ny["exerciseRatio"]), (dao_han - hom_nay).days / 365, r_dg, sigma, gia_ban
                    )
                    if con_ngay is not None and con_ngay <= CANH_BAO_NGAY_GD_CUOI and dao_han
                    else None
                ),
                "dao_han": dao_han,
            }
        )
        # Cảnh báo: nội dung chỉ có mã, %, giá - không có số tiền, khối lượng (tin gửi lên máy chủ Discord)
        if con_ngay is not None and con_ngay <= CANH_BAO_NGAY_GD_CUOI:
            canh_bao.append((ma, "gd_cuoi", f"còn {con_ngay} ngày tới ngày giao dịch cuối {ngay_gd_cuoi:%d/%m/%Y}"))
        # làm tròn trước khi so ngưỡng: 20.600 / 20.000 − 1 tính ra 0,030000000000000027 > 0,03 (lỗi số thực ngay tại biên)
        if round(S / K - 1, 9) <= CANH_BAO_CACH_GIA_TH:
            canh_bao.append(
                (
                    ma,
                    "gan_gia_th",
                    f"{cs} {so(S)} đ "
                    + (
                        f"đã dưới giá thực hiện {so(K)} đ ({pt(S / K - 1, 1)})"
                        if S < K
                        else f"chỉ cao hơn giá thực hiện {so(K)} đ {pt(S / K - 1, 1, False)}"
                    ),
                )
            )
        if round(lai_pct, 9) >= chot_loi:
            canh_bao.append(
                (ma, "chot_loi", f"lãi nếu bán ngay {pt(lai_pct)} (ngưỡng {pt(chot_loi)}), giá chờ mua {so(gia_ban)} đ")
            )
        if round(lai_pct, 9) <= -cat_lo:
            canh_bao.append(
                (ma, "cat_lo", f"lỗ nếu bán ngay {pt(lai_pct)} (ngưỡng {pt(-cat_lo)}), giá chờ mua {so(gia_ban)} đ")
            )
        if not math.isnan(lech) and abs(round(lech, 9)) >= CANH_BAO_LECH:
            ngay_mua = f"{v['ngay_mua'][8:]}/{v['ngay_mua'][5:7]}"
            canh_bao.append(
                (ma, "lech_am", f"CW không theo kịp {cs}: thấp hơn mức lẽ ra {pt(lech, 1)} kể từ ngày mua {ngay_mua}")
                if lech < 0
                else (
                    ma,
                    "lech_duong",
                    f"CW cao hơn mức lẽ ra theo {cs} {pt(lech, 1)} kể từ ngày mua {ngay_mua}: dễ bị kéo về",
                )
            )
        cb_dat = canh_bao_cw_dat(
            v["so_luong"], gia_bid, S, K, C.doc_ty_le(ny["exerciseRatio"]), dao_han, hom_nay, r_dg, sigma, df, ma, cs
        )
        if cb_dat:
            canh_bao.append((ma, "cw_dat", cb_dat))
        if gia_bid is None:
            canh_bao.append((ma, "khong_nguoi_mua", "sổ lệnh không có giá chờ mua: hiện không bán ra được"))
        if canh_bao_iv:
            canh_bao.append((ma, "iv_bat_thuong", canh_bao_iv.split(":")[0]))
        if kl_truoc.get(ma) and kl_moi[ma] > kl_truoc[ma]:
            canh_bao.append(
                (
                    ma,
                    "phat_hanh_them",
                    (
                        f"khối lượng niêm yết tăng {pt(kl_moi[ma] / kl_truoc[ma] - 1)}: "
                        "tổ chức phát hành bán thêm, giá dễ bị ép xuống"
                    ),
                )
            )
    return dong, canh_bao, kl_moi


def doc_lich_su(ngay):
    """Lịch sử giá CS (đã điều chỉnh quyền) lưu ở lần quét ngày `ngay`: {mã CS: [[ngày, giá]]}; chưa có -> {}."""
    file = C.THU_MUC_KET_QUA / f"lich_su_{ngay}.json"
    return json.loads(file.read_text(encoding="utf-8")) if ngay and file.exists() else {}


def tai_bang_gia(ds_ma, df, cho=15):
    """Bảng giá trực tiếp cho các CW + cổ phiếu cơ sở của chúng: thường 1 lượt gọi; mã CS chưa có trong lần quét thì thêm 1 lượt."""
    ma_cs = set(df.loc[df["Mã CW"].isin(ds_ma), "Mã CS"]) if df is not None else set()
    bang = C.lay_bang_gia(sorted(set(ds_ma) | ma_cs), cho=cho)
    thieu = {bang[m][0]["underlyingSymbol"] for m in ds_ma if m in bang} - bang.keys()
    return {**bang, **C.lay_bang_gia(sorted(thieu), cho=cho)} if thieu else bang


def chon_canh_bao_moi(canh_bao, dang_bao):
    """Chỉ gửi cảnh báo VỪA xuất hiện (chưa có trong dang_bao). Trả về (cảnh báo mới, danh sách đang báo mới)."""
    khoa = lambda cb: f"{cb[0]}|{cb[1]}"
    return [cb for cb in canh_bao if khoa(cb) not in set(dang_bao)], sorted({khoa(cb) for cb in canh_bao})


# ============ DISCORD ============
def gui_discord(noi_dung, url):
    """Gửi 1 tin qua webhook Discord. Chỉ nhận URL webhook của Discord; không bao giờ in URL ra (trong URL có mã bí mật)."""
    if not url.startswith(URL_DISCORD_HOP_LE):
        raise ValueError(
            "DISCORD_WEBHOOK_URL trong .env không phải webhook Discord (https://discord.com/api/webhooks/...)"
        )
    yeu_cau = urllib.request.Request(
        url,
        data=json.dumps({"content": noi_dung[:1900]}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "cw_scanner"},
    )
    with urllib.request.urlopen(yeu_cau, timeout=10):  # lỗi mạng / 4xx / 5xx -> báo lỗi, lần sau gửi lại
        pass


def noi_dung_discord(moi, luc):
    return f"**Cảnh báo danh mục CW** ({luc:%H:%M %d/%m})\n" + "\n".join(f"⚠ **{ma}**: {nd}" for ma, _, nd in moi)


def chia_tin(noi_dung, toi_da=1900):
    """Discord nhận tối đa 2.000 ký tự/tin: ghép theo mục (ngăn bởi dòng trống) để không cắt đôi khối bảng;
    mục nào tự nó quá dài thì mới cắt theo dòng."""
    tin, cur = [], ""
    for muc in noi_dung.split("\n\n"):
        if len(muc) > toi_da:
            tin += [cur] if cur else []
            cur = ""
            for dong in muc.split("\n"):
                if cur and len(cur) + len(dong) + 1 > toi_da:
                    tin.append(cur)
                    cur = ""
                cur = f"{cur}\n{dong}" if cur else dong[:toi_da]
            continue
        if cur and len(cur) + len(muc) + 2 > toi_da:
            tin.append(cur)
            cur = ""
        cur = f"{cur}\n\n{muc}" if cur else muc
    return tin + [cur] if cur else tin


def bang(cot, hang):
    """Bảng chữ đều cột trong khối ``` (Discord không có bảng thật). Cột đầu căn trái, còn lại căn phải."""
    rong = [max(len(str(x)) for x in [c] + [h[i] for h in hang]) for i, c in enumerate(cot)]
    dong = lambda h: "  ".join(str(x).ljust(rong[0]) if i == 0 else str(x).rjust(rong[i]) for i, x in enumerate(h))
    return "```\n" + "\n".join([dong(cot)] + [dong(h) for h in hang]) + "\n```"


def _x(x):
    """8.52 -> '8,5x' (đòn bẩy); thiếu số liệu -> '—'."""
    return f"{x:.1f}x".replace(".", ",") if not math.isnan(x) else "—"


COT_CW = ["Mã CW", "Giá", "H.lý", "%", "IV-HV", "Cần", "ĐB"]
GHI_CHU_CW = (
    "_Giá = giá mua (chào bán) · H.lý = giá hợp lý · % = so với giá hợp lý · IV-HV (điểm) · "
    "Cần = % CS phải tăng để hòa vốn · ĐB = đòn bẩy_"
)


def _hang_cw(h):
    """1 CW thành hàng bảng: giá mua, hợp lý, %, IV − HV, % CS cần tăng để hòa vốn, đòn bẩy."""
    so1 = lambda x: f"{x:+.1f}".replace(".", ",")
    return [
        h["Mã CW"],
        so(h["Giá mua"]),
        so(h["Giá hợp lý"]),
        so1(h["Đắt/rẻ %"]),
        so1(h["IV − HV"]),
        so1(h["CS tăng % để hòa vốn"]),
        _x(h["Đòn bẩy"]),
    ]


def doc_ket_qua_truoc(ngay):
    """Bảng kết quả của lần quét gần nhất TRƯỚC ngày `ngay` (quét lại trong ngày vẫn so với ngày giao dịch trước); chưa có -> None."""
    cu = [f for f in sorted(C.THU_MUC_KET_QUA.glob("cw_*.csv")) if f.stem[3:] < str(ngay)]
    return pd.read_csv(cu[-1], encoding="utf-8-sig", keep_default_na=False) if cu else None


def cw_moi_vao_nhom(df_nay, df_truoc):
    """CW hôm nay ở nhóm NÊN XEM XÉT mà lần quét trước ở THEO DÕI / BỎ QUA (mã mới niêm yết không tính: đã có mục CW mới).
    Thêm cột "Từ nhóm"; giữ thứ tự của df_nay (IV − HV thấp nhất trước)."""
    if df_truoc is None:
        return df_nay.iloc[0:0]
    truoc = dict(zip(df_truoc["Mã CW"], df_truoc["Đánh giá"]))
    moi = df_nay[
        (df_nay["Đánh giá"] == "NÊN XEM XÉT") & df_nay["Mã CW"].map(lambda m: truoc.get(m) in ("THEO DÕI", "BỎ QUA"))
    ]
    return moi.assign(**{"Từ nhóm": moi["Mã CW"].map(truoc)})


def bao_cao_ngay(df, ngay_quet, dong, canh_bao, lai_da_chot, luc, moi_vao=None, lech_moi_vao=None, quet_loi=None):
    """Nội dung báo cáo tổng hợp hằng ngày (dùng riêng, có số tiền)."""
    phan = [
        f"📊 **Báo cáo CW {luc:%H:%M %d/%m/%Y}** – quét {ngay_quet:%d/%m}: "
        + ", ".join(f"{k} {v}" for k, v in df["Đánh giá"].value_counts().items())
    ]
    if quet_loi:  # (lý do, thời điểm của số liệu đang dùng)
        phan[0] += f"\n⚠ **Quét hôm nay lỗi** ({quet_loi[0][:150]}); số liệu bên dưới là của lần quét {quet_loi[1]}"
    # 0. Mới vào nhóm Nên xem xét (so với lần quét trước): độ lệch 20 phiên và IV so với CW cùng mã để tham khảo
    if moi_vao is not None and len(moi_vao):
        hien = moi_vao.head(MAX_MA_MOI_VAO)
        tv = lambda h: (
            f"{h['IV %']:.0f}/{h['IV cùng mã %']:.0f}"
            if not math.isnan(h.get("IV cùng mã %", math.nan)) and not math.isnan(h["IV %"])
            else "—"
        )
        lech = lambda m: "—" if math.isnan((lech_moi_vao or {}).get(m, math.nan)) else pt(lech_moi_vao[m], 1)
        phan.append(
            f"🔔 **Mới vào nhóm Nên xem xét** ({len(moi_vao)} mã)\n"
            + bang(COT_CW, [_hang_cw(h) for _, h in hien.iterrows()])
            + "\n"
            + bang(
                ["Mã CW", "Từ", "IV/TV cùng mã", "Lệch 20p"],
                [
                    [h["Mã CW"], {"THEO DÕI": "TD", "BỎ QUA": "BQ"}.get(h["Từ nhóm"], "?"), tv(h), lech(h["Mã CW"])]
                    for _, h in hien.iterrows()
                ],
            )
            + (f"\nvà {len(moi_vao) - len(hien)} mã khác" if len(moi_vao) > len(hien) else "")
            + "\n_Từ: nhóm lần quét trước (TD theo dõi, BQ bỏ qua) · IV/TV: IV của CW / trung vị IV các CW cùng mã · "
            "Lệch 20p: so với mức lẽ ra theo CS trong 20 phiên (tham khảo, không phải tín hiệu mua)_"
        )
    # 1. Danh mục
    phan.append("💼 **Danh mục**")
    co_gia = [d for d in dong if d.get("co_gia")]
    if not dong:
        phan[-1] += "\nChưa có lệnh nào (nhập ở trang 💼 Danh mục)."
    if co_gia:
        dau = lambda x: ("+" if x >= 0 else "-") + so(abs(x))
        phan[-1] += "\n" + bang(
            ["Mã CW", "SL", "Vốn", "Bán", "Lãi%", "Lãi đ"],
            [
                [
                    d["ma"],
                    so(d["so_luong"]),
                    so(d["gia_von"]),
                    so(d["gia_ban"]),
                    pt(d["lai_pct"], 1).rstrip("%"),
                    dau(d["lai"]),
                ]
                for d in co_gia
            ],
        )
        phan[-1] += "\n" + bang(
            ["Mã CW", "Cách", "Còn", "ĐB", "Lệch"],
            [
                [
                    d["ma"],
                    pt(d["cach_K"], 1),
                    f"{d['con_ngay']}d",
                    _x(d["don_bay"]),
                    "—" if math.isnan(d["lech"]) else pt(d["lech"], 1) + ("*" if d["lech_r0"] else ""),
                ]
                for d in co_gia
            ],
        )
        von, lai = sum(d["so_luong"] * d["gia_von"] for d in co_gia), sum(d["lai"] for d in co_gia)
        phan[-1] += (
            f"\nTổng vốn **{so(von)} đ** · nếu bán hết ngay **{dau(lai)} đ ({pt(lai / von, 1)})** · "
            f"đã chốt {dau(lai_da_chot)} đ\n_Cách = CS so với giá thực hiện · Còn = số ngày tới ngày GD cuối · Lệch = giá CW so với mức lẽ ra theo CS kể từ lệnh mua gần nhất (âm: CW không theo kịp; * tính với r = 0)_"
        )
    for d in dong:
        if not d.get("co_gia"):
            phan[
                -1
            ] += f"\n• **{d['ma']}**: {so(d['so_luong'])} CW, giá vốn {so(d['gia_von'])} đ – không có giá trực tiếp"
    # 1b. Sắp hết hạn (≤ CANH_BAO_NGAY_GD_CUOI ngày tới ngày GD cuối): giữ đến đáo hạn hay bán
    sap_het = [d for d in co_gia if d.get("giu_hay_ban")]
    if sap_het:
        ngay_ = lambda x: f"{x:%d/%m/%Y}" if x else "—"
        phan.append(
            "⏳ **Sắp hết hạn: giữ đến đáo hạn hay bán**\n"
            + bang(
                ["Mã CW", "Bán ngay", "Giữ (MH)", "CS cần", "Cách", "Còn"],
                [
                    [
                        d["ma"],
                        so(d["giu_hay_ban"]["ban_ngay"]),
                        "—" if math.isnan(d["giu_hay_ban"]["giu_mh"]) else so(d["giu_hay_ban"]["giu_mh"]),
                        so(d["giu_hay_ban"]["cs_can"]),
                        pt(d["giu_hay_ban"]["cach"], 1),
                        f"{d['con_ngay']}d",
                    ]
                    for d in sap_het
                ],
            )
            + "".join(
                f"\n• **{d['ma']}**: CW về 0 nếu {d['cs']} ≤ {so(d['K'])} ({pt(d['giu_hay_ban']['ve_0'], 1)}) · "
                f"GD cuối {ngay_(d['ngay_gd_cuoi'])} · đáo hạn {ngay_(d['dao_han'])}"
                + ("" if d["co_nguoi_mua"] else ' · không ai đặt mua: "Bán ngay" tính theo giá khớp')
                for d in sap_het
            )
            + "\n_Bán ngay: giá chờ mua sau phí, thuế · Giữ (MH): giá trị nếu giữ đến đáo hạn theo mô hình σ lịch sử (không phải dự báo) · "
            "CS cần: giá CS bình quân 5 phiên trước đáo hạn để giữ bằng bán ngay (cao hơn thì giữ có lợi hơn) · "
            "Sau ngày GD cuối không bán được; xem lịch nghỉ lễ nếu 5 phiên đó rơi gần kỳ nghỉ_"
        )
    # 2. Gần ngưỡng chốt lời / cắt lỗ
    gan = [d for d in co_gia if d["lai_pct"] >= d["chot_loi"] - GAN_NGUONG or d["lai_pct"] <= -d["cat_lo"] + GAN_NGUONG]
    if gan:
        phan.append("🎯 **Gần ngưỡng chốt lời / cắt lỗ**")
        for d in gan:
            loai, nguong = ("chốt lời", d["chot_loi"]) if d["lai_pct"] > 0 else ("cắt lỗ", -d["cat_lo"])
            phan[-1] += "\n" + (
                f"• **{d['ma']}** {pt(d['lai_pct'], 1)} – ngưỡng {loai} {pt(nguong)}, "
                + (
                    "ĐÃ CHẠM"
                    if abs(d["lai_pct"]) >= abs(nguong)
                    else f"còn {pt(abs(nguong) - abs(d['lai_pct']), 1, False)}"
                )
            )
    # 3. Cảnh báo
    if canh_bao:
        phan.append("⚠ **Cảnh báo**\n" + "\n".join(f"• **{m}**: {nd}" for m, _, nd in canh_bao))
    # 4. CW mới phát hành, định giá tốt
    moi = df[(df["Mới"] == "MỚI") & (df["IV − HV"] <= C.MAX_IV_TRU_HV * 100)] if "Mới" in df else df.iloc[0:0]
    phan.append(
        "🆕 **CW mới phát hành, định giá tốt** (IV − HV ≤ "
        + pt(C.MAX_IV_TRU_HV, 0).rstrip("%")
        + " điểm)\n"
        + (bang(COT_CW, [_hang_cw(h) for _, h in moi.iterrows()]) if len(moi) else "Hôm nay không có.")
    )
    # 5. Nên xem xét + IV bất thường
    tot = df[df["Đánh giá"] == "NÊN XEM XÉT"].head(SO_MA_NOI_BAT)
    phan.append(
        f"⭐ **Top {len(tot)} Nên xem xét**\n"
        + bang(COT_CW, [_hang_cw(h) for _, h in tot.iterrows()])
        + "\n"
        + GHI_CHU_CW
    )
    if "Cảnh báo" in df and (df["Cảnh báo"].fillna("") != "").any():
        phan.append(
            "❗ **IV bất thường**\n"
            + "\n".join(
                f"• **{h['Mã CW']}**: {h['Cảnh báo'].split(':')[0]}"
                for _, h in df[df["Cảnh báo"].fillna("") != ""].iterrows()
            )
        )
    return "\n\n".join(phan)


def tinh_lech_20_phien(h, ngay_quet, lich_su):
    """Độ lệch 20 phiên của 1 CW (dòng trong bảng quét): 1 lượt vnstock lấy lịch sử giá CW. Lỗi -> NaN và ghi log."""
    try:
        d = C.lay_gia_dong_cua(h["Mã CW"])
        he_so = 10 ** round(math.log10(h["Giá CW"] / float(d["close"].iloc[-1])))  # vnstock có thể trả nghìn đồng
        gia = {str(t)[:10]: float(g) * he_so for t, g in zip(d["time"], d["close"])}
        kl = {str(t)[:10]: float(v) for t, v in zip(d["time"], d["volume"])}
        dao_han = ngay_quet + timedelta(days=int(h["Ngày còn lại"]))
        _, hang = C.lech_20_phien(
            gia,
            kl,
            dict(lich_su.get(h["Mã CS"], [])),
            h["Giá thực hiện"],
            h["Tỷ lệ CĐ"],
            dao_han,
            float(h["r %"]) / 100,
        )
        return hang[-1][4] if hang else math.nan
    # lỗi mạng / hết lượt gọi: chỉ cột Lệch của mã này ghi "—", báo cáo vẫn gửi
    except Exception as e:  # noqa: BLE001
        print(f"  [!] Không tính được độ lệch {h['Mã CW']}: {e}")
        return math.nan


def gui_bao_cao_ngay(luc=None, quet_loi=""):
    """Lập và gửi báo cáo ngày lên Discord (sau lần quét theo lịch)."""
    luc = luc or datetime.now()
    from web import doc_ket_qua  # nhập ở đây để tránh vòng lặp import

    df, ngay = doc_ket_qua()
    if df is None:
        print(f"{luc:%d/%m %H:%M} [!] Chưa có kết quả quét, không lập được báo cáo")
        return
    tat_ca = tinh_vi_the(doc_lenh())
    vt = {m: v for m, v in tat_ca.items() if v["so_luong"] > 0}
    dong, canh_bao = [], []
    if vt:
        tt = json.loads(FILE_TRANG_THAI.read_text(encoding="utf-8")) if FILE_TRANG_THAI.exists() else {}
        dong, canh_bao, _ = danh_gia_danh_muc(
            vt, tai_bang_gia(list(vt), df), df, luc.date(), tt.get("kl_niem_yet", {}), doc_lich_su(ngay)
        )
    url = C.doc_env().get("DISCORD_WEBHOOK_URL", "")
    if not url:
        print(f"{luc:%d/%m %H:%M} [!] Chưa có DISCORD_WEBHOOK_URL trong .env, không gửi báo cáo")
        return
    moi_vao, lech_moi_vao = cw_moi_vao_nhom(df, doc_ket_qua_truoc(ngay)), {}
    ls = doc_lich_su(ngay)
    for _, h in moi_vao.head(MAX_MA_MOI_VAO).iterrows():
        lech_moi_vao[h["Mã CW"]] = tinh_lech_20_phien(h, ngay, ls)
    if quet_loi:  # thời điểm của file kết quả đang dùng (lần quét thành công gần nhất)
        tep = max(C.THU_MUC_KET_QUA.glob("cw_*.csv"))
        quet_loi = (quet_loi, f"{datetime.fromtimestamp(tep.stat().st_mtime):%d/%m %H:%M}")
    lai_chot = sum(v["lai_da_chot"] for v in tat_ca.values())
    tin = chia_tin(bao_cao_ngay(df, ngay, dong, canh_bao, lai_chot, luc, moi_vao, lech_moi_vao, quet_loi or None))
    for t in tin:
        gui_discord(t, url)
    print(f"{luc:%d/%m %H:%M} Đã gửi báo cáo ngày ({len(tin)} tin)")


def trong_gio_khop_lenh(luc):
    return luc.weekday() < 5 and any(a <= luc.time() <= b for a, b in GIO_KHOP_LENH)


def kiem_tra(luon=False, luc=None):
    """Lần kiểm tra theo lịch: tính cảnh báo, gửi Discord những cảnh báo vừa xuất hiện. Trả về các cảnh báo đã gửi."""
    luc = luc or datetime.now()
    if not luon and not trong_gio_khop_lenh(luc):
        return []
    vt = {ma: v for ma, v in tinh_vi_the(doc_lenh()).items() if v["so_luong"] > 0}
    if not vt:
        return []
    from web import doc_ket_qua  # nhập ở đây để tránh vòng lặp import (web.py dùng danh_muc.py)

    df, ngay_quet = doc_ket_qua()
    df = (
        df if df is not None else pd.DataFrame(columns=["Mã CW", "Mã CS", "IV %"])
    )  # chưa quét lần nào: bỏ phần IV, đòn bẩy
    bang_gia = tai_bang_gia(list(vt), df)
    hom_nay = str(luc.date())
    if not any(ny.get("tradingDate") == hom_nay for ny, *_ in bang_gia.values()):
        return []  # ngày nghỉ lễ / Tết: bảng giá vẫn là phiên trước, không có gì mới để báo
    trang_thai = json.loads(FILE_TRANG_THAI.read_text(encoding="utf-8")) if FILE_TRANG_THAI.exists() else {}
    _, canh_bao, kl_moi = danh_gia_danh_muc(
        vt, bang_gia, df, luc.date(), trang_thai.get("kl_niem_yet", {}), doc_lich_su(ngay_quet)
    )
    moi, dang_bao = chon_canh_bao_moi(canh_bao, trang_thai.get("dang_bao", []))
    # mỗi loại cảnh báo của mỗi mã tối đa 1 tin/ngày: giá dao động quanh ngưỡng thì không gửi lặp (lỗi thật 22/10/2026)
    da_gui = {k: ngay for k, ngay in trang_thai.get("da_gui", {}).items() if ngay == hom_nay}
    moi = [cb for cb in moi if f"{cb[0]}|{cb[1]}" not in da_gui]
    if moi:
        url = C.doc_env().get("DISCORD_WEBHOOK_URL", "")
        if not url:
            print(f"{luc:%d/%m %H:%M} [!] Có {len(moi)} cảnh báo mới nhưng chưa có DISCORD_WEBHOOK_URL trong .env")
            return []  # không lưu trạng thái: có webhook rồi thì lần sau vẫn gửi
        gui_discord(noi_dung_discord(moi, luc), url)
        print(f"{luc:%d/%m %H:%M} Đã gửi {len(moi)} cảnh báo lên Discord: " + ", ".join(f"{m} {l}" for m, l, _ in moi))
    # lưu sau khi gửi thành công: gửi lỗi thì lần kiểm tra sau gửi lại
    FILE_TRANG_THAI.write_text(
        json.dumps(
            {
                "dang_bao": dang_bao,
                "kl_niem_yet": kl_moi,
                "da_gui": {**da_gui, **{f"{m}|{l}": hom_nay for m, l, _ in moi}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return moi


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--bao-cao" in sys.argv:
        gui_bao_cao_ngay(quet_loi=os.environ.get("QUET_LOI", ""))  # chay_quet_tu_dong.sh truyền lý do khi quét lỗi
    else:
        kiem_tra(luon="--luon" in sys.argv)
