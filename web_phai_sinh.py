"""Trang hợp đồng tương lai chỉ số VN30, VN100 (/phai-sinh) và chi tiết từng hợp đồng (/phai-sinh/<mã>)."""

import math
from datetime import date

import cw_scanner
import phai_sinh as P
import web_chung as W
from web_chung import ESC, bieu_do, hang_doi, o_so, so, trang

KICH_BAN_CHI_SO = (
    -10,
    -5,
    -2,
    0,
    2,
    5,
    10,
)  # % chỉ số lúc ngày GD cuối so với hôm nay, cho bảng lãi/lỗ giữ đến đáo hạn
SO_PHIEN_BASIS = 50  # biểu đồ basis theo ngày: số phiên gần nhất
KL_MONG = 100  # HĐ khớp / phiên: dưới mức này Tóm tắt cảnh báo thanh khoản mỏng (chỉ để cảnh báo, không lọc hợp đồng)


def thang_hd(h):
    """'VN30 Index Futures 112026' (tên trên bảng giá) -> 'T11/2026'; không đọc được thì để mã."""
    ten = h["ten"].split()[-1]
    return f"T{ten[:2]}/{ten[2:]}" if len(ten) == 6 and ten.isdigit() else h["ma"]


def chi_so_hd(h, gia_cs, hom_nay):
    """Các chỉ số của 1 hợp đồng so với chỉ số cơ sở cùng ngày giá: basis, basis năm hóa, ngày còn lại, số phiên tới ngày GD cuối."""
    S = gia_cs[h["chi_so"]].get(h["ngay_gia"], math.nan)
    con = (h["gd_cuoi"] - hom_nay).days if h["gd_cuoi"] else -1
    # năm hóa theo số ngày từ ngày của giá F, S (Hull ch. 5), không từ hôm nay: xem cuối tuần / trước 9:00 T không ngắn đi
    con_gia = (h["gd_cuoi"] - date.fromisoformat(h["ngay_gia"])).days if h["gd_cuoi"] else -1
    b, bp = P.basis(h["gia"], S)
    return {
        "S": S,
        "basis": b,
        "basis_pt": bp,
        "nam_hoa": P.basis_nam_hoa(h["gia"], S, con_gia) if con_gia > 0 else math.nan,
        "con_ngay": con,
        "so_phien": P.so_phien(hom_nay, h["gd_cuoi"]) if h["gd_cuoi"] else 0,
    }


def ghi_chu_ky_quy(cs):
    """Tỷ lệ ký quỹ ban đầu của chỉ số `cs` kèm nguồn."""
    return f"{so(P.TY_LE_KY_QUY_BAN_DAU[cs] * 100, 0)}% ({P.NGUON_KY_QUY})"


GIAI_THICH = (
    "<b>Basis</b> = giá hợp đồng − chỉ số cơ sở (điểm). Hợp đồng thanh toán bằng tiền theo giá thanh toán cuối cùng: "
    "trung bình chỉ số 30 phút cuối ngày giao dịch cuối, bỏ 3 giá trị cao nhất và 3 thấp nhất (VSD, từ 06/2022), nên basis về "
    "gần 0 lúc đó. <b>Basis năm hóa</b> = ln(giá HĐ / chỉ số) / thời gian còn lại (năm): theo lý thuyết cost-of-carry "
    "(Hull ch. 5) bằng lãi suất phi rủi ro r trừ tỷ suất cổ tức q của rổ chỉ số. Basis năm hóa thấp hơn r nhiều = thị trường đang "
    "trả giá HĐ thấp (cổ tức sắp chia, tâm lý bi quan); cao hơn r = trả giá cao. Chưa có số q chắc chắn nên trang không tính giá "
    "hợp lý; trang Cảnh báo chỉ dùng <b>cận trên</b> chỉ số × e^(rT) (q = 0) để bắt HĐ đắt bất thường. "
    f"1 điểm = {so(P.HE_SO_NHAN)} đ/hợp đồng. Hợp đồng ít giao dịch (KL phiên vài hợp đồng) thì giá đóng cửa có thể lệch "
    "xa giá thật, basis nhiễu."
)


def bang_hop_dong(ds, gia_cs, hom_nay):
    """Bảng các hợp đồng của 1 chỉ số: giá, basis, năm hóa, ngày GD cuối, ngày còn lại, KL phiên, ký quỹ 1 HĐ."""
    hang = []
    for h in ds:
        if not h["gd_cuoi"]:
            hang.append(f'<tr><td>{h["ma"]}</td><td colspan="9">thiếu ngày đáo hạn (bảng giá Vietcap lỗi)</td></tr>')
            continue
        c = chi_so_hd(h, gia_cs, hom_nay)
        lop = "gia-tang" if c["basis"] > 0 else ("gia-giam" if c["basis"] < 0 else "")
        hang.append(
            f'<tr data-href="/phai-sinh/{h["ma"]}"><td><a href="/phai-sinh/{h["ma"]}">{h["ma"]}</a></td><td>{thang_hd(h)}</td>'
            f'<td class="so">{so(h["gia"], 1)}</td><td class="so {lop}">{so(c["basis"], 2, True)}</td>'
            f'<td class="so {lop}">{so(c["basis_pt"], 2, True)}%</td><td class="so">{so(c["nam_hoa"], 2, True)}%</td>'
            f'<td>{h["gd_cuoi"]:%d/%m/%Y}</td><td class="so">{c["con_ngay"]}</td><td class="so">{so(h["kl"])}</td>'
            f'<td class="so">{so(P.ky_quy_ban_dau(h["gia"], h["chi_so"]) / 1e6, 1)}</td></tr>'
        )
    return (
        '<div class="cuon"><table><thead><tr><th>Mã</th><th>Đáo hạn</th><th class="so">Giá</th><th class="so">Basis (điểm)</th>'
        '<th class="so">Basis %</th><th class="so">Năm hóa</th><th>Ngày GD cuối</th><th class="so">Còn (ngày)</th>'
        f'<th class="so">KL phiên</th><th class="so">Ký quỹ 1 HĐ (triệu)</th></tr></thead><tbody>{"".join(hang)}</tbody></table></div>'
    )


def trang_phai_sinh():
    try:
        ds, gia_cs, canh_bao = P.lay_du_lieu()
    # mất mạng / vnstock lỗi: báo rõ, không có số cũ để dùng
    except Exception as e:  # noqa: BLE001
        return trang(
            "Hợp đồng tương lai",
            f'<h1>Hợp đồng tương lai</h1><p class="loi" role="alert">Không tải được dữ liệu: {ESC(str(e)[:200])}</p>',
            "/phai-sinh",
        )
    hom_nay, r = date.today(), cw_scanner.LAI_SUAT_PHI_RUI_RO * 100
    phan = [
        (
            "<h1>Hợp đồng tương lai chỉ số</h1>"
            f'<p class="phu">Giá: nến ngày vnstock lúc mở trang (trong phiên là giá khớp mới nhất) · so với lãi suất phi rủi ro r = '
            f"{so(r, 1)}%/năm (giả định, dùng chung với định giá CW) · bấm vào một hợp đồng để xem chi tiết</p>"
        )
    ]
    if canh_bao:
        phan.append('<p class="ghi-chu-canh-bao">⚠ ' + ESC("; ".join(canh_bao)) + "</p>")
    for cs in P.CHI_SO_HD:
        ngay_s = max(gia_cs[cs])
        phan.append(
            f'<section class="the"><h2>Hợp đồng tương lai {cs}</h2>'
            f'<p class="phu">{cs} <b>{so(gia_cs[cs][ngay_s], 2)}</b> điểm · giá ngày {ngay_s[8:]}/{ngay_s[5:7]}/{ngay_s[:4]} · '
            f"ký quỹ ban đầu {ghi_chu_ky_quy(cs)}</p>"
            + bang_hop_dong([h for h in ds if h["chi_so"] == cs], gia_cs, hom_nay)
            + "</section>"
        )
    phan.append(
        f'<section class="the"><details class="giai-thich"><summary>ℹ Basis là gì</summary><p class="phu">{GIAI_THICH}</p>'
        "</details></section>"
    )
    return trang("Hợp đồng tương lai", "".join(phan), "/phai-sinh")


def trang_phai_sinh_chi_tiet(ma):
    if not P.MAU_MA_HD.fullmatch(ma) or ma not in P.HOP_DONG:  # chỉ nhận mã hợp lệ (chặn mã lạ từ URL)
        return None
    try:
        ds, gia_cs, canh_bao = P.lay_du_lieu()
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
    hom_nay, F, cs = date.today(), h["gia"], h["chi_so"]
    c = chi_so_hd(h, gia_cs, hom_nay)
    S, r = c["S"], cw_scanner.LAI_SUAT_PHI_RUI_RO * 100
    kq = P.ky_quy_ban_dau(F, cs)
    gop, rong = P.lai_lo_dao_han(F, F, 1, c["so_phien"], cs)
    chi_phi = gop - rong  # phí + thuế khứ hồi nếu giữ đến ngày GD cuối (chỉ số lúc đó = giá mua)
    tl = P.TY_LE_KY_QUY_BAN_DAU[cs]
    lop = lambda v: "gia-tang" if v > 0 else ("gia-giam" if v < 0 else "")
    phan = [
        f'<p><a href="/phai-sinh">← Tất cả hợp đồng</a></p><h1>{ESC(ma)} <small class="phu">{thang_hd(h)}</small></h1>'
    ]
    if canh_bao:
        phan.append('<p class="ghi-chu-canh-bao">⚠ ' + ESC("; ".join(canh_bao)) + "</p>")
    phan.append(
        '<div class="luoi-o">'
        + o_so(
            f"Giá HĐ / {cs}",
            f"{so(F, 1)} / {so(S, 2)}",
            f"điểm · giá ngày {h['ngay_gia'][8:]}/{h['ngay_gia'][5:7]} · KL phiên {so(h['kl'])} HĐ",
        )
        + o_so(
            "Basis",
            f'<span class="{lop(c["basis"])}">{so(c["basis"], 2, True)} điểm</span>',
            f"{so(c['basis_pt'], 2, True)}% · dương = HĐ cao hơn {cs}; về 0 ngày GD cuối",
        )
        + o_so(
            "Basis năm hóa",
            f"{so(c['nam_hoa'], 2, True)}%/năm",
            f"so với r = {so(r, 1)}%: chênh {so(c['nam_hoa'] - r, 2, True)} điểm (= −cổ tức ngầm định ± tâm lý)",
        )
        + o_so(
            "Ngày giao dịch cuối",
            f"{h['gd_cuoi']:%d/%m/%Y}",
            f"còn {c['con_ngay']} ngày ({c['so_phien']} phiên); thanh toán theo trung bình {cs} 30 phút cuối ngày này"
            + (f", tiền về ngày {h['dao_han']:%d/%m}" if h["dao_han"] else ""),
        )
        + o_so("Giá trị 1 hợp đồng", f"{so(F * P.HE_SO_NHAN / 1e6, 1)} triệu đ", f"1 điểm = {so(P.HE_SO_NHAN)} đ")
        + o_so(
            "Ký quỹ ban đầu 1 HĐ",
            f"{so(kq / 1e6, 2)} triệu đ",
            f"{ghi_chu_ky_quy(cs)} → đòn bẩy ≈ {so(1 / tl, 1)} lần",
        )
        + o_so(
            f"{cs} ±1% →",
            f"≈ ±{so(S * 0.01 * P.HE_SO_NHAN)} đ/HĐ",
            f"≈ ±{so(S * 0.01 * P.HE_SO_NHAN / kq * 100, 1)}% tiền ký quỹ",
        )
        + o_so(
            "Phí + thuế nếu giữ đến đáo hạn",
            f"≈ {so(chi_phi)} đ/HĐ",
            f"= {so(chi_phi / P.HE_SO_NHAN, 2)} điểm; phí CTCK 2 lần, Sở, bù trừ, thuế 2 lần",
        )
        + "</div>"
    )
    # Tóm tắt
    cau = (
        f"Hợp đồng {ESC(ma)} ({thang_hd(h)}) đang <b>{'cao hơn' if c['basis'] > 0 else 'thấp hơn'} {cs} "
        f"{so(abs(c['basis']), 2)} điểm</b> ({so(c['basis_pt'], 2, True)}%). Nếu giữ đến ngày giao dịch cuối "
        f"{h['gd_cuoi']:%d/%m/%Y}, hợp đồng thanh toán theo {cs} hôm đó nên khoản chênh này "
        + (
            "mất đi với người mua (Long), có lợi cho người bán (Short)"
            if c["basis"] > 0
            else "có lợi cho người mua (Long)"
        )
        + f". Basis năm hóa {so(c['nam_hoa'], 2, True)}%/năm so với r = {so(r, 1)}%/năm."
        + (
            f" <b>⚠ Phiên gần nhất chỉ khớp {so(h['kl'])} hợp đồng: thanh khoản rất mỏng, giá đóng cửa có thể lệch xa giá thật, "
            "khó vào / ra đúng giá.</b>"
            if h["kl"] < KL_MONG
            else ""
        )
    )
    m_tom_tat = (
        f'<section class="the"><h2>Tóm tắt</h2><p class="tom-tat">{cau}</p>'
        f'<p class="phu">Mỗi hợp đồng cần ký quỹ khoảng {so(kq / 1e6, 1)} triệu đ; {cs} biến động 1% làm lãi/lỗ khoảng '
        f"{so(S * 0.01 * P.HE_SO_NHAN / kq * 100, 1)}% số tiền ký quỹ. Lỗ có thể vượt tiền ký quỹ nếu thị trường đi ngược mạnh "
        "(bị gọi ký quỹ bổ sung hoặc đóng vị thế bắt buộc).</p></section>"
    )
    m_gia_dinh = (
        '<section class="the"><p class="phu" style="margin:0">Phí, thuế, ký quỹ theo 1 công ty lớn làm chuẩn: phí CTCK '
        f"{so(P.PHI_CTCK_HD)} đ/HĐ/lần (biểu giá SSI hiệu lực 01/01/2022, < 100 HĐ/ngày), phí Sở HNX {so(P.PHI_SO_HD)} đ/HĐ, phí bù trừ "
        f"VSDC {so(P.PHI_BU_TRU_HD)} đ/HĐ mỗi lệnh khớp (QĐ 1541/QĐ-BTC; thay phí vị thế theo ngày từ 05/05/2025), ký quỹ ban đầu {ghi_chu_ky_quy(cs)}, thuế {so(P.THUE_TNCN * 100, 1)}% × giá × "
        f"{so(P.HE_SO_NHAN)} × tỷ lệ ký quỹ / 2 mỗi lần. Kiểm tra lại với công ty chứng khoán của bạn; chưa tính phí quản lý tài sản "
        "ký quỹ (theo tháng, theo tài khoản).</p></section>"
    )
    # Nếu giữ đến ngày GD cuối
    dong = []
    for pt_ in KICH_BAN_CHI_SO:
        S_T = S * (1 + pt_ / 100)
        _, long_ = P.lai_lo_dao_han(F, S_T, 1, c["so_phien"], cs)
        _, short_ = P.lai_lo_dao_han(F, S_T, -1, c["so_phien"], cs)
        dong.append(
            f'<tr{" class=hang-goc" if pt_ == 0 else ""}><td>{"Giữ nguyên" if pt_ == 0 else f"{pt_:+d}%"}</td>'
            f'<td class="so">{so(S_T, 1)}</td><td class="so {lop(long_)}">{so(long_, 0, True)}</td>'
            f'<td class="so {lop(long_)}">{so(long_ / kq * 100, 1, True)}%</td><td class="so {lop(short_)}">{so(short_, 0, True)}</td>'
            f'<td class="so {lop(short_)}">{so(short_ / kq * 100, 1, True)}%</td></tr>'
        )
    m_neu_giu = (
        f'<section class="the"><h2>Nếu giữ 1 hợp đồng đến ngày GD cuối ({h["gd_cuoi"]:%d/%m/%Y})</h2>'
        f'<p class="phu">Mở vị thế ở giá {so(F, 1)}, thanh toán theo giá thanh toán cuối cùng (≈ {cs} 30 phút cuối ngày GD cuối); đã trừ phí, thuế. % tính trên tiền ký quỹ '
        f'ban đầu {so(kq / 1e6, 1)} triệu đ.</p><div class="cuon"><table><thead><tr><th>{cs} thay đổi</th><th class="so">{cs} lúc đó</th>'
        '<th class="so">Long (đ)</th><th class="so">Long / ký quỹ</th><th class="so">Short (đ)</th><th class="so">Short / ký quỹ</th>'
        f'</tr></thead><tbody>{"".join(dong)}</tbody></table></div></section>'
    )
    # Basis theo ngày (mã liên tục: sang tháng mới vnstock nối sang hợp đồng kế tiếp)
    chung = sorted(set(h["lich_su"]) & set(gia_cs[cs]))[-SO_PHIEN_BASIS:]
    m_basis = (
        '<section class="the"><h2>Basis theo ngày</h2>'
        f'<p class="phu">Giá đóng cửa {ESC(ma)} − {cs} đóng cửa cùng ngày, {len(chung)} phiên gần nhất. {ESC(ma)} là mã liên tục: '
        "tới ngày đáo hạn vnstock nối sang hợp đồng kế tiếp, nên basis có thể nhảy bậc ở ngày chuyển.</p>"
        + (
            bieu_do(
                [[d, round(h["lich_su"][d] - gia_cs[cs][d], 2)] for d in chung],
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
        W.muc_nen(ma, cs, F, S, h["bang_gia"], chi_so=cs, nhan=P.HE_SO_NHAN),
        m_basis,
        (
            f'<section class="the"><details class="giai-thich" open><summary>ℹ Basis là gì</summary><p class="phu">{GIAI_THICH}</p>'
            "</details></section>"
        ),
    ]
    return trang(f"{ma} – hợp đồng tương lai", "".join(phan), "/phai-sinh")
