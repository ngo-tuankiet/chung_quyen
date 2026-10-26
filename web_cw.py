"""Trang chứng quyền: danh sách (trang chính), phân tích chi tiết từng CW, CW sắp ra mắt."""

import json
import math
from datetime import date, datetime, timedelta

import cw_scanner
import danh_muc
import web_chung as W  # doc_ket_qua và trạng thái LOI/NHAT_KY/LOI_DANH_MUC đọc qua module: test patch được, handler gán được
from web_chung import BO_NHO_IV, ESC, KET_LUAN, VON_MAC_DINH, bang, bieu_do, dat_re, huy_hieu, o_so, so, trang


# ============ TRANG CHÍNH ============
def trang_chinh():
    df, ngay = W.doc_ket_qua()
    co_key = bool(cw_scanner.doc_env().get("VNSTOCK_API_KEY"))
    phan = [
        (
            '<div class="dau-trang"><div><h1>Quét chứng quyền</h1>'
            f'<p class="phu">{f"Dữ liệu ngày {ngay:%d/%m/%Y} · {len(df)} CW · định giá bằng Black-Scholes" if ngay else "Chưa có dữ liệu"}'
            f' · API key vnstock: {"đã nhập ✓" if co_key else "<b>chưa nhập</b> (mở file .env để điền)"}</p></div>'
            '<form method="post" action="/quet" onsubmit="this.nut.disabled = true; this.nut.textContent = \'Đang quét... (1-3 phút)\';">'
            '<button class="nut" name="nut">Quét ngay</button></form></div>'
        )
    ]
    if W.LOI:
        phan.append(f'<p class="loi" role="alert">{ESC(W.LOI)}</p>')
    if W.NHAT_KY:  # tự mở nhật ký nếu có cảnh báo [!]
        phan.append(
            f'<details class="the"{" open" if "[!]" in W.NHAT_KY else ""}><summary>Nhật ký lần quét gần nhất</summary><pre>{ESC(W.NHAT_KY)}</pre></details>'
        )
    if df is None:
        phan.append(
            '<div class="the"><h2>Chưa có kết quả</h2><p>Lần đầu dùng? Làm theo 3 bước:</p><ol>'
            "<li>Bấm nút <b>Quét ngay</b> ở góc trên bên phải và chờ 1-3 phút.</li>"
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
    if len(moi):
        phan.append(
            f'<section class="the"><h2>CW mới phát hành ({len(moi)})</h2><div class="cuon">{bang(moi)}</div></section>'
        )
    phan.append(
        f'<section class="the"><h2>Nên xem xét ({len(tot)})</h2><p class="phu">Đạt cả 4 tiêu chí, xếp theo IV − HV (thấp nhất trước = rẻ nhất so với mức dao động 1 năm qua).</p>'
        + (f'<div class="cuon">{bang(tot)}</div>' if len(tot) else "<p>Hôm nay không có CW nào đạt cả 4 tiêu chí.</p>")
        + "</section>"
    )
    phan.append(
        f'<section class="the"><h2>Tất cả {len(df)} CW</h2>'
        '<input type="search" data-loc="#bang-tat-ca" placeholder="Tìm theo mã CW, mã cổ phiếu hoặc TCPH (vd: VPB, SSI)" aria-label="Tìm chứng quyền">'
        f'<div class="cuon cao">{bang(df, id_bang="bang-tat-ca")}</div></section>'
    )
    return trang("Quét chứng quyền", "".join(phan), "/")


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
    T, hoa_von, tang = ngay_con_lai / 365, K + P * ty_le, float(h["CS tăng % để hòa vốn"])
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
            - cw_scanner.black_scholes_call(S, K, T - 1 / 365, r, iv)[0]
        ) / ty_le
    else:  # không giải được: chia đều phần giá trị thời gian còn lại cho số ngày
        mat_gia = max(gia_tri_tg, 0) / max(ngay_con_lai, 1)
    chu_dat_re, lop_dat_re = dat_re(h["Đắt/rẻ %"])

    phan = [
        f'<div class="dau-trang"><div><h1>{ESC(ma)}</h1><p class="phu">Chứng quyền mua <b>{ESC(cs)}</b> · TCPH {ESC(h["TCPH"])}'
        f" · đáo hạn {ngay_dao_han:%d/%m/%Y} (còn {ngay_con_lai} ngày)</p>"
        f'<p class="{"phu" if truc_tiep else "loi"}"{"" if truc_tiep else " role=alert"}>Định giá theo {nguon}. '
        f"σ lịch sử và lãi suất lấy từ lần quét ngày {ngay:%d/%m/%Y}.</p></div>"
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
    phan.append(
        f'<section class="the"><h2>Tóm tắt</h2><p class="tom-tat">Bạn trả <b>{so(P)} đ</b> cho 1 CW ({mo_ta_gia}; mô hình tính giá hợp lý là {so(h["Giá hợp lý"])} đ). '
        f"Nếu giữ đến ngày {ngay_dao_han:%d/%m/%Y}, giá {ESC(cs)} cần cao hơn <b>{so(hoa_von)} đ</b> ({so(tang, 1, True)}% so với hiện tại {so(S)} đ) thì mới có lãi. "
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

    # Rủi ro với số tiền của bạn (đã tính phí mua, thuế khi nhận tiền; con số "xác suất" là của mô hình, không phải dự báo)
    rr = C.rui_ro_theo_tien(von * 1_000_000, P, S, K, ty_le, T, r, sigma_ls, float(h["Đòn bẩy"]))
    gd_cuoi = date.fromisoformat(h["Ngày GD cuối"]) if h.get("Ngày GD cuối") else None
    phi_chu, thue_chu = so(C.PHI_GIAO_DICH * 100, 2), so(C.THUE_BAN * 100, 1)
    phan.append(
        f'<section class="the" id="rui-ro"><h2>Rủi ro với số tiền của bạn</h2>'
        f'<form method="get" action="/cw/{ESC(ma)}#rui-ro" style="margin-top:8px"><label>Số tiền định đầu tư '
        f'<input type="number" name="von" min="1" max="10000" step="1" value="{von}" style="width:7em"> triệu đồng</label> '
        '<button class="nut" style="padding:6px 14px">Tính lại</button></form><div class="luoi-o">'
        + o_so(
            "Mua được",
            f"{so(rr['so_cw'])} CW" if rr["so_cw"] else "Chưa đủ 1 lô",
            f"≈ {so(rr['tien_chi'])} đ, đã gồm phí mua {phi_chu}% (lô 100 CW)",
        )
        + o_so(
            "Tương đương nắm",
            f"{so(rr['tiep_xuc'] / 1e6, 1)} triệu đ {ESC(cs)}",
            f"≈ {so(rr['so_cp'])} cổ phiếu · gấp {so(rr['tiep_xuc'] / (von * 1e6), 1)} lần số tiền bỏ ra",
        )
        + o_so(
            "Mất toàn bộ tiền nếu",
            f"{ESC(cs)} ≤ {so(K)} đ",
            (
                f"tức giảm {so(-rr['giam_ve_0'] * 100, 1)}% vào lúc đáo hạn · xác suất theo mô hình ≈ {so(rr['xs_ve_0'] * 100, 0)}% "
                "(σ lịch sử, không phải dự báo)"
                if rr["giam_ve_0"] < 0
                else f"{ESC(cs)} đang thấp hơn giá thực hiện"
            ),
        )
        + o_so(
            f"{ESC(cs)} giảm 1%",
            f"≈ −{so(rr['mat_khi_giam_1pct'])} đ",
            f"trước ngày đáo hạn, theo đòn bẩy {so(h['Đòn bẩy'], 1)}x; giảm sâu thì mất nhanh hơn",
        )
        + o_so(
            "Ngày giao dịch cuối",
            f"{gd_cuoi:%d/%m/%Y}" if gd_cuoi else "Không rõ",
            (
                f"còn {(gd_cuoi - ngay_tinh).days} ngày để bán; sau đó chỉ chờ nhận tiền theo giá trung bình 5 phiên trước "
                f"ngày đáo hạn {ngay_dao_han:%d/%m/%Y}"
                if gd_cuoi
                else "bấm Quét ngay để lấy ngày này"
            ),
        )
        + o_so(
            "Hòa vốn có phí, thuế",
            f"{so(rr['hoa_von_phi'])} đ",
            f"{ESC(cs)} cần {so((rr['hoa_von_phi'] / S - 1) * 100, 1, True)}% (chưa tính phí: {so(hoa_von)} đ). "
            f"Phí {phi_chu}% + thuế {thue_chu}% khi nhận tiền là giả định - kiểm tra với công ty chứng khoán của bạn",
        )
        + "</div></section>"
    )

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
    phan.append(
        '<div class="luoi-o">'
        + o_so(
            "Giá mua / giá hợp lý",
            f"{so(P)} / {so(h['Giá hợp lý'])}",
            '<a href="#cach-tinh" onclick="document.getElementById(\'cach-tinh\').open = true">Xem cách tính giá hợp lý ↓</a>',
        )
        + o_so("So với giá hợp lý", f'<span class="{lop_dat_re}">{chu_dat_re}</span>', "Rẻ = giá mua thấp hơn mô hình")
        + o_so("Điểm hòa vốn", f"{so(hoa_von)} đ", f"{ESC(cs)} cần {so(tang, 1, True)}% đến ngày đáo hạn")
        + o_so(
            "Đòn bẩy", f"{so(h['Đòn bẩy'], 1)}x", f"{ESC(cs)} tăng/giảm 1% → CW tăng/giảm khoảng {so(h['Đòn bẩy'], 1)}%"
        )
        + o_so(
            "Delta", so(delta, 2), f"{ESC(cs)} tăng/giảm 1.000 đ → 1 CW tăng/giảm khoảng {so(delta / ty_le * 1000)} đ"
        )
        + o_so(
            "Mất giá theo thời gian",
            f"{so(mat_gia, 1 if mat_gia < 10 else 0)} đ/ngày",
            f"≈ {so(mat_gia / P * 100, 2 if mat_gia / P < 0.001 else 1)}% giá CW mỗi ngày nếu {ESC(cs)} đứng yên",
        )
        + o_so(
            "Biến động ngầm định (IV)",
            f"{so(iv * 100, 0)}%" if iv else "—",
            f"Lịch sử 1 năm (HV): {so(sigma_ls * 100, 0)}%. {so_sanh_bd}"
            + (f" Trung vị IV các CW {ESC(cs)} khác: {so(tv_cung_ma, 0)}%." if math.isfinite(tv_cung_ma) else ""),
        )
        + "</div>"
    )

    # Giá hợp lý được tính thế nào: từng bước bằng số thật của mã này, nói bằng lời thường
    if ngay_con_lai > 0:
        N, bdd, kc = (
            C.phan_phoi_chuan,
            sigma_ls * math.sqrt(T),
            math.log(S / K),
        )  # bdd: biên độ dao động đến ngày đáo hạn
        d1 = (kc + (r + sigma_ls**2 / 2) * T) / bdd
        d2, ck = d1 - bdd, math.exp(-r * T)
        nhan, tra = S * N(d1), K * ck * N(d2)
        gia_cw_tinh, mo_phong = (nhan - tra) / ty_le, C.mo_phong_gia(S, K, T, r, sigma_ls) / ty_le
        c = ESC(cs)
        buoc = [
            (
                "Thu thập 5 con số",
                (
                    f"Giá {c} hôm nay <b>S = {so(S)} đ</b> · giá thực hiện <b>K = {so(K)} đ</b> · còn <b>{ngay_con_lai} ngày = {so(T, 3)} năm</b>"
                    f" · {c} dao động khoảng <b>σ = {so(sigma_ls * 100, 1)}%/năm</b> (đo từ giá 1 năm qua) · lãi suất <b>r = {so(r * 100, 1)}%/năm</b>."
                ),
            ),
            (
                "Giá đang cách giá thực hiện bao xa?",
                (
                    f"ln(S ÷ K) = ln({so(S)} ÷ {so(K)}) = <b>{so(kc, 3)}</b> → giá {c} đang "
                    f"{'cao' if kc >= 0 else 'thấp'} hơn giá thực hiện khoảng <b>{so(abs(kc) * 100, 1)}%</b>."
                ),
            ),
            (
                "Từ nay đến ngày đáo hạn, giá thường dao động bao nhiêu?",
                (
                    f"σ × √T = {so(sigma_ls * 100, 1)}% × √{so(T, 3)} = <b>{so(bdd * 100, 1)}%</b>"
                    f" → trong {ngay_con_lai} ngày tới, giá {c} thường lên/xuống trong khoảng <b>±{so(bdd * 100, 0)}%</b>."
                ),
            ),
            (
                "Đổi khoảng cách thành “số bước dao động”",
                (
                    f"d1 = (khoảng cách + một chút cho lãi suất và dao động) ÷ biên độ = ({so(kc, 3)} + "
                    f"{so((r + sigma_ls**2 / 2) * T, 3)}) ÷ {so(bdd, 3)} = <b>{so(d1, 2)}</b> · d2 = d1 − biên độ = <b>{so(d2, 2)}</b>."
                    f" Hiểu đơn giản: giá đang {'trên' if d2 >= 0 else 'dưới'} giá thực hiện khoảng {so(abs(d2), 1)} bước dao động."
                ),
            ),
            (
                "Đổi “số bước” thành xác suất",
                (
                    f"Tra bảng phân phối chuẩn (Excel: hàm NORM.S.DIST): <b>N(d2) = {so(N(d2) * 100, 0)}%</b> = khả năng tới ngày đáo hạn "
                    f"giá {c} vẫn trên {so(K)} đ (theo mô hình) · <b>N(d1) = {so(N(d1) * 100, 0)}%</b> – đây chính là <b>delta = {so(N(d1), 2)}</b>."
                ),
            ),
            (
                "Ráp vào công thức",
                (
                    f"Giá 1 quyền chọn = <b>phần nhận được − phần phải trả</b> = S × N(d1) − K × e<sup>−rT</sup> × N(d2) = "
                    f"{so(S)} × {so(N(d1), 3)} − {so(K)} × {so(ck, 3)} × {so(N(d2), 3)} = {so(nhan)} − {so(tra)} = <b>{so(nhan - tra)} đ</b> (cho 1 cổ phiếu)."
                ),
            ),
            (
                "Chia cho tỷ lệ chuyển đổi",
                f"{so(nhan - tra)} ÷ {so(ty_le, 4)} = <b>{so(gia_cw_tinh)} đ / 1 CW</b>. Giá mua là {so(P)} đ → <b>{chu_dat_re}</b> so với giá hợp lý."
                + (
                    f" <small class='phu'>(Bảng ghi {so(h['Giá hợp lý'])} đ: chênh vài đồng do mức dao động hiển thị đã làm tròn.)</small>"
                    if round(gia_cw_tinh) != int(h["Giá hợp lý"])
                    else ""
                ),
            ),
        ]
        phan.append(
            f'<details class="the" id="cach-tinh"><summary><h2 style="display:inline">📐 Giá hợp lý {so(h["Giá hợp lý"])} đ được tính thế nào?</h2>'
            ' <span class="phu">(bấm để xem từng bước)</span></summary>'
            f'<p class="tom-tat"><b>Ý tưởng:</b> tưởng tượng hàng nghìn kịch bản giá {c} có thể xảy ra đến ngày đáo hạn, với mức dao động như 1 năm qua. '
            f"Mỗi kịch bản, CW trả một số tiền hoặc về 0. <b>Giá hợp lý = trung bình số tiền đó, quy về tiền hôm nay.</b> "
            'Công thức Black-Scholes tính ra con số trung bình này chỉ bằng 7 bước:</p><ol class="cac-buoc">'
            + "".join(
                f"<li><b>Bước {k} – {t}{'' if t.endswith('?') else '.'}</b><br>{nd}</li>"
                for k, (t, nd) in enumerate(buoc, 1)
            )
            + f'</ol><p class="ghi-chu-canh-bao" style="border-left-color: var(--xanh); background: color-mix(in srgb, var(--xanh) 8%, transparent)">'
            f"<b>Kiểm chứng:</b> chương trình vừa thử <b>20.000 kịch bản</b> ngẫu nhiên cho giá {c} đến ngày đáo hạn. Trung bình CW trả "
            f"<b>≈ {so(mo_phong)} đ</b> (quy về hôm nay), gần bằng kết quả công thức {so(gia_cw_tinh)} đ.</p>"
            '<p class="phu">Nhớ: con số này dựa trên giả định cổ phiếu sẽ dao động như 1 năm qua. Nó là thước đo để so sánh, không phải dự báo giá.</p></details>'
        )

    # Khối lượng CW: sổ lệnh tải cùng lần định giá trực tiếp ở đầu trang (lỗi thì dùng số lúc quét)
    kl_ny, kl_khop = float(h["KL niêm yết"]), h["KL khớp"]
    ban, mua = (so_lenh.get("askPrices") or [])[:3], (so_lenh.get("bidPrices") or [])[:3]
    kl_ban = C.tong_kl(so_lenh, "askPrices") if so_lenh else h["KL chào bán"]
    kl_mua = C.tong_kl(so_lenh, "bidPrices") if so_lenh else h["KL chờ mua"]
    gia = lambda m: m.get("price") or 0
    tien = lambda m: gia(m) * (m.get("volume") or 0)  # thành tiền của một mức giá (đ)

    def o_sl(ds, i):  # 3 ô (giá, khối lượng, thành tiền) của một mức giá; không có mức đó thì "—"
        if i >= len(ds):
            return '<td class="so">—</td>' * 3
        return f'<td class="so">{so(gia(ds[i]))}</td><td class="so">{so(ds[i].get("volume") or 0)}</td><td class="so">{so(tien(ds[i]) / 1e6, 1)}</td>'

    def goi_y_ben(
        ds, ten_gia, viec
    ):  # vd: "ở giá thấp nhất 920 đ chỉ có 5.100 CW (≈ 4,7 triệu đ). Mua hết cả 3 mức ..."
        kl3, tien3 = sum(m.get("volume") or 0 for m in ds), sum(tien(m) for m in ds)
        return (
            f"Ở giá {ten_gia} {so(gia(ds[0]))} đ chỉ có <b>{so(ds[0].get('volume') or 0)} CW</b> (≈ {so(tien(ds[0]) / 1e6, 1)} triệu đ). "
            f"{viec} hết cả {len(ds)} mức ({so(gia(ds[0]))}–{so(gia(ds[-1]))} đ): ≈ {so(tien3 / 1e6, 1)} triệu đ, "
            f"giá trung bình ≈ {so(tien3 / kl3 if kl3 else math.nan)} đ"
        )

    dong_sl = (
        "".join(f"<tr>{o_sl(mua, i)}{o_sl(ban, i)}</tr>" for i in range(3))
        if (ban or mua)
        else '<tr><td colspan="6">Sổ lệnh đang trống (ngoài giờ giao dịch hoặc chưa có lệnh).</td></tr>'
    )
    phan.append(
        '<section class="the" id="khoi-luong"><h2>Khối lượng CW</h2><div class="luoi-o">'
        + o_so("Khối lượng phát hành", f"{so(kl_ny)} CW", "tổng số CW được niêm yết (được phép bán ra)")
        + o_so(
            "Đang chào bán (3 mức giá)",
            f"{so(kl_ban)} CW",
            goi_y_ben(ban, "thấp nhất", "Mua") if ban else "ở 3 mức giá bán thấp nhất",
        )
        + o_so(
            "Đang chờ mua (3 mức giá)",
            f"{so(kl_mua)} CW",
            goi_y_ben(mua, "cao nhất", "Bán") if mua else "ở 3 mức giá mua cao nhất",
        )
        + o_so(
            "Đã khớp trong phiên",
            f"{so(kl_khop)} CW",
            f"≈ {so(kl_khop / kl_ny * 100, 1)}% khối lượng phát hành" if kl_ny > 0 else "",
        )
        + '</div><div class="cuon"><table style="max-width:820px"><thead><tr><th class="so">Giá chờ mua (đ)</th><th class="so">KL chờ mua</th>'
        '<th class="so">Thành tiền (triệu đ)</th><th class="so">Giá chào bán (đ)</th><th class="so">KL chào bán</th><th class="so">Thành tiền (triệu đ)</th>'
        f"</tr></thead><tbody>{dong_sl}</tbody></table></div>"
        '<p class="phu">Sổ lệnh 3 mức giá tốt nhất. Mua nhiều hơn khối lượng ở giá thấp nhất thì phần còn lại phải mua ở các mức giá cao hơn '
        f"(bán thì ngược lại). Nguồn: {nguon}.</p>"
        '<details><summary>Vì sao không có "số CW đã bán ra" và "số CW còn lại"?</summary>'
        "<p>Các nguồn dữ liệu miễn phí (bảng giá Vietcap, KBS, vnstock gói miễn phí) chỉ công bố <b>tổng khối lượng phát hành</b>, "
        "không công bố nhà đầu tư đang nắm bao nhiêu CW. Phần CW chưa bán thường nằm trong tay <b>tổ chức phát hành</b>: họ là bên tạo lập "
        'thị trường, đặt lệnh bán dần ra và đặt lệnh mua lại. Vì vậy con số <b>"có thể mua ngay"</b> trên thực tế là khối lượng '
        "<b>đang chào bán</b> trong sổ lệnh. Tổ chức phát hành có thể đặt thêm lệnh bán sau đó, nhưng không vượt quá khối lượng phát hành. "
        "Nếu cần con số chính xác, hãy xem thông báo của tổ chức phát hành hoặc ứng dụng của công ty chứng khoán bạn dùng (nếu có hiển thị).</p></details></section>"
    )

    # Biểu đồ giá cổ phiếu cơ sở
    file_ls = C.THU_MUC_KET_QUA / f"lich_su_{ngay}.json"
    lich_su = json.loads(file_ls.read_text(encoding="utf-8")).get(cs) if file_ls.exists() else None
    phan.append(
        f'<section class="the"><h2>Giá {ESC(cs)} 1 năm qua</h2>'
        f'<p class="phu">Muốn có lãi khi giữ đến đáo hạn, giá {ESC(cs)} phải nằm trên đường <b>hòa vốn</b>. Rê chuột lên biểu đồ để xem giá từng ngày.</p>'
        + (
            bieu_do(lich_su, [("Giá thực hiện", K, "tc-thuc-hien"), ("Hòa vốn", hoa_von, "tc-hoa-von")], f"Giá {cs}")
            if lich_su
            else "<p>Chưa có dữ liệu biểu đồ. Bấm <b>Quét ngay</b> ở trang chính để tải.</p>"
        )
        + "</section>"
    )

    # IV theo thời gian: giá CW từ vnstock (1 lượt gọi, nhớ trong ngày) + giá CS đã điều chỉnh quyền trong file lịch sử lúc quét
    bo_nho, loi_iv = BO_NHO_IV.get((ma, date.today())), ""
    if bo_nho is None and lich_su:
        try:
            df_cw = C.lay_gia_dong_cua(ma)
            he_so = 10 ** round(math.log10(P_khop / float(df_cw["close"].iloc[-1])))  # vnstock có thể trả nghìn đồng
            gia_cw = {str(t)[:10]: float(g) * he_so for t, g in zip(df_cw["time"], df_cw["close"])}
            kl_cw = {str(t)[:10]: float(v) for t, v in zip(df_cw["time"], df_cw["volume"])}
            bo_nho = BO_NHO_IV[(ma, date.today())] = {
                "iv": C.lich_su_iv(gia_cw, dict(lich_su), K, ty_le, ngay_dao_han, r),
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
    phan.append(
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
    nguong_lech = danh_muc.CANH_BAO_LECH * 100
    mau_bang = hang_lech[:: max(len(hang_lech) // 4, 1)][:4] + hang_lech[-1:] if hang_lech else []
    phan.append(
        f'<section class="the"><h2>{ESC(ma)} có theo kịp {ESC(cs)} không?</h2>'
        f'<p class="phu">Lệch = giá CW thực tế so với giá "lẽ ra" nếu CW giữ nguyên mức IV của ngày mốc và chỉ chạy theo giá {ESC(cs)} '
        f"(đã gồm đòn bẩy và mất giá theo thời gian). Âm: CW không theo kịp cổ phiếu; dương: CW chạy nhanh hơn, dễ bị kéo về. "
        f"Trong khoảng ±{so(nguong_lech, 0)}% là bình thường. Mốc: "
        + (
            f"{moc[8:]}/{moc[5:7]}/{moc[:4]} (phiên đầu tiên trong 20 phiên gần nhất khớp ≥ {so(C.MIN_KHOI_LUONG)} CW).</p>"
            if moc
            else "—.</p>"
        )
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
            + '<div class="cuon"><table style="max-width:640px"><thead><tr><th>Ngày</th>'
            f'<th class="so">{ESC(cs)}</th><th class="so">CW thực tế</th><th class="so">CW lẽ ra</th><th class="so">Lệch</th></tr></thead><tbody>'
            + "".join(
                f'<tr><td>{d[8:]}/{d[5:7]}</td><td class="so">{so(a * 100, 1, True)}%</td><td class="so">{so(b * 100, 1, True)}%</td>'
                f'<td class="so">{so(c * 100, 1, True)}%</td><td class="so {"am" if e <= -danh_muc.CANH_BAO_LECH else ""}">'
                f"<b>{so(e * 100, 1, True)}%</b></td></tr>"
                for d, a, b, c, e in mau_bang
            )
            + "</tbody></table></div>"
            if len(lech_ls) >= 2
            else f'<p>{loi_iv or "Chưa đủ dữ liệu (cần ít nhất 2 phiên có giao dịch đủ thanh khoản)."}</p>'
        )
        + "</section>"
    )

    # Kịch bản lãi/lỗ khi đáo hạn
    so_cw, gia_von = rr["so_cw"], P * (1 + C.PHI_GIAO_DICH)  # giá vốn 1 CW đã gồm phí mua
    dong = []
    for thay_doi in (-20, -10, -5, 0, 5, 10, 15, 20, 30):
        gia_cs = S * (1 + thay_doi / 100)
        nhan_ve = max(gia_cs - K, 0) / ty_le
        lai = nhan_ve * (1 - C.THUE_BAN) - gia_von  # đã trừ thuế khi nhận tiền
        lop = "duong" if lai > 0 else ("am" if lai < 0 else "")
        dong.append(
            f'<tr{" class=hang-goc" if thay_doi == 0 else ""}><td>{"Giữ nguyên" if thay_doi == 0 else f"{thay_doi:+d}%"}</td>'
            f'<td class="so">{so(gia_cs)}</td><td class="so">{so(nhan_ve)}</td><td class="so {lop}">{so(lai, 0, True)}</td>'
            f'<td class="so {lop}">{so(lai / gia_von * 100, 0, True)}%</td><td class="so {lop}">{so(lai * so_cw, 0, True)}</td></tr>'
        )
    phan.append(
        f'<section class="the"><h2>Nếu giữ đến ngày đáo hạn ({ngay_dao_han:%d/%m/%Y})</h2>'
        f'<p class="phu">Lãi/lỗ theo giá {ESC(cs)} lúc đáo hạn (giá thanh toán thực tế là trung bình 5 phiên trước đáo hạn). '
        f'Đã trừ phí mua {phi_chu}% và thuế {thue_chu}% khi nhận tiền. Lỗ tối đa là toàn bộ tiền mua CW.</p><div class="cuon"><table><thead><tr><th>{ESC(cs)} thay đổi</th><th class="so">Giá {ESC(cs)} (đ)</th>'
        f'<th class="so">Nhận về / CW (đ)</th><th class="so">Lãi/lỗ / CW (đ)</th><th class="so">Lãi/lỗ</th>'
        f'<th class="so">Với {so(so_cw)} CW ≈ {von} triệu (đ)</th></tr></thead><tbody>{"".join(dong)}</tbody></table></div></section>'
    )

    # So sánh các CW cùng mã cơ sở
    cung_cs = df[df["Mã CS"] == cs].sort_values("IV − HV", na_position="last")
    phan.append(
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
    phan.append(
        '<section class="the"><h2>Điều khoản &amp; số liệu</h2><dl class="dieu-khoan">'
        + "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in dk)
        + "</dl></section>"
    )
    return trang(f"{ma} – phân tích chứng quyền", "".join(phan))


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
                "hãy tải lại trang sau ít phút hoặc bấm Quét ngay ở trang chính.</p>"
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
            gia_hl = C.black_scholes_call(S, K, con / 365, C.LAI_SUAT_PHI_RUI_RO, cs["Biến động %/năm"] / 100)[
                0
            ] / C.doc_ty_le(x["ty_le"])
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
