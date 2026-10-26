"""Kiểm tra kiem_chung_truyen_dan.py bằng dữ liệu giả (không gọi mạng). Chạy: python -m pytest -q   hoặc
python test_kiem_chung_truyen_dan.py"""

import math
from datetime import date
from unittest import mock

import pandas as pd
import pytest

import cw_scanner as C
import kiem_chung_truyen_dan as T

LICH = pd.bdate_range("2026-01-05", periods=10)  # T2 05/01 … T6 16/01
DK = {"ma": "CTST2601", "cs": "TST", "tcph": "X", "K": 20_000.0, "ty_le": 2.0}
DK |= {"dao_han": date(2026, 12, 31), "gd_cuoi": date(2026, 12, 29)}
# CW ngang giá: phiên a (05/01) IV 30%, phiên b (12/01, 5 phiên sau) CS +5% và TCPH hạ IV còn 27%
GIA_CS = pd.Series(20_000.0, LICH).mask(LICH >= LICH[5], 21_000.0)
NAM = lambda d: (DK["dao_han"] - d.date()).days / 365
GIA = pd.Series(C.black_scholes_call(20_000, 20_000, NAM(LICH[0]), 0.0, 0.30)[0] / 2, LICH)
GIA.iloc[5] = C.black_scholes_call(21_000, 20_000, NAM(LICH[5]), 0.0, 0.27)[0] / 2
KL = pd.Series(50_000.0, LICH)


def chay(kl=KL, dk=DK, gia_cs=GIA_CS):
    return T.cua_so(dk, GIA, kl, gia_cs, LICH, r=0.0)


def test_cua_so():
    w = chay()
    assert len(w) == 1  # 10 phiên: cửa sổ 05/01 → 12/01; cửa sổ 12/01 thiếu phiên b (19/01)
    h = w.iloc[0]
    assert h["Ngày"] == LICH[0] and math.isclose(h["CS %"], 0.05)
    assert math.isclose(h["ΔIV"], -0.03, abs_tol=1e-9) and math.isclose(h["IV a"], 0.30, abs_tol=1e-9)
    # mô hình = Black-Scholes ở S 21.000 với IV 30% giữ nguyên; thực = giá ở IV 27%
    mo_hinh = C.black_scholes_call(21_000, 20_000, NAM(LICH[5]), 0.0, 0.30)[0] / 2 / GIA[LICH[0]] - 1
    assert math.isclose(h["Mô hình %"], mo_hinh) and math.isclose(h["Thực %"], GIA[LICH[5]] / GIA[LICH[0]] - 1)
    assert h["Thực %"] < h["Mô hình %"]  # IV giảm: CW chạy ít hơn mô hình


def test_cua_so_bo_loc():
    assert chay(kl=KL.mask(LICH == LICH[5], 0.0)).empty  # phiên b CW không khớp: giá đóng cửa cũ
    assert chay(dk=DK | {"gd_cuoi": date(2026, 1, 20)}).empty  # phiên a còn 15 ngày tới GD cuối < 20
    assert chay(gia_cs=GIA_CS * 3).empty  # CS 60.000 so K 20.000: delta ≈ 1, ngoài DELTA_DO


def test_bang_he_so_tinh_tay():
    d1, d2, d3 = pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-12"), pd.Timestamp("2026-01-19")
    w = pd.DataFrame(
        {
            "Mã CW": ["A", "B", "C", "A"],
            "TCPH": ["X"] * 4,
            "Ngày": [d1, d2, d2, d3],
            "CS %": [0.05, 0.04, 0.01, -0.03],
            "ΔIV": [-0.03, -0.02, -0.01, 0.03],
            "Mô hình %": [0.50, 0.40, 0.04, -0.30],
            "Thực %": [0.30, 0.36, 0.05, -0.15],
        }
    )
    b = T.bang_he_so(w).set_index("Chiều CS")
    # tăng: β từ 2 cửa sổ |CS| ≥ 2%: −0,03 / 0,05 = −0,6 và −0,02 / 0,04 = −0,5 -> trung vị −0,55 (C: CS +1% bị loại);
    # truyền dẫn từ 2 cửa sổ |mô hình| ≥ 5%: 0,30 / 0,50 = 0,6 và 0,36 / 0,40 = 0,9 -> 0,75 (C: mô hình 4% bị loại)
    t = b.loc["tăng"]
    assert (t["Cửa sổ β"], t["Số CW"], t["Số ngày"], t["Cửa sổ truyền dẫn"]) == (2, 2, 2, 2)
    assert math.isclose(t["β"], -0.55) and math.isclose(t["Truyền dẫn"], 0.75)
    # t theo ngày: trung bình từng ngày −0,6 và −0,5 -> TB −0,55, độ lệch chuẩn 0,0707 -> t = −0,55 / (0,0707 / √2) = −11
    assert math.isclose(t["t β"], -11.0)
    # giảm: CS −3% mà IV +3 điểm -> β = 0,03 / −0,03 = −1 (cùng dấu với chiều tăng: IV đi ngược CS); −0,15 / −0,30 = 0,5
    g = b.loc["giảm"]
    assert (
        math.isclose(g["β"], -1.0) and math.isclose(g["Truyền dẫn"], 0.5) and math.isnan(g["t β"])
    )  # 1 ngày: không có t


def test_mo_hinh_hieu_chinh():
    w = chay()
    bang = pd.DataFrame({"TCPH": ["X"], "Chiều CS": ["tăng"], "Cửa sổ β": [C.MIN_MAU_HE_SO_IV], "β": [-0.6]})
    # β −0,6 × CS +5% = IV −3 điểm: 30% -> 27%, đúng IV thực phiên b -> mô hình hiệu chỉnh = thực
    assert math.isclose(T.mo_hinh_hieu_chinh(w, bang, r=0.0)[0], w["Thực %"][0], rel_tol=1e-9)
    # TCPH dưới ngưỡng mẫu: β = 0, như mô hình gốc
    it = bang.assign(**{"Cửa sổ β": [C.MIN_MAU_HE_SO_IV - 1]})
    assert math.isclose(T.mo_hinh_hieu_chinh(w, it, r=0.0)[0], w["Mô hình %"][0])
    # IV hiệu chỉnh ≤ 0: chỉ còn nội tại. S 21.000, K 10.000, tỷ lệ 2, giá a 5.000 -> (21.000 − 10.000) / 2 / 5.000 − 1 = +10%
    x = pd.DataFrame({"TCPH": ["X"], "CS %": [0.05], "S b": [21_000.0], "K": [10_000.0], "T b": [0.5]})
    x = x.assign(**{"IV a": [0.02], "Tỷ lệ": [2.0], "Giá a": [5_000.0]})
    assert math.isclose(T.mo_hinh_hieu_chinh(x, bang.assign(β=[-1.0]), r=0.0)[0], 0.10)


if __name__ == "__main__":
    for ten, f in list(globals().items()):
        if ten.startswith("test_"):
            f()
    print("OK")


def test_kiem_f_khong_kiem_duoc_ca_nao_thi_dung():
    # HOSE không trả giá thô cho CW nào -> chưa kiểm được đơn vị f, không được chạy tiếp như đã kiểm
    dk = {"ma": "CVPB2501", "cs": "VPB", "gd_cuoi": date(2025, 6, 2)}
    lich = pd.to_datetime(["2025-06-02", "2026-10-26"])
    with (
        mock.patch.object(T.C, "dang_nhap"),
        mock.patch.object(T, "gia_tho_hose", return_value=None),
        pytest.raises(ValueError, match="không kiểm được"),
    ):
        T.lay_bo_sung(lich, {"VPB": pd.Series([20000.0], index=lich[:1])}, [(dk, None, None)], {})
