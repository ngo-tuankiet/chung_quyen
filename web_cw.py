"""Trang chứng quyền: danh sách (trang chính), phân tích chi tiết từng CW, CW sắp ra mắt."""

import json
import math
from datetime import date, datetime, timedelta

import cw_scanner
import danh_muc
import web_chung as W  # doc_ket_qua và trạng thái QUET/LOI_DANH_MUC đọc qua module: test patch được, handler gán được
import web_luot
from web_chung import (
    BO_NHO_IV,
    ESC,
    KET_LUAN,
    VON_MAC_DINH,
    bang,
    bieu_do,
    dat_re,
    hang_doi,
    huy_hieu,
    o_so,
    so,
    trang,
)


# ============ TRANG CHÍNH ============
def trang_chinh():
    df, ngay = W.doc_ket_qua()
    co_key = bool(cw_scanner.doc_env().get("VNSTOCK_API_KEY"))
    phan = [
        (
            '<div class="dau-trang"><div><h1>Quét chứng quyền</h1>'
            f'<p class="phu">{f"Dữ liệu ngày {ngay:%d/%m/%Y} · {len(df)} CW · định giá bằng Black-Scholes" if ngay else "Chưa có dữ liệu"}'
            f' · API key vnstock: {"đã nhập ✓" if co_key else "<b>chưa nhập</b> (mở file .env để điền)"}</p></div></div>'
        )
    ]
    if df is None:
        phan.append(
            '<div class="the"><h2>Chưa có kết quả</h2><p>Lần đầu dùng? Làm theo 3 bước:</p><ol>'
            "<li>Bấm nút <b>🔄 Quét</b> ở góc trên bên phải và chờ 1-3 phút.</li>"
            "<li>Xem bảng <b>Nên xem xét</b> hiện ra - đó là những chứng quyền đạt cả 4 tiêu chí.</li>"
            "<li>Bấm vào một mã để xem phân tích chi tiết trước khi quyết định.</li></ol>"
            '<p>Chưa biết chứng quyền là gì? Đọc <a href="/huong-dan">Hướng dẫn sử dụng</a> (khoảng 5 phút).</p></div>'
        )
        return trang("Quét chứng quyền", "".join(phan), "/")

    dem = df["Đánh giá"].value_counts()
    moi, tot = df[df["Mới"] == "MỚI"], df[df["Đánh giá"] == "NÊN XEM XÉT"]
    phan.append(
        '<div class="luoi-o">'
        + "".join(o_so(huy_hieu(k), so(dem.get(k, 0))) for k in KET_LUAN)
        + o_so("CW mới phát hành", so(len(moi)), "so với lần quét trước")
        + "</div>"
    )
    phan.append(
        f'<p class="phu">Tiêu chí (tính theo giá mua = giá chào bán thấp nhất): còn ≥ {cw_scanner.MIN_NGAY_CON_LAI} ngày · IV − HV ≤ {so(cw_scanner.MAX_IV_TRU_HV * 100, 0, True)} điểm'
        f" · cổ phiếu cơ sở tăng ≤ {cw_scanner.MAX_TANG_DE_HOA_VON:.0%} là hòa vốn · khớp ≥ {so(cw_scanner.MIN_KHOI_LUONG)} CW/phiên."
        " Bấm vào một mã để xem phân tích chi tiết, rê chuột lên tiêu đề cột để xem giải thích."
        ' Chưa rõ cách dùng? Đọc <a href="/huong-dan">Hướng dẫn sử dụng</a>.</p>'
    )
    phan.append(muc_giam_manh(danh_muc.doc_giam_manh(date.today())))
    if len(moi):
        phan.append(
            f'<section class="the"><h2>CW mới phát hành ({len(moi)})</h2><div class="cuon">{bang(moi)}</div></section>'
        )
    phan.append(
        f'<section class="the"><h2>Nên xem xét ({len(tot)})</h2><p class="phu">Đạt cả 4 tiêu chí, xếp theo IV − HV (thấp nhất trước = rẻ nhất so với mức dao động 1 năm qua).</p>'
        + (f'<div class="cuon">{bang(tot)}</div>' if len(tot) else "<p>Hôm nay không có CW nào đạt cả 4 tiêu chí.</p>")
        + "</section>"
    )
    phan.append(web_luot.muc_luot(df, ngay))
    phan.append(
        f'<section class="the"><h2>Tất cả {len(df)} CW</h2>'
        '<input type="search" data-loc="#bang-tat-ca" placeholder="Tìm theo mã CW, mã cổ phiếu hoặc TCPH (vd: VPB, SSI)" aria-label="Tìm chứng quyền">'
        f'<div class="cuon cao">{bang(df, id_bang="bang-tat-ca")}</div></section>'
    )
    return trang("Quét chứng quyền", "".join(phan), "/")


def muc_giam_manh(ds, nay=None):
    """Mục ⚠ các CW (nhóm Nên xem xét / Theo dõi) đã giảm quá ngưỡng so với giá tham chiếu hôm nay; không có thì rỗng.
    nay: mã -> (giá mua nay, đắt/rẻ nay) từ web_canh_bao.gia_nay; None (trang không tải giá trực tiếp) thì không có cột "nay".
    """
    if not ds:
        return ""
    pt = lambda x: f"{so(x * 100, 1, True)}%" if math.isfinite(x) else "—"
    dr = lambda x: '<span class="{1}">{0}</span>'.format(*dat_re(x * 100))

    def dong(ma, g):
        # file trước 02/11/2026 không có dat_re, lech_20: hiện "—"
        lop, o_nay, dr_nay = "", "", ""
        if nay is not None:
            gia, dat_re_nay = nay.get(ma, (None, math.nan))
            # giá mua nay không còn thấp hơn tham chiếu quá ngưỡng (cùng cách làm tròn với danh_muc.cw_giam_manh): hết tác dụng
            hoi = gia is not None and round(gia / g["ref"] - 1, 9) >= -danh_muc.NGUONG_GIAM_MANH
            lop = ' class="da-hoi"' if hoi else ""
            o_nay = (
                f'<td class="so">{so(gia)} ({pt(gia / g["ref"] - 1)}){" đã hồi" if hoi else ""}</td>'
                if gia
                else "<td>—</td>"
            )
            dr_nay = f" → {dr(dat_re_nay)}"
        return (
            f'<tr{lop}><td><a href="/cw/{ESC(ma)}">{ESC(ma)}</a></td><td>{ESC(g["cs"])}</td>'
            f'<td class="so"><b>{pt(g["giam"])}</b></td><td class="so">{so(g["gia"])} / {so(g["ref"])}</td>{o_nay}'
            f'<td class="so">{so(g["kl"])}</td><td class="so">{pt(g["cs_pt"])}</td><td class="so">{pt(g["lech"])}</td>'
            f'<td class="so">{dr(g.get("dat_re", math.nan))}{dr_nay}</td>'
            f'<td class="so">{pt(g.get("lech_20", math.nan))}</td><td>{ESC(g["luc"])}</td></tr>'
        )

    hang = "".join(dong(ma, g) for ma, g in sorted(ds.items(), key=lambda x: x[1]["giam"]))
    return (
        f'<section class="the" role="alert"><h2>⚠ CW giảm mạnh hôm nay ({len(ds)})</h2>'
        f'<p class="phu">CW nhóm Nên xem xét / Theo dõi có giá khớp giảm quá {danh_muc.NGUONG_GIAM_MANH:.0%} so với giá tham chiếu '
        f"(= giá đóng cửa phiên trước) <b>và</b> lệch ≤ −{danh_muc.NGUONG_LECH_GIAM_MANH:.0%} so với mức lẽ ra theo cổ phiếu cơ sở "
        f"<b>và</b> Lệch 20p < −{danh_muc.NGUONG_LECH_20_GIAM_MANH:.0%} (tụt hẳn so với CS cả 20 phiên, từ 03/11/2026), "
        "tức riêng CW bị bán chứ không phải do CS giảm × đòn bẩy. Lệch tính từ phiên gần nhất CW khớp đủ "
        f"{so(cw_scanner.GIA_TRI_KHOP_TOI_THIEU / 1e6)} triệu (IV ngày đó, giá CS cùng ngày, đã trừ mất giá theo thời gian tới hôm nay). "
        f"Lệnh khớp gần nhất dưới {so(cw_scanner.GIA_TRI_KHOP_TOI_THIEU / 1e6)} triệu là lệnh lẻ: xét theo giá phải trả để mua đủ số tiền đó. "
        "Đắt/rẻ (so với giá hợp lý theo biến động 1 năm của CS) và Lệch 20p tính ở giá lúc báo, nên có thể khác số trong danh sách "
        "chứng quyền (tính lúc quét). Kiểm mỗi 5 phút trong giờ khớp lệnh, số liệu ở lần kiểm mới nhất."
        + (
            " <b>Giá mua nay</b> = giá chào bán thấp nhất lúc mở trang, Đắt/rẻ sau dấu → tính ở giá đó (cùng số với trang chi "
            f'tiết). Dòng mờ ghi "đã hồi": giá mua nay không còn thấp hơn tham chiếu quá {danh_muc.NGUONG_GIAM_MANH:.0%}, '
            "cảnh báo đã hết tác dụng."
            if nay is not None
            else ""
        )
        + "</p>"
        '<div class="cuon"><table><thead><tr><th>Mã CW</th><th>Mã CS</th><th class="so">Giảm</th><th class="so">Giá khớp / TC</th>'
        + (
            '<th class="so" title="Giá chào bán thấp nhất lúc mở trang (% so với tham chiếu)">Giá mua nay</th>'
            if nay is not None
            else ""
        )
        + '<th class="so">KL khớp</th><th class="so">CS hôm nay</th><th class="so">Lệch</th>'
        '<th class="so" title="Giá lúc báo (→ giá mua nay) so với giá hợp lý theo biến động 1 năm của CS (cùng cách tính cột '
        'Đắt/rẻ ở danh sách)">'
        f"Đắt/rẻ{' lúc báo → nay' if nay is not None else ''}</th>"
        '<th class="so" title="Lệch 20 phiên tính ở giá lúc báo; danh sách chứng quyền ghi số lúc quét">Lệch 20p</th>'
        "<th>Báo lúc</th></tr></thead>"
        f"<tbody>{hang}</tbody></table></div></section>"
    )


# ============ TRANG CHI TIẾT ============
def trang_chi_tiet(ma, von=VON_MAC_DINH):
    df, ngay = W.doc_ket_qua()
    if df is None or ma not in set(df["Mã CW"]):
        return None
    h, C = df[df["Mã CW"] == ma].iloc[0].to_dict(), cw_scanner
    cs, sigma_ls, ket_luan_quet = h["Mã CS"], float(h["Biến động %/năm"]) / 100, h["Đánh giá"]
    r = (
        float(h["r %"]) / 100 if "r %" in h else C.LAI_SUAT_PHI_RUI_RO
    )  # đúng lãi suất của lần quét (file cũ: cấu hình hiện tại)
    # Định giá lại theo giá trực tiếp: CW + cổ phiếu cơ sở trong 1 lần gọi (chờ tối đa 5 giây); σ và r giữ như lúc quét
    try:
        bang_gia = C.lay_bang_gia([ma, cs], cho=5)
        niem_yet, khop, so_lenh = bang_gia[ma]
        S_truc_tiep = C.gia_hien_tai(*bang_gia[cs])
    # mất mạng / máy chủ lỗi / thiếu mã: dùng đúng số lúc quét và báo rõ trên trang
    except Exception as e:  # noqa: BLE001
        so_lenh, ngay_tinh, truc_tiep = {}, ngay, False
        nguon = f"KHÔNG tải được giá trực tiếp ({ESC(str(e)[:120])}), đang dùng số liệu lúc quét ngày {ngay:%d/%m/%Y}"
    else:
        h.update(C.dinh_gia(niem_yet, khop, so_lenh, S_truc_tiep, sigma_ls, date.today(), r))
        ngay_tinh, truc_tiep = date.today(), True
        nguon = (
            f"bảng giá Vietcap lúc {datetime.now():%H:%M %d/%m/%Y} "
            f"({'trạng thái cuối phiên gần nhất' if khop.get('session') == 'ENDED' else 'trong phiên'})"
        )
    # P = giá mua (chào bán thấp nhất): giá người mua phải trả, dùng cho mọi chỉ số bên dưới
    S, K, ty_le, P = float(h["Giá CS"]), float(h["Giá thực hiện"]), float(h["Tỷ lệ CĐ"]), float(h["Giá mua"])
    P_khop, nguon_gia, ngay_con_lai = float(h["Giá CW"]), h["Nguồn giá mua"], int(h["Ngày còn lại"])
    T, tang = ngay_con_lai / C.NGAY_MOT_NAM, float(h["CS tăng % để hòa vốn"])
    ngay_dao_han = ngay_tinh + timedelta(days=ngay_con_lai)
    iv = cw_scanner.bien_dong_ngam_dinh(P, S, K, T, r, ty_le)
    toi_thieu = cw_scanner.can_duoi(S, K, T, r)  # giá tối thiểu của quyền trên 1 cổ phiếu theo mô hình
    tv_cung_ma, canh_bao_iv = cw_scanner.so_iv_cung_ma(
        df, ma, cs, iv * 100 if iv else math.nan
    )  # IV so với CW khác cùng mã CS
    # IV − HV (điểm %): ưu tiên số trong CSV để khớp với kết luận lúc quét; file cũ chưa có cột này thì tính lại
    iv_hv = float(h["IV − HV"]) if math.isfinite(h["IV − HV"]) else ((iv - sigma_ls) * 100 if iv else math.nan)
    mo_ta_gia = (
        f"giá chào bán thấp nhất; giá khớp gần nhất {so(P_khop)} đ"
        if nguon_gia == "ask"
        else f"sổ lệnh trống nên dùng giá {nguon_gia}"
    )
    noi_tai = max(S - K, 0) / ty_le  # phần lãi nếu đáo hạn ngay hôm nay
    gia_tri_tg = P - noi_tai  # phần sẽ mất dần về 0 đến ngày đáo hạn
    if iv:  # mất giá theo thời gian tính theo mức biến động thị trường đang dùng
        mat_gia = (
            cw_scanner.black_scholes_call(S, K, T, r, iv)[0]
            - cw_scanner.black_scholes_call(S, K, T - 1 / C.NGAY_MOT_NAM, r, iv)[0]
        ) / ty_le
    else:  # không giải được: chia đều phần giá trị thời gian còn lại cho số ngày
        mat_gia = max(gia_tri_tg, 0) / max(ngay_con_lai, 1)
    chu_dat_re, lop_dat_re = dat_re(h["Đắt/rẻ %"])

    # mô tả mã + nguồn số liệu: đặt dưới Tóm tắt (người dùng chọn 30/10/2026)
    dong_nguon = f"Định giá theo {nguon}. σ lịch sử và lãi suất lấy từ lần quét ngày {ngay:%d/%m/%Y}."
    m_thong_tin = (
        f'<section class="the"><p class="phu" style="margin:0">Chứng quyền mua <b>{ESC(cs)}</b> · TCPH {ESC(h["TCPH"])}'
        f" · đáo hạn {ngay_dao_han:%d/%m/%Y} (còn {ngay_con_lai} ngày)</p>"
        + (f'<p class="phu" style="margin:6px 0 0">{dong_nguon}</p>' if truc_tiep else "")
        + "</section>"
    )
    phan = [
        f'<div class="dau-trang"><div><h1>{ESC(ma)}</h1>'
        + (
            "" if truc_tiep else f"<p class=loi role=alert>{dong_nguon}</p>"
        )  # lỗi giá trực tiếp: giữ ở đầu trang cho dễ thấy
        + "</div>"
        f'<div>{huy_hieu(h["Đánh giá"], True)}'
        + (
            f'<p class="phu">Lúc quét {ngay:%d/%m}: {ESC(KET_LUAN.get(ket_luan_quet, ("", "", ket_luan_quet))[2])}</p>'
            if h["Đánh giá"] != ket_luan_quet
            else ""
        )
        + "</div></div>"
    ]

    # Tóm tắt + 4 tiêu chí
    if math.isfinite(iv_hv):
        dat_iv, noi_dung_iv = (
            iv_hv <= C.MAX_IV_TRU_HV * 100,
            f"IV − HV = {so(iv_hv, 1, True)} điểm ({chu_dat_re} so với giá hợp lý)",
        )
    elif (
        P * ty_le < toi_thieu
    ):  # không giải được IV vì giá quá thấp: rẻ hơn mọi mức dao động -> đạt (kèm cảnh báo ở trên)
        dat_iv, noi_dung_iv = True, "Giá mua dưới mức tối thiểu của mô hình, rẻ hơn mọi mức dao động (xem lưu ý ở trên)"
    else:
        dat_iv, noi_dung_iv = False, "Giá mua cao bất thường, không giải được IV"
    tieu_chi = [
        (
            ngay_con_lai >= C.MIN_NGAY_CON_LAI,
            f"Còn {ngay_con_lai} ngày đến đáo hạn",
            f"cần ≥ {C.MIN_NGAY_CON_LAI} ngày",
        ),
        (dat_iv, noi_dung_iv, f"cần IV − HV ≤ {so(C.MAX_IV_TRU_HV * 100, 0, True)} điểm"),
        (
            tang <= C.MAX_TANG_DE_HOA_VON * 100,
            f"{ESC(cs)} cần tăng {so(tang, 1, True)}% để hòa vốn",
            f"cần ≤ {C.MAX_TANG_DE_HOA_VON:.0%}",
        ),
        (
            int(h["KL khớp"]) >= C.MIN_KHOI_LUONG,
            f"Khớp {so(h['KL khớp'])} CW trong phiên",
            f"cần ≥ {so(C.MIN_KHOI_LUONG)}",
        ),
    ]
    dong_tc = "".join(
        f'<li><b class="{"duong" if dat else "am"}" aria-label="{"Đạt" if dat else "Không đạt"}">{"✓" if dat else "✕"}</b>'
        f"<span>{noi_dung} <small>({yeu_cau})</small></span></li>"
        for dat, noi_dung, yeu_cau in tieu_chi
    )
    # hòa vốn đã gồm phí mua, thuế khi nhận tiền (rui_ro_theo_tien)
    rr = C.rui_ro_theo_tien(von * 1_000_000, P, S, K, ty_le, T, r, sigma_ls, float(h["Đòn bẩy"]))
    gd_cuoi = date.fromisoformat(h["Ngày GD cuối"]) if h.get("Ngày GD cuối") else None
    phi_chu, thue_chu = so(C.PHI_GIAO_DICH * 100, 2), so(C.THUE_BAN * 100, 1)
    hoa_von_phi = rr["hoa_von_phi"]
    m_tom_tat = (
        f'<section class="the"><h2>Tóm tắt</h2><p class="tom-tat">Bạn trả <b>{so(P)} đ</b> cho 1 CW ({mo_ta_gia}; mô hình tính giá hợp lý là {so(h["Giá hợp lý"])} đ). '
        f"Nếu giữ đến ngày {ngay_dao_han:%d/%m/%Y}, giá {ESC(cs)} cần cao hơn <b>{so(hoa_von_phi)} đ</b> ({so((hoa_von_phi / S - 1) * 100, 1, True)}% so với hiện tại {so(S)} đ, đã trừ phí, thuế) thì mới có lãi. "
        f"Trong {so(P)} đ có {so(noi_tai)} đ <b>giá trị nội tại</b> (phần lãi nếu đáo hạn ngay hôm nay) và {so(gia_tri_tg)} đ <b>giá trị thời gian</b> "
        f"(mất dần về 0 đến ngày đáo hạn, khoảng {so(mat_gia, 1 if mat_gia < 10 else 0)} đ/ngày nếu giá {ESC(cs)} đứng yên).</p>"
        + (
            f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ Bất thường:</b> giá CW đang thấp hơn cả giá trị nội tại. Có thể do sắp điều chỉnh '
            f'điều khoản (cổ tức, chia tách…) hoặc thanh khoản kém. Hãy đọc thông báo mới nhất của {ESC(h["TCPH"])} về mã này trước khi mua.</p>'
            if gia_tri_tg < 0
            else (
                f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ Lưu ý:</b> giá mua × tỷ lệ = {so(P * ty_le)} đ, thấp hơn mức tối thiểu theo mô hình '
                f"S − K × e<sup>−rT</sup> = {so(toi_thieu)} đ (lãi suất giả định {so(r * 100, 1)}%). Không có mức dao động nào cho ra giá này, nên chữ "
                f"“{chu_dat_re}” chủ yếu đến từ giả định (lãi suất, mức dao động 1 năm qua), không chắc là món hời. "
                f'Hãy so với các CW khác của {ESC(cs)} và đọc thông báo của {ESC(h["TCPH"])} trước khi mua.</p>'
                if P * ty_le < toi_thieu
                else ""
            )
        )
        + (
            f'<p class="ghi-chu-canh-bao" role="note"><b>⚠ IV bất thường:</b> {ESC(canh_bao_iv)}.</p>'
            if canh_bao_iv
            else ""
        )
        + f'<ul class="tieu-chi">{dong_tc}</ul>'
        '<p class="phu">Chưa hiểu các con số? Xem <a href="/huong-dan#trang-phan-tich">cách đọc trang phân tích</a> và '
        '<a href="/huong-dan#truoc-khi-mua">5 câu tự hỏi trước khi mua</a>.</p></section>'
    )
    m_nen = W.muc_nen(ma, cs, P_khop, S, *((bang_gia[ma], bang_gia[cs]) if truc_tiep else (None, None)))

    # Các chỉ số chính
    delta = C.black_scholes_call(S, K, T, r, sigma_ls)[
        1
    ]  # N(d1): giá trị quyền trên 1 cổ phiếu tăng bao nhiêu khi cổ phiếu tăng 1 đ
    so_sanh_bd = (
        (
            f"IV − HV = {so(iv_hv, 1, True)} điểm → thị trường đang định giá CW "
            + ("rẻ hơn" if iv_hv < 0 else "đắt hơn")
            + " mức dao động 1 năm qua."
        )
        if math.isfinite(iv_hv)
        else (
            f"Không giải được: giá mua dưới mức tối thiểu S − K × e^(−rT) (lãi suất giả định {so(r * 100, 1)}%)."
            if P * ty_le < toi_thieu
            else "Không giải được: giá mua cao bất thường so với mô hình."
        )
    )
    m_o_so = (
        '<div class="luoi-o">'
        + o_so(
            "Giá mua / giá hợp lý",
            f"{so(P)} / {so(h['Giá hợp lý'])}",
            "giá chào bán thấp nhất / giá Black-Scholes với HV 1 năm",
        )
        + o_so("So với giá hợp lý", f'<span class="{lop_dat_re}">{chu_dat_re}</span>', "Rẻ = giá mua thấp hơn mô hình")
        + o_so(
            "Hòa vốn (đã trừ phí, thuế)",
            f"{so(hoa_von_phi)} đ",
            f'{ESC(cs)} cần <b class="am">{so((hoa_von_phi / S - 1) * 100, 1, True)}%</b> đến ngày đáo hạn. '
            f"Phí {phi_chu}% + thuế {thue_chu}% là giả định - kiểm tra với công ty chứng khoán của bạn",
        )
        + o_so(
            "Đòn bẩy", f"{so(h['Đòn bẩy'], 1)}x", f"{ESC(cs)} tăng/giảm 1% → CW tăng/giảm khoảng {so(h['Đòn bẩy'], 1)}%"
        )
        + o_so(
            "Delta", so(delta, 2), f"{ESC(cs)} tăng/giảm 1.000 đ → 1 CW tăng/giảm khoảng {so(delta / ty_le * 1000)} đ"
        )
        + o_so(
            "Biến động ngầm định (IV)",
            f"{so(iv * 100, 0)}%" if iv else "—",
            f"Lịch sử 1 năm (HV): {so(sigma_ls * 100, 0)}%. {so_sanh_bd}"
            + (f" Trung vị IV các CW {ESC(cs)} khác: {so(tv_cung_ma, 0)}%." if math.isfinite(tv_cung_ma) else ""),
        )
        + o_so(
            "Ngày giao dịch cuối",
            f"{gd_cuoi:%d/%m/%Y}" if gd_cuoi else "Không rõ",
            (
                f"còn {(gd_cuoi - ngay_tinh).days} ngày để bán; sau đó chỉ chờ nhận tiền theo giá trung bình 5 phiên trước "
                f"ngày đáo hạn {ngay_dao_han:%d/%m/%Y}"
                if gd_cuoi
                else "bấm 🔄 Quét để lấy ngày này"
            ),
        )
        + o_so(
            "Khối lượng phát hành", f"{so(float(h['KL niêm yết']))} CW", "tổng số CW được niêm yết (được phép bán ra)"
        )
        + "</div>"
    )

    # Giá CS đã điều chỉnh quyền lúc quét (dùng cho IV theo thời gian, độ lệch so với CS)
    file_ls = C.THU_MUC_KET_QUA / f"lich_su_{ngay}.json"
    lich_su = json.loads(file_ls.read_text(encoding="utf-8")).get(cs) if file_ls.exists() else None

    # IV theo thời gian: giá CW từ vnstock (1 lượt gọi, nhớ trong ngày) + giá CS đã điều chỉnh quyền trong file lịch sử lúc quét
    bo_nho, loi_iv = BO_NHO_IV.get((ma, date.today())), ""
    if bo_nho is None and lich_su:
        try:
            gia_cw, kl_cw = C.lich_su_cw(ma, P_khop, C.NGAY_MOT_NAM)
            # phiên khớp lẻ: giá đóng cửa không mua được -> IV ngày đó giả, bỏ (như lech_20_phien)
            gia_du = {d: g for d, g in gia_cw.items() if g * kl_cw[d] >= C.GIA_TRI_KHOP_TOI_THIEU}
            bo_nho = BO_NHO_IV[(ma, date.today())] = {
                "iv": C.lich_su_iv(gia_du, dict(lich_su), K, ty_le, ngay_dao_han, r),
                "gia": gia_cw,
                "kl": kl_cw,
            }
        # lỗi mạng / hết lượt gọi: chỉ mục này không có biểu đồ, phần còn lại của trang vẫn dùng được
        except Exception as e:  # noqa: BLE001
            loi_iv = f"Chưa tải được lịch sử giá {ESC(ma)} ({ESC(str(e)[:120])}). Mở lại trang sau ít phút."
    iv_ls = bo_nho["iv"] if bo_nho else None
    duong_ke_iv = [("HV 1 năm", sigma_ls * 100, "tc-thuc-hien")] + (
        [("Trung vị cùng mã", tv_cung_ma, "tc-hoa-von")] if math.isfinite(tv_cung_ma) else []
    )
    m_iv = (
        f'<section class="the"><h2>IV của {ESC(ma)} theo thời gian</h2>'
        f'<p class="phu">Mức dao động mà giá CW "giả định" mỗi ngày, so với dao động thật 1 năm qua (HV) và trung vị IV các CW {ESC(cs)} khác '
        f"hôm nay. IV thường cao lúc mới phát hành rồi giảm dần; đáng chú ý khi IV xuống thấp hẳn dưới HV và trung vị cùng mã (tổ chức phát hành "
        f"đang bán ra rẻ, giá có thể còn thấp nữa trước khi đáo hạn). Điểm ở 0% = giá dưới "
        f"mức tối thiểu của mô hình. Tính bằng điều khoản hiện tại, giá {ESC(cs)} đã điều chỉnh quyền và lãi suất {so(r * 100, 1)}%.</p>"
        + (
            bieu_do(iv_ls, duong_ke_iv, f"IV của {ma}", "%", "IV (%)")
            if iv_ls and len(iv_ls) >= 2
            else f'<p>{loi_iv or "Chưa đủ dữ liệu để vẽ (cần ít nhất 2 ngày có giá CW và giá cổ phiếu cơ sở)."}</p>'
        )
        + "</section>"
    )

    # Lệch so với cổ phiếu cơ sở 20 phiên (mốc = phiên đầu tiên đủ thanh khoản)
    moc, hang_lech = (
        C.lech_20_phien(bo_nho["gia"], bo_nho["kl"], dict(lich_su), K, ty_le, ngay_dao_han, r) if bo_nho else (None, [])
    )
    lech_ls = [[d, round(lech * 100, 1)] for d, *_, lech in hang_lech]
    # lệch chỉ đến từ IV đổi (giá lẽ ra giữ IV mốc): hiện IV 2 đầu để thấy ngay lệch sâu là do TCPH hạ IV một lần hay đang lệch
    # (CHPG2637 02/11/2026: −63% vì IV 54% ngày mốc 06/10 bị hạ còn 30% ngày 16–19/10, từ đó CW chạy sát HPG)
    iv_ngay = dict(iv_ls or [])
    iv_moc, iv_cuoi = (iv_ngay.get(moc), iv_ngay.get(hang_lech[-1][0])) if hang_lech else (None, None)
    dong_iv = (  # ghi chú ngắn (≤ GIAI_THICH_TOI_THIEU ký tự) để luôn hiện, không bị thu vào "ℹ Giải thích"
        f'<p class="phu"><b>IV ngày mốc {so(iv_moc, 0)}% → phiên {hang_lech[-1][0][8:]}/{hang_lech[-1][0][5:7]} '
        f"{so(iv_cuoi, 0)}%</b>: lệch chỉ đến từ IV đổi.</p>"
        if iv_moc and iv_cuoi
        else ""
    )
    nguong_lech = danh_muc.CANH_BAO_LECH * 100
    mau_bang = hang_lech[:: max(len(hang_lech) // 4, 1)][:4] + hang_lech[-1:] if hang_lech else []
    m_theo_kip = (
        f'<section class="the"><h2>{ESC(ma)} có theo kịp {ESC(cs)} không?</h2>'
        f'<p class="phu">Lệch = giá CW thực tế so với giá "lẽ ra" nếu CW giữ nguyên mức IV của ngày mốc và chỉ chạy theo giá {ESC(cs)} '
        f"(đã gồm đòn bẩy và mất giá theo thời gian). Âm: CW không theo kịp cổ phiếu; dương: CW chạy nhanh hơn, dễ bị kéo về. "
        f"Trong khoảng ±{so(nguong_lech, 0)}% là bình thường. Mốc: "
        + (
            f"{moc[8:]}/{moc[5:7]}/{moc[:4]} (phiên đầu tiên trong 20 phiên gần nhất khớp ≥ {so(C.MIN_KHOI_LUONG)} CW)."
            if moc
            else "—."
        )
        + " IV hạ một lần rồi đứng yên (đường lệch đi ngang) là tổ chức phát hành đã hạ giá chào bán: CW vẫn chạy theo "
        f"{ESC(cs)} từ đó, số lệch giữ nguyên tới khi mốc trôi qua ngày hạ.</p>"
        + dong_iv
        + (
            bieu_do(
                lech_ls,
                [
                    (f"−{so(nguong_lech, 0)}%", -nguong_lech, "tc-hoa-von"),
                    ("0%", 0, "tc-thuc-hien"),
                    (f"+{so(nguong_lech, 0)}%", nguong_lech, "tc-hoa-von"),
                ],
                f"Lệch của {ma}",
                "%",
                "Lệch (%)",
            )
            + '<details style="margin-top:8px"><summary>Xem bảng CW thực tế so với lẽ ra</summary>'
            '<div class="cuon"><table style="max-width:640px"><thead><tr><th>Ngày</th>'
            f'<th class="so">{ESC(cs)}</th><th class="so">CW thực tế</th><th class="so">CW lẽ ra</th><th class="so">Lệch</th></tr></thead><tbody>'
            + "".join(
                f'<tr><td>{d[8:]}/{d[5:7]}</td><td class="so">{so(a * 100, 1, True)}%</td><td class="so">{so(b * 100, 1, True)}%</td>'
                f'<td class="so">{so(c * 100, 1, True)}%</td><td class="so {"am" if e <= -danh_muc.CANH_BAO_LECH else ""}">'
                f"<b>{so(e * 100, 1, True)}%</b></td></tr>"
                for d, a, b, c, e in mau_bang
            )
            + "</tbody></table></div></details>"
            if len(lech_ls) >= 2
            else f'<p>{loi_iv or "Chưa đủ dữ liệu (cần ít nhất 2 phiên có giao dịch đủ thanh khoản)."}</p>'
        )
        + "</section>"
    )

    # Kịch bản lãi/lỗ khi đáo hạn
    gia_von = P * (1 + C.PHI_GIAO_DICH)  # giá vốn 1 CW đã gồm phí mua
    dong = []
    for thay_doi in (-20, -10, -5, 0, 5, 10, 15, 20, 30):
        gia_cs = S * (1 + thay_doi / 100)
        nhan_ve = C.tien_dao_han(
            gia_cs, K, ty_le
        )  # sau thuế 0,1% trên giá trị danh nghĩa CS: Nhận về − giá vốn = Lãi/lỗ
        lai = nhan_ve - gia_von
        lop = "duong" if lai > 0 else ("am" if lai < 0 else "")
        dong.append(
            f'<tr{" class=hang-goc" if thay_doi == 0 else ""}><td>{"Giữ nguyên" if thay_doi == 0 else f"{thay_doi:+d}%"}</td>'
            f'<td class="so">{so(gia_cs)}</td><td class="so">{so(nhan_ve)}</td><td class="so {lop}">{so(lai, 0, True)}</td>'
            f'<td class="so {lop}">{so(lai / gia_von * 100, 0, True)}%</td></tr>'
        )
    m_neu_giu = (
        f'<section class="the"><h2>Nếu giữ đến ngày đáo hạn ({ngay_dao_han:%d/%m/%Y})</h2>'
        f'<p class="phu">Lãi/lỗ theo giá {ESC(cs)} lúc đáo hạn (giá thanh toán thực tế là trung bình 5 phiên trước đáo hạn). '
        f"Đã trừ phí mua {phi_chu}% và thuế {thue_chu}% khi nhận tiền (thuế tính trên giá trị cổ phiếu, không trên tiền nhận về). "
        "Lỗ tối đa gần bằng toàn bộ tiền mua CW; nếu giá thanh toán chỉ nhỉnh hơn giá thực hiện vài chục đồng thì thuế có thể "
        f'lớn hơn tiền nhận, lỗ nhỉnh hơn một chút.</p><div class="cuon"><table><thead><tr><th>{ESC(cs)} thay đổi</th><th class="so">Giá {ESC(cs)} (đ)</th>'
        f'<th class="so">Nhận về / CW sau thuế (đ)</th><th class="so">Lãi/lỗ / CW (đ)</th><th class="so">Lãi/lỗ</th>'
        f'</tr></thead><tbody>{"".join(dong)}</tbody></table></div></section>'
    )

    # So sánh các CW cùng mã cơ sở
    cung_cs = df[df["Mã CS"] == cs].sort_values("IV − HV", na_position="last")
    m_cw_khac = (
        f'<section class="the"><h2>Các CW khác của {ESC(cs)} ({len(cung_cs)})</h2>'
        f'<p class="phu">Cùng một cổ phiếu cơ sở nhưng khác TCPH, giá thực hiện và thời hạn. Xếp theo IV − HV (thấp nhất = rẻ nhất trước); dòng tô nền là CW đang xem.</p>'
        f'<div class="cuon">{bang(cung_cs, ma)}</div></section>'
    )

    # Điều khoản
    dk = [
        ("Mã cổ phiếu cơ sở", ESC(cs)),
        ("Tổ chức phát hành", ESC(h["TCPH"])),
        ("Giá thực hiện", f"{so(K)} đ"),
        ("Tỷ lệ chuyển đổi", f"{so(ty_le, 4)} CW : 1 cổ phiếu"),
        ("Ngày đáo hạn", f"{ngay_dao_han:%d/%m/%Y}"),
        ("Giá cổ phiếu cơ sở", f"{so(S)} đ"),
        ("Giá mua lúc quét", f"{so(P)} đ (giá {nguon_gia})"),
        ("Giá khớp gần nhất", f"{so(P_khop)} đ"),
        ("Khối lượng khớp", f"{so(h['KL khớp'])} CW"),
        ("Biến động lịch sử 1 năm", f"{so(sigma_ls * 100, 1)}%"),
        ("Lãi suất phi rủi ro (giả định)", f"{so(r * 100, 1)}%"),
    ]
    m_dieu_khoan = (
        '<section class="the"><h2>Điều khoản &amp; số liệu</h2><dl class="dieu-khoan">'
        + "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in dk)
        + "</dl></section>"
    )
    # bố cục (người dùng chọn 30/10/2026): số liệu chính -> tóm tắt + lãi/lỗ nếu giữ đến đáo hạn -> thị trường lúc này
    # -> CW so với CS | IV -> tham khảo. Hàng đôi: 2 mục cạnh nhau, màn hình < 1.100 px xếp 1 cột
    phan += [
        m_o_so,
        hang_doi(f'<div class="cot-doc">{m_tom_tat}{m_thong_tin}</div>', m_neu_giu),
        m_nen,
        hang_doi(m_theo_kip, m_iv),
        m_cw_khac,
        m_dieu_khoan,
    ]
    return trang(f"{ma} – phân tích chứng quyền", "".join(phan), "/")  # thuộc tab Chứng quyền (nút 🔄 Quét)


# ============ TRANG CW SẮP RA MẮT ============
def trang_sap_ra_mat(tai_moi=False):
    """CW đã được HOSE chấp thuận niêm yết nhưng chưa giao dịch, kèm giá hợp lý dự kiến để so sánh khi lên sàn."""
    C = cw_scanner
    df, ngay = W.doc_ket_qua()
    phan = [
        (
            '<div class="dau-trang"><div><h1>Chứng quyền sắp ra mắt</h1><p class="phu">Các CW đã được HOSE chấp thuận niêm yết '
            "nhưng <b>chưa giao dịch</b>. Mã CW (ví dụ CVPB26xx) sẽ có khi lên sàn.</p></div></div>"
        )
    ]
    luu = sorted(C.THU_MUC_KET_QUA.glob("sap_ra_mat_*.json"))
    tai_lai = ' · <a href="/sap-ra-mat?tai_moi=1">tải lại trực tiếp từ HOSE</a> (có thể mất 10-40 giây)'
    try:
        # đã quét hôm nay thì dùng ngay danh sách vừa lưu (máy chủ HOSE thường chậm); muốn mới nhất thì bấm "tải lại"
        if luu and luu[-1].stem[11:] == str(date.today()) and not tai_moi:
            ds, nguon = (
                C.doc_cw_sap_ra_mat(json.loads(luu[-1].read_text(encoding="utf-8"))),
                "hsx.vn, danh sách lưu lúc quét hôm nay" + tai_lai,
            )
        else:
            ds, nguon = (
                C.doc_cw_sap_ra_mat(C.tai_du_lieu_hose_cw(cho=12)),
                "hsx.vn (Niêm yết mới → DS CW được chấp thuận chính thức), tải trực tiếp lúc mở trang",
            )
    # ranh giới gọi vnstock/mạng: lỗi được báo ra (nhật ký hoặc trên trang), không nuốt
    except Exception as e:  # noqa: BLE001
        if not luu:
            phan.append(
                f'<p class="loi" role="alert">Không tải được danh sách từ HOSE ({ESC(str(e))}). Máy chủ HOSE có thể đang chậm, '
                "hãy tải lại trang sau ít phút hoặc bấm 🔄 Quét ở trang chính.</p>"
            )
            return trang("CW sắp ra mắt", "".join(phan), "/sap-ra-mat")
        ds = C.doc_cw_sap_ra_mat(json.loads(luu[-1].read_text(encoding="utf-8")))
        nguon = (
            f"không tải được trực tiếp từ HOSE ({ESC(str(e))}), dùng danh sách lưu lúc quét ngày {date.fromisoformat(luu[-1].stem[11:]):%d/%m/%Y}"
            + tai_lai
        )

    # Bỏ mã đã hết hạn và mã đã lên sàn (cùng mã CS + giá thực hiện + ngày đáo hạn với một CW trong lần quét gần nhất)
    hom_nay, co_so, dang_gd = date.today(), {}, set()
    if df is not None:
        dang_gd = {
            (h["Mã CS"], round(h["Giá thực hiện"]), ngay + timedelta(days=int(h["Ngày còn lại"])))
            for _, h in df.iterrows()
        }
        co_so = df.groupby("Mã CS")[["Giá CS", "Biến động %/năm"]].first().to_dict("index")
    sap = sorted(
        (
            x
            for x in ds
            if x["ngay_dao_han"]
            and x["ngay_dao_han"] > hom_nay
            and (x["ma_cs"], round(x["gia_thuc_hien"] or 0), x["ngay_dao_han"]) not in dang_gd
        ),
        key=lambda x: (x["ngay_chap_thuan"] or date.min, x["ten"]),
        reverse=True,
    )

    dv = lambda v: (
        v if isinstance(v, (int, float)) and math.isfinite(v) else -1
    )  # giá trị để sắp xếp; thiếu số liệu xếp cuối
    dong = []
    for x in sap:
        K, cs, con = x["gia_thuc_hien"], co_so.get(x["ma_cs"]), (x["ngay_dao_han"] - hom_nay).days
        ngay_ct = f'{x["ngay_chap_thuan"]:%d/%m/%Y}' if x["ngay_chap_thuan"] else "—"
        S = cs["Giá CS"] if cs else math.nan
        try:  # giá hợp lý dự kiến nếu CW lên sàn hôm nay, dùng giá & mức dao động của cổ phiếu cơ sở ở lần quét gần nhất
            gia_hl = C.black_scholes_call(
                S, K, con / C.NGAY_MOT_NAM, C.LAI_SUAT_PHI_RUI_RO, cs["Biến động %/năm"] / 100
            )[0] / C.doc_ty_le(x["ty_le"])
        except (TypeError, ValueError, ZeroDivisionError):  # thiếu giá CS / giá thực hiện / tỷ lệ từ HOSE -> hiện "—"
            gia_hl = math.nan
        lech = (K / S - 1) * 100 if K and not math.isnan(S) else math.nan
        dong.append(
            f'<tr><td data-v="{x["ngay_chap_thuan"] or ""}">{ngay_ct}</td><td>{ESC(x["ten"].replace("Chứng quyền ", ""))}</td>'
            f'<td class="so" data-v="{dv(gia_hl)}"><b>{so(gia_hl)}</b></td>'
            f'<td class="so" data-v="{dv(S)}">{so(S)}</td><td class="so" data-v="{dv(K)}">{so(K or math.nan)}</td>'
            f'<td class="so" data-v="{dv(lech)}">{so(lech, 1, True)}%</td><td class="so">{ESC(x["ty_le"])}</td>'
            f'<td data-v="{x["ngay_dao_han"]}">{x["ngay_dao_han"]:%d/%m/%Y}</td><td class="so" data-v="{con}">{so(con)}</td>'
            f'<td class="so" data-v="{dv(x["kl_niem_yet"])}">{so(x["kl_niem_yet"] or math.nan)}</td></tr>'
        )
    cot = [
        ("Ngày chấp thuận", ""),
        ("Chứng quyền", ""),
        ("Giá hợp lý dự kiến", "so"),
        ("Giá CS", "so"),
        ("Giá thực hiện", "so"),
        ("So với giá CS", "so"),
        ("Tỷ lệ CĐ", "so"),
        ("Đáo hạn", ""),
        ("Còn (ngày)", "so"),
        ("KL niêm yết", "so"),
    ]
    dau = "".join(
        f'<th class="{lop}"><button type="button" title="Bấm để sắp xếp">{ten}</button></th>' for ten, lop in cot
    )
    phan.append(
        f'<section class="the"><h2>{len(sap)} CW đang chờ lên sàn</h2>'
        + (
            f'<div class="cuon"><table><thead><tr>{dau}</tr></thead><tbody>{"".join(dong)}</tbody></table></div>'
            if sap
            else "<p>Hiện không có CW nào đang chờ lên sàn.</p>"
        )
        + f'<p class="phu">Nguồn: {nguon}.</p></section>'
        '<section class="the"><h2>Đọc bảng này thế nào?</h2><ul>'
        '<li><b>Chứng quyền</b>: tên đầy đủ theo HOSE, dạng <i>Mã CS / Tổ chức phát hành / thời hạn / số thứ tự</i>. Ví dụ "VPB/MSVN/7M/0226" là CW của VPB do MSVN phát hành, thời hạn 7 tháng.</li>'
        "<li><b>So với giá CS</b>: giá thực hiện so với giá cổ phiếu hiện tại. Số dương = giá thực hiện cao hơn (cổ phiếu phải tăng thêm chừng đó mới có giá trị nội tại).</li>"
        "<li><b>Giá hợp lý dự kiến</b> (đồng/CW): tính bằng Black-Scholes như các CW đang giao dịch, dùng giá và mức dao động của cổ phiếu cơ sở ở lần quét gần nhất"
        f'{f" (ngày {ngay:%d/%m/%Y})" if ngay else ""}. Khi CW lên sàn, so giá giao dịch với con số này: <b>thấp hơn là rẻ</b>, cao hơn là đắt.</li>'
        '<li>Mã nào chưa có giá cổ phiếu cơ sở trong lần quét gần nhất thì giá hợp lý hiện "—".</li>'
        '<li>Khi CW đã lên sàn, nó sẽ tự biến mất khỏi trang này và xuất hiện trong <a href="/">danh sách chính</a> (được đánh dấu <span class="chip">Mới</span>).</li>'
        "</ul></section>"
    )
    return trang("CW sắp ra mắt", "".join(phan), "/sap-ra-mat")
