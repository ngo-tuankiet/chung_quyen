"""Kiểm tra phai_sinh.py bằng số tính tay (không gọi mạng). Chạy: python -m pytest -q   hoặc   python test_phai_sinh.py"""

import math
from datetime import date

import phai_sinh as P


def test_basis_va_basis_nam_hoa():
    # F 1.858,0, VN30 1.855,04 (đóng cửa 30/10/2026): basis +2,96 điểm = +0,1596%
    diem, pt = P.basis(1858.0, 1855.04)
    assert math.isclose(diem, 2.96) and math.isclose(pt, (1858 / 1855.04 - 1) * 100)
    # năm hóa: ln(1.858 / 1.855,04) / (20 / 365) = 2,910%/năm (còn 20 ngày lịch tới ngày GD cuối)
    assert math.isclose(P.basis_nam_hoa(1858.0, 1855.04, 20), math.log(1858 / 1855.04) / (20 / 365) * 100)
    assert math.isclose(P.basis_nam_hoa(1858.0, 1855.04, 20), 2.9104, abs_tol=1e-3)
    assert math.isnan(P.basis_nam_hoa(1858.0, 1855.04, 0))  # đáo hạn hôm nay: không năm hóa


def test_ky_quy_va_thue():
    # ký quỹ ban đầu 1 HĐ = 1.858 × 100.000 × 17% = 31.586.000 đ
    assert math.isclose(P.ky_quy_ban_dau(1858), 31_586_000)
    # thuế 1 lần, 1 HĐ ở 1.000 điểm: 0,1% × 1.000 × 100.000 × 17% / 2 = 8.500 đ (ví dụ Pinetree: 2 HĐ -> 17.000 đ)
    assert math.isclose(P.thue_mot_lan(1000), 8_500)


def test_lai_lo_giu_den_dao_han_tinh_tay():
    # Long 1 HĐ ở 1.858, VN30 ngày GD cuối 1.900, giữ 14 phiên: gộp (1.900 − 1.858) × 100.000 = 4.200.000 đ
    # phí: CTCK 3.000 × 2 (mở + đáo hạn) + Sở 2.700 + bù trừ 2.550 (lúc mở) = 11.250, không còn phí vị thế theo ngày từ
    # 05/05/2025; thuế 8,5 × (1.858 + 1.900) = 31.943
    gop, rong = P.lai_lo_dao_han(1858, 1900, 1, 14)
    assert math.isclose(gop, 4_200_000) and math.isclose(rong, 4_200_000 - 11_250 - 31_943)
    # Short cùng kịch bản: gộp −4.200.000, cùng chi phí
    gop, rong = P.lai_lo_dao_han(1858, 1900, -1, 14)
    assert math.isclose(gop, -4_200_000) and math.isclose(rong, -4_200_000 - 11_250 - 31_943)


def test_phien_giu_va_doc_ngay():
    # thứ Sáu 30/10/2026 -> GD cuối thứ Năm 19/11/2026: 14 phiên (bỏ thứ Bảy, Chủ nhật; chưa trừ ngày lễ)
    assert P.so_phien(date(2026, 10, 30), date(2026, 11, 19)) == 14
    assert P.doc_ngay("19/11/2026") == date(2026, 11, 19) and P.doc_ngay("") is None
    # chỉ nhận mã đúng dạng (chặn mã lạ từ URL)
    assert (
        P.MAU_MA_HD.fullmatch("VN30F1M") and P.MAU_MA_HD.fullmatch("VN100F2Q") and not P.MAU_MA_HD.fullmatch("VN30F3M")
    )
    assert not P.MAU_MA_HD.fullmatch("VN50F1M")
    # mã -> chỉ số cơ sở
    assert P.chi_so_cua("VN30F2M") == "VN30" and P.chi_so_cua("VN100F1Q") == "VN100"


def test_ky_quy_theo_chi_so():
    # VN100 1.770 điểm: ký quỹ = 1.770 × 100.000 × tỷ lệ của VN100; thuế dùng cùng tỷ lệ
    tl = P.TY_LE_KY_QUY_BAN_DAU["VN100"]
    assert math.isclose(P.ky_quy_ban_dau(1770, "VN100"), 1770 * 100_000 * tl)
    assert math.isclose(P.thue_mot_lan(1770, "VN100"), 0.001 * 1770 * 100_000 * tl / 2)


def test_bang_gia_theo_ma_krx():
    from unittest import mock

    # bí danh: giá khớp 0, sổ lệnh rỗng; mã KRX (ticker) có sổ lệnh -> ghép về bí danh theo mappingSymbol
    bi_danh = {
        "VN30F1M": ({"symbol": "VN30F1M", "ticker": "41I1GB000"}, {"matchPrice": 0}, {"bidPrices": []}),
        "VN100F2Q": ({"symbol": "VN100F2Q", "ticker": "41I2H6000"}, {"matchPrice": 0}, {"bidPrices": []}),
    }
    krx = {"41I1GB000": ({"symbol": "41I1GB000", "mappingSymbol": "VN30F1M"}, {"matchPrice": 1858}, {"bidPrices": [1]})}
    with mock.patch.object(P.C, "lay_bang_gia", return_value=krx) as goi:
        kq = P.bang_gia_krx(bi_danh)
    assert goi.call_args.args[0] == ["41I1GB000", "41I2H6000"]
    assert kq["VN30F1M"] is krx["41I1GB000"]
    assert kq["VN100F2Q"] is bi_danh["VN100F2Q"]  # Vietcap không trả mã KRX: giữ bản ghi bí danh


def test_trang_web_phai_sinh():
    from unittest import mock

    import web_chung
    import web_phai_sinh as W

    hom_nay = date.today()
    gd_cuoi = date.fromordinal(hom_nay.toordinal() + 20)
    hd = {
        "ma": "VN30F1M",
        "chi_so": "VN30",
        "kl": 138_045.0,
        "ten": "VN30 Index Futures 112026",
        "gia": 1858.0,
        "ngay_gia": "2026-10-30",
        "lich_su": {"2026-10-29": 1880.8, "2026-10-30": 1858.0},
        "gd_cuoi": gd_cuoi,
        "dao_han": None,
        "bang_gia": None,
    }
    vn30 = {"2026-10-29": 1877.18, "2026-10-30": 1855.04}
    hd100 = {**hd, "ma": "VN100F1M", "chi_so": "VN100", "kl": 15.0, "ten": "VN100 Index Futures 112026", "gia": 1769.4}
    hd100["lich_su"] = {"2026-10-30": 1769.4}
    gia_cs = {"VN30": vn30, "VN100": {"2026-10-30": 1761.77}}
    with (
        mock.patch.object(P, "lay_du_lieu", return_value=([hd, hd100], gia_cs, [])),
        mock.patch.object(web_chung, "muc_nen", return_value=""),  # mục nến gọi mạng: kiểm riêng ở test_cw_scanner
    ):
        ds = W.trang_phai_sinh()
        ct = W.trang_phai_sinh_chi_tiet("VN30F1M")
        ct100 = W.trang_phai_sinh_chi_tiet("VN100F1M")
        assert W.trang_phai_sinh_chi_tiet("VN30F3M") is None and W.trang_phai_sinh_chi_tiet("VN30F2Q") is not None
    # basis 1.858 − 1.855,04 = +2,96 điểm; tháng đáo hạn đọc từ tên; ký quỹ 31,6 triệu
    assert "T11/2026" in ds and "+2,96" in ds and "31,6" in ds and 'href="/phai-sinh/VN30F1M"' in ds
    # VN100: mục riêng, basis 1.769,4 − 1.761,77 = +7,63 điểm; KL 15 HĐ -> cảnh báo thanh khoản mỏng
    assert "Hợp đồng tương lai VN100" in ds and "+7,63" in ds and "hiệu lực 16/10/2026" in ds
    assert "thanh khoản rất mỏng" in ct100 and "VN100 thay đổi" in ct100 and "thanh khoản rất mỏng" not in ct
    # chi tiết: dòng "Giữ nguyên" Long = 0 điểm gộp − phí, thuế; basis theo ngày 29/10: 1.880,8 − 1.877,18 = +3,62
    _, long_ = P.lai_lo_dao_han(1858.0, 1855.04, 1, P.so_phien(hom_nay, gd_cuoi))
    assert web_chung.so(long_, 0, True) in ct and "Basis theo ngày" in ct and "3.62" in ct


def test_basis_nam_hoa_tinh_tu_ngay_cua_gia():
    import web_phai_sinh as W

    # Audit 04/11/2026: F 1.858, VN30 1.855 giá ngày thứ Sáu 13/11, GD cuối 19/11. Xem Chủ nhật 15/11: còn 4 ngày (hiển thị),
    # nhưng năm hóa tính 6 ngày từ ngày giá: ln(1.858 / 1.855) / (6 / 365) = 0,0016160 / 0,016438 = 9,83%/năm (cách cũ: 14,75%)
    h = {"chi_so": "VN30", "ngay_gia": "2026-11-13", "gd_cuoi": date(2026, 11, 19), "gia": 1858.0}
    c = W.chi_so_hd(h, {"VN30": {"2026-11-13": 1855.0}}, date(2026, 11, 15))
    assert c["con_ngay"] == 4 and abs(c["nam_hoa"] - math.log(1858 / 1855) / (6 / 365) * 100) < 1e-9
    assert abs(c["nam_hoa"] - 9.83) < 0.01


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - phái sinh đúng")
