"""Trang hợp đồng tương lai chỉ số VN30 (/phai-sinh) và chi tiết từng hợp đồng (/phai-sinh/<mã>)."""

import math
from datetime import date

import cw_scanner
import phai_sinh as P
import web_chung as W
from web_chung import ESC, bieu_do, hang_doi, o_so, so, trang

KICH_BAN_VN30 = (-10, -5, -2, 0, 2, 5, 10)  # % VN30 lúc ngày GD cuối so với hôm nay, cho bảng lãi/lỗ giữ đến đáo hạn
SO_PHIEN_BASIS = 50  # biểu đồ basis theo ngày: số phiên gần nhất


def thang_hd(h):
    """'VN30 Index Futures 112026' (tên trên bảng giá) -> 'T11/2026'; không đọc được thì để mã."""
    ten = h["ten"].split()[-1]
    return f"T{ten[:2]}/{ten[2:]}" if len(ten) == 6 and ten.isdigit() else h["ma"]


def chi_so_hd(h, vn30, hom_nay):
    """Các chỉ số của 1 hợp đồng so với VN30 cùng ngày giá: basis, basis năm hóa, ngày còn lại, số phiên tới ngày GD cuối."""
    S = vn30.get(h["ngay_gia"], math.nan)
    con = (h["gd_cuoi"] - hom_nay).days if h["gd_cuoi"] else -1
    b, bp = P.basis(h["gia"], S)
    return {
        "S": S,
        "basis": b,
        "basis_pt": bp,
        "nam_hoa": P.basis_nam_hoa(h["gia"], S, con) if con > 0 else math.nan,
        "con_ngay": con,
        "so_phien": P.so_phien(hom_nay, h["gd_cuoi"]) if h["gd_cuoi"] else 0,
    }


GIAI_THICH = (
    "<b>Basis</b> = giá hợp đồng − VN30 (điểm). Hợp đồng thanh toán bằng tiền theo VN30 đóng cửa ngày giao dịch cuối, nên basis "
    "về 0 lúc đó. <b>Basis năm hóa</b> = ln(giá HĐ / VN30) / thời gian còn lại (năm): theo lý thuyết cost-of-carry (Hull ch. 5) "
    "bằng lãi suất phi rủi ro r trừ tỷ suất cổ tức của VN30 q. Basis năm hóa thấp hơn r nhiều = thị trường đang trả giá HĐ "
    "thấp (cổ tức sắp chia, tâm lý bi quan); cao hơn r = trả giá cao. Chưa có số q chắc chắn nên trang không tính giá hợp lý. "
    f"1 điểm = {so(P.HE_SO_NHAN)} đ/hợp đồng."
)


def trang_phai_sinh():
    try:
        ds, vn30, canh_bao = P.lay_du_lieu()
    # mất mạng / vnstock lỗi: báo rõ, không có số cũ để dùng
    except Exception as e:  # noqa: BLE001
        return trang(
            "Hợp đồng tương lai",
            f'<h1>Hợp đồng tương lai VN30</h1><p class="loi" role="alert">Không tải được dữ liệu: {ESC(str(e)[:200])}</p>',
            "/phai-sinh",
        )
    hom_nay, ngay_s = date.today(), max(vn30)
    r = cw_scanner.LAI_SUAT_PHI_RUI_RO * 100
    hang = []
    for h in ds:
        c = chi_so_hd(h, vn30, hom_nay)
        lop = "gia-tang" if c["basis"] > 0 else ("gia-giam" if c["basis"] < 0 else "")
        hang.append(
            f'<tr data-href="/phai-sinh/{h["ma"]}"><td><a href="/phai-sinh/{h["ma"]}">{h["ma"]}</a></td><td>{thang_hd(h)}</td>'
            f'<td class="so">{so(h["gia"], 1)}</td><td class="so {lop}">{so(c["basis"], 2, True)}</td>'
            f'<td class="so {lop}">{so(c["basis_pt"], 2, True)}%</td><td class="so">{so(c["nam_hoa"], 2, True)}%</td>'
            f'<td>{h["gd_cuoi"]:%d/%m/%Y}</td><td class="so">{c["con_ngay"]}</td>'
            f'<td class="so">{so(P.ky_quy_ban_dau(h["gia"]) / 1e6, 1)}</td></tr>'
            if h["gd_cuoi"]
            else f'<tr><td>{h["ma"]}</td><td colspan="8">thiếu ngày đáo hạn (bảng giá Vietcap lỗi)</td></tr>'
        )
    phan = [
        (
            "<h1>Hợp đồng tương lai VN30</h1>"
            f'<p class="phu">VN30 <b>{so(vn30[ngay_s], 2)}</b> điểm · giá ngày {ngay_s[8:]}/{ngay_s[5:7]}/{ngay_s[:4]} (nến ngày vnstock lúc mở '
            "trang, trong phiên là giá khớp mới nhất) · bấm vào một hợp đồng để xem chi tiết</p>"
        )
    ]
    if canh_bao:
        phan.append('<p class="ghi-chu-canh-bao">⚠ ' + ESC("; ".join(canh_bao)) + "</p>")
    phan.append(
        '<section class="the"><h2>Basis các hợp đồng</h2>'
        f'<p class="phu">So với lãi suất phi rủi ro r = {so(r, 1)}%/năm (giả định, dùng chung với định giá CW).</p>'
        '<div class="cuon"><table><thead><tr><th>Mã</th><th>Đáo hạn</th><th class="so">Giá</th><th class="so">Basis (điểm)</th>'
        '<th class="so">Basis %</th><th class="so">Năm hóa</th><th>Ngày GD cuối</th><th class="so">Còn (ngày)</th>'
        f'<th class="so">Ký quỹ 1 HĐ (triệu)</th></tr></thead><tbody>{"".join(hang)}</tbody></table></div>'
        f'<details class="giai-thich"><summary>ℹ Giải thích</summary><p class="phu">{GIAI_THICH}</p></details></section>'
    )
    return trang("Hợp đồng tương lai", "".join(phan), "/phai-sinh")


def trang_phai_sinh_chi_tiet(ma):
    if not P.MAU_MA_HD.fullmatch(ma) or ma not in P.HOP_DONG:  # chỉ nhận mã hợp lệ (chặn mã lạ từ URL)
        return None
    try:
        ds, vn30, canh_bao = P.lay_du_lieu()
    # mất mạng: báo rõ
    except Exception as e:  # noqa: BLE001
        return trang(
            ma,
            f'<h1>{ESC(ma)}</h1><p class="loi" role="alert">Không tải được dữ liệu: {ESC(str(e)[:200])}</p>',
            "/phai-sinh",
        )
    h = next((x for x in ds if x["ma"] == ma), None)
    if h is None or not h["gd_cuoi"]:
        return trang(
            ma,
            f'<h1>{ESC(ma)}</h1><p class="loi" role="alert">Thiếu dữ liệu: {ESC("; ".join(canh_bao))}</p>',
            "/phai-sinh",
        )
    hom_nay, F = date.today(), h["gia"]
    c = chi_so_hd(h, vn30, hom_nay)
    S, r = c["S"], cw_scanner.LAI_SUAT_PHI_RUI_RO * 100
    kq = P.ky_quy_ban_dau(F)
    gop, rong = P.lai_lo_dao_han(F, F, 1, c["so_phien"])
    chi_phi = gop - rong  # phí + thuế khứ hồi nếu giữ đến ngày GD cuối (VN30 lúc đó = giá mua)
    lop = lambda v: "gia-tang" if v > 0 else ("gia-giam" if v < 0 else "")
    phan = [
        f'<p><a href="/phai-sinh">← Tất cả hợp đồng</a></p><h1>{ESC(ma)} <small class="phu">{thang_hd(h)}</small></h1>'
    ]
    if canh_bao:
        phan.append('<p class="ghi-chu-canh-bao">⚠ ' + ESC("; ".join(canh_bao)) + "</p>")
    phan.append(
        '<div class="luoi-o">'
        + o_so("Giá HĐ / VN30", f"{so(F, 1)} / {so(S, 2)}", f"điểm · giá ngày {h['ngay_gia'][8:]}/{h['ngay_gia'][5:7]}")
        + o_so(
            "Basis",
            f'<span class="{lop(c["basis"])}">{so(c["basis"], 2, True)} điểm</span>',
            f"{so(c['basis_pt'], 2, True)}% · dương = HĐ cao hơn VN30; về 0 ngày GD cuối",
        )
        + o_so(
            "Basis năm hóa",
            f"{so(c['nam_hoa'], 2, True)}%/năm",
            f"so với r = {so(r, 1)}%: chênh {so(c['nam_hoa'] - r, 2, True)} điểm (= −cổ tức ngầm định ± tâm lý)",
        )
        + o_so(
            "Ngày giao dịch cuối",
            f"{h['gd_cuoi']:%d/%m/%Y}",
            f"còn {c['con_ngay']} ngày ({c['so_phien']} phiên); thanh toán theo VN30 đóng cửa ngày này"
            + (f", tiền về ngày {h['dao_han']:%d/%m}" if h["dao_han"] else ""),
        )
        + o_so("Giá trị 1 hợp đồng", f"{so(F * P.HE_SO_NHAN / 1e6, 1)} triệu đ", f"1 điểm = {so(P.HE_SO_NHAN)} đ")
        + o_so(
            "Ký quỹ ban đầu 1 HĐ",
            f"{so(kq / 1e6, 2)} triệu đ",
            f"{so(P.TY_LE_KY_QUY_BAN_DAU * 100, 0)}% giá trị (VSDC) → đòn bẩy ≈ {so(1 / P.TY_LE_KY_QUY_BAN_DAU, 1)} lần",
        )
        + o_so(
            "VN30 ±1% →",
            f"≈ ±{so(S * 0.01 * P.HE_SO_NHAN)} đ/HĐ",
            f"≈ ±{so(S * 0.01 * P.HE_SO_NHAN / kq * 100, 1)}% tiền ký quỹ",
        )
        + o_so(
            "Phí + thuế nếu giữ đến đáo hạn",
            f"≈ {so(chi_phi)} đ/HĐ",
            f"= {so(chi_phi / P.HE_SO_NHAN, 2)} điểm; phí CTCK, Sở, vị thế {c['so_phien']} phiên, thuế 2 lần",
        )
        + "</div>"
    )
    # Tóm tắt
    cau = (
        f"Hợp đồng {ESC(ma)} ({thang_hd(h)}) đang <b>{'cao hơn' if c['basis'] > 0 else 'thấp hơn'} VN30 "
        f"{so(abs(c['basis']), 2)} điểm</b> ({so(c['basis_pt'], 2, True)}%). Nếu giữ đến ngày giao dịch cuối "
        f"{h['gd_cuoi']:%d/%m/%Y}, hợp đồng thanh toán theo VN30 hôm đó nên khoản chênh này "
        + (
            "mất đi với người mua (Long), có lợi cho người bán (Short)"
            if c["basis"] > 0
            else "có lợi cho người mua (Long)"
        )
        + f". Basis năm hóa {so(c['nam_hoa'], 2, True)}%/năm so với r = {so(r, 1)}%/năm."
    )
    m_tom_tat = (
        f'<section class="the"><h2>Tóm tắt</h2><p class="tom-tat">{cau}</p>'
        f'<p class="phu">Mỗi hợp đồng cần ký quỹ khoảng {so(kq / 1e6, 1)} triệu đ; VN30 biến động 1% làm lãi/lỗ khoảng '
        f"{so(S * 0.01 * P.HE_SO_NHAN / kq * 100, 1)}% số tiền ký quỹ. Lỗ có thể vượt tiền ký quỹ nếu thị trường đi ngược mạnh "
        "(bị gọi ký quỹ bổ sung hoặc đóng vị thế bắt buộc).</p></section>"
    )
    m_gia_dinh = (
        '<section class="the"><p class="phu" style="margin:0">Phí, thuế, ký quỹ theo 1 công ty lớn làm chuẩn: phí CTCK '
        f"{so(P.PHI_CTCK_HD)} đ/HĐ/lần (biểu giá SSI hiệu lực 01/01/2022, < 100 HĐ/ngày), phí Sở HNX {so(P.PHI_SO_HD)} đ/HĐ, phí vị thế "
        f"VSDC {so(P.PHI_VI_THE_HD_NGAY)} đ/HĐ/ngày, ký quỹ ban đầu {so(P.TY_LE_KY_QUY_BAN_DAU * 100, 0)}% (VSDC, hiệu lực 22/11/2024), "
        f"thuế {so(P.THUE_TNCN * 100, 1)}% × giá × {so(P.HE_SO_NHAN)} × tỷ lệ ký quỹ / 2 mỗi lần. Kiểm tra lại với công ty chứng khoán "
        "của bạn; chưa tính phí quản lý tài sản ký quỹ (theo tháng, theo tài khoản).</p></section>"
    )
    # Nếu giữ đến ngày GD cuối
    dong = []
    for pt_ in KICH_BAN_VN30:
        S_T = S * (1 + pt_ / 100)
        _, long_ = P.lai_lo_dao_han(F, S_T, 1, c["so_phien"])
        _, short_ = P.lai_lo_dao_han(F, S_T, -1, c["so_phien"])
        dong.append(
            f'<tr{" class=hang-goc" if pt_ == 0 else ""}><td>{"Giữ nguyên" if pt_ == 0 else f"{pt_:+d}%"}</td>'
            f'<td class="so">{so(S_T, 1)}</td><td class="so {lop(long_)}">{so(long_, 0, True)}</td>'
            f'<td class="so {lop(long_)}">{so(long_ / kq * 100, 1, True)}%</td><td class="so {lop(short_)}">{so(short_, 0, True)}</td>'
            f'<td class="so {lop(short_)}">{so(short_ / kq * 100, 1, True)}%</td></tr>'
        )
    m_neu_giu = (
        f'<section class="the"><h2>Nếu giữ 1 hợp đồng đến ngày GD cuối ({h["gd_cuoi"]:%d/%m/%Y})</h2>'
        f'<p class="phu">Mở vị thế ở giá {so(F, 1)}, thanh toán theo VN30 ngày GD cuối; đã trừ phí, thuế. % tính trên tiền ký quỹ '
        f'ban đầu {so(kq / 1e6, 1)} triệu đ.</p><div class="cuon"><table><thead><tr><th>VN30 thay đổi</th><th class="so">VN30 lúc đó</th>'
        '<th class="so">Long (đ)</th><th class="so">Long / ký quỹ</th><th class="so">Short (đ)</th><th class="so">Short / ký quỹ</th>'
        f'</tr></thead><tbody>{"".join(dong)}</tbody></table></div></section>'
    )
    # Basis theo ngày (mã liên tục: sang tháng mới vnstock nối sang hợp đồng kế tiếp)
    chung = sorted(set(h["lich_su"]) & set(vn30))[-SO_PHIEN_BASIS:]
    m_basis = (
        '<section class="the"><h2>Basis theo ngày</h2>'
        f'<p class="phu">Giá đóng cửa {ESC(ma)} − VN30 đóng cửa cùng ngày, {len(chung)} phiên gần nhất. {ESC(ma)} là mã liên tục: '
        "tới ngày đáo hạn vnstock nối sang hợp đồng kế tiếp, nên basis có thể nhảy bậc ở ngày chuyển.</p>"
        + (
            bieu_do(
                [[d, round(h["lich_su"][d] - vn30[d], 2)] for d in chung],
                [("Basis 0", 0.0, "tc-thuc-hien")],
                f"Basis {ma}",
                "điểm",
                "Basis (điểm)",
                so_le=2,
            )
            if len(chung) > 1
            else "<p>Chưa đủ dữ liệu.</p>"
        )
        + "</section>"
    )
    phan += [
        hang_doi(f'<div class="cot-doc">{m_tom_tat}{m_gia_dinh}</div>', m_neu_giu),
        W.muc_nen(ma, P.CHI_SO, F, S, h["bang_gia"], chi_so=P.CHI_SO, nhan=P.HE_SO_NHAN),
        m_basis,
        (
            f'<section class="the"><details class="giai-thich" open><summary>ℹ Basis là gì</summary><p class="phu">{GIAI_THICH}</p>'
            "</details></section>"
        ),
    ]
    return trang(f"{ma} – hợp đồng tương lai", "".join(phan), "/phai-sinh")
