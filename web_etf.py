"""Trang ETF (/etf) và chi tiết từng quỹ (/etf/<mã>)."""

import math
from datetime import datetime

import pandas as pd

import chiet_khau
import cw_scanner
import etf
import web_chung as W
from web_chung import ESC, bieu_do, hang_doi, o_so, so, trang

# ============ ETF ============
GIAI_THICH_SO_CS = (
    "Chỉ số giá chưa gồm cổ tức nên quỹ thường cao hơn một chút; thấp hơn nhiều: xem NAV so với chỉ số để biết do quỹ "
    "bám kém hay do giá rời NAV"
)
# (cột trong file kết quả, tiêu đề, số lẻ (None = chữ), có dấu +/−, hậu tố, giải thích khi rê chuột)
COT_CHI_SO = [
    ("Giá", "Điểm", 2, False, "", "Điểm chỉ số phiên cuối"),
    ("1T %", "1T", 1, True, "%", "Lợi nhuận 1 tháng lịch (theo giá, chưa gồm cổ tức)"),
    ("3T %", "3T", 1, True, "%", "Lợi nhuận 3 tháng lịch"),
    ("6T %", "6T", 1, True, "%", "Lợi nhuận 6 tháng lịch"),
    ("1N %", "1N", 1, True, "%", "Lợi nhuận 1 năm"),
    (
        "Xu hướng",
        "Xu hướng",
        None,
        False,
        "",
        "Tăng: giá và MA50 cùng trên MA200 · Giảm: cùng dưới · còn lại: Đi ngang",
    ),
    ("RSI14", "RSI14", 0, False, "", "RSI 14 phiên (Wilder): trên 70 là tăng nóng, dưới 30 là bị bán quá mức"),
    ("Biến động năm %", "Biến động", 1, False, "%", "Độ lệch chuẩn lợi suất ngày × √250 (như HV của CW)"),
    ("Giảm sâu nhất 1N %", "Sâu nhất 1N", 1, True, "%", "Mức giảm lớn nhất từ đỉnh trong 1 năm"),
    ("Cách đỉnh 1N %", "Cách đỉnh", 1, True, "%", "Giá hiện tại so với đỉnh 1 năm"),
]
COT_ETF = (
    [("Chỉ số", "Chỉ số", None, False, "", "Chỉ số mà quỹ mô phỏng"), ("Giá", "Giá (đ)", 0, False, "", "Giá khớp cuối")]
    + COT_CHI_SO[1:5]
    + [
        (
            "so CS",
            "so CS 1N",
            1,
            True,
            "",
            "Lợi nhuận 1 năm của quỹ − của chỉ số (điểm %). " + GIAI_THICH_SO_CS,
        )
    ]
    + COT_CHI_SO[5:]
    + [
        (
            "GTGD TB20 (tỷ)",
            "GTGD TB20",
            2,
            False,
            "",
            "Giá trị giao dịch TB 20 phiên, tỷ đồng (phiên không khớp tính 0)",
        ),
        ("Khối ngoại ròng (tỷ)", "Khối ngoại", 2, True, "", "Nhà đầu tư nước ngoài mua − bán trong phiên, tỷ đồng"),
        ("CCQ lưu hành", "CCQ lưu hành", 0, False, "", "Số chứng chỉ quỹ lưu hành: tăng = có tiền góp thêm vào quỹ"),
        (
            "Phiên khớp 1N",
            "Phiên khớp",
            0,
            False,
            "",
            f"Số phiên có khớp lệnh trong 1 năm (dưới {etf.MIN_PHIEN_KHOP}: chỉ số kỹ thuật kém tin cậy)",
        ),
        ("Phí quản lý %", "Phí QL", 2, False, "%", "Phí quản lý %/năm (điền trong etf.py, PHI_QUAN_LY)"),
    ]
)


COT_CK = [
    (
        "Đạt",
        "Đạt ngưỡng",
        None,
        False,
        "",
        "🟢: lãi ròng nếu về NAV ≥ ngưỡng và mua được ≥ mức tối thiểu (chiet_khau.py)",
    ),
    ("Chỉ số", "Chỉ số", None, False, "", "Chỉ số mà quỹ mô phỏng"),
    (
        "Giá chào bán",
        "Chào bán (đ)",
        0,
        False,
        "",
        "Giá chào bán tốt nhất: giá mua được ngay (sau 14:45 là sổ lệnh còn lại)",
    ),
    ("KL chào bán", "KL chào bán", 0, False, "", "Số CCQ ở giá chào bán tốt nhất"),
    ("iNAV", "iNAV (đ)", 0, False, "", "NAV ước tính trong phiên (SSI iBoard); sau 14:45 là iNAV cuối phiên"),
    ("Chiết khấu mua được %", "CK", 1, True, "%", "Giá chào bán / iNAV − 1: âm = mua được dưới NAV"),
    (
        "Lãi ròng nếu về NAV %",
        "Lãi ròng",
        1,
        True,
        "%",
        "Lãi nếu mua ở giá chào bán rồi bán đúng NAV, sau phí mua/bán và thuế bán",
    ),
    ("Mua được đạt ngưỡng (đ)", "Mua được (đ)", 0, False, "", "Giá trị chào bán ở các mức giá đạt ngưỡng lãi ròng"),
    (
        "CL NAV trung vị 1N %",
        "Thường lệch",
        1,
        True,
        "%",
        "Trung vị (giá đóng cửa / NAV − 1) 1 năm của chính quỹ: quỹ luôn chiết khấu thì CK âm chưa chắc là rẻ bất thường",
    ),
    ("CL NAV thấp nhất 1N %", "Sâu nhất 1N", 1, True, "%", "Mức chiết khấu sâu nhất 1 năm (theo giá đóng cửa)"),
    (
        "Phiên chưa khớp",
        "Phiên chưa khớp",
        0,
        False,
        "",
        "Số phiên từ lần khớp cuối: giá khớp cũ thì đừng tin giá khớp",
    ),
    ("GTGD TB20 (tỷ)", "GTGD TB20", 2, False, "", "Giá trị giao dịch TB 20 phiên, tỷ đồng: thấp = khó bán ra"),
    ("Phí quản lý %", "Phí QL", 2, False, "%", "Phí quản lý %/năm"),
    (
        "NAV so CS 1N",
        "NAV−CS 1N",
        1,
        True,
        "",
        "Lợi nhuận NAV 1 năm − của chỉ số (điểm %): âm nhiều = quỹ bám chỉ số kém. " + GIAI_THICH_SO_CS,
    ),
]


def bang_etf(df, cot, la_quy, id_bang="", cot_ma="Mã", lien_ket="/etf/", ten_ma=None):
    """Bảng số theo danh sách cột (dùng cho ETF và trang Lướt CW); bấm tiêu đề để sắp xếp, bấm vào mã để mở trang chi tiết
    (la_quy: có liên kết lien_ket + mã)."""
    dau = "".join(
        f'<th class="{"" if le is None else "so"}"><button type="button" title="{ESC(gt)} (Bấm để sắp xếp.)">{ESC(td)}</button></th>'
        for _, td, le, _, _, gt in cot
    )
    dong = []
    for _, h in df.iterrows():
        ma = ESC(h[cot_ma])
        chip = (
            f'<span class="chip" style="color:var(--chu-am)" title="{ESC(h["Cảnh báo"])}" aria-label="Cảnh báo: {ESC(h["Cảnh báo"])}">⚠</span>'
            if h["Cảnh báo"]
            else ""
        )
        o = [f'<td><a href="{lien_ket}{ma}">{ma}</a>{chip}</td>' if la_quy else f"<td>{ma}{chip}</td>"]
        for c, _, le, co_dau, hau_to, _ in cot:
            v = h[c]
            if le is None:
                o.append(f"<td>{ESC(str(v))}</td>")
            elif not math.isfinite(v):
                o.append('<td class="so" data-v="-1e18">—</td>')
            else:
                lop = (" duong" if v > 0 else " am" if v < 0 else "") if co_dau else ""
                o.append(f'<td class="so{lop}" data-v="{v}">{so(v, le, co_dau)}{hau_to}</td>')
        href = f' data-href="{lien_ket}{ma}"' if la_quy else ""
        dong.append(f'<tr{href}>{"".join(o)}</tr>')
    return (
        f'<table{f" id={id_bang}" if id_bang else ""}><thead><tr><th><button type="button" title="Bấm để sắp xếp.">'
        f'{ten_ma or ("Quỹ" if la_quy else "Chỉ số")}</button></th>{dau}</tr></thead><tbody>{"".join(dong)}</tbody></table>'
    )


def doc_etf():
    """(chỉ số, quỹ có cột "so CS", ngày) từ file kết quả ETF mới nhất; chưa có -> (None, None, None)."""
    df, ngay = etf.doc_ket_qua()
    if df is None:
        return None, None, None
    cs, quy = df[df["Loại"] == "Chỉ số"], df[df["Loại"] == "ETF"].copy()
    quy["so CS"] = quy["1N %"] - quy["Chỉ số"].map(dict(zip(cs["Mã"], cs["1N %"])))
    return cs, quy, ngay


def trang_etf():
    cs, quy, ngay = doc_etf()
    phan = [
        '<h1>Quỹ ETF</h1><p class="phu">'
        + (
            f"Dữ liệu ngày {ngay:%d/%m/%Y} · {len(quy)} quỹ · tự cập nhật 9:40 thứ Hai–Sáu (giữa phiên)"
            if ngay
            else "Chưa có dữ liệu"
        )
        + "</p>"
    ]
    if ngay is None:
        phan.append(
            '<div class="the"><h2>Chưa có kết quả</h2><p>Chạy <code>.venv/bin/python etf.py --no-discord</code> '
            "trong thư mục dự án (hoặc chờ lịch 9:40) rồi tải lại trang.</p></div>"
        )
        return trang("Quỹ ETF", "".join(phan), "/etf")
    phan.append(
        '<p class="phu">Rê chuột lên tiêu đề cột để xem giải thích, bấm vào một quỹ để xem biểu đồ giá và chênh lệch so với NAV.</p>'
    )
    ck = quy.assign(
        Đạt=lambda d: d["Mua được đạt ngưỡng (đ)"].map(lambda v: "🟢" if v >= chiet_khau.MIN_GIA_TRI_CHAO_BAN else "")
    ).sort_values("Lãi ròng nếu về NAV %", ascending=False)
    phan.append(
        '<section class="the"><h2>Chiết khấu so với NAV</h2>'
        f'<p class="phu">Ngưỡng: lãi ròng nếu mua ở giá chào bán rồi bán đúng NAV ≥ {chiet_khau.NGUONG_LAI_RONG:.0%} và mua được '
        f"≥ {so(chiet_khau.MIN_GIA_TRI_CHAO_BAN / 1e6)} triệu. Chỉ có lời khi giá quay về sát NAV — quỹ ít giao dịch có thể "
        "chiết khấu rất lâu (xem cột Thường lệch).</p>"
        f'<div class="cuon">{bang_etf(ck, COT_CK, True)}</div></section>'
    )
    phan.append(
        f'<section class="the"><h2>Chỉ số ({len(cs)})</h2><div class="cuon">{bang_etf(cs, COT_CHI_SO, False)}</div></section>'
    )
    phan.append(
        f'<section class="the"><h2>Tất cả {len(quy)} quỹ</h2>'
        '<input type="search" data-loc="#bang-etf" placeholder="Tìm theo mã quỹ hoặc chỉ số (vd: VN30, DIAMOND)" aria-label="Tìm quỹ ETF">'
        f'<div class="cuon cao">{bang_etf(quy, COT_ETF, True, "bang-etf")}</div></section>'
    )
    canh_bao = [(h["Mã"], h["Cảnh báo"]) for d in (cs, quy) for _, h in d.iterrows() if h["Cảnh báo"]]
    if canh_bao:
        phan.append(
            f'<details class="the"><summary>Cảnh báo dữ liệu ({len(canh_bao)})</summary><ul>'
            + "".join(f"<li><b>{ESC(m)}</b>: {ESC(c)}</li>" for m, c in canh_bao)
            + "</ul></details>"
        )
    return trang("Quỹ ETF", "".join(phan), "/etf")


def doc_nav(ma):
    """NAV đã làm sạch của 1 quỹ từ file ket_qua/nav_etf_*.csv.gz mới nhất CÓ quỹ đó (etf.py lưu lúc 9:40; hôm nguồn lỗi
    thì quỹ thiếu ở file mới) -> Series, chưa có -> None. File hỏng: báo lỗi (trang hiện lý do)."""
    for tep in sorted(cw_scanner.THU_MUC_KET_QUA.glob("nav_etf_*.csv.gz"), reverse=True):
        d = pd.read_csv(tep, compression="gzip")
        d = d[d["Mã"] == ma]
        if len(d):
            return pd.Series(d["NAV"].to_numpy(float), pd.DatetimeIndex(d["Ngày"]))
    return None


def muc_nen_etf(ma, cs, h, gia_cs):
    """Mục nến H1/H4/D1 của quỹ và chỉ số mô phỏng (chung trục) + độ sâu, khớp lệnh của quỹ: như trang CW.
    Bảng giá Vietcap trực tiếp (1 lượt); lỗi mạng thì nến vẫn vẽ theo giá lúc quét, ô sổ lệnh báo không lấy được."""
    try:
        bg = cw_scanner.lay_bang_gia([ma]).get(ma)
    # lỗi mạng: không có sổ lệnh trực tiếp, mục nến vẫn dùng được
    except Exception:  # noqa: BLE001
        bg = None
    P = cw_scanner.gia_hien_tai(*bg[:2]) if bg else h["Giá"]
    return W.muc_nen(ma, cs, P, gia_cs, bg, chi_so=etf.TEN_TRONG_VNSTOCK.get(cs, cs))


SO_NGAY_INAV = 5  # mục giá so với iNAV trong phiên: số ngày gần nhất (file ket_qua/inav_*.csv) được chọn xem


def ck_dat_nguong():
    """Giá chào bán / iNAV − 1 (%) mà lãi ròng nếu về iNAV vừa đúng NGUONG_LAI_RONG (suy ngược lai_rong_neu_ve_nav):
    (1 − phí − thuế) / ((1 + phí) × (1 + ngưỡng)) − 1."""
    phi, thue = cw_scanner.PHI_GIAO_DICH, cw_scanner.THUE_BAN
    return ((1 - phi - thue) / ((1 + phi) * (1 + chiet_khau.NGUONG_LAI_RONG)) - 1) * 100


def doc_inav_trong_phien(ma, so_ngay=SO_NGAY_INAV):
    """{'YYYY-MM-DD': {diem: [[HH:MM, giá chào bán / iNAV − 1 (%)]], thap_nhat: (giờ, %), trung_vi: %, cuoi: (giờ, %)}} của
    `so_ngay` file ket_qua/inav_*.csv gần nhất (chiet_khau.py ghi 5 phút/lần trong giờ khớp lệnh từ 23/10/2026).
    Bỏ dòng chưa có iNAV hoặc không có ai chào bán (không có giá mua được thì không có chiết khấu thật)."""
    kq = {}
    for tep in sorted(cw_scanner.THU_MUC_KET_QUA.glob("inav_*.csv"))[-so_ngay:]:
        d = pd.read_csv(tep, encoding="utf-8-sig")
        d = d[(d["Mã"] == ma) & (d["iNAV"] > 0) & (d["Giá chào bán"] > 0)]
        if not len(d):
            continue
        ck = ((d["Giá chào bán"] / d["iNAV"] - 1) * 100).round(2)
        diem = [[str(g)[:5], float(v)] for g, v in zip(d["Giờ"], ck)]
        kq[tep.stem[5:]] = {
            "diem": diem,
            "thap_nhat": tuple(diem[int(ck.to_numpy().argmin())]),
            "trung_vi": float(ck.median()),
            "cuoi": tuple(diem[-1]),
        }
    return kq


def muc_inav_trong_phien(ma, thuong_lech):
    """Mục "Giá so với iNAV trong phiên": mỗi ngày 1 biểu đồ giá chào bán / iNAV − 1 theo giờ (nút chọn ngày), kèm mốc ngang
    iNAV, ngưỡng lãi ròng và mức thường lệch; dòng tóm tắt: lúc rẻ nhất, trung vị, cuối phiên, số lần đạt ngưỡng."""
    dau = '<section class="the"><h2>Giá so với iNAV trong phiên</h2>'
    try:
        cac_ngay = doc_inav_trong_phien(ma)
    # file ghi dở / hỏng: chỉ mục này báo lỗi
    except Exception as e:  # noqa: BLE001
        return f'{dau}<p class="loi" role="alert">Không đọc được file iNAV: {ESC(str(e)[:150])}</p></section>'
    if not cac_ngay:
        return f"{dau}<p>Chưa có dữ liệu iNAV trong phiên của {ESC(ma)} (lưu 5 phút/lần từ 23/10/2026).</p></section>"
    nguong = ck_dat_nguong()
    ke = [
        ("Ngang iNAV", 0.0, "tc-thuc-hien"),
        (f"Ngưỡng lãi {so(chiet_khau.NGUONG_LAI_RONG * 100, 0)}%", nguong, "tc-hoa-von"),
    ]
    ke += [("Thường lệch", float(thuong_lech), "ma-dai")] if math.isfinite(thuong_lech) else []
    cuoi = list(cac_ngay)[-1]
    nut = "".join(
        f'<button type="button" data-chon-khung="{d}" aria-pressed="{str(d == cuoi).lower()}">{d[8:]}/{d[5:7]}</button>'
        for d in cac_ngay
    )
    khung = "".join(
        f'<div class="khung-nen" data-khung="{d}"{"" if d == cuoi else " hidden"}><p class="tom-nen">Rẻ nhất '
        f"<b>{so(v['thap_nhat'][1], 2, True)}%</b> lúc {v['thap_nhat'][0]} · trung vị {so(v['trung_vi'], 2, True)}% · cuối "
        f"{so(v['cuoi'][1], 2, True)}% lúc {v['cuoi'][0]} · đạt ngưỡng {sum(p <= nguong for _, p in v['diem'])}/{len(v['diem'])} lần đo</p>"
        + bieu_do(
            v["diem"], ke, f"Giá chào bán / iNAV {ma} ngày {d}", "%", "Chào bán / iNAV − 1 (%)", so_le=2, truc_gio=True
        )
        + "</div>"
        for d, v in cac_ngay.items()
    )
    return (
        f'{dau}<div class="chon-khung" role="group" aria-label="Chọn ngày">{nut}</div>'
        '<p class="phu">Giá chào bán thấp nhất (giá mua được ngay) so với iNAV, đo 5 phút/lần trong giờ khớp lệnh (SSI iBoard). '
        f"Dưới 0 = rẻ hơn giá trị tài sản; dưới đường cam ({so(nguong, 2, True)}%) thì lãi ròng nếu giá về iNAV ≥ "
        f"{so(chiet_khau.NGUONG_LAI_RONG * 100, 0)}% sau phí, thuế; nét đứt là mức thường lệch 1 năm của quỹ. Lúc không ai chào bán "
        "thì không có điểm. iNAV của SSI là số ước tính, có lúc cập nhật chậm.</p>"
        f"{khung}</section>"
    )


def nav_so_voi_chi_so(nav, cs):
    """NAV và chỉ số (Series theo ngày) -> ([[ngày, % NAV từ mốc]], [% chỉ số cùng ngày], % NAV cả kỳ, % chỉ số cả kỳ).
    Chỉ lấy ngày cả hai cùng có, mốc = ngày chung đầu tiên (cùng mốc thì mới so được)."""
    nav, cs = nav.align(cs, join="inner")
    nav_pt, cs_pt = (nav / nav.iloc[0] - 1) * 100, (cs / cs.iloc[0] - 1) * 100
    diem = [[str(d.date()), float(v)] for d, v in nav_pt.items()]
    return diem, [float(v) for v in cs_pt], float(nav_pt.iloc[-1]), float(cs_pt.iloc[-1])


def muc_theo_kip_chi_so(ma, cs):
    """Mục "ETF có theo kịp chỉ số không": % NAV so với % chỉ số mô phỏng trong 1 năm tới ngày NAV cuối (1 lượt vnstock cho
    chỉ số, floating=6 vì điểm chia 1.000)."""
    dau = f'<section class="the"><h2>{ESC(ma)} có theo kịp {ESC(cs)} không?</h2>'
    try:
        nav = doc_nav(ma)
        if nav is None or len(nav) < 2:
            return f"{dau}<p>Chưa có lịch sử NAV của quỹ này.</p></section>"
        df = cw_scanner.lay_gia_dong_cua(etf.TEN_TRONG_VNSTOCK.get(cs, cs), etf.SO_NGAY_LICH_SU, "VCI", floating=6)
        gia_cs = etf.chuoi_gia(df, etf.HE_SO_CHI_SO)[0]
        nav = nav[nav.index > nav.index[-1] - pd.DateOffset(years=1)]
        diem, duong_cs, nav_tong, cs_tong = nav_so_voi_chi_so(nav, gia_cs)
    # mất mạng / file NAV hỏng: chỉ mục này báo lỗi
    except Exception as e:  # noqa: BLE001
        return f'{dau}<p class="loi" role="alert">Không vẽ được: {ESC(str(e)[:150])}</p></section>'
    if len(diem) < 2:
        return f"{dau}<p>Chưa đủ ngày có cả NAV và điểm {ESC(cs)} để so.</p></section>"
    chenh = nav_tong - cs_tong
    return (
        dau + f'<p class="tom-nen">Từ {diem[0][0][8:]}/{diem[0][0][5:7]}/{diem[0][0][:4]} đến {diem[-1][0][8:]}/'
        f"{diem[-1][0][5:7]}/{diem[-1][0][:4]}: NAV <b>{so(nav_tong, 1, True)}%</b>, {ESC(cs)} <b>{so(cs_tong, 1, True)}%</b> → "
        f'NAV − chỉ số <b class="{"gia-tang" if chenh >= 0 else "gia-giam"}">{so(chenh, 1, True)} điểm</b></p>'
        '<p class="phu">Đường xanh: % thay đổi NAV của quỹ; đường cam: % thay đổi điểm chỉ số, cùng mốc ngày đầu. Chỉ số là chỉ số '
        "giá (chưa cộng cổ tức) còn NAV có cổ tức nên quỹ bám tốt thường cao hơn chỉ số một chút; thấp hơn nhiều = quỹ bám kém "
        "(phí, tiền mặt, sai số mô phỏng). Đây là bám chỉ số của NAV; giá có thể lệch thêm khỏi NAV (xem chênh lệch giá/NAV).</p>"
        + bieu_do(
            diem,
            [("0%", 0.0, "tc-thuc-hien")],
            f"NAV {ma} so với {cs}",
            "%",
            "NAV từ mốc (%)",
            [(cs, duong_cs, "ma-ngan")],
            1,
        )
        + "</section>"
    )


def so_lieu_truc_tiep(ma, h, ngay):
    """Giá chào bán, KL chào bán, iNAV, NAV T-1, giá chờ mua, chiết khấu, lãi ròng nếu về NAV, mua được đạt ngưỡng của 1 quỹ theo
    SSI iBoard lúc mở trang (1 lượt gọi cả rổ). Lỗi mạng / chưa có iNAV -> số lúc quét. Trả về (số liệu, mô tả nguồn, lỗi).
    """
    try:
        bg = chiet_khau.lay_ssi().get(ma)
        loi = "" if bg else "SSI không có quỹ này"
    # ranh giới gọi mạng: trang vẫn dùng số lúc quét và báo rõ
    except Exception as e:  # noqa: BLE001
        bg, loi = None, f"{type(e).__name__}: {e}"[:150]
    if bg and (bg.get("iNAV") or 0) > 0:
        so_lieu = {**chiet_khau.danh_gia_quy(bg), "Giá chờ mua": bg.get("best1Bid") or math.nan}
        return so_lieu, f"SSI iBoard lúc {datetime.now():%H:%M %d/%m/%Y}", ""
    cot = ["iNAV", "NAV T-1", "Giá chào bán", "KL chào bán", "Chiết khấu mua được %", "Lãi ròng nếu về NAV %"]
    cot += ["Mua được đạt ngưỡng (đ)", "CK 1 lệnh %"]
    return (
        {**{c: h[c] for c in cot}, "Giá chờ mua": math.nan},
        f"số lúc quét ngày {ngay:%d/%m/%Y}",
        loi or "SSI chưa có iNAV",
    )


def kich_ban_ban(gia, inav, gia_cho_mua, thuong_lech_pct, gia_lenh=math.nan):
    """[(kịch bản, giá bán, lãi/lỗ 1 CCQ (đ), lãi ròng %, lãi/lỗ cả lệnh (đ))] nếu mua 1 CCQ ở giá chào bán `gia` rồi bán: ngay ở
    giá chờ mua, khi giá về mức thường lệch (iNAV × (1 + trung vị chênh lệch 1 năm)), khi giá về đúng iNAV; iNAV giữ nguyên. Phí,
    thuế như chiet_khau.lai_rong_neu_ve_nav. Lãi/lỗ cả lệnh: lệnh GIA_TRI_LENH mua ở gia_lenh (giá bình quân ăn dần các mức
    chào bán, chiet_khau.gia_mua_lenh), không phải giá 1 lô nhân lên; thiếu thì NaN. Thiếu số liệu thì bỏ dòng (không đoán).
    """
    phi, thue = cw_scanner.PHI_GIAO_DICH, cw_scanner.THUE_BAN
    kb = [
        ("Bán ngay ở giá chờ mua", gia_cho_mua),
        ("Giá về mức thường lệch", inav * (1 + thuong_lech_pct / 100)),
        ("Giá về đúng iNAV", inav),
    ]
    if not (math.isfinite(gia) and gia > 0):
        return []
    return [
        (
            ten,
            b,
            b * (1 - phi - thue) - gia * (1 + phi),
            chiet_khau.lai_rong_neu_ve_nav(gia, b) * 100,
            chiet_khau.lai_rong_neu_ve_nav(gia_lenh, b) * chiet_khau.GIA_TRI_LENH,
        )
        for ten, b in kb
        if math.isfinite(b) and b > 0
    ]


def trang_etf_chi_tiet(ma):
    cac_cs, quy, ngay = doc_etf()
    if ngay is None or ma not in set(quy["Mã"]):  # chỉ nhận mã có trong file kết quả (chặn mã lạ từ URL)
        return None
    h = quy[quy["Mã"] == ma].iloc[0]
    cs = h["Chỉ số"]
    o = lambda c, le=1, dau=True, hau_to="%": so(h[c], le, dau) + (hau_to if math.isfinite(h[c]) else "")
    pt_ = lambda v, le=1: so(v, le, True) + "%" if math.isfinite(v) else "—"
    lop = lambda v, tot_khi_am=False: (
        "" if not math.isfinite(v) or v == 0 else ("duong" if (v < 0) == tot_khi_am else "am")
    )  # xanh / đỏ
    lt, nguon, loi = so_lieu_truc_tiep(ma, h, ngay)
    gia, inav, ck, lr = lt["Giá chào bán"], lt["iNAV"], lt["Chiết khấu mua được %"], lt["Lãi ròng nếu về NAV %"]
    tv, md = h["CL NAV trung vị 1N %"], lt["Mua được đạt ngưỡng (đ)"]
    phi_chu, thue_chu = so(cw_scanner.PHI_GIAO_DICH * 100, 2), so(cw_scanner.THUE_BAN * 100, 1)
    phan = [f'<p><a href="/etf">← Tất cả quỹ ETF</a></p><h1>{ESC(ma)}</h1>']
    if loi:  # không lấy được giá trực tiếp: báo ở đầu trang cho dễ thấy
        phan.append(f'<p class="loi" role="alert">Không lấy được iNAV trực tiếp ({ESC(loi)}), đang dùng {nguon}.</p>')
    if h["Cảnh báo"]:
        phan.append(f'<p class="ghi-chu-canh-bao">⚠ {ESC(h["Cảnh báo"])}</p>')

    # Hàng ô đầu trang (người dùng chọn 30/10/2026: gọn như trang CW)
    phan.append(
        '<div class="luoi-o">'
        + o_so(
            "Giá chào bán / iNAV",
            f"{so(gia)} / {so(inav)}",
            "giá mua được ngay / giá trị tài sản ước tính trong phiên",
        )
        + o_so(
            "Chiết khấu mua được",
            f'<span class="{lop(ck, True)}">{pt_(ck, 2)}</span>',
            f"âm = giá chào bán thấp hơn iNAV · ở giá đó có {so(lt['KL chào bán'])} CCQ"
            + (f" ≈ {so(gia * lt['KL chào bán'] / 1e6, 1)} triệu đ" if math.isfinite(gia) else ""),
        )
        + o_so(
            "Lãi ròng nếu về iNAV",
            f'<span class="{lop(lr)}">{pt_(lr, 2)}</span>',
            f"đã trừ phí {phi_chu}% × 2 + thuế {thue_chu}% · ngưỡng ≥ {so(chiet_khau.NGUONG_LAI_RONG * 100, 0)}%",
        )
        + o_so(
            "Thường lệch NAV (1 năm)",
            pt_(tv),
            f"trung vị giá đóng cửa / NAV − 1; sâu nhất {o('CL NAV thấp nhất 1N %')}",
        )
        + o_so(
            "Bám chỉ số (1 năm)",
            o("NAV so CS 1N", hau_to=" điểm"),
            f"lợi nhuận NAV − lợi nhuận {ESC(cs)}; âm nhiều = quỹ bám kém",
        )
        + o_so(
            "Giá trị giao dịch TB 20 phiên",
            f"{so(h['GTGD TB20 (tỷ)'], 2)} tỷ",
            f"{so(h['Phiên khớp 1N'])} phiên có khớp lệnh trong 1 năm",
        )
        + o_so("NAV phiên trước", f"{so(lt['NAV T-1'])} đ", f"lịch sử NAV Vietcap đến {ESC(h['Ngày NAV cuối']) or '—'}")
        + o_so("Chứng chỉ quỹ lưu hành", so(h["CCQ lưu hành"]), "tăng = có tiền góp thêm vào quỹ")
        + "</div>"
    )

    # Tóm tắt + tiêu chí
    if math.isfinite(gia):
        cau = (
            f"Bạn trả <b>{so(gia)} đ</b> cho 1 CCQ (giá chào bán thấp nhất), iNAV là {so(inav)} đ: giá đang "
            + ("thấp hơn" if ck < 0 else "cao hơn")
            + f" iNAV <b>{so(abs(ck), 2)}%</b>. Nếu giá về đúng iNAV (iNAV giữ nguyên), lãi ròng sau phí, thuế là "
            f'<b class="{lop(lr)}">{pt_(lr, 2)}</b>.'
        )
    else:
        cau = f"Hiện không có ai chào bán {ESC(ma)}: chưa mua được ngay."
    if math.isfinite(tv):
        cau += f" Quỹ này thường lệch <b>{pt_(tv)}</b> so với NAV (trung vị 1 năm)" + (
            f", nên giá hiện tại {'rẻ hơn' if ck < tv else 'đắt hơn'} mức thường {so(abs(ck - tv), 1)} điểm."
            if math.isfinite(ck)
            else "."
        )
    tieu_chi = [
        (
            math.isfinite(lr) and lr >= chiet_khau.NGUONG_LAI_RONG * 100,
            f"Lãi ròng nếu về iNAV {pt_(lr, 2)}",
            f"cần ≥ {so(chiet_khau.NGUONG_LAI_RONG * 100, 0)}%",
        ),
        (
            md >= chiet_khau.MIN_GIA_TRI_CHAO_BAN,
            f"Mua được {so(md / 1e6, 1)} triệu đ ở các mức giá đạt ngưỡng",
            f"cần ≥ {so(chiet_khau.MIN_GIA_TRI_CHAO_BAN / 1e6)} triệu",
        ),
        (
            math.isfinite(ck) and math.isfinite(tv) and ck < tv,
            f"Chiết khấu {pt_(ck, 2)} so với mức thường lệch {pt_(tv)}",
            "cần sâu hơn mức thường",
        ),
    ]
    dong_tc = "".join(
        f'<li><b class="{"duong" if dat else "am"}" aria-label="{"Đạt" if dat else "Không đạt"}">{"✓" if dat else "✕"}</b>'
        f"<span>{nd} <small>({yc})</small></span></li>"
        for dat, nd, yc in tieu_chi
    )
    m_tom_tat = (
        f'<section class="the"><h2>Tóm tắt</h2><p class="tom-tat">{cau}</p><ul class="tieu-chi">{dong_tc}</ul>'
        '<p class="phu">Kiểm chứng 2 năm (KE_HOACH Phần 8): mua ở phiên sau khi đạt ngưỡng thì phần lãi nhờ chiết khấu thu hẹp '
        "≈ 0 sau phí; chỉ có lời khi mua được đúng lúc trong phiên, ở giá chào bán thật (xem mục giá so với iNAV trong phiên).</p></section>"
    )
    m_thong_tin = (
        f'<section class="the"><p class="phu" style="margin:0">Quỹ ETF mô phỏng <b>{ESC(cs)}</b> · phí quản lý '
        f"{o('Phí quản lý %', 2, False)}/năm · dữ liệu quét ngày {ngay:%d/%m/%Y}</p>"
        f'<p class="phu" style="margin:6px 0 0">Giá chào bán, iNAV theo {nguon}.</p></section>'
    )
    lenh = chiet_khau.GIA_TRI_LENH
    # giá bình quân 1 lệnh từ "CK 1 lệnh %" (làm tròn 0,01%: lệch ≤ 2.500 đ trên 50 triệu)
    kb = kich_ban_ban(gia, inav, lt["Giá chờ mua"], tv, inav * (1 + lt["CK 1 lệnh %"] / 100))
    m_neu = (
        '<section class="the"><h2>Nếu mua bây giờ rồi bán</h2>'
        f'<p class="phu">Mua 1 CCQ ở giá chào bán {so(gia)} đ (+ phí {phi_chu}%), bán trừ phí {phi_chu}% và thuế {thue_chu}%; '
        "giả định iNAV giữ nguyên (chỉ số đứng yên). Lệnh lớn ăn vào các mức chào bán cao hơn: chiết khấu cho 1 lệnh "
        f"{so(lenh / 1e6)} triệu là {pt_(lt['CK 1 lệnh %'], 2)}.</p>"
        + (
            '<div class="cuon"><table><thead><tr><th>Kịch bản</th><th class="so">Giá bán (đ)</th>'
            '<th class="so">Lãi/lỗ 1 CCQ (đ)</th><th class="so">Lãi ròng</th>'
            f'<th class="so" title="Lệnh {so(lenh / 1e6)} triệu mua ở giá bình quân ăn dần 3 mức chào bán (—: 3 mức không đủ)">'
            f"Lệnh {so(lenh / 1e6)} triệu (đ)</th></tr></thead><tbody>"
            + "".join(
                f'<tr><td>{ten}</td><td class="so">{so(b)}</td><td class="so {lop(d)}">{so(d, 0, True)}</td>'
                f'<td class="so {lop(p)}">{so(p, 2, True)}%</td><td class="so {lop(v)}">{so(v, 0, True)}</td></tr>'
                for ten, b, d, p, v in kb
            )
            + "</tbody></table></div>"
            if kb
            else "<p>Không có người chào bán nên chưa tính được.</p>"
        )
        + "</section>"
    )

    # Chênh lệch giá / NAV 1 năm (giá đóng cửa vnstock + NAV Vietcap đã làm sạch)
    bd_cl = "<p>Chưa có lịch sử NAV của quỹ này.</p>"
    try:  # 1 lượt gọi vnstock mỗi lần mở trang
        ls = cw_scanner.lay_gia_dong_cua(ma, etf.SO_NGAY_LICH_SU, "VCI")
        gia_ls = etf.chuoi_gia(ls, 10 ** round(math.log10(h["Giá"] / float(ls["close"].iloc[-1]))))[
            0
        ]  # nghìn đồng -> đồng
        nav = doc_nav(ma)
        cl = ((gia_ls / nav).dropna() - 1) * 100 if nav is not None else pd.Series(dtype=float)  # chỉ phiên có khớp
        cl = cl[cl.index > cl.index[-1] - pd.DateOffset(years=1)] if len(cl) else cl
        if len(cl) > 1:
            bd_cl = bieu_do(
                [[str(d.date()), round(float(v), 2)] for d, v in cl.items()],
                [("Trung vị", float(cl.median()), "tc-thuc-hien"), ("Ngang NAV", 0.0, "tc-hoa-von")],
                f"Chênh lệch giá/NAV {ma}",
                don_vi="%",
                ten_cot="Giá / NAV − 1 (%)",
                so_le=1,
            )
    # mất mạng / vnstock lỗi / file NAV hỏng: báo rõ trên trang, phần còn lại vẫn dùng được
    except Exception as e:  # noqa: BLE001
        bd_cl = f'<p class="loi" role="alert">Không vẽ được chênh lệch giá/NAV: {ESC(str(e)[:200])}</p>'
    m_cl = (
        '<section class="the"><h2>Chênh lệch giá / NAV 1 năm</h2>'
        '<p class="phu">Giá đóng cửa các phiên có khớp chia NAV cùng ngày − 1. Dưới 0 = chiết khấu. Giá đóng cửa của quỹ ít '
        "giao dịch thường là 1 lô nhỏ nên đường này nhiễu; đường xám là trung vị (mức thường lệch), đường cam là ngang NAV.</p>"
        f"{bd_cl}</section>"
    )

    # Số liệu khác (tham khảo)
    dk = [
        ("Giá khớp cuối", f"{so(h['Giá'])} đ (phiên {ESC(h['Ngày giá cuối'])})"),
        ("Lợi nhuận 1T / 3T / 6T / 1N", f"{o('1T %')} / {o('3T %')} / {o('6T %')} / {o('1N %')}"),
        (f"Giá so với {ESC(cs)} (1 năm)", o("so CS", hau_to=" điểm")),
        ("Xu hướng", f"{ESC(h['Xu hướng']) or '—'} (MA50 {so(h['MA50'])} · MA200 {so(h['MA200'])})"),
        ("RSI14", so(h["RSI14"], 0)),
        ("Biến động năm", o("Biến động năm %", dau=False)),
        ("Giảm sâu nhất / cách đỉnh 1 năm", f"{o('Giảm sâu nhất 1N %')} / {o('Cách đỉnh 1N %')}"),
        ("Khối ngoại ròng trong phiên", f"{so(h['Khối ngoại ròng (tỷ)'], 2, True)} tỷ"),
        ("Phiên chưa khớp", so(h["Phiên chưa khớp"])),
    ]
    m_so_lieu = (
        '<section class="the"><h2>Số liệu khác</h2><p class="phu">'
        + GIAI_THICH_SO_CS
        + '.</p><dl class="dieu-khoan">'
        + "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in dk)
        + "</dl></section>"
    )
    phan += [
        hang_doi(f'<div class="cot-doc">{m_tom_tat}{m_thong_tin}</div>', m_neu),
        muc_nen_etf(ma, cs, h, float(cac_cs.loc[cac_cs["Mã"] == cs, "Giá"].iloc[0])),
        hang_doi(muc_inav_trong_phien(ma, tv), m_cl),
        muc_theo_kip_chi_so(ma, cs),
        m_so_lieu,
    ]
    return trang(f"{ma} - Quỹ ETF", "".join(phan), "/etf")
