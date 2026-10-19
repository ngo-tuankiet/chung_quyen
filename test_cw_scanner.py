"""Kiểm tra công thức. Chạy: python -m pytest -q   hoặc   python test_cw_scanner.py (không cần cài pytest)."""
import math
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

from cw_scanner import (bien_dong_ngam_dinh, black_scholes_call, can_duoi, danh_gia, dinh_gia, doc_cw_sap_ra_mat, doc_env, doc_ty_le,
                        gia_mua, mo_phong_gia, so_iv_cung_ma, tong_kl)

# Sổ lệnh mẫu (CVPB2615 cuối phiên 16/10/2026, mức thứ 3 thiếu khối lượng)
SO_LENH = {"askPrices": [{"price": 1250, "volume": 30300}, {"price": 1260, "volume": 30000}, {"price": 1290, "volume": None}]}


def test_black_scholes_vi_du_hull():
    # Ví dụ kinh điển (sách Hull): S=100, K=100, T=1 năm, r=5%, sigma=20% -> giá 10.45, delta 0.637
    gia, delta = black_scholes_call(100, 100, 1, 0.05, 0.2)
    assert abs(gia - 10.4506) < 1e-3 and abs(delta - 0.6368) < 1e-3, (gia, delta)
    assert black_scholes_call(120, 100, 0, 0.05, 0.2) == (20, 1.0)  # đáo hạn: chỉ còn giá trị nội tại


def test_mo_phong_gan_cong_thuc():
    # Mô phỏng 20.000 kịch bản cho ra gần đúng giá của công thức (sai số < 3%)
    assert abs(mo_phong_gia(100, 100, 1, 0.05, 0.2) / 10.4506 - 1) < 0.03


def test_bien_dong_ngam_dinh():
    # Giải ngược đúng sigma đã dùng để tạo giá; giá dưới giá trị nội tại -> None
    gia_cw = black_scholes_call(24500, 22605, 0.337, 0.04, 0.30)[0] / 1.5863
    assert abs(bien_dong_ngam_dinh(gia_cw, 24500, 22605, 0.337, 0.04, 1.5863) - 0.30) < 1e-4
    assert bien_dong_ngam_dinh(100, 24500, 22605, 0.337, 0.04, 1.5863) is None


def test_tong_kl():
    # Cộng khối lượng 3 mức giá; thiếu dữ liệu (ngoài giờ, mã mới) thì ra 0 chứ không lỗi
    assert tong_kl(SO_LENH, "askPrices") == 60300 and tong_kl(SO_LENH, "bidPrices") == 0 and tong_kl({}, "askPrices") == 0


def test_gia_mua():
    # Chào bán thấp nhất; sổ lệnh trống -> giá khớp; chưa khớp -> tham chiếu; mức giá dạng chữ (phiên ATO/ATC) bị bỏ qua
    ny, kl = {"refPrice": 1230}, {"matchPrice": 1240}
    assert gia_mua(ny, kl, SO_LENH) == (1250, "ask")
    assert gia_mua(ny, kl, {"askPrices": [{"price": "ATC", "volume": 100}, {"price": 0, "volume": 5}]}) == (1240, "khớp")
    assert gia_mua(ny, {"matchPrice": 0}, {}) == (1230, "tham chiếu")


def test_cvpb2615_tinh_tay():
    # KE_HOACH Phần 1: S=24.500, K=22.605, 123 ngày, r=4%, sigma=32,8%, tỷ lệ 1,5863
    T = 123 / 365
    assert abs(black_scholes_call(24500, 22605, T, 0.04, 0.328)[0] / 1.5863 - 1944) < 2  # tài liệu: ≈ 1.944 đ
    # Mức tối thiểu = 24.500 − 22.605 × e^(−0,04 × 0,337) = 24.500 − 22.302,3 ≈ 2.197,7 đ (cho 1 cổ phiếu)
    assert abs(can_duoi(24500, 22605, T, 0.04) - 2197.7) < 0.5
    # Giá chào bán 1.250 đ × 1,5863 = 1.982,9 đ < 2.197,7 đ -> không có sigma nào khớp
    assert bien_dong_ngam_dinh(1250, 24500, 22605, T, 0.04, 1.5863) is None
    assert can_duoi(20000, 22605, T, 0.04) == 0 and can_duoi(24500, 22605, 0, 0.04) == 1895  # ngoài tiền -> 0; đáo hạn -> nội tại


def test_dinh_gia_cvpb2615():
    # Số liệu thật cuối phiên 16/10/2026, định giá ngày 18/10 (còn 122 ngày), sigma VPB 31,8%, r 4%
    ny = {"exercisePrice": 22605, "exerciseRatio": "1.5863:1", "maturityDate": "20270217", "refPrice": 1230,
          "underlyingSymbol": "VPB", "issuerName": "ACBS", "listedShare": 18_000_000}
    kq = dinh_gia(ny, {"matchPrice": 1240, "accumulatedVolume": 891_900}, SO_LENH, 24500, 0.318, date(2026, 10, 18), 0.04)
    assert kq["Ngày còn lại"] == 122 and kq["Giá mua"] == 1250 and kq["Nguồn giá mua"] == "ask"
    assert kq["Giá hợp lý"] == 1910 and kq["Delta"] == 0.73 and kq["Đòn bẩy"] == 9.0  # delta 0,727 × 24.500 / (1.250 × 1,5863)
    assert kq["CS tăng % để hòa vốn"] == 0.4  # (22.605 + 1.250 × 1,5863) / 24.500 − 1 = 0,36%
    assert math.isnan(kq["IV %"]) and kq["Ghi chú IV"].startswith("giá mua dưới mức tối thiểu")
    assert kq["Đánh giá"] == "NÊN XEM XÉT"  # dưới mức tối thiểu được tính là đạt tiêu chí 2


def test_so_iv_cung_ma():
    # A rẻ bất thường: IV 5% < 50% × trung vị (40, 45, 50) = 22,5%; B bình thường; FPT chỉ có 1 CW khác -> không so
    df = pd.DataFrame({"Mã CW": ["A", "B", "C", "D", "E", "F1", "F2"], "Mã CS": ["VPB"] * 5 + ["FPT"] * 2,
                       "IV %": [5.0, 40.0, 45.0, 50.0, math.nan, 30.0, 3.0]})
    tv, cb = so_iv_cung_ma(df, "A", "VPB", 5.0)
    assert tv == 45 and cb.startswith("IV 5% chỉ bằng 11% trung vị 45% của 3 CW VPB khác")
    assert so_iv_cung_ma(df, "B", "VPB", 40.0) == (45, "")  # trung vị (5, 45, 50) = 45; 40 ≥ 22,5
    assert so_iv_cung_ma(df, "E", "VPB", math.nan)[1] == ""  # không giải được IV: đã có cảnh báo riêng
    assert math.isnan(so_iv_cung_ma(df, "F2", "FPT", 3.0)[0])


def test_doc_cw_sap_ra_mat():
    # Đọc đúng dữ liệu kiểu HOSE (ngày dạng giây Unix), thiếu trường thì không lỗi
    hose = {"data": {"list": [{"acceptDate": 1791331200, "listingVolume": 6000000.0, "listingdbSecuritiesCoveredWarrant": {
        "cwname": "Chứng quyền ACB/MSVN/7M/0126", "underlyingSymbol": "ACB", "exPrice": 20600.0, "exRatio": "2:1",
        "maturityDate": 1810684800, "deadline": 7.0}}, {"name": "thiếu dữ liệu"}]}}
    cw = doc_cw_sap_ra_mat(hose)
    assert cw[0]["ma_cs"] == "ACB" and cw[0]["ngay_chap_thuan"] == date(2026, 10, 7) and cw[0]["ngay_dao_han"] == date(2027, 5, 19)
    assert cw[1]["ma_cs"] == "" and cw[1]["ngay_dao_han"] is None and doc_cw_sap_ra_mat({}) == []


def test_doc_ty_le():
    assert doc_ty_le("1.7245:1") == 1.7245 and doc_ty_le("10.0:1") == 10


def test_danh_gia():
    assert danh_gia(120, -0.05, 0.08, 50_000) == ("NÊN XEM XÉT", "đạt cả 4 tiêu chí")
    assert danh_gia(30, -0.05, 0.08, 50_000)[0] == "THEO DÕI"
    assert danh_gia(30, 0.50, 0.08, 50_000)[0] == "BỎ QUA"
    # Tiêu chí 2: IV − HV ≤ +3 điểm; −inf (giá dưới mức tối thiểu) đạt; +inf (giá cao bất thường) trượt
    assert danh_gia(120, 0.03, 0.08, 50_000)[0] == "NÊN XEM XÉT"
    assert danh_gia(120, 0.031, 0.08, 50_000) == ("THEO DÕI", "IV cao hơn lịch sử +3,1 điểm")
    assert danh_gia(120, -math.inf, 0.08, 50_000)[0] == "NÊN XEM XÉT"
    assert danh_gia(120, math.inf, 0.08, 50_000) == ("THEO DÕI", "giá mua cao bất thường")


def test_nguong_iv_quanh_tien():
    # Vì sao +3 điểm: CW quanh tiền (S = K = 30.000, 120 ngày, σ = 30%) đắt 10% về giá <=> IV ≈ 33,3% (+3,3 điểm),
    # đúng như xấp xỉ giá ≈ 0,4 × S × σ × √T (tỉ lệ thuận với σ)
    p = black_scholes_call(30000, 30000, 120 / 365, 0.04, 0.30)[0]
    assert abs(bien_dong_ngam_dinh(1.1 * p, 30000, 30000, 120 / 365, 0.04, 1) - 0.333) < 0.001


def test_doc_env():
    with tempfile.TemporaryDirectory() as tmp:
        env = Path(tmp) / ".env"
        env.write_text('# ghi chú\nVNSTOCK_API_KEY = "abc=123"\nTRONG=\n', encoding="utf-8")
        assert doc_env(env) == {"VNSTOCK_API_KEY": "abc=123", "TRONG": ""}
        assert doc_env(Path(tmp) / "khong_co") == {}


if __name__ == "__main__":  # chạy không cần pytest: gọi lần lượt mọi hàm test_*, lỗi thì dừng và báo
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - công thức đúng")
