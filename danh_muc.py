"""
danh_muc.py - Theo dõi danh mục CW đang nắm: lưu lệnh, tính vị thế (giá vốn bình quân), lãi/lỗ nếu bán ngay,
cảnh báo (gần ngày GD cuối, cổ phiếu cơ sở gần giá thực hiện, chạm chốt lời/cắt lỗ, bất thường) và gửi Discord.

Kiểm tra:  python danh_muc.py          (launchd gọi mỗi 5 phút; ngoài giờ khớp lệnh thì thoát ngay, không gọi mạng)
           python danh_muc.py --luon   (kiểm tra bất kể giờ: dùng sau lần quét 14:00)
           python danh_muc.py --bao-cao (báo cáo ngày lên Discord: lãi/lỗ mã đang giữ + bất thường)
Lệnh lưu trong danh_muc.csv (không đưa lên git). Webhook Discord: DISCORD_WEBHOOK_URL trong .env.
Chỉ gửi Discord cảnh báo BẤT THƯỜNG (BAT_THUONG) VỪA xuất hiện, mỗi loại của mỗi mã tối đa 1 tin/ngày.
"""

import csv
import json
import math
import os
import re
import shutil
import sys
import urllib.request
from datetime import date, datetime
from datetime import time as gio

import numpy as np
import pandas as pd

import cw_scanner as C

# ============ CẤU HÌNH ============
CHOT_LOI_MAC_DINH = 0.50  # báo khi lãi nếu bán ngay ≥ +50% (đặt riêng được cho từng lệnh mua)
CAT_LO_MAC_DINH = 0.30  # báo khi lỗ nếu bán ngay ≥ 30%
CANH_BAO_NGAY_GD_CUOI = 20  # báo khi còn ≤ 20 ngày (lịch) tới ngày giao dịch cuối
# Báo gấp khi còn ≤ 2 phiên tới ngày GD cuối. Ngày GD cuối lấy từ bảng giá (lastTradingDate), không tự tính: quy chế cũ
# là 2 phiên trước đáo hạn (T−2), chưa xác minh trong quy chế niêm yết CW theo TT 122/2025.
CANH_BAO_PHIEN_GD_CUOI_GAP = 2
CANH_BAO_CACH_GIA_TH = 0.03  # báo khi cổ phiếu cơ sở cao hơn giá thực hiện ≤ 3% (hoặc đã xuống dưới)
GIO_KHOP_LENH = [(gio(9, 15), gio(11, 30)), (gio(13, 0), gio(14, 45))]  # HOSE: khớp liên tục sáng, chiều + ATC
NGUONG_CW_DAT = 0.15  # báo khi bán ngay ≥ giá trị theo mô hình × 1,15 VÀ IV (theo giá chờ mua) > trung vị IV CW cùng mã
CANH_BAO_LECH = 0.15  # báo khi CW lệch ≥ 15% so với mức lẽ ra theo cổ phiếu cơ sở (từ lệnh mua gần nhất), cả hai chiều
# Trạng thái bán của mỗi vị thế (KE_HOACH Phần 5, "Khi nào bán"): chỉ hiện trên web, không gửi Discord
MUC_KHONG, MUC_CAN_NHAC, MUC_NEN_BAN = 0, 1, 2
TEN_MUC = {MUC_KHONG: "⚪ Không có tín hiệu bán", MUC_CAN_NHAC: "🟡 Cân nhắc bán", MUC_NEN_BAN: "🔴 Nên bán"}
THETA_CAN_NHAC, THETA_NEN_BAN = 0.01, 0.02  # mất giá 1 ngày (CS, IV đứng yên) so với giá CW; heuristic, chờ backtest
SO_PHIEN_THANH_TOAN = 5  # giá thanh toán = bình quân giá đóng cửa 5 phiên liền trước đáo hạn (QĐ 34/QĐ-SGDHCM Điều 12)
# Lý do bán theo thứ tự ưu tiên (đứng trước = lý do chính khi cùng mức); cảnh báo không có ở đây chỉ là thông tin
LY_DO_BAN = {
    "cat_lo": "chạm cắt lỗ",
    "chot_loi": "chạm chốt lời",
    "cw_dat": "CW đắt hơn mô hình",
    "theta_cao": "mất giá theo thời gian nhanh",
    "gd_cuoi_gap": "còn rất ít phiên để bán",
    "gd_cuoi": "sắp tới ngày GD cuối",
    "ky_thanh_toan": "đang trong 5 phiên tính giá thanh toán",
    "lech_duong": "CW cao hơn mức lẽ ra theo CS",
    "phat_hanh_them": "TCPH phát hành thêm",
    "theta": "mất giá theo thời gian",
}
# Discord chỉ báo bất thường (người dùng chốt 23/10/2026); các cảnh báo khác (gần giá thực hiện, IV bất thường, lệch so với CS,
# mức Cân nhắc bán) chỉ hiện trên web. Báo cáo ngày chỉ có lãi/lỗ mã đang giữ + mục Bất thường.
BAT_THUONG = {
    "chot_loi",
    "cat_lo",
    "cw_dat",
    "theta_cao",
    "gd_cuoi",
    "gd_cuoi_gap",
    "ky_thanh_toan",
    "phat_hanh_them",
    "khong_nguoi_mua",
    "khong_co_gia",
}
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
            {
                "so_luong": 0,
                "von": 0.0,
                "lai_da_chot": 0.0,
                "chot_loi": None,
                "cat_lo": None,
                "ngay_mua": None,
                "mua": [],
            },
        )
        if l["loai"] == "MUA":
            v["von"] += l["so_luong"] * l["gia"] * (1 + C.PHI_GIAO_DICH)
            v["so_luong"] += l["so_luong"]
            v["ngay_mua"] = l["ngay"]  # ngày mốc (thời gian còn lại) khi đo độ lệch so với CS
            v["mua"].append((l["ngay"], l["so_luong"]))  # để lấy giá CS bình quân đi cùng giá vốn bình quân
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
            if not v["so_luong"]:
                v["mua"] = []  # đóng hết vị thế: lần mua sau là vị thế mới
    for v in vt.values():
        v["gia_von"] = v.pop("von") / v["so_luong"] if v["so_luong"] else 0.0
    return vt


def giu_hay_ban(S, K, ty_le, T, r, sigma, gia_ban):
    """So bán ngay với giữ đến đáo hạn cho 1 CW (giá VND):
    ban_ngay = giá chờ mua sau phí + thuế; giu_mh = giá trị nếu giữ theo mô hình (sigma lịch sử, trừ thuế khi nhận tiền);
    cs_can = giá CS (bình quân 5 phiên trước đáo hạn) để tiền nhận về bằng bán ngay; cach = cs_can / S − 1; ve_0 = K / S − 1.
    """
    ban_ngay = gia_ban * (1 - C.PHI_GIAO_DICH - C.THUE_BAN)
    # thuế 0,1% tính trên giá trị danh nghĩa CS khi có lãi (C.tien_dao_han): kỳ vọng rủi ro trung tính của S_T·1{S_T>K}
    # chiết khấu về hôm nay là S·N(d1) = S·delta, nên giá trị giữ = (giá call − thuế·S·delta) / tỷ lệ
    if math.isnan(sigma):
        giu_mh = float("nan")
    else:
        call, delta = C.black_scholes_call(S, K, T, r, sigma)
        giu_mh = (call - C.THUE_BAN * S * delta) / ty_le
    cs_can = (K + ty_le * ban_ngay) / (1 - C.THUE_BAN)  # tien_dao_han(cs_can) = ban_ngay
    return {"ban_ngay": ban_ngay, "giu_mh": giu_mh, "cs_can": cs_can, "cach": cs_can / S - 1, "ve_0": K / S - 1}


def phien_thanh_toan(dao_han):
    """SO_PHIEN_THANH_TOAN phiên liền trước đáo hạn (mới nhất trước), dùng tính giá thanh toán.
    shortcut: chỉ bỏ cuối tuần, chưa bỏ ngày lễ; nếu cần chính xác thì lấy lịch nghỉ của HOSE."""
    dh = np.datetime64(dao_han)
    return [np.busday_offset(dh, -i, roll="backward").astype(date) for i in range(1, SO_PHIEN_THANH_TOAN + 1)]


def san_ly_thuyet(S, K, ty_le, r, hom_nay, dao_han):
    """Giá trị tối thiểu (đ/CW) nếu giữ tới đáo hạn: [0,999·S·TB(e^(−r(T−tᵢ))) − K·e^(−rT)] / tỷ lệ, tᵢ là 5 phiên tính giá
    thanh toán (bỏ cuối tuần), 0,1% là thuế trên giá thanh toán. Cận dưới call châu Âu (Hull ch. 11) cho giá bình quân.
    """
    chiet_khau = (
        sum(math.exp(-r * (dao_han - p).days / C.NGAY_MOT_NAM) for p in phien_thanh_toan(dao_han)) / SO_PHIEN_THANH_TOAN
    )
    return C.can_duoi((1 - C.THUE_BAN) * S * chiet_khau, K, (dao_han - hom_nay).days / C.NGAY_MOT_NAM, r) / ty_le


def trang_thai_vi_the(loai, tu_dat_chot, tu_dat_cat, mat_gia_ngay):
    """(mức, [lý do theo ưu tiên]) từ tập loại cảnh báo đang bật của 1 vị thế. Nên bán: chốt lời/cắt lỗ do người dùng tự đặt,
    CW đắt, mất giá ≥ THETA_NEN_BAN/ngày; Cân nhắc: ngưỡng mặc định và các lý do khác trong LY_DO_BAN; còn lại là thông tin.
    """
    muc = {
        "cat_lo": MUC_NEN_BAN if tu_dat_cat else MUC_CAN_NHAC,
        "chot_loi": MUC_NEN_BAN if tu_dat_chot else MUC_CAN_NHAC,
    }
    muc["cw_dat"] = muc["theta_cao"] = MUC_NEN_BAN
    bat = set(loai)
    if -mat_gia_ngay >= THETA_NEN_BAN:  # NaN: so sánh luôn sai, không bật
        bat.add("theta_cao")
    elif -mat_gia_ngay >= THETA_CAN_NHAC:
        bat.add("theta")
    thu_tu = list(LY_DO_BAN)
    ly_do = sorted((l for l in bat if l in LY_DO_BAN), key=lambda l: (-muc.get(l, MUC_CAN_NHAC), thu_tu.index(l)))
    return (muc.get(ly_do[0], MUC_CAN_NHAC) if ly_do else MUC_KHONG), ly_do


def lo_100(x):
    """Làm tròn số cổ phiếu theo lô 100 (làm tròn lên từ 50: 450 -> 500)."""
    return int(x / 100 + 0.5) * 100


def canh_bao_cw_dat(so_luong, gia_bid, S, K, ty_le, dao_han, hom_nay, r, sigma, df, ma, cs):
    """Nội dung cảnh báo "CW đắt, cân nhắc chuyển sang cổ phiếu" hoặc "" nếu không đủ điều kiện:
    (1) bán ngay ≥ giá trị theo mô hình × (1 + NGUONG_CW_DAT); (2) IV theo giá chờ mua > trung vị IV các CW cùng mã.
    Có ghi số tiền (người dùng yêu cầu): tiền thu về, vốn mua cổ phiếu đủ số và theo delta (lô 100)."""
    if not gia_bid or not dao_han or math.isnan(sigma):
        return ""
    T = (dao_han - hom_nay).days / C.NGAY_MOT_NAM
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
        iv, don_bay, canh_bao_iv, sigma, mat_gia = float("nan"), float("nan"), "", float("nan"), float("nan")
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
            mat_gia = dg["Mất giá/ngày %"] / 100  # tính ở IV giá chào bán, cùng số với trang ⚡ Lướt CW
            canh_bao_iv = C.so_iv_cung_ma(df, ma, cs, iv)[1]
        chot_loi, cat_lo = v["chot_loi"] or CHOT_LOI_MAC_DINH, v["cat_lo"] or CAT_LO_MAC_DINH
        # Lệch so với CS: mốc = giá vốn bình quân (bỏ phí) đi cùng giá CS bình quân theo số lượng các lần mua (cùng cách
        # bình quân), ngày mốc = lần mua gần nhất. Giá CW hiện tại = giá giữa sổ lệnh: CW chưa khớp trong phiên thì giá khớp /
        # tham chiếu là giá cũ, so với giá CS trực tiếp sẽ ra lệch giả. Sổ lệnh thiếu 1 bên thì không đo.
        lech, r_lech = float("nan"), None
        ls = (lich_su or {}).get(cs, [])
        S_mua = [([g for d, g in ls if d <= ngay] or [None])[-1] for ngay, _ in v.get("mua", [])]
        gia_chao, nguon_chao = C.gia_mua(ny, kl, so_lenh)
        if S_mua and None not in S_mua and gia_bid and nguon_chao == "ask" and dao_han:
            S0 = sum(g * q for g, (_, q) in zip(S_mua, v["mua"])) / sum(q for _, q in v["mua"])
            lech, r_lech = C.lech_theo_cs(
                v["gia_von"] / (1 + C.PHI_GIAO_DICH),
                S0,
                date.fromisoformat(v["ngay_mua"]),
                (gia_bid + gia_chao) / 2,
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
                        S,
                        K,
                        C.doc_ty_le(ny["exerciseRatio"]),
                        (dao_han - hom_nay).days / C.NGAY_MOT_NAM,
                        r_dg,
                        sigma,
                        gia_ban,
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
        con_phien = (
            int(np.busday_count(hom_nay, ngay_gd_cuoi)) if ngay_gd_cuoi else None
        )  # cùng giới hạn ngày lễ như trên
        if con_phien is not None and 0 <= con_phien <= CANH_BAO_PHIEN_GD_CUOI_GAP:
            canh_bao.append(
                (
                    ma,
                    "gd_cuoi_gap",
                    f"còn {con_phien} phiên tới ngày GD cuối {ngay_gd_cuoi:%d/%m}: sau đó không bán được nữa",
                )
            )
        if dao_han and hom_nay in phien_thanh_toan(dao_han):
            canh_bao.append(
                (
                    ma,
                    "ky_thanh_toan",
                    f"giá đóng cửa {cs} các phiên tới {phien_thanh_toan(dao_han)[0]:%d/%m} quyết định tiền nhận về "
                    + f"(bình quân {SO_PHIEN_THANH_TOAN} phiên, đáo hạn {dao_han:%d/%m})",
                )
            )
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
        # trạng thái bán: chỉ gắn vào dòng (web), không thêm vào canh_bao nên không đổi tin Discord
        cua_ma = {l: nd for m, l, nd in canh_bao if m == ma}
        thong_tin = []
        if "lech_duong" in cua_ma and dao_han:
            # lãi do TCPH nâng IV chỉ là lý do Cân nhắc bán khi CW không còn rẻ: bán ngay ≥ giá trị theo HV, hoặc IV (giá chào bán)
            # ≥ trung vị IV cùng mã. Còn rẻ thì chỉ là thông tin (người dùng chốt 23/10/2026)
            g = giu_hay_ban(
                S, K, C.doc_ty_le(ny["exerciseRatio"]), (dao_han - hom_nay).days / C.NGAY_MOT_NAM, r_dg, sigma, gia_ban
            )
            tv = C.so_iv_cung_ma(df, ma, cs, iv)[0] if len(quet) else math.nan
            if g["ban_ngay"] < g["giu_mh"] and not iv >= tv:  # NaN: không đủ CW cùng mã thì chỉ xét theo HV
                thong_tin.append(
                    f"{cua_ma.pop('lech_duong').split(':')[0]}, nhưng vẫn rẻ hơn mô hình "
                    f"{pt(1 - g['ban_ngay'] / g['giu_mh'], dau=False)} (giá trị theo HV {so(g['giu_mh'])} đ, không phải dự báo)"
                )
        muc, ly_do = trang_thai_vi_the(cua_ma, v["chot_loi"] is not None, v["cat_lo"] is not None, mat_gia)
        chi_tiet = {l: f"{LY_DO_BAN[l]}: mất {pt(-mat_gia, 2, False)}/ngày" for l in ("theta_cao", "theta")}
        san = san_ly_thuyet(S, K, C.doc_ty_le(ny["exerciseRatio"]), r_dg, hom_nay, dao_han) if dao_han else float("nan")
        dong[-1]["trang_thai"] = {
            "muc": muc,
            "ly_do": [(l, cua_ma.get(l) or chi_tiet.get(l, "")) for l in ly_do],
            "duoi_san": gia_ban * (1 - C.PHI_GIAO_DICH - C.THUE_BAN) < san,
            "san": san,
            "mat_gia_ngay": mat_gia,
            "thong_tin": thong_tin,
        }
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
        # allowed_mentions rỗng: chữ lấy từ API ngoài (mã, tên quỹ) không biến thành "@everyone" thông báo cả server
        data=json.dumps({"content": noi_dung[:1900], "allowed_mentions": {"parse": []}}).encode(),
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


def bat_thuong(dong, canh_bao):
    """Cảnh báo đáng gửi Discord: loại trong BAT_THUONG, cộng "mất giá theo thời gian nhanh" lấy từ trạng thái bán."""
    them = [
        (d["ma"], l, f"{nd} (CS, IV đứng yên)")
        for d in dong
        for l, nd in d.get("trang_thai", {}).get("ly_do", [])
        if l == "theta_cao"
    ]
    return [cb for cb in canh_bao if cb[1] in BAT_THUONG] + them


def bao_cao_ngay(dong, canh_bao, lai_da_chot, luc, quet_loi=None):
    """Báo cáo ngày (dùng riêng, có số tiền): lãi/lỗ từng mã đang giữ; mục Bất thường chỉ khi có. "" nếu không có gì để báo."""
    phan = [f"⚠ **Quét hôm nay lỗi** ({quet_loi[0][:150]}); số liệu là của lần quét {quet_loi[1]}"] if quet_loi else []
    co_gia = [d for d in dong if d.get("co_gia")]
    if co_gia:
        dau = lambda x: ("+" if x >= 0 else "-") + so(abs(x))
        von, lai = sum(d["so_luong"] * d["gia_von"] for d in co_gia), sum(d["lai"] for d in co_gia)
        phan.append(
            bang(
                ["Mã CW", "SL", "Vốn", "Bán", "Lãi%", "Lãi đ"],
                [
                    [d["ma"], so(d["so_luong"]), so(d["gia_von"]), so(d["gia_ban"])]
                    + [pt(d["lai_pct"], 1).rstrip("%"), dau(d["lai"])]
                    for d in co_gia
                ],
            )
            + f"\nNếu bán hết ngay **{dau(lai)} đ ({pt(lai / von, 1)})** · đã chốt {dau(lai_da_chot)} đ"
        )
    phan += [f"• **{d['ma']}**: {so(d['so_luong'])} CW – không có giá trực tiếp" for d in dong if not d.get("co_gia")]
    bt = bat_thuong(dong, canh_bao)
    if bt:
        phan.append("⚠ **Bất thường**\n" + "\n".join(f"• **{m}**: {nd}" for m, _, nd in bt))
    return f"💼 **Danh mục CW {luc:%H:%M %d/%m/%Y}**\n" + "\n\n".join(phan) if phan else ""


def gui_bao_cao_ngay(luc=None, quet_loi=""):
    """Lập và gửi báo cáo ngày lên Discord (sau lần quét theo lịch)."""
    luc = luc or datetime.now()
    from web_chung import doc_ket_qua  # nhập ở đây để tránh vòng lặp import

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
    if quet_loi:  # thời điểm của file kết quả đang dùng (lần quét thành công gần nhất)
        tep = max(C.THU_MUC_KET_QUA.glob("cw_*.csv"))
        quet_loi = (quet_loi, f"{datetime.fromtimestamp(tep.stat().st_mtime):%d/%m %H:%M}")
    lai_chot = sum(v["lai_da_chot"] for v in tat_ca.values())
    noi_dung = bao_cao_ngay(dong, canh_bao, lai_chot, luc, quet_loi or None)
    if not noi_dung:
        print(f"{luc:%d/%m %H:%M} Không nắm CW nào và không có gì bất thường: không gửi báo cáo")
        return
    tin = chia_tin(noi_dung)
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
    from web_chung import doc_ket_qua  # nhập ở đây để tránh vòng lặp import (web_chung.py dùng danh_muc.py)

    df, ngay_quet = doc_ket_qua()
    df = (
        df if df is not None else pd.DataFrame(columns=["Mã CW", "Mã CS", "IV %"])
    )  # chưa quét lần nào: bỏ phần IV, đòn bẩy
    bang_gia = tai_bang_gia(list(vt), df)
    hom_nay = str(luc.date())
    if not any(ny.get("tradingDate") == hom_nay for ny, *_ in bang_gia.values()):
        return []  # ngày nghỉ lễ / Tết: bảng giá vẫn là phiên trước, không có gì mới để báo
    trang_thai = json.loads(FILE_TRANG_THAI.read_text(encoding="utf-8")) if FILE_TRANG_THAI.exists() else {}
    dong, canh_bao, kl_moi = danh_gia_danh_muc(
        vt, bang_gia, df, luc.date(), trang_thai.get("kl_niem_yet", {}), doc_lich_su(ngay_quet)
    )
    moi, dang_bao = chon_canh_bao_moi(bat_thuong(dong, canh_bao), trang_thai.get("dang_bao", []))
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
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]  # stdout luôn là TextIOWrapper
    if "--bao-cao" in sys.argv:
        gui_bao_cao_ngay(quet_loi=os.environ.get("QUET_LOI", ""))  # chay_quet_tu_dong.sh truyền lý do khi quét lỗi
    else:
        kiem_tra(luon="--luon" in sys.argv)
