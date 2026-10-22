"""Kiểm tra etf.py bằng dữ liệu giả (không gọi mạng). Chạy: python -m pytest -q   hoặc   python test_etf.py"""

import math
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import pandas as pd

import cw_scanner
import etf as E

HOM_NAY = date(2026, 10, 22)  # thứ Năm


def chuoi(ngay_gia):
    return pd.Series([g for _, g in ngay_gia], pd.DatetimeIndex([pd.Timestamp(d) for d, _ in ngay_gia]))


def df_vnstock(gia, ket_thuc=HOM_NAY, kl=1000):
    """DataFrame giống vnstock: giờ 07:00 múi giờ Việt Nam, mỗi ngày làm việc 1 dòng."""
    t = pd.bdate_range(end=ket_thuc, periods=len(gia)).tz_localize("Asia/Ho_Chi_Minh") + pd.Timedelta(hours=7)
    return pd.DataFrame({"time": t, "close": gia, "volume": kl})


def test_loi_nhuan_theo_thang_lich():
    g = chuoi([("2026-01-15", 100), ("2026-02-13", 110), ("2026-03-16", 121)])
    # mốc 1 tháng = 16/02 -> phiên gần nhất trước đó 13/02 (110): 121 / 110 − 1 = 10%
    assert math.isclose(E.loi_nhuan(g, date(2026, 3, 16), 1), 0.10)
    assert math.isnan(E.loi_nhuan(g, date(2026, 3, 16), 3))  # mốc 16/12/2025: quỹ chưa có giá
    # 31/03 − 1 tháng = 28/02 (không có ngày 31/02): phiên 13/02 -> 121 / 110 − 1
    assert math.isclose(E.loi_nhuan(g, date(2026, 3, 31), 1), 0.10)


def test_rsi_wilder_tinh_tay():
    # n = 2, giá 1, 2, 3, 2, 4: thay đổi +1, +1, −1, +2
    # 2 phiên đầu: TB tăng 1, TB giảm 0; phiên −1: tăng (1 + 0)/2 = 0,5, giảm (0 + 1)/2 = 0,5 -> RSI 50
    assert math.isclose(E.rsi(pd.Series([1.0, 2, 3, 2]), 2), 50)
    # phiên +2: tăng (0,5 + 2)/2 = 1,25, giảm (0,5 + 0)/2 = 0,25 -> RS 5 -> RSI 100 − 100/6 = 83,33
    assert math.isclose(E.rsi(pd.Series([1.0, 2, 3, 2, 4]), 2), 100 - 100 / 6)
    assert E.rsi(pd.Series([1.0, 2, 3]), 2) == 100  # chỉ tăng
    assert math.isnan(E.rsi(pd.Series([5.0] * 20)))  # đứng yên: không xác định
    assert math.isnan(E.rsi(pd.Series([1.0, 2])))  # chưa đủ 14 phiên


def test_xu_huong_theo_ma50_ma200():
    assert E.xu_huong(pd.Series(range(1, 201), dtype=float)) == "Tăng"
    assert E.xu_huong(pd.Series(range(200, 0, -1), dtype=float)) == "Giảm"
    # 150 phiên 100, 49 phiên 90, phiên cuối 120: MA200 = (15.000 + 4.410 + 120)/200 = 97,65;
    # MA50 = (4.410 + 120)/50 = 90,6 < MA200 nhưng giá 120 > MA200 -> đi ngang
    assert E.xu_huong(pd.Series([100.0] * 150 + [90.0] * 49 + [120.0])) == "Đi ngang"
    assert E.xu_huong(pd.Series([1.0] * 199)) == ""


def test_bien_dong_nam_tinh_tay():
    # ln(110/100) = 0,09531; ln(99/110) = −0,10536; độ lệch chuẩn mẫu 0,14190 × √250 = 2,2436
    assert math.isclose(E.bien_dong_nam(pd.Series([100.0, 110, 99])), 2.2436, rel_tol=1e-4)


def test_giam_tu_dinh_trong_1_nam():
    g = chuoi([("2024-06-03", 200), ("2026-01-05", 100), ("2026-03-02", 120), ("2026-06-01", 90), ("2026-10-22", 108)])
    # bỏ giá 200 (quá 1 năm); đỉnh 120: sâu nhất 90/120 − 1 = −25%, hiện tại 108/120 − 1 = −10%
    sut, cach_dinh = E.giam_tu_dinh(g, HOM_NAY)
    assert math.isclose(sut, -0.25) and math.isclose(cach_dinh, -0.10)


def test_gtgd_tinh_ca_phien_khong_khop():
    lich = pd.bdate_range(end=HOM_NAY, periods=30)
    gia = pd.Series([10_000.0, 20_000.0], [lich[-1], lich[-5]])
    kl = pd.Series([1_000.0, 500.0], [lich[-1], lich[-5]])
    # (10.000 × 1.000 + 20.000 × 500) / 20 phiên = 1.000.000 đ/phiên
    assert E.gtgd_trung_binh(gia, kl, lich) == 1_000_000


def test_chuoi_gia_bo_phien_khong_khop_va_doi_don_vi():
    df = df_vnstock([20.0, 21.0, 22.0], kl=[100, 0, 300])
    gia, kl = E.chuoi_gia(df, 1000)
    assert list(gia) == [20_000, 22_000] and list(kl) == [100, 300]
    assert gia.index[-1] == pd.Timestamp(HOM_NAY)  # bỏ giờ và múi giờ: so được với lịch VNINDEX


def test_moi_quy_chi_thuoc_1_chi_so():
    tat_ca = [m for ds in E.QUY_THEO_CHI_SO.values() for m in ds]
    assert len(tat_ca) == len(set(tat_ca))


def bang_gia_mau(ma, gia, **khop):
    ny = {"symbol": ma, "refPrice": gia, "tradingDate": str(HOM_NAY), "listedShare": 100_000_000}
    return ny, {"matchPrice": gia, **khop}, {}


def du_lieu_mau():
    n = 300
    tang = [1.0 + 0.3 * i / (n - 1) for i in range(n)]  # chỉ số theo đơn vị vnstock (điểm / 1.000)
    ls_cs = {"VNINDEX": df_vnstock(tang), "VN30": df_vnstock(tang), "VNDIAMOND": "InputError: không có mã"}
    ls_quy = {
        # lịch sử (nghìn đồng) dừng ở hôm qua: phiên hôm nay lấy từ bảng giá
        "E1VFVN30": df_vnstock([20.0] * (n - 1), ket_thuc=date(2026, 10, 21), kl=10_000),
        "FUEVN50G": df_vnstock([15.0] * 50),
        "FUEBFVND": "NetworkError: hết thời gian chờ",
    }
    bang_gia = {
        "E1VFVN30": bang_gia_mau(
            "E1VFVN30",
            26_000,
            accumulatedValue=5_000,  # triệu đồng
            accumulatedVolume=200_000,
            foreignBuyValue=3e9,
            foreignSellValue=1e9,
        ),
        "FUEVN50G": bang_gia_mau("FUEVN50G", 15_000, accumulatedValue=0),
        "FUEBFVND": bang_gia_mau("FUEBFVND", 9_000),
    }
    return ["E1VFVN30", "FUEBFVND", "FUEVN50G"], ls_quy, ls_cs, bang_gia


def test_lap_bang():
    df, ngay = E.lap_bang(*du_lieu_mau(), HOM_NAY)
    assert ngay == HOM_NAY and list(df.columns) == E.COT
    h = df.set_index("Mã").loc["E1VFVN30"]
    # 20,0 nghìn đồng × 1.000 = 20.000 đ suốt 1 năm, hôm nay khớp 26.000 đ -> 1N = 26.000 / 20.000 − 1 = +30%
    assert h["Giá"] == 26_000 and h["1N %"] == 30.0 and h["Ngày giá cuối"] == str(HOM_NAY)
    assert h["GTGD hôm nay (tỷ)"] == 5.0 and h["Khối ngoại ròng (tỷ)"] == 2.0 and h["CCQ lưu hành"] == 100_000_000
    assert h["Chỉ số"] == "VN30" and h["Cảnh báo"] == ""
    cs = df.set_index("Mã").loc["VN30"]
    assert cs["Loại"] == "Chỉ số" and math.isclose(cs["Giá"], 1300)  # 1,3 × 1.000 điểm
    g = df.set_index("Mã").loc["FUEVN50G"]
    assert g["Chỉ số"] == "VNINDEX" and "chưa có trong danh sách" in g["Cảnh báo"] and "chỉ 50 phiên" in g["Cảnh báo"]
    assert "NetworkError" in df.set_index("Mã").loc["FUEBFVND", "Cảnh báo"]
    assert "không lấy được lịch sử chỉ số" in df.set_index("Mã").loc["VNDIAMOND", "Cảnh báo"]


def test_bao_cao():
    df, ngay = E.lap_bang(*du_lieu_mau(), HOM_NAY)
    truoc = df.copy()
    truoc.loc[truoc["Mã"] == "E1VFVN30", ["CCQ lưu hành", "Xu hướng"]] = [98_000_000, "Đi ngang"]
    bc = E.bao_cao(df, truoc, datetime(2026, 10, 22, 15, 30), ngay)
    assert bc.startswith("**📊 Báo cáo ETF** (15:30 22/10)") and bc.count("```") % 2 == 0
    assert "E1VFVN30: Đi ngang → **Tăng**" in bc
    # +2.000.000 CCQ / 98.000.000 = +2,0%; × 26.000 đ = 52,0 tỷ
    assert "E1VFVN30: +2.000.000 CCQ (+2,0%, ≈ 52,0 tỷ)" in bc
    assert "Mua ròng: E1VFVN30 2,0" in bc
    assert "⚠ **FUEBFVND**" in bc and "Không phải lời khuyên" not in bc
    assert E.bao_cao(df, None, datetime(2026, 10, 22, 15, 30), ngay)  # chưa có ngày trước: bỏ phần so sánh


def test_luu_doc_lai_va_trang_web():
    import web

    df, _ = E.lap_bang(*du_lieu_mau(), HOM_NAY)
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cw_scanner, "THU_MUC_KET_QUA", Path(tmp)):
        assert E.doc_ket_qua() == (None, None) and "Chưa có kết quả" in web.trang_etf()
        df.to_csv(Path(tmp) / f"etf_{HOM_NAY}.csv", index=False, encoding="utf-8-sig")
        doc, ngay = E.doc_ket_qua()
        assert ngay == HOM_NAY and doc["Cảnh báo"].tolist() == df["Cảnh báo"].tolist()
        assert E.doc_ket_qua(truoc=HOM_NAY) == (None, None)  # chỉ có file hôm nay: không có phiên trước để so
        trang = web.trang_etf()
        # so CS của E1VFVN30 = 1N của quỹ (+30%) − 1N của đúng chỉ số nó mô phỏng (VN30), ghép theo tên chỉ số
        so_cs = 30.0 - df.set_index("Mã").loc["VN30", "1N %"]
        assert f'data-v="{so_cs}">{web.so(so_cs, 1, True)}</td>' in trang and 'href="/etf/E1VFVN30"' in trang
        assert "Cảnh báo dữ liệu (3)" in trang  # VNDIAMOND (chỉ số lỗi), FUEBFVND (lỗi dữ liệu), FUEVN50G (chưa ánh xạ)
        assert web.trang_etf_chi_tiet("ZZZ") is None  # mã không có trong file kết quả: 404
        with mock.patch.object(cw_scanner, "lay_gia_dong_cua", side_effect=RuntimeError("mất mạng")):
            ct = web.trang_etf_chi_tiet("E1VFVN30")
        assert "26.000 đ" in ct and "Không tải được lịch sử giá: mất mạng" in ct


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - ETF đúng")
