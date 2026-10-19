"""Kiểm tra công thức. Chạy: python -m pytest -q   hoặc   python test_cw_scanner.py (không cần cài pytest)."""
import contextlib
import io
import math
import re
import tempfile
from datetime import date, timedelta
from unittest import mock
from pathlib import Path

import pandas as pd

import cw_scanner
from cw_scanner import (bien_dong_ngam_dinh, black_scholes_call, can_duoi, danh_gia, dinh_gia, doc_cw_sap_ra_mat, doc_env, doc_ty_le,
                        gia_mua, mo_phong_gia, rui_ro_theo_tien, so_iv_cung_ma, tong_kl)

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
          "underlyingSymbol": "VPB", "issuerName": "ACBS", "listedShare": 18_000_000, "lastTradingDate": "20270215"}
    kq = dinh_gia(ny, {"matchPrice": 1240, "accumulatedVolume": 891_900}, SO_LENH, 24500, 0.318, date(2026, 10, 18), 0.04)
    assert kq["Ngày còn lại"] == 122 and kq["Giá mua"] == 1250 and kq["Nguồn giá mua"] == "ask"
    assert kq["Giá hợp lý"] == 1910 and kq["Delta"] == 0.73 and kq["Đòn bẩy"] == 9.0  # delta 0,727 × 24.500 / (1.250 × 1,5863)
    assert kq["CS tăng % để hòa vốn"] == 0.4  # (22.605 + 1.250 × 1,5863) / 24.500 − 1 = 0,36%
    assert math.isnan(kq["IV %"]) and kq["Ghi chú IV"].startswith("giá mua dưới mức tối thiểu")
    assert kq["Đánh giá"] == "NÊN XEM XÉT"  # dưới mức tối thiểu được tính là đạt tiêu chí 2
    assert kq["Ngày GD cuối"] == "2027-02-15"


def test_so_iv_cung_ma():
    # A rẻ bất thường: IV 5% < 50% × trung vị (40, 45, 50) = 22,5%; B bình thường; FPT chỉ có 1 CW khác -> không so
    df = pd.DataFrame({"Mã CW": ["A", "B", "C", "D", "E", "F1", "F2"], "Mã CS": ["VPB"] * 5 + ["FPT"] * 2,
                       "IV %": [5.0, 40.0, 45.0, 50.0, math.nan, 30.0, 3.0]})
    tv, cb = so_iv_cung_ma(df, "A", "VPB", 5.0)
    assert tv == 45 and cb.startswith("IV 5% chỉ bằng 11% trung vị 45% của 3 CW VPB khác")
    assert so_iv_cung_ma(df, "B", "VPB", 40.0) == (45, "")  # trung vị (5, 45, 50) = 45; 40 ≥ 22,5
    assert so_iv_cung_ma(df, "E", "VPB", math.nan)[1] == ""  # không giải được IV: đã có cảnh báo riêng
    assert math.isnan(so_iv_cung_ma(df, "F2", "FPT", 3.0)[0])


def test_rui_ro_theo_tien_cvpb2615():
    # 10 triệu, giá mua 1.250, phí 0,15%: 10.000.000 / 1.251,875 = 7.988 -> lô 100 = 7.900 CW (8.000 CW sẽ tốn 10.015.000 đ)
    rr = rui_ro_theo_tien(10_000_000, 1250, 24500, 22605, 1.5863, 122 / 365, 0.04, 0.318, 9.0)
    assert rr["so_cw"] == 7900 and abs(rr["tien_chi"] - 9_889_812.5) < 1
    assert abs(rr["tiep_xuc"] - 7900 / 1.5863 * 24500) < 1  # ≈ 122,0 triệu đ cổ phiếu VPB
    # Hòa vốn có phí = 22.605 + 1,5863 × 1.250 × 1,0015 / 0,999 = 22.605 + 1.987,8 = 24.592,8
    assert abs(rr["hoa_von_phi"] - 24592.8) < 0.5
    assert abs(rr["giam_ve_0"] - (22605 / 24500 - 1)) < 1e-9  # -7,73%
    assert 0.2 < rr["xs_ve_0"] < 0.4  # N(−d2) với σ 31,8%, 122 ngày
    assert rr["mat_khi_giam_1pct"] == 7900 * 1250 * 9.0 / 100  # đòn bẩy 9x: CS −1% ≈ CW −9%
    assert rui_ro_theo_tien(1_000_000, 1250, 22000, 22605, 1.5863, 0, 0.04, 0.318, 9.0)["xs_ve_0"] == 1.0  # đáo hạn, ngoài tiền


def test_doc_von():
    # Tham số ?von= từ URL: chỉ nhận số nguyên 1..10.000 (triệu đồng), còn lại về mặc định 10
    from web import doc_von
    assert doc_von("/cw/CVPB2615?von=50") == 50 and doc_von("/cw/CVPB2615") == 10
    assert all(doc_von(f"/cw/CVPB2615?von={x}") == 10 for x in ("-5", "abc", "0", "10001", "1e3", "5.5", "%3Cscript%3E"))


def test_doc_ghi_file_luon_co_encoding():
    # Windows không mặc định UTF-8: đọc/ghi file thiếu encoding thì tiếng Việt trong JSON (danh sách HOSE) làm lỗi lưu/đọc
    for ten in ("cw_scanner.py", "web.py"):
        for so_dong, dong in enumerate((Path(__file__).parent / ten).read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.(read|write)_text\(", dong):
                assert "encoding=" in dong, f"{ten}:{so_dong} thiếu encoding"


def test_ly_do_dinh_dang_so_viet_nam():
    assert danh_gia(120, -0.05, 0.08, 5_700)[1] == "ít giao dịch (5.700 CW)"


def test_main_bo_qua_ma_khong_co_lich_su():
    # Mã cơ sở BBB không có lịch sử giá -> nhật ký báo "bị bỏ qua" thì CW của BBB KHÔNG được có trong kết quả
    dao_han = (date.today() + timedelta(days=120)).strftime("%Y%m%d")
    cw = lambda cs: ({"underlyingSymbol": cs, "exercisePrice": 20000, "exerciseRatio": "2:1", "maturityDate": dao_han, "refPrice": 1500,
                      "issuerName": "TEST", "listedShare": 1_000_000, "lastTradingDate": dao_han},
                     {"matchPrice": 1500, "accumulatedVolume": 50_000}, SO_LENH)
    bang = {"CAAA2601": cw("AAA"), "CBBB2601": cw("BBB"), "AAA": ({"refPrice": 21000}, {"matchPrice": 21000}, {}),
            "BBB": ({"refPrice": 21000}, {"matchPrice": 21000}, {})}

    class Quote:
        def __init__(self, source, symbol):
            self.ma = symbol

        def history(self, **_):
            if self.ma == "BBB":
                return pd.DataFrame({"time": [], "close": []})
            return pd.DataFrame({"time": [date.today() - timedelta(days=i) for i in range(30, 0, -1)],
                                 "close": [21 + (i % 3) * 0.3 for i in range(30)]})  # nghìn đồng như vnstock

    with tempfile.TemporaryDirectory() as tmp, mock.patch.multiple(
            cw_scanner, doc_env=lambda: {}, Quote=Quote, lay_bang_gia=lambda ds, cho=30: {m: bang[m] for m in ds},
            Listing=lambda source: mock.Mock(all_covered_warrant=lambda: ["CAAA2601", "CBBB2601"]),
            tai_du_lieu_hose_cw=lambda **_: {"data": {"list": []}},
            THU_MUC_KET_QUA=Path(tmp), FILE_CW_DA_BIET=Path(tmp) / "cw_da_biet.txt"), \
            contextlib.redirect_stdout(io.StringIO()) as nhat_ky:
        cw_scanner.main()
        ket_qua = pd.read_csv(next(Path(tmp).glob("cw_*.csv")), encoding="utf-8-sig")
    assert "Không lấy được lịch sử giá BBB (các CW của mã này bị bỏ qua)" in nhat_ky.getvalue()
    assert list(ket_qua["Mã CW"]) == ["CAAA2601"]


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
