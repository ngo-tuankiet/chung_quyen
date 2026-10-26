"""Kiểm tra công thức. Chạy: python -m pytest -q   hoặc   python test_cw_scanner.py (không cần cài pytest)."""

import ast
import contextlib
import io
import math
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

import cw_scanner
from cw_scanner import (
    bien_dong_ngam_dinh,
    black_scholes_call,
    can_duoi,
    danh_gia,
    dinh_gia,
    doc_cw_sap_ra_mat,
    doc_env,
    doc_ty_le,
    gia_mua,
    lech_20_phien,
    lech_theo_cs,
    lich_su_iv,
    mo_phong_gia,
    rui_ro_theo_tien,
    so_iv_cung_ma,
    tong_kl,
)

# Sổ lệnh mẫu (CVPB2615 cuối phiên 16/10/2026, mức thứ 3 thiếu khối lượng)
SO_LENH = {
    "askPrices": [{"price": 1250, "volume": 30300}, {"price": 1260, "volume": 30000}, {"price": 1290, "volume": None}]
}


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
    assert (
        tong_kl(SO_LENH, "askPrices") == 60300 and tong_kl(SO_LENH, "bidPrices") == 0 and tong_kl({}, "askPrices") == 0
    )


def test_gia_mua():
    # Chào bán thấp nhất; sổ lệnh trống -> giá khớp; chưa khớp -> tham chiếu; mức giá dạng chữ (phiên ATO/ATC) bị bỏ qua
    ny, kl = {"refPrice": 1230}, {"matchPrice": 1240}
    assert gia_mua(ny, kl, SO_LENH) == (1250, "ask")
    assert gia_mua(ny, kl, {"askPrices": [{"price": "ATC", "volume": 100}, {"price": 0, "volume": 5}]}) == (
        1240,
        "khớp",
    )
    assert gia_mua(ny, {"matchPrice": 0}, {}) == (1230, "tham chiếu")


def test_cvpb2615_tinh_tay():
    # KE_HOACH Phần 1: S=24.500, K=22.605, 123 ngày, r=4%, sigma=32,8%, tỷ lệ 1,5863
    T = 123 / 365
    assert abs(black_scholes_call(24500, 22605, T, 0.04, 0.328)[0] / 1.5863 - 1944) < 2  # tài liệu: ≈ 1.944 đ
    # Mức tối thiểu = 24.500 − 22.605 × e^(−0,04 × 0,337) = 24.500 − 22.302,3 ≈ 2.197,7 đ (cho 1 cổ phiếu)
    assert abs(can_duoi(24500, 22605, T, 0.04) - 2197.7) < 0.5
    # Giá chào bán 1.250 đ × 1,5863 = 1.982,9 đ < 2.197,7 đ -> không có sigma nào khớp
    assert bien_dong_ngam_dinh(1250, 24500, 22605, T, 0.04, 1.5863) is None
    assert (
        can_duoi(20000, 22605, T, 0.04) == 0 and can_duoi(24500, 22605, 0, 0.04) == 1895
    )  # ngoài tiền -> 0; đáo hạn -> nội tại


def test_dinh_gia_cvpb2615():
    # Số liệu thật cuối phiên 16/10/2026, định giá ngày 18/10 (còn 122 ngày), sigma VPB 31,8%, r 4%
    ny = {
        "exercisePrice": 22605,
        "exerciseRatio": "1.5863:1",
        "maturityDate": "20270217",
        "refPrice": 1230,
        "underlyingSymbol": "VPB",
        "issuerName": "ACBS",
        "listedShare": 18_000_000,
        "lastTradingDate": "20270215",
    }
    kq = dinh_gia(
        ny, {"matchPrice": 1240, "accumulatedVolume": 891_900}, SO_LENH, 24500, 0.318, date(2026, 10, 18), 0.04
    )
    assert kq["Ngày còn lại"] == 122 and kq["Giá mua"] == 1250 and kq["Nguồn giá mua"] == "ask"
    assert (
        kq["Giá hợp lý"] == 1910 and kq["Delta"] == 0.73 and kq["Đòn bẩy"] == 9.0
    )  # delta 0,727 × 24.500 / (1.250 × 1,5863)
    assert kq["CS tăng % để hòa vốn"] == 0.4  # (22.605 + 1.250 × 1,5863) / 24.500 − 1 = 0,36%
    assert math.isnan(kq["IV %"]) and kq["Ghi chú IV"].startswith("giá mua dưới mức tối thiểu")
    assert kq["Đánh giá"] == "NÊN XEM XÉT"  # dưới mức tối thiểu được tính là đạt tiêu chí 2
    assert kq["Ngày GD cuối"] == "2027-02-15"
    # sổ lệnh mẫu không có người chờ mua -> không bán ra được ngay: không tính lướt
    assert math.isnan(kq["Giá chờ mua"]) and math.isnan(kq["Lướt: CS cần tăng %"]) and kq["Bên mua 3 bước (triệu)"] == 0


def test_gia_cho_mua_va_gia_tri_ben():
    so_lenh = {
        "bidPrices": [{"price": 990, "volume": 10_000}, {"price": "ATC", "volume": 500}, {"price": 980, "volume": None}]
    }
    assert cw_scanner.gia_cho_mua(so_lenh) == 990 and cw_scanner.gia_cho_mua({}) is None
    assert cw_scanner.gia_tri_ben(so_lenh, "bidPrices") == 9_900_000  # 990 × 10.000; mức chữ / không khối lượng bỏ qua


def test_so_ngay_lich():
    assert cw_scanner.so_ngay_lich(date(2026, 10, 23), 5) == 7  # thứ Sáu + 5 phiên = thứ Sáu tuần sau
    assert cw_scanner.so_ngay_lich(date(2026, 10, 21), 2) == 2  # thứ Tư -> thứ Sáu


def test_luot_ngan_han_tinh_tay():
    # CW sâu trong tiền, biến động rất thấp (r = 0): giá 1 CW ≈ (S − K) / tỷ lệ. S 30.000, K 20.000, tỷ lệ 2:
    # chờ mua 5.000,5 (≈ nội tại 5.000), chào bán 5.100
    f = lambda **k: cw_scanner.luot_ngan_han(5_100, 5_000.5, 30_000, 20_000, 2, 60, 0.0, 0, **k)
    # không phí: CW phải lên 5.100 -> S = 20.000 + 2 × 5.100 = 30.200 -> CS +0,667%
    assert abs(f(phi=0, thue=0)[0] - 200 / 30_000) < 5e-5
    # có phí 0,15% hai chiều + thuế 0,1%: CW phải bán được 5.100 × 1,0015 / 0,9975 = 5.120,45 -> S = 30.240,9 -> +0,803%
    hoa_von, lai = f()
    assert abs(hoa_von - 240.9 / 30_000) < 5e-5
    # CS +5% = 31.500 -> CW ≈ 5.750: 5.750 × 0,9975 / (5.100 × 1,0015) − 1 = 5.735,63 / 5.107,65 − 1 = +12,29%
    assert abs(lai - 0.12295) < 1e-3
    # CW quanh giá thực hiện: giữ càng lâu càng mất giá theo thời gian -> CS phải tăng nhiều hơn để hòa vốn
    atm = lambda ngay_giu: cw_scanner.luot_ngan_han(1_050, 1_000, 20_000, 20_000, 2, 60, 0.04, ngay_giu)[0]
    assert 0 < atm(0) < atm(7) < atm(14)
    # giá chờ mua dưới mức tối thiểu (S − K) / tỷ lệ = 5.000: không giải được IV -> không tính
    assert math.isnan(cw_scanner.luot_ngan_han(5_100, 4_900, 30_000, 20_000, 2, 60, 0.0, 7)[0])


def test_luot_ngan_han_hieu_chinh_iv():
    # CW sâu trong tiền như trên, IV kịch bản ≤ 0 (d_iv = −1): Black-Scholes chỉ còn nội tại (r = 0). CS +5% = 31.500 -> bán đúng
    # (31.500 − 20.000) / 2 = 5.750: 5.750 × 0,9975 / (5.100 × 1,0015) − 1 = 5.735,625 / 5.107,65 − 1 = +12,2948%
    f = lambda d_iv: cw_scanner.luot_ngan_han(5_100, 5_000.5, 30_000, 20_000, 2, 60, 0.0, 0, d_iv=d_iv)
    assert math.isclose(f(-1.0)[1], 5_735.625 / 5_107.65 - 1, rel_tol=1e-12)
    assert abs(f(-1.0)[1] - 0.122948) < 1e-6
    assert f(-1.0)[0] == f(0.0)[0]  # hòa vốn không đổi: d_iv chỉ áp vào kịch bản
    # CW quanh giá: IV kịch bản thấp hơn thì lãi kịch bản thấp hơn
    atm = lambda d_iv: cw_scanner.luot_ngan_han(1_050, 1_000, 20_000, 20_000, 2, 60, 0.04, 7, d_iv=d_iv)[1]
    assert atm(-0.05) < atm(0.0) < atm(0.05)


def test_lai_kb_hieu_chinh_va_doc_he_so_iv():
    h = {"Giá mua": 1_050, "Giá chờ mua": 1_000, "Giá CS": 20_000, "Giá thực hiện": 20_000, "Tỷ lệ CĐ": 2.0}
    h |= {"Ngày còn lại": 60, "r %": 4.0}
    df = pd.DataFrame([h | {"TCPH": t} for t in ("A", "B", "C")])
    # quét thứ Sáu 23/10/2026 + 5 phiên = 7 ngày lịch; β −0,64 điểm IV / 1% CS × kịch bản +5% = IV −3,2 điểm
    lai = lambda d_iv: round(
        cw_scanner.luot_ngan_han(1_050, 1_000, 20_000, 20_000, 2, 60, 0.04, 7, d_iv=d_iv)[1] * 100, 1
    )
    kq = cw_scanner.lai_kb_hieu_chinh(df, date(2026, 10, 23), {"A": 0.0, "B": -0.64})
    assert (
        kq[:2] == [lai(0.0), lai(-0.032)] and kq[1] < kq[0] and math.isnan(kq[2])
    )  # β = 0: đúng cột gốc; C: không có β
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cw_scanner, "THU_MUC_KET_QUA", Path(tmp)):
        assert cw_scanner.doc_he_so_iv() == (None, {})
        b = pd.DataFrame({"TCPH": ["ACBS", "ACBS", "KAFI"], "Chiều CS": ["tăng", "giảm", "tăng"]})
        b = b.assign(**{"Cửa sổ β": [245, 225, 49], "β": [-0.64, -0.68, -0.02]})
        b.to_csv(Path(tmp) / "he_so_iv_tcph_2026-10-23.csv", index=False, encoding="utf-8-sig")
        b.assign(β=0.0).to_csv(Path(tmp) / "he_so_iv_tcph_2026-10-01.csv", index=False, encoding="utf-8-sig")
        # file mới nhất; chiều "tăng" (KICH_BAN_TANG > 0); KAFI 49 cửa sổ < MIN_MAU_HE_SO_IV = 50: không hiệu chỉnh
        assert cw_scanner.doc_he_so_iv() == ("he_so_iv_tcph_2026-10-23.csv", {"ACBS": -0.64})


def test_chon_luot():
    hang = lambda ma, **k: {
        "Mã CW": ma,
        "Nguồn giá mua": "ask",
        "Giá chờ mua": 1_000,
        "Bên mua 3 bước (triệu)": 50.0,
        "Spread %": 2.0,
        "Ngày GD cuối": "2026-12-30",
        "Ngày còn lại": 70,
        "Lướt: CS cần tăng %": 1.5,
        "Lướt: lãi kịch bản %": 20.0,
        **k,
    }
    df = pd.DataFrame(
        [
            hang("A", **{"Lướt: CS cần tăng %": 1.2}),
            hang("B", **{"Spread %": 6.0}),
            hang("C", **{"Bên mua 3 bước (triệu)": 10.0}),
            hang("D", **{"Nguồn giá mua": "khớp"}),
            hang("E", **{"Ngày GD cuối": "2026-11-05"}),  # 23/10 -> 05/11 = 13 ngày
            hang("F", **{"Lướt: CS cần tăng %": math.nan}),
            hang("G"),
            hang("H", **{"Giá chờ mua": math.nan}),
        ]
    )
    dat, loai = cw_scanner.chon_luot(df, date(2026, 10, 23))
    assert list(dat["Mã CW"]) == ["A", "G"]  # CS cần tăng ít nhất trước
    ly_do = dict(zip(loai["Mã CW"], loai["Lý do loại lướt"]))
    assert ly_do == {
        "B": "spread 6,0%",
        "C": "bên mua chỉ 10,0 triệu",
        "D": "không có người chào bán",
        "E": "còn 13 ngày tới GD cuối",
        "F": "không tính được hòa vốn (giá chờ mua dưới mức tối thiểu)",
        "H": "không có người chờ mua",
    }


def test_so_iv_cung_ma():
    # A rẻ bất thường: IV 5% < 50% × trung vị (40, 45, 50) = 22,5%; B bình thường; FPT chỉ có 1 CW khác -> không so
    df = pd.DataFrame(
        {
            "Mã CW": ["A", "B", "C", "D", "E", "F1", "F2"],
            "Mã CS": ["VPB"] * 5 + ["FPT"] * 2,
            "IV %": [5.0, 40.0, 45.0, 50.0, math.nan, 30.0, 3.0],
        }
    )
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
    # Hòa vốn có phí, thuế 0,1% trên giá trị danh nghĩa CS: (22.605 + 1,5863 × 1.250 × 1,0015) / 0,999
    # = (22.605 + 1.985,85) / 0,999 = 24.615,5
    assert abs(rr["hoa_von_phi"] - 24615.5) < 0.5
    assert abs(rr["giam_ve_0"] - (22605 / 24500 - 1)) < 1e-9  # -7,73%
    assert 0.2 < rr["xs_ve_0"] < 0.4  # N(−d2) với σ 31,8%, 122 ngày
    assert rr["mat_khi_giam_1pct"] == 7900 * 1250 * 9.0 / 100  # đòn bẩy 9x: CS −1% ≈ CW −9%
    assert (
        rui_ro_theo_tien(1_000_000, 1250, 22000, 22605, 1.5863, 0, 0.04, 0.318, 9.0)["xs_ve_0"] == 1.0
    )  # đáo hạn, ngoài tiền


def test_doc_von():
    # Tham số ?von= từ URL: chỉ nhận số nguyên 1..10.000 (triệu đồng), còn lại về mặc định 10
    from web_chung import doc_von

    assert doc_von("/cw/CVPB2615?von=50") == 50 and doc_von("/cw/CVPB2615") == 10
    assert all(
        doc_von(f"/cw/CVPB2615?von={x}") == 10 for x in ("-5", "abc", "0", "10001", "1e3", "5.5", "%3Cscript%3E")
    )


def test_doc_ghi_file_luon_co_encoding():
    # Windows không mặc định UTF-8: đọc/ghi file thiếu encoding thì tiếng Việt trong JSON (danh sách HOSE) làm lỗi lưu/đọc
    # Duyệt cây cú pháp (không theo dòng): black có thể tách một lời gọi ra nhiều dòng
    for ten in ("cw_scanner.py", "danh_muc.py", "etf.py", *(p.name for p in Path(__file__).parent.glob("web*.py"))):
        cay = ast.parse((Path(__file__).parent / ten).read_text(encoding="utf-8"))
        for n in ast.walk(cay):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("read_text", "write_text"):
                assert any(k.arg == "encoding" for k in n.keywords), f"{ten}:{n.lineno} thiếu encoding"


def test_cu_phap_chay_duoc_tu_python_310():
    # Script cài đặt nhận Python 3.10+: cú pháp chỉ có từ 3.12 (vd f-string lồng nhau dùng lại cùng dấu nháy) làm web.py
    # không khởi động được trên 3.10/3.11. Python mới hơn không tự bắt được -> dùng ruff với target 3.10.
    ruff = Path(sys.executable).with_name("ruff")
    if not ruff.exists():  # chưa cài công cụ dev (requirements-dev.txt): bỏ qua
        return
    tep = [str(f) for f in Path(__file__).parent.glob("*.py")]
    kq = subprocess.run(
        [str(ruff), "check", "--target-version", "py310", "--select", "F821", *tep],
        capture_output=True,
        text=True,
        check=False,
    )  # tự đọc kết quả bên dưới
    assert "invalid-syntax" not in kq.stdout, kq.stdout


def test_ly_do_dinh_dang_so_viet_nam():
    assert danh_gia(120, -0.05, 0.08, 5_700)[1] == "ít giao dịch (5.700 CW)"


def test_main_bo_qua_ma_khong_co_lich_su():
    # Mã cơ sở BBB không có lịch sử giá -> nhật ký báo "bị bỏ qua" thì CW của BBB KHÔNG được có trong kết quả
    dao_han = (date.today() + timedelta(days=120)).strftime("%Y%m%d")
    cw = lambda cs: (
        {
            "underlyingSymbol": cs,
            "exercisePrice": 20000,
            "exerciseRatio": "2:1",
            "maturityDate": dao_han,
            "refPrice": 1500,
            "issuerName": "TEST",
            "listedShare": 1_000_000,
            "lastTradingDate": dao_han,
        },
        {"matchPrice": 1500, "accumulatedVolume": 50_000},
        SO_LENH,
    )
    bang = {
        "CAAA2601": cw("AAA"),
        "CBBB2601": cw("BBB"),
        "AAA": ({"refPrice": 21000}, {"matchPrice": 21000}, {}),
        "BBB": ({"refPrice": 21000}, {"matchPrice": 21000}, {}),
    }

    class Quote:
        def __init__(self, source, symbol):
            self.ma = symbol

        def history(self, **_):
            if self.ma == "BBB":
                return pd.DataFrame({"time": [], "close": []})
            return pd.DataFrame(
                {
                    "time": [date.today() - timedelta(days=i) for i in range(30, 0, -1)],
                    "close": [21 + (i % 3) * 0.3 for i in range(30)],
                }
            )  # nghìn đồng như vnstock

    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.multiple(
            cw_scanner,
            doc_env=dict,
            Quote=Quote,
            lay_bang_gia=lambda ds, cho=30: {m: bang[m] for m in ds},
            Listing=lambda source: mock.Mock(all_covered_warrant=lambda: ["CAAA2601", "CBBB2601"]),
            tai_du_lieu_hose_cw=lambda **_: {"data": {"list": []}},
            THU_MUC_KET_QUA=Path(tmp),
            FILE_CW_DA_BIET=Path(tmp) / "cw_da_biet.txt",
        ),
        contextlib.redirect_stdout(io.StringIO()) as nhat_ky,
    ):
        cw_scanner.main()
        ket_qua = pd.read_csv(next(Path(tmp).glob("cw_*.csv")), encoding="utf-8-sig")
    assert "Không lấy được lịch sử giá BBB (các CW của mã này bị bỏ qua)" in nhat_ky.getvalue()
    assert list(ket_qua["Mã CW"]) == ["CAAA2601"]


def test_lech_theo_cs():
    # CVPB2615: mốc 01/10 giá CW tạo từ sigma 30%; 19/10 VPB 25.000. Giá thực tế đúng bằng giá lẽ ra -> lệch 0;
    # bằng 80% giá lẽ ra -> lệch −20%
    K, n, dh, r = 22605, 1.5863, date(2027, 2, 17), 0.04
    d0, d1 = date(2026, 10, 1), date(2026, 10, 19)
    P0 = black_scholes_call(23000, K, (dh - d0).days / 365, r, 0.30)[0] / n
    le_ra = black_scholes_call(25000, K, (dh - d1).days / 365, r, 0.30)[0] / n
    lech, r_dung = lech_theo_cs(P0, 23000, d0, le_ra, 25000, d1, K, n, dh, r)
    assert abs(lech) < 1e-4 and r_dung == r
    assert abs(lech_theo_cs(P0, 23000, d0, 0.8 * le_ra, 25000, d1, K, n, dh, r)[0] + 0.20) < 1e-4
    # giá mốc 1.250 dưới mức tối thiểu (~2.198 cho 1 CP) -> tính bằng r = 0
    assert lech_theo_cs(1250, 24500, d0, 1300, 24600, d1, K, n, dh, r)[1] == 0.0


def test_lech_20_phien():
    # Giá CW tạo từ sigma 30% mỗi ngày -> lệch 0; phiên đầu khớp ít (500 CW) không được làm mốc; ngày thiếu giá CS bỏ qua
    K, n, dh, r = 22605, 1.5863, date(2027, 2, 17), 0.04
    gia_cs = {"2026-10-13": 24000.0, "2026-10-14": 24400.0, "2026-10-15": 24300.0, "2026-10-16": 24500.0}
    gia_cw = {
        d: black_scholes_call(S, K, (dh - date.fromisoformat(d)).days / 365, r, 0.30)[0] / n for d, S in gia_cs.items()
    }
    gia_cw["2026-10-12"] = 999.0  # không có giá CS
    kl = {"2026-10-13": 500, "2026-10-14": 50_000, "2026-10-15": 40_000, "2026-10-16": 30_000}
    moc, hang = lech_20_phien(gia_cw, kl, gia_cs, K, n, dh, r)
    assert moc == "2026-10-14" and [h[0] for h in hang] == ["2026-10-14", "2026-10-15", "2026-10-16"]
    assert all(abs(h[4]) < 1e-4 for h in hang) and abs(hang[-1][1] - (24500 / 24400 - 1)) < 1e-12
    assert lech_20_phien(gia_cw, {}, gia_cs, K, n, dh, r) == (None, [])  # không phiên nào đủ thanh khoản


def test_lech_hien_tai_doi_don_vi_va_lay_phien_cuoi():
    # Lịch sử vnstock theo nghìn đồng; CW 16/10 cao hơn mức lẽ ra theo CS 10% -> lệch hiện tại +10%, mốc 14/10 (13/10 khớp ít)
    K, n, dh, r = 22605, 1.5863, date(2027, 2, 17), 0.04
    gia_cs = {"2026-10-13": 24000.0, "2026-10-14": 24400.0, "2026-10-15": 24300.0, "2026-10-16": 24500.0}
    gia = {
        d: black_scholes_call(S, K, (dh - date.fromisoformat(d)).days / 365, r, 0.30)[0] / n for d, S in gia_cs.items()
    }
    gia["2026-10-16"] *= 1.10
    df = pd.DataFrame(
        {"time": list(gia), "close": [g / 1000 for g in gia.values()], "volume": [500, 50_000, 40_000, 30_000]}
    )
    with mock.patch.object(cw_scanner, "lay_gia_dong_cua", return_value=df):
        lech, moc = cw_scanner.lech_hien_tai("CVPB2615", gia["2026-10-16"], gia_cs, K, n, dh, r)
    assert moc == "2026-10-14" and abs(lech - 0.10) < 1e-6


def test_cot_lech_tren_web():
    import web_chung as web

    df = pd.DataFrame([{c: math.nan for c in web.COT_SO_LUOT} for _ in range(3)])
    goc = {
        "Mã CW": "CA",
        "Mã CS": "VPB",
        "TCPH": "X",
        "Mới": "",
        "Cảnh báo": "",
        "Ghi chú IV": "",
        "Nguồn giá mua": "ask",
    }
    goc |= {"Ngày còn lại": 90, "Giá mua": 1000, "Giá hợp lý": 1100, "Đắt/rẻ %": -9.1, "IV %": 30.0, "IV − HV": -2.0}
    goc |= {"CS tăng % để hòa vốn": 5.0, "Đòn bẩy": 6.0, "Delta": 0.5, "KL khớp": 10_000, "KL chào bán": 5_000}
    goc |= {"Đánh giá": "THEO DÕI", "Lý do": "", "Mốc lệch": "2026-10-01"}
    for c, v in goc.items():
        df[c] = v
    df["Lệch 20 phiên %"] = [-18.2, 4.5, math.nan]
    html = web.bang(df)
    # vượt ±15% thì in đậm; trống thì "—"; mốc nằm trong title của ô
    assert "<b>-18,2%</b>" in html and ">+4,5%</td>" in html and 'title="mốc 2026-10-01"' in html
    assert html.count("</th>") == len(web.COT)  # tiêu đề và ô khớp số cột


def test_tien_dao_han_thue_tren_gia_tri_danh_nghia():
    # giá thanh toán 40.000, K 32.000, tỷ lệ 3: (40.000 − 32.000 − 0,001 × 40.000) / 3 = 7.960 / 3 = 2.653,33 đ/CW
    assert abs(cw_scanner.tien_dao_han(40_000, 32_000, 3) - 2653.333) < 1e-3
    assert cw_scanner.tien_dao_han(31_000, 32_000, 3) == 0  # không có lãi: không thực hiện, không thuế
    assert cw_scanner.tien_dao_han(32_020, 32_000, 3) < 0  # lãi 20 đ < thuế 32 đ: thuế lớn hơn tiền nhận


def test_bien_dong_lich_su_tinh_tay():
    # giá 100 -> 110 -> 99: ln 1,1 = 0,09531; ln 0,9 = −0,10536; độ lệch chuẩn mẫu 0,14190 × √250 = 2,2436
    df = pd.DataFrame({"time": ["2026-10-20", "2026-10-21", "2026-10-22"], "close": [100.0, 110.0, 99.0]})
    with mock.patch.object(cw_scanner, "lay_gia_dong_cua", return_value=df) as lay:
        sigma, n, ls = cw_scanner.bien_dong_lich_su("VPB")
    assert abs(sigma - 2.2436) < 1e-4 and n == 2 and ls[-1] == ["2026-10-22", 99.0]
    assert lay.call_args[0][1] == cw_scanner.SO_NGAY_LICH_SU_HV  # đủ ngày lịch cho 250 phiên


def test_lich_su_iv():
    # Giá CW tạo từ Black-Scholes với sigma 30% -> giải ngược ra đúng 30% mỗi ngày; ngày thiếu giá CS thì bỏ;
    # ngày giá CW dưới mức tối thiểu S − K·e^(−rT) thì ghi 0 (không có mức biến động nào khớp)
    K, ty_le, r, dao_han = 22605, 1.5863, 0.04, date(2027, 2, 17)
    gia_cs = {"2026-10-14": 24350.0, "2026-10-15": 24450.0, "2026-10-16": 24500.0}
    gia_cw = {
        d: black_scholes_call(S, K, (dao_han - date.fromisoformat(d)).days / 365, r, 0.30)[0] / ty_le
        for d, S in gia_cs.items()
    }
    gia_cw["2026-10-13"] = 1000.0  # không có giá CS ngày này -> bỏ
    gia_cw["2026-10-16"] = 1250.0  # 1.250 × 1,5863 = 1.983 < mức tối thiểu ≈ 2.198 (ca CVPB2615)
    kq = lich_su_iv(gia_cw, gia_cs, K, ty_le, dao_han, r)
    assert [d for d, _ in kq] == ["2026-10-14", "2026-10-15", "2026-10-16"]
    assert kq[0][1] == kq[1][1] == 30.0 and kq[2][1] == 0.0


def test_doc_cw_sap_ra_mat():
    # Đọc đúng dữ liệu kiểu HOSE (ngày dạng giây Unix), thiếu trường thì không lỗi
    hose = {
        "data": {
            "list": [
                {
                    "acceptDate": 1791331200,
                    "listingVolume": 6000000.0,
                    "listingdbSecuritiesCoveredWarrant": {
                        "cwname": "Chứng quyền ACB/MSVN/7M/0126",
                        "underlyingSymbol": "ACB",
                        "exPrice": 20600.0,
                        "exRatio": "2:1",
                        "maturityDate": 1810684800,
                        "deadline": 7.0,
                    },
                },
                {"name": "thiếu dữ liệu"},
            ]
        }
    }
    cw = doc_cw_sap_ra_mat(hose)
    assert (
        cw[0]["ma_cs"] == "ACB"
        and cw[0]["ngay_chap_thuan"] == date(2026, 10, 7)
        and cw[0]["ngay_dao_han"] == date(2027, 5, 19)
    )
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
