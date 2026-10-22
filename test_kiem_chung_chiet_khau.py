"""Kiểm tra kiem_chung_chiet_khau.py bằng dữ liệu giả (không gọi mạng). Chạy: python -m pytest -q   hoặc
python test_kiem_chung_chiet_khau.py"""

import math

import pandas as pd

import kiem_chung_chiet_khau as K

LICH = pd.bdate_range("2026-01-05", periods=8)  # T2 05/01 … T4 14/01
# quỹ không khớp phiên 07/01 và 14/01
GIA = pd.Series([9_700.0, 9_800, 9_900, 9_700, 10_000, 10_100], LICH[[0, 1, 3, 4, 5, 6]])
NAV = pd.Series(10_000.0, LICH.drop(LICH[6]))  # chưa có NAV 13/01
d = lambda s: pd.Timestamp(f"2026-01-{s}")


def test_phien_tin_hieu():
    # 9.700 / NAV 10.000: lãi ròng 9.975 / 9.714,55 − 1 = +2,68% ≥ 2%; 9.800: +1,63%, 9.900: +0,61% -> không
    assert list(K.phien_tin_hieu(GIA, NAV)) == [d("05"), d("09")]


def test_lai_su_kien_tinh_tay():
    lenh = K.mo_phong(GIA, NAV, LICH, [d("05"), d("09")], 1).set_index("Ngày tín hiệu")
    # mua 9.700 (05/01) + phí = 9.714,55; bán 9.800 (06/01) − phí − thuế = 9.775,5 -> 60,95 / 9.714,55 = +0,6274%
    assert math.isclose(lenh.loc[d("05"), "Lãi"], 9_775.5 / 9_714.55 - 1) and lenh.loc[d("05"), "Ngày bán"] == d("06")
    assert math.isclose(lenh.loc[d("05"), "Lãi"], 0.006274, abs_tol=1e-6)
    # 09/01 -> 12/01 bán 10.000: 9.975 / 9.714,55 − 1 = +2,681% (đúng bằng lãi ròng nếu về NAV)
    assert math.isclose(lenh.loc[d("09"), "Lãi"], 0.026810, abs_tol=1e-6)
    # giữ 2 phiên: phiên đích 07/01 không khớp -> giá cũ không bán được, bán ở phiên khớp kế tiếp 08/01 (9.900), giữ 3 phiên
    hai = K.mo_phong(GIA, NAV, LICH, [d("05")], 2).iloc[0]
    assert hai["Ngày bán"] == d("08") and hai["Phiên giữ"] == 3
    assert math.isclose(hai["Lãi"], 9_875.25 / 9_714.55 - 1)  # +1,654%
    assert math.isclose(hai["CL mua"], -0.03) and math.isclose(hai["CL bán"], -0.01)  # chênh lệch thu hẹp 2 điểm
    assert math.isclose(hai["Vượt NAV"], hai["Lãi"])  # NAV đứng yên: toàn bộ lãi là nhờ chênh lệch thu hẹp
    # NAV ngày bán tăng 1% (10.100): lãi giá vẫn +1,654% nhưng vượt NAV chỉ 1,016542 / 1,01 − 1 = +0,648%
    nav_len = NAV.copy()
    nav_len[d("08")] = 10_100
    vuot = K.mo_phong(GIA, nav_len, LICH, [d("05")], 2).iloc[0]["Vượt NAV"]
    assert math.isclose(vuot, 9_875.25 / 9_714.55 / 1.01 - 1) and math.isclose(vuot, 0.006478, abs_tol=1e-6)


def test_tre_1_phien_va_lenh_chua_dong():
    # kịch bản B: tín hiệu 05/01, mua phiên khớp kế tiếp 06/01 (9.800), +1 phiên = 07/01 không khớp -> bán 08/01 (9.900)
    b = K.mo_phong(GIA, NAV, LICH, [d("05")], 1, tre=1).iloc[0]
    assert (b["Ngày mua"], b["Ngày bán"], b["Phiên giữ"]) == (d("06"), d("08"), 2)
    assert math.isclose(b["Lãi"], 9_875.25 / (9_800 * 1.0015) - 1)  # +0,617%
    assert math.isclose(b["CL tín hiệu"], -0.03) and math.isclose(b["CL mua"], -0.02)
    # chưa có phiên bán trước cuối dữ liệu -> bỏ, không tính giá cũ
    assert K.mo_phong(GIA, NAV, LICH, [d("09")], 5).empty and K.mo_phong(GIA, NAV, LICH, [d("13")], 1, tre=1).empty


def test_doc_lap_khong_chong_lenh():
    lenh = K.mo_phong(GIA, NAV, LICH, GIA.index, 2)
    # 05 -> bán 08; 06 (≤ 08) bỏ; 08 (tín hiệu đúng ngày bán, ≤ 08) bỏ; 09 -> bán 13; 12, 13 chưa có phiên bán
    assert list(lenh["Ngày tín hiệu"]) == [d("05"), d("06"), d("08"), d("09")]
    dl = K.doc_lap(lenh)
    assert list(dl["Ngày tín hiệu"]) == [d("05"), d("09")]
    t = K.tom_tat(dl)
    # 05 -> 08: +1,654%; 09 -> 13 (10.100): 10.074,75 / 9.714,55 − 1 = +3,708%; trung vị = TB = +2,681%
    assert t["n"] == 2 and math.isclose(t["Lãi TV"], (9_875.25 + 10_074.75) / 2 / 9_714.55 - 1)
    assert t["% lãi"] == 1.0
    # 13/01 không có NAV: chỉ lệnh 05 tính thu hẹp (−3% -> −1%)
    assert t["% CL hẹp"] == 1.0 and math.isclose(t["Vượt NAV TV"], 9_875.25 / 9_714.55 - 1)


def test_gia_ngoai_lich_la_loi():
    try:
        K.mo_phong(pd.Series([1.0], [d("10")]), NAV, LICH, [d("10")], 1)  # thứ Bảy
    except ValueError:
        return
    raise AssertionError("giá ngoài lịch phải báo lỗi")


def test_nhom_thanh_khoan():
    assert [K.nhom_thanh_khoan(x) for x in (1.5e9, 1e9, 5e8, 1e8, 0)] == [
        "cao ≥ 1 tỷ",
        "cao ≥ 1 tỷ",
        "vừa 0,1–1 tỷ",
        "vừa 0,1–1 tỷ",
        "mỏng < 0,1 tỷ",
    ]


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - kiểm chứng chiết khấu đúng")
