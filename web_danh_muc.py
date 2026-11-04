"""Trang Danh mục (/danh-muc): lệnh đang nắm, lãi/lỗ, cảnh báo."""

import json
from datetime import date, datetime

import pandas as pd

import cw_scanner
import danh_muc
import web_chung as W  # doc_ket_qua và trạng thái QUET/LOI_DANH_MUC đọc qua module: test patch được, handler gán được
from web_chung import ESC, hang_doi, o_so, so, trang


# ============ TRANG DANH MỤC ============
def o_trang_thai(tt):
    """Ô "Trạng thái" của 1 vị thế: mức, các lý do (lý do chính đứng đầu), ghi chú dưới sàn lý thuyết."""
    if not tt:
        return "—"
    dong = [f"<b>{ESC(danh_muc.TEN_MUC[tt['muc']])}</b>"]
    dong += [f"<small>{ESC(nd or danh_muc.LY_DO_BAN[l])}</small>" for l, nd in tt["ly_do"]]  # nd: nội dung cảnh báo
    dong += [f"<small>ℹ {ESC(x)}</small>" for x in tt.get("thong_tin", [])]
    if tt["duoi_san"]:
        dong.append(f"<small class=am>🛑 bán dưới giá trị tối thiểu nếu giữ tới đáo hạn ({so(tt['san'])} đ)</small>")
    return "<br>".join(dong)


def o_thao_tac(ma, so_luong, gia_ban, hom_nay):
    """Ô Thao tác của 1 vị thế: ✕ Chốt (lệnh bán, mặc định bán hết ở giá chờ mua tốt nhất) và + Trung bình giá (lệnh mua thêm).
    Cả hai gửi về /danh-muc/them như form Thêm lệnh, nên kiểm tra (bán không vượt số đang nắm, lô 100, bước giá) và giá vốn
    bình quân dùng chung danh_muc.them_lenh / tinh_vi_the."""

    def form(nhan, loai, kl, gia, nut):
        kl_max = f' max="{so_luong}"' if loai == "BAN" else ""
        return (
            f'<details class="thao-tac"><summary>{nhan}</summary><form method="post" action="/danh-muc/them" class="form-lenh">'
            f'<input type="hidden" name="ma_cw" value="{ma}"><input type="hidden" name="loai" value="{loai}">'
            f'<label>Ngày<input type="date" name="ngay" value="{hom_nay}" max="{hom_nay}" required></label>'
            f'<label>Số lượng<input type="number" name="so_luong" min="100" step="100"{kl_max} value="{kl}" required></label>'
            f'<label>Giá<input name="gia" inputmode="decimal" required size="7" value="{gia}" placeholder="0,87"></label>'
            f'<button class="nut">{nut}</button></form></details>'
        )

    # điền sẵn theo nghìn đồng (0,08 = 80 đ) như app chứng khoán: danh_muc.doc_gia hiểu số < 100 là nghìn đồng.
    # Từ 100.000 đ thì nghìn đồng ≥ 100 sẽ bị đọc thành đồng: ghi thẳng theo đồng
    gia = "" if not gia_ban else f"{gia_ban:.0f}" if gia_ban >= 100_000 else f"{gia_ban / 1000:g}".replace(".", ",")
    return form("✕ Chốt", "BAN", so_luong, gia, "Lưu lệnh bán") + form(
        "+ Trung bình giá", "MUA", "", "", "Lưu lệnh mua"
    )


def trang_danh_muc():
    """Danh mục CW đang nắm: thêm/xóa lệnh, vị thế và cảnh báo theo giá trực tiếp."""
    C, D = cw_scanner, danh_muc
    df, ngay_quet = W.doc_ket_qua()
    phi_thue = f"phí {so(C.PHI_GIAO_DICH * 100, 2)}% + thuế {so(C.THUE_BAN * 100, 1)}%"
    phan = [
        (
            '<div class="dau-trang"><div><h1>Danh mục của tôi</h1><p class="phu">Lệnh lưu trong file <code>danh_muc.csv</code> trên máy này '
            f"(không đưa lên git, sao lưu mỗi ngày cùng kết quả quét). Lãi/lỗ tính <b>nếu bán ngay</b> ở giá chờ mua tốt nhất, đã trừ {phi_thue}; "
            "giá vốn bình quân đã gồm phí mua. Cảnh báo gửi Discord khi vừa xuất hiện (xem Hướng dẫn).</p></div></div>"
        )
    ]
    if W.LOI_DANH_MUC:
        phan.append(f'<p class="loi" role="alert">{ESC(W.LOI_DANH_MUC)}</p>')
        W.LOI_DANH_MUC = ""
    try:
        ds = D.doc_lenh()
        tat_ca = D.tinh_vi_the(ds)
    except Exception as e:  # file bị sửa tay sai định dạng: dừng lại, không ghi đè lên dữ liệu  # noqa: BLE001
        phan.append(
            f'<p class="loi" role="alert">File danh_muc.csv bị lỗi, hãy sửa lại bằng tay (bản trước: danh_muc.csv.bak): {ESC(str(e))}</p>'
        )
        return trang("Danh mục", "".join(phan), "/danh-muc")
    vt = {m: v for m, v in tat_ca.items() if v["so_luong"] > 0}
    hom_nay = date.today()

    m_canh_bao = m_dang_nam = m_da_chot = m_lich_su = ""
    # Vị thế đang nắm (giá trực tiếp)
    if vt:
        try:
            bang_gia = D.tai_bang_gia(list(vt), df, cho=5)
            nguon = f"bảng giá Vietcap lúc {datetime.now():%H:%M %d/%m/%Y}"
        except Exception as e:  # mất mạng: chỉ hiện số đang nắm và giá vốn  # noqa: BLE001
            bang_gia, nguon = None, f"KHÔNG tải được giá trực tiếp ({ESC(str(e)[:120])})"
        if bang_gia is not None:
            tt = json.loads(D.FILE_TRANG_THAI.read_text(encoding="utf-8")) if D.FILE_TRANG_THAI.exists() else {}
            dong, canh_bao, _ = D.danh_gia_danh_muc(
                vt,
                bang_gia,
                df if df is not None else pd.DataFrame(columns=["Mã CW", "Mã CS", "IV %"]),
                date.today(),
                tt.get("kl_niem_yet", {}),
                D.doc_lich_su(ngay_quet),
            )
        else:
            dong, canh_bao = [{"ma": m, **v, "co_gia": False} for m, v in sorted(vt.items())], []
        if canh_bao:
            m_canh_bao = (
                '<section class="the"><h2>⚠ Cảnh báo hiện tại</h2><ul>'
                + "".join(f"<li><b>{ESC(m)}</b>: {ESC(nd)}</li>" for m, _, nd in canh_bao)
                + "</ul></section>"
            )
        hang = []
        for d in dong:
            ma = ESC(d["ma"])
            if not d["co_gia"]:
                hang.append(
                    f'<tr><td><a href="/cw/{ma}">{ma}</a>{o_thao_tac(ma, d["so_luong"], None, hom_nay)}</td><td></td>'
                    f'<td class="so">{so(d["so_luong"])}</td>'
                    f'<td class="so">{so(d["gia_von"], 1)}</td><td colspan="7">không có giá trực tiếp</td></tr>'
                )
                continue
            lop = "duong" if d["lai"] > 0 else ("am" if d["lai"] < 0 else "")
            # tính trước: f-string lồng nhau dùng lại cùng dấu nháy chỉ chạy từ Python 3.12 (web phải chạy được từ 3.10)
            ngay_gd = (
                f"{d['ngay_gd_cuoi']:%d/%m/%Y}<br><small>còn {d['con_ngay']} ngày</small>" if d["ngay_gd_cuoi"] else "—"
            )
            # ✕ Chốt / + Trung bình giá nằm dưới mã: bảng rộng hơn màn hình (cột Trạng thái dài), cột cuối phải kéo ngang mới thấy
            thao_tac = o_thao_tac(ma, d["so_luong"], d["gia_ban"] if d["co_nguoi_mua"] else None, hom_nay)
            hang.append(
                f'<tr><td><a href="/cw/{ma}">{ma}</a>{thao_tac}</td><td>{ESC(d["cs"])}</td><td class="so">{so(d["so_luong"])}</td>'
                f'<td class="so">{so(d["gia_von"], 1)}</td><td class="so">{so(d["gia_ban"])}{"" if d["co_nguoi_mua"] else " <small class=am>không ai mua</small>"}</td>'
                f'<td class="so {lop}">{so(d["lai"], 0, True)}<br><small>{so(d["lai_pct"] * 100, 1, True)}%</small></td>'
                f'<td class="so">+{so(d["chot_loi"] * 100, 0)}% / −{so(d["cat_lo"] * 100, 0)}%</td>'
                f'<td class="so">{so(d["S"])} / {so(d["K"])}<br><small>{so(d["cach_K"] * 100, 1, True)}%</small></td>'
                f"<td>{ngay_gd}</td>"
                f'<td class="so">{so(d["don_bay"], 1)}x</td><td>{o_trang_thai(d.get("trang_thai"))}</td></tr>'
            )
        co_gia = [d for d in dong if d["co_gia"]]
        tiep_xuc = {}
        for d in co_gia:
            tiep_xuc[d["cs"]] = tiep_xuc.get(d["cs"], 0) + d["tiep_xuc"]
        von = sum(d["so_luong"] * d["gia_von"] for d in dong)
        m_dang_nam = (
            f'<section class="the"><h2>Đang nắm ({len(dong)} mã)</h2><p class="phu">Giá: {nguon}. Dưới mỗi mã: <b>✕ Chốt</b> ghi lệnh '
            "bán (mặc định bán hết ở giá chờ mua tốt nhất, sửa được), <b>+ Trung bình giá</b> ghi lệnh mua thêm, giá vốn tự tính lại "
            'bình quân.</p><div class="luoi-o">'
            + o_so(
                "Tiền vốn đang nằm trong CW", f"{so(von / 1e6, 1)} triệu đ", "theo giá vốn bình quân, đã gồm phí mua"
            )
            + (
                o_so(
                    "Lãi/lỗ nếu bán hết ngay",
                    f'<span class="{"duong" if sum(d["lai"] for d in co_gia) >= 0 else "am"}">'
                    f'{so(sum(d["lai"] for d in co_gia) / 1e6, 2, True)} triệu đ</span>',
                    f"đã trừ {phi_thue} khi bán",
                )
                if co_gia
                else ""
            )
            + o_so(
                "Tương đương nắm cổ phiếu cơ sở",
                " · ".join(f"{ESC(cs)} {so(v / 1e6, 0)} tr" for cs, v in sorted(tiep_xuc.items())) or "—",
                "giá trị cổ phiếu mà các CW đang đại diện (thường gấp 5–15 lần tiền vốn)",
            )
            + "</div>"
            '<div class="cuon"><table><thead><tr><th>Mã CW</th><th>Mã CS</th><th class="so">Số lượng</th><th class="so">Giá vốn</th>'
            '<th class="so">Giá bán được</th><th class="so">Lãi/lỗ nếu bán ngay</th><th class="so">Chốt lời / cắt lỗ</th>'
            '<th class="so">Giá CS / giá TH</th><th>Ngày GD cuối</th><th class="so">Đòn bẩy</th><th>Trạng thái</th></tr></thead>'
            f'<tbody>{"".join(hang)}</tbody></table></div></section>'
        )
    # Mã đã bán hết: dấu ✕, ngày bán cuối, lãi/lỗ đã chốt (đã trừ phí, thuế)
    da_chot = sorted(m for m, v in tat_ca.items() if not v["so_luong"])
    if da_chot:
        ngay_ban = {m: max(d["ngay"] for d in ds if d["ma_cw"] == m and d["loai"] == "BAN") for m in da_chot}
        hang = "".join(
            f'<tr><td>✕ <a href="/cw/{ESC(m)}">{ESC(m)}</a></td><td>{ngay_ban[m][8:]}/{ngay_ban[m][5:7]}/{ngay_ban[m][:4]}</td>'
            f'<td class="so {"duong" if tat_ca[m]["lai_da_chot"] >= 0 else "am"}">{so(tat_ca[m]["lai_da_chot"], 0, True)} đ</td></tr>'
            for m in sorted(da_chot, key=lambda m: ngay_ban[m], reverse=True)
        )
        m_da_chot = (
            f'<section class="the"><h2>✕ Đã chốt ({len(da_chot)} mã)</h2><p class="phu">Mã đã bán hết. Lãi/lỗ đã trừ phí, thuế, '
            "theo giá vốn bình quân lúc bán.</p>"
            '<div class="cuon"><table><thead><tr><th>Mã CW</th><th>Ngày bán cuối</th><th class="so">Lãi/lỗ đã chốt</th></tr></thead>'
            f"<tbody>{hang}</tbody></table></div></section>"
        )
    lai_chot = sum(v["lai_da_chot"] for v in tat_ca.values())

    # Thêm lệnh
    ds_ma = sorted(df["Mã CW"]) if df is not None else []
    m_them = (
        '<form method="post" action="/danh-muc/them" class="the form-lenh"><h2>Thêm lệnh</h2>'
        f'<label>Ngày<input type="date" name="ngay" value="{hom_nay}" max="{hom_nay}" required></label>'
        '<label>Mã CW<input name="ma_cw" list="ds-ma" required size="10" pattern="[Cc][A-Za-z]{3}[0-9]{4}" placeholder="CVPB2615"></label>'
        f'<datalist id="ds-ma">{"".join(f"<option value={ESC(m)}>" for m in ds_ma)}</datalist>'
        '<label>Loại<select name="loai"><option value="MUA">Mua</option><option value="BAN">Bán</option></select></label>'
        '<label>Số lượng (lô 100)<input type="number" name="so_luong" min="100" step="100" required></label>'
        '<label>Giá khớp (vd 0,87 hoặc 870)<input name="gia" inputmode="decimal" required size="10" placeholder="0,87"></label>'
        f'<label>Chốt lời % (lệnh mua)<input type="number" name="chot_loi" min="1" max="1000" placeholder="{so(danh_muc.CHOT_LOI_MAC_DINH * 100, 0)}"></label>'
        f'<label>Cắt lỗ % (lệnh mua)<input type="number" name="cat_lo" min="1" max="100" placeholder="{so(danh_muc.CAT_LO_MAC_DINH * 100, 0)}"></label>'
        '<label>Ghi chú<input name="ghi_chu" maxlength="200" size="18"></label>'
        '<p><button class="nut">Lưu lệnh</button></p>'
        '<p class="phu">Chốt lời / cắt lỗ để trống thì dùng mức mặc định ở đầu file danh_muc.py. Lệnh bán không được vượt số đang nắm.</p></form>'
    )

    # Lịch sử lệnh
    if ds:
        nguong = lambda d: (
            ("" if d["chot_loi"] is None else f"+{so(d['chot_loi'] * 100, 0)}%")
            + ("" if d["cat_lo"] is None else f" / −{so(d['cat_lo'] * 100, 0)}%")
        )
        hang = "".join(
            f'<tr><td class="so">{d["id"]}</td><td>{d["ngay"][8:]}/{d["ngay"][5:7]}/{d["ngay"][:4]}</td><td>{ESC(d["ma_cw"])}</td>'
            f'<td>{"Mua" if d["loai"] == "MUA" else "✕ Bán"}</td><td class="so">{so(d["so_luong"])}</td><td class="so">{so(d["gia"])}</td>'
            f'<td class="so">{nguong(d)}</td><td class="ly-do">{ESC(d["ghi_chu"])}</td>'
            f'<td><form method="post" action="/danh-muc/xoa" onsubmit="return confirm(\'Xóa lệnh số {d["id"]}?\')">'
            f'<input type="hidden" name="id" value="{d["id"]}"><button class="nut-nho">Xóa</button></form></td></tr>'
            for d in sorted(ds, key=lambda d: (d["ngay"], d["id"]), reverse=True)
        )
        m_lich_su = (
            f'<section class="the"><h2>Lịch sử lệnh ({len(ds)})</h2><p class="phu">Lãi/lỗ đã chốt (các lệnh bán): '
            f'<b class="{"duong" if lai_chot >= 0 else "am"}">{so(lai_chot, 0, True)} đ</b>. Xóa nhầm thì bản trước nằm trong danh_muc.csv.bak.</p>'
            '<div class="cuon"><table><thead><tr><th class="so">Số</th><th>Ngày</th><th>Mã CW</th><th>Loại</th><th class="so">Số lượng</th>'
            f'<th class="so">Giá</th><th class="so">Chốt / cắt</th><th>Ghi chú</th><th></th></tr></thead><tbody>{hang}</tbody></table></div></section>'
        )
    # Cảnh báo | Thêm lệnh cạnh nhau (người dùng chọn 30/10/2026), bảng Đang nắm và Lịch sử lệnh trải ngang
    phan += [hang_doi(m_canh_bao, m_them), m_dang_nam, m_da_chot, m_lich_su]
    return trang("Danh mục", "".join(phan), "/danh-muc")
