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


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - phái sinh đúng")
