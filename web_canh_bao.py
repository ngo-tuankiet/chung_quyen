"""Trang 🔔 Cảnh báo giá (/canh-bao): giá lệch bất thường ĐANG mua được (CW, ETF, HĐTL VN30F/VN100F) + các mức giá tự đặt.
tin_canh_bao: cùng các cảnh báo đó + CW giảm mạnh + cảnh báo danh mục, dạng JSON (/canh-bao/tin) để mọi trang đang mở báo
âm thanh + thông báo (JS trong web_chung). Công thức và giả định: canh_bao_gia.py. Chỉ đọc: không ghi file, không gửi Discord
(GET có thể do trang web khác gọi).
"""

import json
import math
from datetime import datetime

import pandas as pd

import canh_bao_gia as CB
import chiet_khau as CK
import cw_scanner as C
import danh_muc
import etf as E
import phai_sinh as P
import web_chung as W  # doc_ket_qua đọc qua module: test patch được
from web_chung import ESC, so, trang
from web_cw import muc_giam_manh
from web_etf import ck_dat_nguong

LOI_MUC_GIA = ""  # lỗi của lần thêm/xóa mức gần nhất (web.py gán), hiện trên trang
CHO_BANG_GIA = 10  # giây chờ bảng giá Vietcap: máy chủ web 1 luồng, chờ lâu thì mọi trang khác phải chờ theo
CHI_SO_HD = ("VN30", "VN100")


def o(v, le=0, dau=False, hau_to="", mau=False):
    """1 ô số (data-v để sắp xếp). mau: tô xanh/đỏ theo dấu."""
    if v is None or not math.isfinite(v):
        return '<td class="so" data-v="-1e18">—</td>'
    lop = (" duong" if v > 0 else " am" if v < 0 else "") if mau else ""
    return f'<td class="so{lop}" data-v="{v}">{so(v, le, dau)}{hau_to}</td>'


def o_dat_re(v):
    """Ô Đắt/rẻ (W.dat_re: chữ Rẻ/Đắt kèm màu), data-v để sắp xếp."""
    chu, lop = W.dat_re(v * 100)
    return f'<td class="so {lop}" data-v="{v if math.isfinite(v) else -1e18}">{chu}</td>'


def bang(tieu_de, hang):
    """Bảng sắp xếp được: tieu_de = [(chữ, là cột số, giải thích)], hang = [chuỗi <tr>...</tr>]."""
    dau = "".join(
        f'<th class="{"so" if la_so else ""}"><button type="button" title="{ESC(gt)} (Bấm để sắp xếp.)">{ESC(td)}</button></th>'
        for td, la_so, gt in tieu_de
    )
    return f'<div class="cuon"><table><thead><tr>{dau}</tr></thead><tbody>{"".join(hang)}</tbody></table></div>'


def lay_du_lieu():
    """Tải mọi nguồn cho trang; nguồn nào lỗi thì ghi lỗi và để trống phần đó (các phần khác vẫn hiện)."""
    loi, kq = [], {}
    kq["df"], kq["ngay_quet"] = W.doc_ket_qua()
    try:
        kq["muc"] = CB.doc_muc_gia()
    except ValueError as e:  # file sửa tay sai tiêu đề: báo, không ghi đè
        kq["muc"] = []
        loi.append(f"muc_gia.csv: {e}")
    try:
        hd = CB.ma_hdtl()
    except Exception as e:  # noqa: BLE001  # lỗi mạng / hết lượt vnstock: chỉ thiếu phần HĐTL
        hd = []
        loi.append(f"danh sách HĐTL (vnstock): {type(e).__name__}")
    ma = set(hd) | {m["ma"] for m in kq["muc"] if not CB.MAU_MA_HD_BI_DANH.fullmatch(m["ma"])}
    if kq["df"] is not None:
        ma |= set(kq["df"]["Mã CW"]) | set(kq["df"]["Mã CS"])
    try:
        kq["bang_gia"] = C.lay_bang_gia(sorted(ma), cho=CHO_BANG_GIA) if ma else {}
    except Exception as e:  # noqa: BLE001
        kq["bang_gia"] = {}
        loi.append(f"bảng giá Vietcap: {type(e).__name__} {str(e)[:80]}")
    try:
        kq["ssi"] = CK.lay_ssi()
    except Exception as e:  # noqa: BLE001
        kq["ssi"] = {}
        loi.append(f"iNAV SSI: {type(e).__name__} {str(e)[:80]}")
    kq["chi_so"] = {}
    for cs in CHI_SO_HD:
        try:
            kq["chi_so"][cs] = CB.gia_chi_so(cs)
        except Exception as e:  # noqa: BLE001
            loi.append(f"chỉ số {cs} (vnstock): {type(e).__name__}")
    bao_cao, _ = E.doc_ket_qua()
    kq["thuong"] = {h["Mã"]: h["CL NAV trung vị 1N %"] for _, h in bao_cao.iterrows()} if bao_cao is not None else {}
    kq["hd"] = {m: kq["bang_gia"][m] for m in hd if m in kq["bang_gia"]}
    return kq, loi


def muc_cw(ds, df):
    nguong = so(CB.NGUONG_LECH_CW * 100, 0)
    if df is None:
        than = "<p>Chưa có kết quả quét CW (bấm 🔄 Quét ở trang này hoặc trang Chứng quyền).</p>"
    elif not ds:
        than = (
            f"<p>Hiện không có CW nào có giá chào bán thấp hơn mức lẽ ra theo CS từ {nguong}% trở lên mà mua được "
            f"≥ {so(CB.MIN_GIA_TRI_MUA / 1e6)} triệu, và thuộc {CB.SO_TOP_CW_RE} dòng đầu danh sách Chứng quyền hoặc giá chào "
            f"bán không đắt hơn giá hợp lý theo biến động 1 năm của CS quá {so(CB.MAX_DAT_RE_CW_RE * 100)}% (cột Đắt/rẻ HV).</p>"
        )
    else:
        hang = [
            f'<tr data-href="/cw/{ESC(x["ma"])}"><td><a href="/cw/{ESC(x["ma"])}">{ESC(x["ma"])}</a>'
            + (f" <small>top {CB.SO_TOP_CW_RE}</small>" if x.get("top") else "")
            + f'</td><td>{ESC(x["cs"])}</td>'
            + o(x["gia"])
            + o(x["le_ra"])
            + o(x["lech"] * 100, 1, True, "%", True)
            + o(x["iv"], 0, False, "%")
            + o(x["iv_tv"], 0, False, "%")
            + o_dat_re(x["re_cung_ma"])
            + o_dat_re(x["dat_re"])
            + o(x["lech_20"] * 100, 1, True, "%", True)
            + o(x["mua_duoc"] / 1e6, 1)
            + o(x["cho_mua"])
            + o(x["spread"] * 100, 1, False, "%")
            + o(x["cs_pt"] * 100, 1, True, "%", True)
            + o(x["con_ngay"])
            + f"<td>{ESC(str(x['tcph']))}</td></tr>"
            for x in ds
        ]
        than = bang(
            [
                ("Mã CW", False, "Bấm để mở trang chi tiết"),
                ("Mã CS", False, "Cổ phiếu cơ sở"),
                ("Giá chào bán", True, "Giá thấp nhất đang bán ra: giá bạn mua được ngay (đ)"),
                (
                    "Lẽ ra",
                    True,
                    "Giá CW lẽ ra có theo giá CS bây giờ, nếu tổ chức phát hành giữ mức IV đã yết lúc quét gần nhất",
                ),
                ("Lệch", True, "Giá chào bán / giá lẽ ra − 1: âm sâu = đang rẻ bất thường so với chính giá TCPH yết"),
                ("IV", True, "IV ở giá chào bán bây giờ (—: giá dưới mức tối thiểu của mô hình)"),
                (
                    "TV cùng mã",
                    True,
                    ("Trung vị IV các CW khác cùng CS lúc quét (chỉ để so, không còn là điều kiện báo từ 04/11/2026)"),
                ),
                (
                    "So cùng mã",
                    True,
                    (
                        "Giá chào bán so với giá Black-Scholes nếu CW được yết ở IV trung vị các CW cùng CS (cột TV cùng mã): "
                        "rẻ/đắt hơn cách thị trường đang định giá các CW khác cùng cổ phiếu"
                    ),
                ),
                (
                    "Đắt/rẻ HV",
                    True,
                    (
                        "Giá chào bán so với giá hợp lý theo biến động 1 năm của CS (cùng cách tính cột Đắt/rẻ ở danh sách). "
                        f"Chỉ báo khi Rẻ hoặc Đắt tối đa {so(CB.MAX_DAT_RE_CW_RE * 100)}%, trừ CW ghi 'top {CB.SO_TOP_CW_RE}' "
                        f"(thuộc {CB.SO_TOP_CW_RE} dòng đầu danh sách Chứng quyền): rẻ so với chính nó mà vẫn đắt theo HV thì "
                        "không phải món hời"
                    ),
                ),
                (
                    "Lệch 20p",
                    True,
                    (
                        "Lệch 20 phiên ở giá chào bán bây giờ (cùng cách tính với cảnh báo CW giảm mạnh): âm = 20 phiên qua CW "
                        "không theo kịp CS, dương = CW đã chạy nhanh hơn CS"
                    ),
                ),
                ("Mua được (tr)", True, f"Giá trị đang chào bán ở các mức rẻ hơn giá lẽ ra từ {nguong}% (triệu đồng)"),
                ("Chờ mua", True, "Giá cao nhất đang có người mua: giá bán ra được ngay (đ)"),
                ("Spread", True, "(chào bán − chờ mua) / giá giữa"),
                ("CS từ lúc quét", True, "Giá CS bây giờ so với lúc quét"),
                ("Còn (ngày)", True, "Số ngày lịch tới ngày giao dịch cuối"),
                ("TCPH", False, "Tổ chức phát hành: ACBS, Vietcap hay hạ IV khi CS tăng"),
            ],
            hang,
        )
    return (
        f'<section class="the"><h2>CW đang rẻ bất thường ({len(ds)})</h2>'
        f'<p class="phu">Giá chào bán thấp hơn giá "lẽ ra" theo cổ phiếu cơ sở từ {nguong}% trở lên, và có ≥ '
        f"{so(CB.MIN_GIA_TRI_MUA / 1e6)} triệu đang bán ở các mức rẻ đó (không tính lô lẻ). Giá lẽ ra = Black-Scholes với IV "
        "của chính giá chào bán lúc quét gần nhất (giá tổ chức phát hành tự yết) và giá CS bây giờ. Bỏ CW còn dưới "
        f"{C.MIN_NGAY_GD_CUOI_LUOT} ngày tới ngày GD cuối. Rủi ro: không phòng hộ được (chưa bán khống cổ phiếu được); mua hôm "
        "nay sớm nhất chiều T+2 mới bán; có thể là tổ chức phát hành chủ động hạ IV chứ không phải bán nhầm.</p>"
        f"{than}</section>"
    )


def muc_etf(ds, ssi):
    lai = so(CK.NGUONG_LAI_RONG * 100, 0)
    if not ssi:
        than = "<p>Chưa lấy được iNAV từ SSI.</p>"
    elif not ds:
        than = (
            f"<p>Hiện không có quỹ nào mua được ≥ {so(CK.MIN_GIA_TRI_CHAO_BAN / 1e6)} triệu ở giá đủ lãi ròng ≥ {lai}% "
            "nếu giá về iNAV.</p>"
        )
    else:
        hang = []
        for x in ds:
            if x["hd"] and math.isfinite(x["so_hd"]):
                phong_ho = (
                    f'bán {so(x["so_hd"], 2)} HĐ {ESC(x["hd"])} cho lệnh {so(CB.GIA_TRI_LENH_ETF / 1e6)} triệu '
                    f'(1 HĐ ứng ≈ {so(x["etf_1_hd"] / 1e6, 1)} triệu ETF)'
                )
            elif x["hd"]:
                phong_ho = f'{ESC(x["hd"])} chưa có giá chờ mua'
            else:
                phong_ho = "không có HĐTL cùng chỉ số"
            hang.append(
                f'<tr data-href="/etf/{ESC(x["ma"])}"><td><a href="/etf/{ESC(x["ma"])}">{ESC(x["ma"])}</a></td>'
                f'<td>{ESC(x["chi_so"])}</td>'
                + o(x["inav"])
                + o(x["gia"])
                + o(x["ck"], 2, True, "%", True)
                + o(x["lai_rong"], 2, True, "%", True)
                + o(x["mua_duoc"] / 1e6, 1)
                + o(x["thuong"], 2, True, "%")
                + f"<td>{phong_ho}</td></tr>"
            )
        than = bang(
            [
                ("Quỹ", False, "Bấm để mở trang chi tiết"),
                ("Chỉ số", False, "Chỉ số quỹ mô phỏng"),
                ("iNAV", True, "Giá trị tài sản ròng ước tính trong phiên (SSI, đ/CCQ)"),
                ("Chào bán", True, "Giá thấp nhất đang bán ra (đ)"),
                ("CK", True, "Giá chào bán / iNAV − 1"),
                ("Lãi ròng nếu về iNAV", True, "Sau phí mua, phí bán, thuế bán"),
                ("Mua được (tr)", True, f"Giá trị đang chào bán ở các mức đủ lãi ròng ≥ {lai}% (triệu đồng)"),
                ("Thường lệch", True, "Trung vị giá/NAV − 1 của 1 năm: mức chênh thường ngày của quỹ"),
                ("Phòng hộ", False, "Bán HĐTL cùng chỉ số để lãi/lỗ không phụ thuộc thị trường lên xuống (Hull ch. 3)"),
            ],
            hang,
        )
    return (
        f'<section class="the"><h2>ETF mua được dưới iNAV ({len(ds)})</h2>'
        f'<p class="phu">Đúng ngưỡng 🟢 của trang ETF: có ≥ {so(CK.MIN_GIA_TRI_CHAO_BAN / 1e6)} triệu đang chào bán ở giá đủ '
        f"lãi ròng ≥ {lai}% nếu giá về iNAV (chiết khấu ≤ −{so(-ck_dat_nguong(), 2)}%), bỏ quỹ lúc nào cũng rẻ hơn NAV "
        f"từ {so(CK.NGUONG_GIAM_SO_INAV * 100, 0)}% (không bất thường). Phòng hộ: quỹ VN30 / VN100 bán HĐTL tháng gần cùng "
        "chỉ số, số HĐ = giá trị ETF / (giá HĐTL × 100.000); HĐ chỉ giao dịch số nguyên nên lệnh nhỏ không phòng hộ trọn được. "
        "Kiểm chứng 2 năm: phần lời nhờ chiết khấu thu hẹp chỉ −0,2…+0,7% sau phí (KE_HOACH Phần 8).</p>"
        f"{than}</section>"
    )


def muc_hdtl(ds):
    if not ds:
        return '<section class="the"><h2>Hợp đồng tương lai</h2><p>Chưa lấy được giá HĐTL (xem lỗi ở đầu trang).</p></section>'
    ten = {"dat": "🔔 Đắt: bán HĐ + mua ETF", "re": "Rẻ: chỉ khi đang giữ ETF"}
    hang = [
        f'<tr><td>{ESC(x["bi_danh"] or x["ma"])}<br><span class="phu">{ESC(x["ma"])}</span></td><td>{ESC(x["chi_so"])}</td>'
        + o(x["gia"], 1)
        + o(x["mua"], 1)
        + o(x["ban"], 1)
        + o(x["S"], 2)
        + o(x["basis"], 2, True, "", True)
        + o(x["hop_ly"], 2)
        + o(x["lech"], 2, True, "", True)
        + o(x["chi_phi"], 2)
        + o(x["lai_khoa"], 2, True, "", True)
        + o(x["kl"])
        + o(x["oi"])
        + f'<td>{x["gd_cuoi"]:%d/%m/%Y}</td><td>{ten.get(x["tin_hieu"], "—")}'
        + (f' ({ESC(x["etf"])})' if x["tin_hieu"] and x["etf"] else "")
        + "</td></tr>"
        for x in ds
    ]
    lech_ngay = [x["bi_danh"] or x["ma"] for x in ds if not x["cung_ngay"]]  # khác ngày hoặc ngoài giờ khớp lệnh
    ky_quy = P.ky_quy_ban_dau(ds[0]["gia"], ds[0]["chi_so"]) if math.isfinite(ds[0]["gia"]) else math.nan
    return (
        f'<section class="the"><h2>Hợp đồng tương lai VN30F / VN100F ({sum(1 for x in ds if x["tin_hieu"])} tín hiệu)</h2>'
        '<p class="phu">Giá hợp lý = chỉ số × e^(r·T) với r = '
        f"{so(C.LAI_SUAT_PHI_RUI_RO * 100, 1)}%/năm, T = số ngày tới ngày GD cuối / 365, chưa trừ cổ tức (Hull ch. 5): đây là "
        "mức cao nhất HĐTL đáng có. <b>Đắt</b> = giá chờ mua của HĐTL cao hơn giá hợp lý cộng chi phí cả 2 chân: bán HĐTL + "
        "mua đủ 1 HĐ (≈ chỉ số × 100.000 đ) ETF cùng chỉ số tốn ít nhất (cột ETF; bỏ quỹ lúc nào cũng rẻ hơn NAV) rồi giữ đến "
        "đáo hạn thì khóa được phần chênh, không phụ thuộc thị trường lên xuống (Lãi khóa, điểm/HĐ, đã trừ phí + thuế 2 chân; "
        "ETF đang rẻ hơn iNAV coi như vẫn rẻ lúc bán, cao hơn iNAV coi như mất phần cao hơn; cổ tức ETF nhận thêm và lãi bỏ lỡ "
        f"của tiền ký quỹ chưa tính). Không báo khi còn dưới {CB.SO_PHIEN_TOI_THIEU_KHOA} phiên tới ngày GD cuối (ETF mua hôm "
        "nay sớm nhất chiều T+2 mới bán). "
        "<b>Rẻ</b> = giá chào bán HĐTL thấp hơn tiền bán ETF cùng chỉ số đem lại sau chi phí: chỉ có lợi nếu bạn ĐANG GIỮ ETF "
        "đó (bán ETF, mua HĐTL; chưa trừ cổ tức bỏ lỡ). Chi phí HĐTL theo trang Phái sinh (phí công ty, Sở, bù trừ VSDC, thuế 2 lần). "
        f"1 HĐ {ESC(ds[0]['bi_danh'] or ds[0]['ma'])} cần ≈ {so(ky_quy / 1e6, 1)} triệu ký quỹ ban đầu; lỗ có thể vượt ký quỹ. VN100F và kỳ hạn xa rất ít giao dịch: "
        "giá khớp có thể cũ, chênh lệch mua–bán rộng.</p>"
        + (
            f'<p class="loi">Ngoài giờ khớp lệnh hoặc chỉ số và HĐTL khác ngày ({ESC(", ".join(lech_ngay))}): không cho '
            "tín hiệu (sổ lệnh còn lại và iNAV không cùng thời điểm).</p>"
            if lech_ngay
            else ""
        )
        + bang(
            [
                ("Mã", False, "Bí danh (tháng gần, tháng sau, 2 quý) và mã KRX"),
                ("Chỉ số", False, "Chỉ số cơ sở"),
                ("Khớp", True, "Giá khớp gần nhất (điểm)"),
                ("Chờ mua", True, "Giá cao nhất đang có người mua: bán HĐ được ngay ở giá này"),
                ("Chào bán", True, "Giá thấp nhất đang bán: mua HĐ được ngay ở giá này"),
                ("Chỉ số", True, "Giá chỉ số (nến ngày VCI)"),
                ("Basis", True, "Khớp − chỉ số (điểm)"),
                ("Hợp lý", True, "Chỉ số × e^(rT), chưa trừ cổ tức"),
                ("Lệch", True, "Khớp − giá hợp lý (điểm)"),
                ("Chi phí", True, "Chi phí 1 HĐ giữ đến đáo hạn, quy ra điểm"),
                (
                    "Lãi khóa",
                    True,
                    "Bán HĐ ở giá chờ mua + mua ETF cùng chỉ số: điểm/HĐ sau chi phí; dương = khóa được lãi",
                ),
                ("KL", True, "Khối lượng khớp trong phiên (HĐ)"),
                ("OI", True, "Số HĐ đang mở"),
                ("GD cuối", False, "Ngày giao dịch cuối (thứ Năm thứ ba của tháng đáo hạn)"),
                ("Tín hiệu", False, "Đắt / rẻ bất thường so với giá hợp lý sau chi phí"),
            ],
            hang,
        )
        + "</section>"
    )


def muc_muc_gia(ds, da_cham, tom_tat=""):
    """Cụm đầu trang (người dùng muốn gọn 1 khung, 02/11/2026): dòng đếm tín hiệu `tom_tat` + mức giá tự đặt + form thêm 1 hàng."""
    hang = []
    for m in ds:
        don_vi = "điểm" if CB.he_so_cua(m["ma"]) > 1 else "đ"
        cham = da_cham.get(str(m["id"]))
        trang_thai = (
            f'<b class="am">🔔 đã chạm lúc {ESC(cham["luc"])}</b>'
            if cham
            else ('<b class="am">🔔 đang chạm</b>' if m["cham"] else ("chưa có giá" if m["gia"] is None else "chưa"))
        )
        hang.append(
            f"<tr><td>{ESC(m['ma'])}</td><td>{CB.CHIEU[m['chieu']]} {so(m['muc'], 1 if don_vi == 'điểm' else 0)} {don_vi}</td>"
            + o(m["gia"], 1 if don_vi == "điểm" else 0)
            + o(m["cach"] * 100 if m["gia"] else math.nan, 1, True, "%")
            + f"<td>{trang_thai}</td><td>{ESC(m['ghi_chu'])}</td>"
            f'<td><form method="post" action="/canh-bao/xoa" onsubmit="return confirm(\'Xóa mức số {m["id"]}?\')">'
            f'<input type="hidden" name="id" value="{m["id"]}"><button class="nut-nho">Xóa</button></form></td></tr>'
        )
    bang_muc = (
        bang(
            [
                ("Mã", False, ""),
                ("Mức", False, "≤: báo khi giá xuống tới mức; ≥: báo khi giá lên tới mức"),
                (
                    "Giá bây giờ",
                    True,
                    f"Giá khớp; lệnh khớp cuối dưới {so(CB.MIN_GIA_TRI_MUA / 1e6)} triệu thì dùng giá chào bán (≤) / chờ mua (≥)",
                ),
                ("Cách mức", True, "Giá bây giờ / mức − 1"),
                ("Trạng thái", False, "Lịch 5 phút trong giờ giao dịch ghi lại lần chạm đầu tiên trong ngày"),
                ("Ghi chú", False, ""),
                ("", False, ""),
            ],
            hang,
        )
        if ds
        else ""  # tiêu đề đã ghi (0)
    )
    discord = "gửi cả Discord" if CB.GUI_DISCORD_MUC_GIA else "chưa gửi Discord (chờ bạn cho phép)"
    return (
        '<section class="the cum-dau">'
        + tom_tat
        + '<div class="hang-muc">'
        + f"<h2>🔔 Mức giá tôi đặt ({len(ds)})</h2>"
        + '<form method="post" action="/canh-bao/them" class="form-lenh form-ngang">'
        '<label>Mã<input name="ma" required size="10" maxlength="12" placeholder="CVPB2615, VPB, E1VFVN30, VN30F1M"></label>'
        '<label>Khi giá<select name="chieu"><option value="duoi">xuống tới ≤</option><option value="tren">lên tới ≥</option></select></label>'
        '<label>Mức giá<input name="muc" inputmode="decimal" required size="10" placeholder="0,87 / 24,5 / 1858,5"></label>'
        '<label>Ghi chú<input name="ghi_chu" maxlength="100" size="16"></label>'
        '<button class="nut">Thêm mức</button></form></div>'
        + (f'<p class="loi" role="alert">{ESC(LOI_MUC_GIA)}</p>' if LOI_MUC_GIA else "")
        + bang_muc
        + f'<p class="phu">CW, cổ phiếu, ETF nhập như ở Danh mục (dưới 100 là nghìn đồng: 0,87 = 870 đ, 24,5 = 24.500 đ); HĐTL '
        f"nhập điểm. Bí danh HĐTL (VN30F1M...) tự chuyển sang hợp đồng mới khi đáo hạn. Lịch 5 phút trong giờ giao dịch ghi "
        f"lại mức đã chạm; {discord}.</p></section>"
    )


def tinh_canh_bao(luc):
    """Tải dữ liệu (lay_du_lieu) và tính các cảnh báo của trang lúc `luc`; dùng chung cho trang và tin_canh_bao."""
    hom_nay = luc.date()
    du_lieu, loi = lay_du_lieu()
    bg, ssi, df = du_lieu["bang_gia"], du_lieu["ssi"], du_lieu["df"]
    cw = (
        CB.cw_lech_re(df, bg, du_lieu["ngay_quet"], hom_nay, danh_muc.doc_lich_su(du_lieu["ngay_quet"]))
        if bg and df is not None
        else []
    )
    phien = sorted({ny.get("tradingDate") for ny, *_ in bg.values() if ny.get("tradingDate")})
    dong_cua = not phien or phien[-1] != str(hom_nay) or not danh_muc.trong_gio_khop_lenh(luc)
    hd = CB.hdtl_lech(
        du_lieu["hd"], du_lieu["chi_so"], ssi, hom_nay, trong_phien=not dong_cua, thuong_lech=du_lieu["thuong"]
    )
    thang_gan = {x["chi_so"]: (x["bi_danh"] or x["ma"], x["mua"]) for x in hd if x["bi_danh"].endswith("F1M")}
    etf = CB.etf_duoi_inav(ssi, du_lieu["thuong"], thang_gan) if ssi else []
    muc = CB.trang_thai_muc(du_lieu["muc"], bg)  # bảng giá lỗi: mọi mức "chưa có giá"
    return du_lieu, loi, cw, phien, dong_cua, hd, etf, muc


def canh_bao_danh_muc(df, ngay_quet, hom_nay):
    """Cảnh báo các CW đang nắm, đúng loại danh_muc.kiem_tra gửi Discord (bat_thuong): [(mã, loại, nội dung)]."""
    D = danh_muc
    vt = {m: v for m, v in D.tinh_vi_the(D.doc_lenh()).items() if v["so_luong"] > 0}
    if not vt:
        return []
    df = df if df is not None else pd.DataFrame(columns=["Mã CW", "Mã CS", "IV %"])  # chưa quét: bỏ phần IV
    tt = json.loads(D.FILE_TRANG_THAI.read_text(encoding="utf-8")) if D.FILE_TRANG_THAI.exists() else {}
    dong, canh_bao, _ = D.danh_gia_danh_muc(
        vt,
        D.tai_bang_gia(list(vt), df, cho=CHO_BANG_GIA),
        df,
        hom_nay,
        tt.get("kl_niem_yet", {}),
        D.doc_lich_su(ngay_quet),
    )
    return D.bat_thuong(dong, canh_bao)


def tin_canh_bao(luc=None):
    """Cảnh báo đang có, cho trình duyệt báo âm thanh + thông báo (JSON /canh-bao/tin): {ngoai_gio, tin, loi}. Mỗi tin: id
    'ngày|loại|mã' (trình duyệt nhớ đã báo: mỗi tin 1 lần/ngày), tieu_de, noi_dung, link. Ngoài giờ khớp lệnh: không tải gì;
    ngày nghỉ (bảng giá vẫn là phiên trước): không báo."""
    luc = luc or datetime.now()
    if not danh_muc.trong_gio_khop_lenh(luc):
        return {"ngoai_gio": True, "tin": [], "loi": []}
    du_lieu, loi, cw, _, dong_cua, hd, etf, muc = tinh_canh_bao(luc)
    if dong_cua:
        return {"ngoai_gio": True, "tin": [], "loi": loi}
    tin, ngay, df = [], str(luc.date()), du_lieu["df"]

    def them(loai, ma, tieu_de, noi_dung, link):
        tin.append({"id": f"{ngay}|{loai}|{ma}", "tieu_de": tieu_de, "noi_dung": noi_dung, "link": link})

    for x in cw:
        them(
            "cw",
            x["ma"],
            f"CW rẻ bất thường: {x['ma']}",
            f"chào bán {so(x['gia'])} đ, lệch {so(x['lech'] * 100, 1, True)}% so với giá lẽ ra theo {x['cs']}; "
            f"mua được {so(x['mua_duoc'] / 1e6, 1)} triệu",
            f"/cw/{x['ma']}",
        )
    for x in etf:
        them(
            "etf",
            x["ma"],
            f"ETF dưới iNAV: {x['ma']}",
            f"chào bán {so(x['gia'])} đ, iNAV {so(x['inav'])} đ, lãi ròng nếu về iNAV {so(x['lai_rong'], 2, True)}%",
            f"/etf/{x['ma']}",
        )
    for x in hd:
        if x["tin_hieu"]:
            ma = x["bi_danh"] or x["ma"]
            them(
                f"hd-{x['tin_hieu']}",
                ma,
                f"HĐTL {'đắt' if x['tin_hieu'] == 'dat' else 'rẻ'}: {ma}",
                f"giá {so(x['gia'], 1)}, hợp lý {so(x['hop_ly'], 1)}, lệch {so(x['lech'], 1, True)} điểm"
                + (f", lãi khóa {so(x['lai_khoa'], 1, True)} điểm" if math.isfinite(x["lai_khoa"]) else ""),
                f"/phai-sinh/{ma}" if P.MAU_MA_HD.fullmatch(ma) else "/canh-bao",
            )
    for m in muc:
        if m["cham"]:
            le = 1 if CB.he_so_cua(m["ma"]) > 1 else 0
            them(
                "muc",
                m["id"],
                f"Chạm mức giá: {m['ma']}",
                f"giá {so(m['gia'], le)} {CB.CHIEU[m['chieu']]} mức {so(m['muc'], le)}"
                + (f" ({m['ghi_chu']})" if m["ghi_chu"] else ""),
                "/canh-bao",
            )
    for g in danh_muc.cw_giam_manh(df, du_lieu["bang_gia"], luc.date(), danh_muc.doc_lich_su(du_lieu["ngay_quet"])):
        them("giam", g["ma"], f"CW giảm mạnh: {g['ma']}", danh_muc.noi_dung_giam_manh(g), f"/cw/{g['ma']}")
    try:
        for ma, loai, noi_dung in canh_bao_danh_muc(df, du_lieu["ngay_quet"], luc.date()):
            them(f"dm-{loai}", ma, f"Danh mục: {ma}", noi_dung, "/danh-muc")
    # danh_muc.csv sửa tay sai, mất mạng: các tin khác vẫn báo
    except Exception as e:  # noqa: BLE001
        loi.append(f"danh mục: {type(e).__name__} {str(e)[:80]}")
    return {"ngoai_gio": False, "tin": tin, "loi": loi}


def gia_nay(ds, bg, df, hom_nay):
    """Mã CW -> (giá mua nay, đắt/rẻ nay) tính đúng như trang chi tiết (C.dinh_gia, HV và r của lần quét) để 2 nơi cùng số.
    Thiếu bảng giá hay dòng quét của mã thì bỏ mã đó (ô hiện —)."""
    kq = {}
    for ma in ds:
        h = df[df["Mã CW"] == ma] if df is not None else ()
        if ma not in bg or not len(h) or h.iloc[0]["Mã CS"] not in bg:
            continue
        h = h.iloc[0]
        r = float(h["r %"]) / 100 if "r %" in h else C.LAI_SUAT_PHI_RUI_RO
        g = C.dinh_gia(*bg[ma], C.gia_hien_tai(*bg[h["Mã CS"]]), float(h["Biến động %/năm"]) / 100, hom_nay, r)
        kq[ma] = (g["Giá mua"], g["Đắt/rẻ %"] / 100)
    return kq


def trang_canh_bao():
    luc = datetime.now()
    hom_nay = luc.date()
    du_lieu, loi, cw, phien, dong_cua, hd, etf, muc = tinh_canh_bao(luc)
    ssi, df = du_lieu["ssi"], du_lieu["df"]
    da_cham = CB.doc_da_cham(str(hom_nay))
    giam_manh = danh_muc.doc_giam_manh(hom_nay)
    phan = [
        (
            '<h1>🔔 Cảnh báo giá</h1><p class="phu">Giá lệch bất thường <b>đang mua được ngay</b> lúc mở trang (so giá trong '
            "sổ lệnh, không so giá khớp: nến giật do khớp lẻ không mua lại được) và các mức giá bạn tự đặt. Tải lại trang để "
            "lấy số mới. Đây là sàng lọc, chưa tín hiệu nào được kiểm chứng là có lãi sau phí: hướng đi của thị trường vẫn là "
            "phần bạn tự nhận định.</p>"
        )
    ]
    if dong_cua:
        phan.append(
            f'<p class="loi">Ngoài giờ khớp lệnh: số liệu là sổ lệnh còn lại của phiên {ESC(phien[-1] if phien else "?")}, '
            "chỉ để xem, không phải cơ hội.</p>"
        )
    phan += [f'<p class="loi" role="alert">Không tải được {ESC(x)}</p>' for x in loi]
    dem = [
        ("CW rẻ bất thường", len(cw), ""),
        ("ETF dưới iNAV", len(etf), ""),
        ("HĐTL đắt/rẻ", sum(1 for x in hd if x["tin_hieu"]), ""),
        ("Mức giá đã chạm", sum(str(m["id"]) in da_cham for m in muc), f" / {so(len(muc))} mức"),
    ]
    tom_tat = (
        '<div class="dem-nhanh">'
        + "".join(f'<span>{nhan} <b{" class=am" if n else ""}>{so(n)}</b>{them}</span>' for nhan, n, them in dem)
        + "</div>"
    )
    phan += [
        # giảm mạnh trải ngang (không ghép cạnh Mức giá): bảng 10 cột không vừa nửa trang (02/11/2026)
        muc_muc_gia(muc, da_cham, tom_tat),
        muc_giam_manh(giam_manh, gia_nay(giam_manh, du_lieu["bang_gia"], df, hom_nay)),
        muc_cw(cw, df),
        muc_etf(etf, ssi),
        muc_hdtl(hd),
    ]
    return trang("Cảnh báo giá", "".join(phan), "/canh-bao")
