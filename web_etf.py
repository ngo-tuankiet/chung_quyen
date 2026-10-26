"""Trang ETF (/etf) và chi tiết từng quỹ (/etf/<mã>)."""

import math

import pandas as pd

import chiet_khau
import cw_scanner
import etf
from web_chung import ESC, bieu_do, o_so, so, trang

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


def trang_etf_chi_tiet(ma):
    _, quy, ngay = doc_etf()
    if ngay is None or ma not in set(quy["Mã"]):  # chỉ nhận mã có trong file kết quả (chặn mã lạ từ URL)
        return None
    h = quy[quy["Mã"] == ma].iloc[0]
    o = lambda c, le=1, dau=True, hau_to="%": so(h[c], le, dau) + (hau_to if math.isfinite(h[c]) else "")
    phan = [
        (
            f'<p><a href="/etf">← Tất cả quỹ ETF</a></p><h1>{ESC(ma)}</h1>'
            f'<p class="phu">Mô phỏng {ESC(h["Chỉ số"])} · dữ liệu ngày {ngay:%d/%m/%Y}</p>'
        )
    ]
    if h["Cảnh báo"]:
        phan.append(f'<p class="ghi-chu-canh-bao">⚠ {ESC(h["Cảnh báo"])}</p>')
    phan.append(
        '<div class="luoi-o">'
        + o_so(
            "Chiết khấu mua được",
            o("Chiết khấu mua được %"),
            f"chào bán {so(h['Giá chào bán'])} × {so(h['KL chào bán'])} CCQ so với iNAV {so(h['iNAV'])} · "
            f"lãi ròng nếu về NAV {o('Lãi ròng nếu về NAV %')}",
        )
        + o_so(
            "Thường lệch NAV (1 năm)",
            o("CL NAV trung vị 1N %"),
            f"trung vị giá đóng cửa / NAV − 1; sâu nhất {o('CL NAV thấp nhất 1N %')}",
        )
        + o_so(
            "NAV so với chỉ số (1 năm)", o("NAV so CS 1N", hau_to=" điểm"), f"NAV đến {ESC(h['Ngày NAV cuối']) or '—'}"
        )
        + o_so("Giá", f"{so(h['Giá'])} đ", f"phiên khớp cuối {ESC(h['Ngày giá cuối'])}")
        + o_so("Lợi nhuận 1 năm", o("1N %"), f"1T {o('1T %')} · 3T {o('3T %')} · 6T {o('6T %')}")
        + o_so(
            f"So với {ESC(h['Chỉ số'])} (1 năm)",
            o("so CS", hau_to=" điểm"),
            GIAI_THICH_SO_CS,
        )
        + o_so("Xu hướng", ESC(h["Xu hướng"]) or "—", f"MA50 {so(h['MA50'])} · MA200 {so(h['MA200'])}")
        + o_so("RSI14", so(h["RSI14"], 0), "trên 70 tăng nóng · dưới 30 bị bán quá mức")
        + o_so("Biến động năm", o("Biến động năm %", dau=False), f"giảm sâu nhất 1 năm {o('Giảm sâu nhất 1N %')}")
        + o_so("Cách đỉnh 1 năm", o("Cách đỉnh 1N %"))
        + o_so(
            "Giá trị giao dịch TB 20 phiên",
            f"{so(h['GTGD TB20 (tỷ)'], 2)} tỷ",
            f"{so(h['Phiên khớp 1N'])} phiên có khớp lệnh trong 1 năm",
        )
        + o_so("Khối ngoại ròng trong phiên", f"{so(h['Khối ngoại ròng (tỷ)'], 2, True)} tỷ")
        + o_so("Chứng chỉ quỹ lưu hành", so(h["CCQ lưu hành"]), "tăng = có tiền góp thêm vào quỹ")
        + "</div>"
    )
    bd_cl = "<p>Chưa có lịch sử NAV của quỹ này.</p>"
    try:  # 1 lượt gọi vnstock mỗi lần mở trang
        ls = cw_scanner.lay_gia_dong_cua(ma, etf.SO_NGAY_LICH_SU, "VCI")
        gia = etf.chuoi_gia(ls, 10 ** round(math.log10(h["Giá"] / float(ls["close"].iloc[-1]))))[
            0
        ]  # nghìn đồng -> đồng
        trong_1_nam = gia.index > gia.index[-1] - pd.DateOffset(years=1)
        lich_su = [[str(d.date()), float(g)] for d, g in gia[trong_1_nam].items()]
        phu = [
            (f"MA{n}", [None if math.isnan(v) else float(v) for v in gia.rolling(n).mean()[trong_1_nam]], lop)
            for n, lop in ((etf.MA_NGAN, "ma-ngan"), (etf.MA_DAI, "ma-dai"))
        ]
        bd = (
            bieu_do(lich_su, [], f"Giá {ma}", duong_phu=phu)
            if len(lich_su) > 1
            else "<p>Quá ít phiên có khớp lệnh trong 1 năm để vẽ biểu đồ.</p>"
        )
    except Exception as e:  # mất mạng / vnstock lỗi: báo rõ trên trang  # noqa: BLE001
        gia, bd = None, f'<p class="loi" role="alert">Không tải được lịch sử giá: {ESC(str(e)[:200])}</p>'
    if gia is not None:
        try:  # file NAV hỏng không được làm mất biểu đồ giá
            nav = doc_nav(ma)
            cl = ((gia / nav).dropna() - 1) * 100 if nav is not None else pd.Series(dtype=float)  # chỉ phiên có khớp
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
        except Exception as e:  # noqa: BLE001
            bd_cl = f'<p class="loi" role="alert">Không đọc được lịch sử NAV: {ESC(str(e)[:200])}</p>'
    phan.append(
        '<section class="the"><h2>Chênh lệch giá / NAV 1 năm</h2>'
        '<p class="phu">Giá đóng cửa các phiên có khớp chia NAV cùng ngày − 1. Dưới 0 = chiết khấu. Giá đóng cửa của quỹ ít '
        "giao dịch thường là 1 lô nhỏ nên đường này nhiễu; đường xám là trung vị, đường cam là ngang NAV.</p>"
        f"{bd_cl}</section>"
    )
    phan.append(
        '<section class="the"><h2>Giá 1 năm, MA50 và MA200</h2>'
        '<p class="phu">MA50 (cam) / MA200 (xám, nét đứt): trung bình giá đóng cửa 50 / 200 phiên có khớp lệnh.</p>'
        f"{bd}</section>"
    )
    return trang(f"{ma} - Quỹ ETF", "".join(phan), "/etf")
