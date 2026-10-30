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
    # phí: CTCK 3.000 × 2 (mở + đáo hạn) + Sở 2.700 + vị thế 2.550 × 14 = 44.400; thuế 8,5 × (1.858 + 1.900) = 31.943
    gop, rong = P.lai_lo_dao_han(1858, 1900, 1, 14)
    assert math.isclose(gop, 4_200_000) and math.isclose(rong, 4_200_000 - 44_400 - 31_943)
    # Short cùng kịch bản: gộp −4.200.000, cùng chi phí
    gop, rong = P.lai_lo_dao_han(1858, 1900, -1, 14)
    assert math.isclose(gop, -4_200_000) and math.isclose(rong, -4_200_000 - 44_400 - 31_943)


def test_phien_giu_va_doc_ngay():
    # thứ Sáu 30/10/2026 -> GD cuối thứ Năm 19/11/2026: 14 phiên (bỏ thứ Bảy, Chủ nhật; chưa trừ ngày lễ)
    assert P.so_phien(date(2026, 10, 30), date(2026, 11, 19)) == 14
    assert P.doc_ngay("19/11/2026") == date(2026, 11, 19) and P.doc_ngay("") is None
    # chỉ nhận mã đúng dạng (chặn mã lạ từ URL)
    assert P.MAU_MA_HD.fullmatch("VN30F1M") and not P.MAU_MA_HD.fullmatch("VN30F3M")


def test_trang_web_phai_sinh():
    from unittest import mock

    import web_chung
    import web_phai_sinh as W

    hom_nay = date.today()
    gd_cuoi = date.fromordinal(hom_nay.toordinal() + 20)
    hd = {
        "ma": "VN30F1M",
        "ten": "VN30 Index Futures 112026",
        "gia": 1858.0,
        "ngay_gia": "2026-10-30",
        "lich_su": {"2026-10-29": 1880.8, "2026-10-30": 1858.0},
        "gd_cuoi": gd_cuoi,
        "dao_han": None,
        "bang_gia": None,
    }
    vn30 = {"2026-10-29": 1877.18, "2026-10-30": 1855.04}
    with (
        mock.patch.object(P, "lay_du_lieu", return_value=([hd], vn30, [])),
        mock.patch.object(web_chung, "muc_nen", return_value=""),  # mục nến gọi mạng: kiểm riêng ở test_cw_scanner
    ):
        ds = W.trang_phai_sinh()
        ct = W.trang_phai_sinh_chi_tiet("VN30F1M")
        assert W.trang_phai_sinh_chi_tiet("VN30F3M") is None and W.trang_phai_sinh_chi_tiet("VN30F2Q") is not None
    # basis 1.858 − 1.855,04 = +2,96 điểm; tháng đáo hạn đọc từ tên; ký quỹ 31,6 triệu
    assert "T11/2026" in ds and "+2,96" in ds and "31,6" in ds and 'href="/phai-sinh/VN30F1M"' in ds
    # chi tiết: dòng "Giữ nguyên" Long = 0 điểm gộp − phí, thuế; basis theo ngày 29/10: 1.880,8 − 1.877,18 = +3,62
    _, long_ = P.lai_lo_dao_han(1858.0, 1855.04, 1, P.so_phien(hom_nay, gd_cuoi))
    assert web_chung.so(long_, 0, True) in ct and "Basis theo ngày" in ct and "3.62" in ct


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - phái sinh đúng")
