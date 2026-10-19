"""
danh_muc.py - Theo dõi danh mục CW đang nắm: lưu lệnh, tính vị thế (giá vốn bình quân), lãi/lỗ nếu bán ngay,
cảnh báo (gần ngày GD cuối, cổ phiếu cơ sở gần giá thực hiện, chạm chốt lời/cắt lỗ, bất thường) và gửi Discord.

Kiểm tra:  python danh_muc.py          (launchd gọi mỗi 15 phút; ngoài giờ khớp lệnh thì thoát ngay, không gọi mạng)
           python danh_muc.py --luon   (kiểm tra bất kể giờ: dùng sau lần quét 14:00)
           python danh_muc.py --bao-cao (báo cáo tổng hợp ngày lên Discord)
Lệnh lưu trong danh_muc.csv (không đưa lên git). Webhook Discord: DISCORD_WEBHOOK_URL trong .env.
Chỉ gửi Discord khi một cảnh báo VỪA xuất hiện; cùng cảnh báo không gửi lại cho tới khi nó hết rồi xảy ra lần nữa.
"""

import csv
import json
import math
import re
import shutil
import sys
import urllib.request
from datetime import date, datetime
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
SO_MA_NOI_BAT = 5  # báo cáo ngày: số mã "Nên xem xét" đưa vào
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


def doc_form(form):
    """Form web {tên: [giá trị]} -> (lệnh, lỗi). Chốt lời / cắt lỗ nhập theo % (50 -> 0.5), để trống = mặc định."""
    lay = lambda k: (form.get(k) or [""])[0].strip()
    try:
        lenh = {
            "ngay": date.fromisoformat(lay("ngay")).isoformat(),
            "ma_cw": lay("ma_cw").upper(),
            "loai": lay("loai"),
            "so_luong": int(lay("so_luong")),
            "gia": float(lay("gia")),
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
        v = vt.setdefault(l["ma_cw"], {"so_luong": 0, "von": 0.0, "lai_da_chot": 0.0, "chot_loi": None, "cat_lo": None})
        if l["loai"] == "MUA":
            v["von"] += l["so_luong"] * l["gia"] * (1 + C.PHI_GIAO_DICH)
            v["so_luong"] += l["so_luong"]
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


def danh_gia_danh_muc(vt, bang_gia, df, hom_nay, kl_truoc):
    """Chỉ số theo giá trực tiếp + cảnh báo cho các vị thế còn nắm.
    bang_gia: kết quả lay_bang_gia (CW + cổ phiếu cơ sở); df: bảng lần quét gần nhất (sigma, r, IV cùng mã);
    kl_truoc: {mã: khối lượng niêm yết lần kiểm tra trước} để phát hiện phát hành thêm.
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
        iv, don_bay, canh_bao_iv = float("nan"), float("nan"), ""
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
            iv, don_bay = dg["IV %"], dg["Đòn bẩy"]
            canh_bao_iv = C.so_iv_cung_ma(df, ma, cs, iv)[1]
        chot_loi, cat_lo = v["chot_loi"] or CHOT_LOI_MAC_DINH, v["cat_lo"] or CAT_LO_MAC_DINH
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
    """Discord nhận tối đa 2.000 ký tự/tin: cắt theo dòng thành nhiều tin."""
    tin, cur = [], ""
    for dong in noi_dung.split("\n"):
        if cur and len(cur) + len(dong) + 1 > toi_da:
            tin.append(cur)
            cur = ""
        cur = f"{cur}\n{dong}" if cur else dong[:toi_da]
    return tin + [cur] if cur else tin


def _x(x):
    """8.52 -> '8,5x' (đòn bẩy); thiếu số liệu -> '—'."""
    return f"{x:.1f}x".replace(".", ",") if not math.isnan(x) else "—"


def _dong_cw(h):
    """1 CW trong báo cáo: giá, % so với giá hợp lý, IV − HV, hòa vốn, đòn bẩy."""
    hoa_von = h["Giá thực hiện"] + h["Giá mua"] * h["Tỷ lệ CĐ"]
    return (
        f"• **{h['Mã CW']}** ({h['Mã CS']} {so(h['Giá CS'])} đ, {h['TCPH']}, còn {h['Ngày còn lại']} ngày)\n"
        f"   Giá mua {so(h['Giá mua'])} đ · hợp lý {so(h['Giá hợp lý'])} đ ({pt(h['Đắt/rẻ %'] / 100, 1)}) · "
        f"IV − HV {pt(h['IV − HV'] / 100, 1).rstrip('%')} điểm\n"
        f"   Hòa vốn {so(hoa_von)} đ ({h['Mã CS']} cần {pt(h['CS tăng % để hòa vốn'] / 100, 1)}) · đòn bẩy {_x(h['Đòn bẩy'])}"
    )


def bao_cao_ngay(df, ngay_quet, dong, canh_bao, lai_da_chot, luc):
    """Nội dung báo cáo tổng hợp hằng ngày (dùng riêng, có số tiền)."""
    phan = [
        f"📊 **Báo cáo CW {luc:%H:%M %d/%m/%Y}** – quét {ngay_quet:%d/%m}: "
        + ", ".join(f"{k} {v}" for k, v in df["Đánh giá"].value_counts().items())
    ]
    # 1. Danh mục
    phan.append("\n💼 **Danh mục**")
    co_gia = [d for d in dong if d.get("co_gia")]
    if not dong:
        phan.append("Chưa có lệnh nào (nhập ở trang 💼 Danh mục).")
    for d in dong:
        if not d.get("co_gia"):
            phan.append(
                f"• **{d['ma']}**: {so(d['so_luong'])} CW, giá vốn {so(d['gia_von'])} đ – không có giá trực tiếp"
            )
            continue
        phan.append(
            f"• **{d['ma']}**: {so(d['so_luong'])} CW · vốn {so(d['gia_von'])} → bán được {so(d['gia_ban'])} đ: "
            f"**{pt(d['lai_pct'], 1)}** ({'+' if d['lai'] >= 0 else '−'}{so(abs(d['lai']))} đ)\n"
            f"   {d['cs']} {so(d['S'])} / giá TH {so(d['K'])} ({pt(d['cach_K'], 1)}) · "
            f"còn {d['con_ngay']} ngày tới ngày GD cuối · đòn bẩy {_x(d['don_bay'])}"
        )
    if co_gia:
        von = sum(d["so_luong"] * d["gia_von"] for d in co_gia)
        lai = sum(d["lai"] for d in co_gia)
        phan.append(
            f"Tổng: vốn {so(von)} đ · nếu bán hết ngay {'+' if lai >= 0 else '−'}{so(abs(lai))} đ ({pt(lai / von, 1)})"
            f" · đã chốt {'+' if lai_da_chot >= 0 else '−'}{so(abs(lai_da_chot))} đ"
        )
    # 2. Gần ngưỡng chốt lời / cắt lỗ
    gan = [d for d in co_gia if d["lai_pct"] >= d["chot_loi"] - GAN_NGUONG or d["lai_pct"] <= -d["cat_lo"] + GAN_NGUONG]
    if gan:
        phan.append("\n🎯 **Gần ngưỡng chốt lời / cắt lỗ**")
        for d in gan:
            loai, nguong = ("chốt lời", d["chot_loi"]) if d["lai_pct"] > 0 else ("cắt lỗ", -d["cat_lo"])
            phan.append(
                f"• **{d['ma']}** {pt(d['lai_pct'], 1)} – ngưỡng {loai} {pt(nguong)}, "
                + (
                    "ĐÃ CHẠM"
                    if abs(d["lai_pct"]) >= abs(nguong)
                    else f"còn {pt(abs(nguong) - abs(d['lai_pct']), 1, False)}"
                )
            )
    # 3. Cảnh báo
    if canh_bao:
        phan.append("\n⚠ **Cảnh báo**")
        phan += [f"• **{m}**: {nd}" for m, _, nd in canh_bao]
    # 4. CW mới phát hành, định giá tốt
    moi = df[(df["Mới"] == "MỚI") & (df["IV − HV"] <= C.MAX_IV_TRU_HV * 100)] if "Mới" in df else df.iloc[0:0]
    phan.append("\n🆕 **CW mới phát hành, định giá tốt** (IV − HV ≤ " + pt(C.MAX_IV_TRU_HV, 0) + ")")
    phan += [_dong_cw(h) for _, h in moi.iterrows()] or ["Hôm nay không có."]
    # 5. Nên xem xét + IV bất thường
    tot = df[df["Đánh giá"] == "NÊN XEM XÉT"].head(SO_MA_NOI_BAT)
    phan.append(f"\n⭐ **Top {len(tot)} Nên xem xét**")
    phan += [_dong_cw(h) for _, h in tot.iterrows()]
    if "Cảnh báo" in df and (df["Cảnh báo"].fillna("") != "").any():
        phan.append("\n❗ **IV bất thường**")
        phan += [
            f"• **{h['Mã CW']}**: {h['Cảnh báo'].split(':')[0]}"
            for _, h in df[df["Cảnh báo"].fillna("") != ""].iterrows()
        ]
    return "\n".join(phan)


def gui_bao_cao_ngay(luc=None):
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
        dong, canh_bao, _ = danh_gia_danh_muc(vt, tai_bang_gia(list(vt), df), df, luc.date(), tt.get("kl_niem_yet", {}))
    url = C.doc_env().get("DISCORD_WEBHOOK_URL", "")
    if not url:
        print(f"{luc:%d/%m %H:%M} [!] Chưa có DISCORD_WEBHOOK_URL trong .env, không gửi báo cáo")
        return
    tin = chia_tin(bao_cao_ngay(df, ngay, dong, canh_bao, sum(v["lai_da_chot"] for v in tat_ca.values()), luc))
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

    df, _ = doc_ket_qua()
    df = (
        df if df is not None else pd.DataFrame(columns=["Mã CW", "Mã CS", "IV %"])
    )  # chưa quét lần nào: bỏ phần IV, đòn bẩy
    bang_gia = tai_bang_gia(list(vt), df)
    trang_thai = json.loads(FILE_TRANG_THAI.read_text(encoding="utf-8")) if FILE_TRANG_THAI.exists() else {}
    _, canh_bao, kl_moi = danh_gia_danh_muc(vt, bang_gia, df, luc.date(), trang_thai.get("kl_niem_yet", {}))
    moi, dang_bao = chon_canh_bao_moi(canh_bao, trang_thai.get("dang_bao", []))
    if moi:
        url = C.doc_env().get("DISCORD_WEBHOOK_URL", "")
        if not url:
            print(f"{luc:%d/%m %H:%M} [!] Có {len(moi)} cảnh báo mới nhưng chưa có DISCORD_WEBHOOK_URL trong .env")
            return []  # không lưu trạng thái: có webhook rồi thì lần sau vẫn gửi
        gui_discord(noi_dung_discord(moi, luc), url)
        print(f"{luc:%d/%m %H:%M} Đã gửi {len(moi)} cảnh báo lên Discord: " + ", ".join(f"{m} {l}" for m, l, _ in moi))
    # lưu sau khi gửi thành công: gửi lỗi thì lần kiểm tra sau gửi lại
    FILE_TRANG_THAI.write_text(
        json.dumps({"dang_bao": dang_bao, "kl_niem_yet": kl_moi}, ensure_ascii=False), encoding="utf-8"
    )
    return moi


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--bao-cao" in sys.argv:
        gui_bao_cao_ngay()
    else:
        kiem_tra(luon="--luon" in sys.argv)
