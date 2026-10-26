"""Trang ⚡ Lướt CW (/luot)."""

import cw_scanner
import web_chung as W  # doc_ket_qua và trạng thái LOI/NHAT_KY/LOI_DANH_MUC đọc qua module: test patch được, handler gán được
from web_chung import ESC, GIAI_THICH_LECH, so, trang
from web_etf import bang_etf

# ============ LƯỚT CW ============
COT_LUOT = [
    ("Mã CS", "Mã CS", None, False, "", "Cổ phiếu cơ sở: hướng đi của nó là phần bạn tự nhận định"),
    (
        "Lướt: CS cần tăng %",
        f"CS cần tăng ({cw_scanner.SO_PHIEN_GIU} phiên)",
        2,
        True,
        "%",
        (
            f"Ưu tiên 2 (xếp theo cột này): CS phải tăng bao nhiêu trong {cw_scanner.SO_PHIEN_GIU} phiên để hòa vốn — mua ở giá "
            "chào bán + phí, bán ở mức giá chờ mua − phí, thuế, CW mất giá theo thời gian; IV giữ nguyên. Càng thấp càng tốt"
        ),
    ),
    (
        "Lướt: lãi kịch bản %",
        f"Lãi nếu CS +{cw_scanner.KICH_BAN_TANG:.0%}",
        1,
        True,
        "%",
        (
            f"Ưu tiên 3: lãi sau phí, thuế nếu CS tăng {cw_scanner.KICH_BAN_TANG:.0%} trong {cw_scanner.SO_PHIEN_GIU} phiên "
            "(cùng giả định); CS đứng yên hoặc giảm thì lỗ tương ứng"
        ),
    ),
    (
        "Lướt: lãi kịch bản hiệu chỉnh %",
        "Hiệu chỉnh TCPH",
        1,
        True,
        "%",
        (
            f"Như cột trước nhưng IV bán ra = IV chờ mua + β × {cw_scanner.KICH_BAN_TANG:.0%}: β = số điểm IV TCPH này đã đổi khi "
            "CS tăng 1% (đo lịch sử, ACBS và Vietcap hạ IV khi CS tăng). — = TCPH ít mẫu, không hiệu chỉnh. Không dùng để xếp hạng"
        ),
    ),
    (
        "Đòn bẩy",
        "Đòn bẩy",
        1,
        False,
        "x",
        "CS +1% thì CW tăng khoảng bấy nhiêu % (theo giá mua); lỗ cũng nhanh như vậy",
    ),
    ("Lệch 20 phiên %", "Lệch 20p", 1, True, "%", GIAI_THICH_LECH),
    ("Mất giá/ngày %", "Mất giá/ngày", 2, True, "%", "CW mất bao nhiêu mỗi ngày nếu CS và IV đứng yên"),
    (
        "IV − HV",
        "IV − HV",
        1,
        True,
        "",
        "Ưu tiên 4: IV (theo giá mua) − biến động lịch sử, điểm %: cao = đắt, IV giảm về thì CW mất giá dù CS tăng",
    ),
    (
        "IV cùng mã %",
        "IV TV cùng mã",
        0,
        False,
        "%",
        "Trung vị IV các CW khác cùng mã CS: IV của CW này cao hơn = đắt hơn",
    ),
    ("Giá mua", "Chào bán", 0, False, "", "Giá chào bán thấp nhất lúc quét: giá mua được ngay"),
    ("Giá chờ mua", "Chờ mua", 0, False, "", "Giá chờ mua cao nhất lúc quét: giá bán ra được ngay"),
    ("Spread %", "Spread", 1, False, "%", "(chào bán − chờ mua) / giá giữa"),
    ("Bên mua 3 bước (triệu)", "Bên mua (tr)", 1, False, "", "Tổng giá trị chờ mua ở 3 bước giá: chỗ để bán ra"),
    ("KL chào bán", "KL chào bán", 0, False, "", "Ưu tiên 5: còn nhiều = TCPH sẵn hàng, giá khó lên nhanh"),
    ("Ngày GD cuối", "GD cuối", None, False, "", "Sau ngày này không bán được"),
    ("TCPH", "TCPH", None, False, "", "Tổ chức phát hành (bên yết giá chính)"),
]


def trang_luot():
    df, ngay = W.doc_ket_qua()
    phan = ["<h1>⚡ Lướt CW 2–5 phiên</h1>"]
    if df is None:
        phan.append(
            '<div class="the"><p>Chưa có kết quả quét. Bấm <b>Quét ngay</b> ở <a href="/">trang chính</a>.</p></div>'
        )
        return trang("Lướt CW", "".join(phan), "/luot-cw")
    dat, loai = cw_scanner.chon_luot(df, ngay)
    C = cw_scanner
    tep_he_so, beta = C.doc_he_so_iv()
    dat = dat.assign(**{"Lướt: lãi kịch bản hiệu chỉnh %": C.lai_kb_hieu_chinh(dat, ngay, beta)})
    he_so = (
        f"Cột <b>Hiệu chỉnh TCPH</b> (lãi nếu CS +{C.KICH_BAN_TANG:.0%}) chỉ để tham khảo, không đổi thứ tự: IV bán ra = IV chờ mua + β × {C.KICH_BAN_TANG:.0%}, "
        f"β đo trên {C.SO_THANG_HE_SO_IV} tháng gần nhất, file <code>{ESC(tep_he_so)}</code> (kiem_chung_truyen_dan.py, TCPH có ≥ "
        f"{C.MIN_MAU_HE_SO_IV} cửa sổ đo): "
        + ", ".join(f"{ESC(t)} {so(b, 2, True)}" for t, b in sorted(beta.items(), key=lambda x: x[1]))
        + " điểm IV khi CS +1%. Đo bằng giá đóng cửa, không phải giá yết của TCPH; hệ số đổi theo thời kỳ."
        if tep_he_so
        else "Chưa có bảng hệ số IV theo TCPH (chạy <code>python kiem_chung_truyen_dan.py</code>): cột hiệu chỉnh để trống."
    )
    phan.append(
        f'<p class="phu">Số liệu lần quét {ngay:%d/%m/%Y} (sổ lệnh lúc quét; bấm vào mã để định giá lại theo giá trực tiếp). '
        f"Python <b>không đoán hướng cổ phiếu</b>: bạn chọn mã CS mình nhận định sẽ tăng, trang này chỉ ra CW nào rẻ và hiệu quả "
        f"nhất để đặt cược đó.</p>"
        '<details class="the" open><summary>Thứ tự ưu tiên khi chọn CW để lướt</summary><ol>'
        f"<li><b>Loại CW khó thoát lệnh:</b> không có người chào bán / chờ mua, bên mua dưới {so(C.MIN_BEN_MUA_LUOT / 1e6)} triệu, "
        f"spread trên {C.MAX_SPREAD_LUOT:.0%}, còn dưới {C.MIN_NGAY_GD_CUOI_LUOT} ngày tới ngày GD cuối.</li>"
        f"<li><b>CS cần tăng ít nhất để hòa vốn trong {C.SO_PHIEN_GIU} phiên</b> (bảng xếp theo cột này): đã gồm đòn bẩy, mất giá "
        "theo thời gian, spread, phí, thuế.</li>"
        f"<li><b>Lãi nếu CS tăng {C.KICH_BAN_TANG:.0%}</b>: CW nào khuếch đại tốt nhất sau chi phí.</li>"
        "<li><b>IV:</b> IV − HV cao hoặc IV cao hơn các CW cùng mã = đắt, IV giảm về thì CW mất giá dù CS tăng.</li>"
        "<li><b>Tổ chức phát hành:</b> khối lượng chào bán còn rất nhiều hoặc vừa phát hành thêm thì giá khó lên.</li></ol>"
        f'<p class="phu">Giả định IV giữ nguyên {C.SO_PHIEN_GIU} phiên; mua phiên T thì sớm nhất chiều T+2 mới bán được. '
        f"Đòn bẩy cao cũng là lỗ nhanh.</p><details><summary>Hệ số IV theo TCPH (cột Hiệu chỉnh TCPH)</summary>"
        f'<p class="phu">{he_so}</p></details></details>'
    )
    if dat["Lướt: CS cần tăng %"].isna().all() and loai["Lướt: CS cần tăng %"].isna().all():
        phan.append('<p class="loi">File quét này từ bản cũ, chưa có số liệu lướt: bấm Quét ngay ở trang chính.</p>')
    phan.append(
        f'<section class="the"><h2>Lướt được ({len(dat)} CW)</h2>'
        '<input type="search" data-loc="#bang-luot" placeholder="Lọc theo mã cổ phiếu hoặc mã CW (vd: VPB, HPG)" '
        'aria-label="Lọc CW theo mã">'
        f'<div class="cuon cao">{bang_etf(dat, COT_LUOT, True, "bang-luot", "Mã CW", "/cw/", "Mã CW")}</div></section>'
    )
    phan.append(
        f'<details class="the"><summary>Bị loại ({len(loai)} CW) và lý do</summary><div class="cuon cao">'
        + bang_etf(
            loai,
            [("Mã CS", "Mã CS", None, False, "", "Cổ phiếu cơ sở"), ("Lý do loại lướt", "Lý do", None, False, "", "")],
            True,
            "",
            "Mã CW",
            "/cw/",
            "Mã CW",
        )
        + "</div></details>"
    )
    return trang("Lướt CW", "".join(phan), "/luot-cw")
