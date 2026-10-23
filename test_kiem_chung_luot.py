"""Kiểm tra kiem_chung_luot.py bằng dữ liệu giả (không gọi mạng). Chạy: python -m pytest -q   hoặc
python test_kiem_chung_luot.py"""

import math
from datetime import date

import pandas as pd

import kiem_chung_luot as L

LICH = pd.bdate_range("2026-01-05", periods=10)  # T2 05/01 … T6 16/01
# CW sâu trong tiền: S 30.000, K 10.000, tỷ lệ 1 -> giá ≈ S − K, giá trị thời gian gần 0
DK = {"ma": "CTST2601", "cs": "TST", "tcph": "X", "K": 10_000.0, "ty_le": 1.0}
DK |= {"dao_han": date(2026, 12, 31), "gd_cuoi": date(2026, 12, 29)}
GIA_CS = pd.Series(30_000.0, LICH).mask(LICH >= LICH[5], 31_000.0)  # CS +3,33% từ 12/01
GIA = pd.Series(20_010.0, LICH).mask(LICH == LICH[5], 21_005.0).mask(LICH == LICH[6], 21_105.0)
KL = pd.Series(50_000.0, LICH)


def chay(kl=KL, dk=DK, spread=10):
    return L.mo_phong(dk, GIA, kl, GIA_CS, LICH, [LICH[0]], 5, spread, r=0.0)


def test_lai_lenh_tinh_tay():
    # mua 1.000 + phí 0,15% = 1.001,5; bán 1.100 − phí − thuế 0,25% = 1.097,25 -> 1.097,25 / 1.001,5 − 1 = +9,5607%
    assert math.isclose(L.lai_lenh(1_000, 1_100), 0.095607, abs_tol=1e-6)
    assert math.isclose(L.lai_lenh(1_000, 1_000), 0.9975 / 1.0015 - 1)  # đứng giá vẫn lỗ phí + thuế ≈ −0,40%


def test_mo_phong_tinh_tay():
    h = chay().iloc[0]
    # mua 05/01: 20.010 + 5 = 20.015; bán 12/01 (5 phiên, 7 ngày lịch): 21.005 − 5 = 21.000
    # 21.000 × 0,9975 / (20.015 × 1,0015) − 1 = 20.947,5 / 20.045,02 − 1 = +4,5023%
    assert (h["Ngày bán"], h["Phiên giữ"]) == (LICH[5], 5)
    assert math.isclose(h["Lãi"], 0.045023, abs_tol=1e-6) and math.isclose(h["CS %"], 1 / 30)
    # mô hình (IV giải từ giá chờ mua 20.005 giữ nguyên): CW sâu trong tiền ≈ S2 − K = 21.000 cộng giá trị thời gian < 5 đồng
    # (ở S = 30.000 giá trị thời gian là 5) -> lãi mô hình trong khoảng [+4,5023%, 21.005 × 0,9975 / 20.045,02 − 1 = +4,5272%]
    assert 0.045022 <= h["Lãi mô hình"] <= 0.045272
    # hòa vốn: phải bán được 20.045,02 / 0,9975 = 20.095,3 -> S = 10.000 + 20.095,3 − giá trị thời gian (0…5) ≈ 30.090…30.095
    assert 0.0030 <= h["Hòa vốn"] <= 0.003177
    assert h["Ngày còn lại"] == 360 and h["Mã CS"] == "TST"


def test_phien_ban_khong_khop_va_bo_loc():
    # 12/01 CW không khớp: giá cũ không bán được -> bán 13/01 ở 21.105 − 5 = 21.100, giữ 6 phiên
    h = chay(kl=KL.mask(LICH == LICH[5], 0.0)).iloc[0]
    assert (h["Ngày bán"], h["Phiên giữ"]) == (LICH[6], 6)
    assert math.isclose(h["Lãi"], 21_100 * 0.9975 / (20_015 * 1.0015) - 1)
    assert chay(kl=KL.mask(LICH == LICH[0], 5_000.0)).empty  # ngày vào khớp < MIN_KHOI_LUONG
    assert chay(spread=1_100).empty  # spread 1.100 / 20.010 = 5,5% > 5%
    assert chay(dk=DK | {"gd_cuoi": date(2026, 1, 20)}).empty  # còn 15 ngày tới GD cuối < 20


def test_mua_tre_1_phien():
    # xếp hạng bằng giá 05/01, mua 06/01 ở 20.010 + 5, bán sau 5 phiên = 13/01 ở 21.105 − 5 = 21.100
    h = L.mo_phong(DK, GIA, KL, GIA_CS, LICH, [LICH[0]], 5, 10, r=0.0, tre=1).iloc[0]
    assert (h["Ngày vào"], h["Ngày mua"], h["Ngày bán"], h["Phiên giữ"]) == (LICH[0], LICH[1], LICH[6], 5)
    assert math.isclose(h["Lãi"], 21_100 * 0.9975 / (20_015 * 1.0015) - 1)  # +5,0002%
    assert math.isclose(h["Hòa vốn"], chay().iloc[0]["Hòa vốn"])  # điểm vẫn tính bằng giá ngày 05/01
    assert L.mo_phong(
        DK, GIA, KL.mask(LICH == LICH[1], 0.0), GIA_CS, LICH, [LICH[0]], 5, 10, tre=1
    ).empty  # 06/01 không khớp


def test_cung_cs_va_hang_nhom():
    d1, d2 = pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-12")
    lenh = pd.DataFrame(
        {
            "Ngày vào": [d1] * 5 + [d2] * 3,
            "Mã CS": ["VPB"] * 3 + ["HPG"] * 2 + ["VPB"] * 3,
            "Phiên giữ": [5] * 7 + [6],
            "Hòa vốn": [0.05, 0.01, 0.02, 0.03, 0.04, 0.01, 0.02, 0.03],
            "Lãi": [-0.02, 0.10, 0.04, 0.0, 0.0, 0.0, 0.0, 0.0],
            "CS %": [0.03] * 3 + [0.01] * 5,
            "Đòn bẩy": [9.0, 3.0, 5.0] + [1.0] * 5,
        }
    )
    # chỉ nhóm (05/01, VPB) đủ 3 CW bán đúng hạn: HPG chỉ 2 CW; (12/01, VPB) còn 2 CW sau khi bỏ lệnh giữ 6 phiên
    n = L.cung_cs(lenh, 5)
    assert len(n) == 1
    h = n.iloc[0]
    assert (h["Lãi đầu"], h["Lãi cuối"], h["Đòn bẩy đầu"]) == (0.10, -0.02, 3.0) and math.isclose(h["Chênh"], 0.12)
    assert math.isclose(h["ρ"], -1.0)  # hòa vốn càng thấp lãi càng cao
    # ngũ phân vị trong ngày: 05/01 có 5 CW -> hạng theo hòa vốn; 12/01 chỉ 3 CW -> bỏ
    x = L.hang_nhom(lenh)
    assert list(x["Nhóm hạng"]) == [5, 1, 2, 3, 4]


def test_dung_hoa_von_va_t_theo_ngay():
    lenh = pd.DataFrame({"CS %": [0.03, 0.0, 0.02], "Hòa vốn": [0.01] * 3, "Lãi": [0.05, -0.02, -0.01]})
    assert math.isclose(L.dung_hoa_von(lenh), 2 / 3)  # lệnh thứ 3: CS vượt hòa vốn mà vẫn lỗ
    ngay = pd.Series(["d1", "d1", "d2", "d3"])
    # trung bình từng ngày 2, 4, 6 -> TB 4, độ lệch chuẩn 2 -> t = 4 / (2 / √3) = 3,4641
    assert math.isclose(L.t_theo_ngay(pd.Series([1.0, 3, 4, 6]), ngay), 3.464102, abs_tol=1e-6)


if __name__ == "__main__":
    for ten, f in list(globals().items()):
        if ten.startswith("test_"):
            f()
    print("OK")
