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


def du_lieu_chiet_khau():
    """du_lieu_mau + FUESSV30 không khớp từ 16/10 (4 phiên), SSI và NAV cho 2 quỹ."""
    ds, ls_quy, ls_cs, bang_gia = du_lieu_mau()
    ls_quy["FUESSV30"] = df_vnstock([20.0] * 295, ket_thuc=date(2026, 10, 16), kl=10_000)
    bang_gia["FUESSV30"] = bang_gia_mau("FUESSV30", 20_000, matchPrice=0, accumulatedValue=0)
    lich = E.chuoi_gia(ls_cs["VNINDEX"])[0].index
    nav = {
        "E1VFVN30": pd.Series(
            20_000.0, lich[lich < pd.Timestamp("2026-10-21")]
        ),  # NAV đứng 20.000, trễ 2 phiên như Vietcap
        "FUESSV30": pd.Series(20_000.0, lich[lich < pd.Timestamp("2026-10-10")]),  # Vietcap ngừng cập nhật từ 09/10
        "FUEVN50G": "Vietcap IQ không có quỹ này",
    }
    ssi = {
        "E1VFVN30": {"iNAV": 27_000.0, "prevINAV": 26_900.0, "best1Offer": 26_000, "best1OfferVol": 1_000},
        "FUESSV30": {"iNAV": 21_000.0, "best1Offer": 20_000, "best1OfferVol": 1_000},
    }
    return ds + ["FUESSV30"], ls_quy, ls_cs, bang_gia, HOM_NAY, ssi, nav


def test_lap_bang_co_chiet_khau_nav():
    df, _ = E.lap_bang(*du_lieu_chiet_khau())
    t = df.set_index("Mã")
    h = t.loc["E1VFVN30"]
    # chào bán 26.000 / iNAV 27.000 − 1 = −3,7%; lãi ròng 27.000 × 0,9975 / (26.000 × 1,0015) − 1 = +3,43%; 26 triệu ≥ 5 triệu
    assert (
        h["Chiết khấu mua được %"] == -3.7
        and h["Lãi ròng nếu về NAV %"] == 3.43
        and h["Mua được đạt ngưỡng (đ)"] == 26e6
    )
    # lịch sử giá 20.000 = NAV 20.000 -> thường lệch 0%. NAV so CS tới hôm nay bằng iNAV: 27.000 / 20.000 − 1 = +35%
    # trừ đúng lợi nhuận 1 năm của VN30 (cùng mốc 22/10/2025)
    assert h["CL NAV trung vị 1N %"] == 0.0 and h["Ngày NAV cuối"] == "2026-10-20"
    assert math.isclose(h["NAV so CS 1N"], 35.0 - t.loc["VN30", "1N %"], abs_tol=0.01)
    # FUESSV30: khớp cuối 16/10, lịch còn 19, 20, 21, 22/10 -> 4 phiên chưa khớp; NAV dừng 09/10 (9 phiên) -> cảnh báo
    assert t.loc["FUESSV30", "Phiên chưa khớp"] == 4 and h["Phiên chưa khớp"] == 0
    assert "NAV Vietcap IQ dừng ở 09/10/2026 (9 phiên trước)" in t.loc["FUESSV30", "Cảnh báo"]
    assert "NAV Vietcap" not in h["Cảnh báo"]  # trễ 2 phiên là bình thường
    assert "chưa có lịch sử NAV: Vietcap IQ không có quỹ này" in t.loc["FUEVN50G", "Cảnh báo"]
    bc = E.bao_cao(df, None, datetime(2026, 10, 22, 15, 30), HOM_NAY, ["không lấy được lịch sử NAV từ Vietcap IQ: X"])
    assert "🟢 **E1VFVN30**: chào bán 26.000 (-3,7% so iNAV 27.000) · lãi ròng +3,4% · mua được 26 triệu" in bc
    # quỹ đạt ngưỡng nhưng giá khớp cũ: dòng 🟢 ghi rõ số phiên chưa khớp
    assert "🟢 **FUESSV30**: chào bán 20.000 (-4,8% so iNAV 21.000)" in bc and "· 4 phiên chưa khớp" in bc
    so_cs = E._d(t.loc["FUESSV30", "1N %"] - t.loc["VN30", "1N %"])
    assert f"**FUESSV30**: giá {so_cs} điểm so VN30" in bc and "→ — · 4 phiên chưa khớp (khớp cuối 16/10)" in bc
    assert "⚠ không lấy được lịch sử NAV từ Vietcap IQ: X" in bc and bc.count("```") % 2 == 0
    assert "**E1VFVN30**: giá" not in bc  # quỹ tăng hơn chỉ số (+30% so với +25%): không nằm trong mục tụt


def test_lay_nav_lam_sach_va_khong_sap_vi_1_quy():
    _, _, ls_cs, _ = du_lieu_mau()
    cs = E.chuoi_gia(ls_cs["VN30"])[0]
    dong = [{"tradingDate": str(d.date()), "navPerShare": float(v) * 20_000} for d, v in cs.items()]
    gai = cs.index[100]
    dong[100]["navPerShare"] *= 1.05  # 1 ngày nhập sai
    tho = {"E1VFVN30": dong, "FUEVN50G": "Vietcap IQ không có quỹ này", "FUEKIV30": [{"navPerShare": 1.0}]}
    with (
        mock.patch.object(E.CK, "lay_ssi", side_effect=RuntimeError("x")),
        mock.patch.object(E.CK, "lay_nav_lich_su", return_value=tho),
    ):
        ssi, ls_nav, loi_nguon = E.lay_nav(["E1VFVN30", "FUEVN50G", "FUEKIV30"], ls_cs)
    assert ssi == {} and loi_nguon[0].startswith("không lấy được iNAV / sổ lệnh từ SSI iBoard: RuntimeError")
    assert gai not in ls_nav["E1VFVN30"].index and len(ls_nav["E1VFVN30"]) == len(cs) - 1
    assert ls_nav["FUEVN50G"] == "Vietcap IQ không có quỹ này"
    assert ls_nav["FUEKIV30"].startswith("dữ liệu NAV lạ: KeyError")  # 1 quỹ hỏng không làm sập báo cáo


def test_doc_file_cu_thieu_cot_moi():
    df, _ = E.lap_bang(*du_lieu_mau(), HOM_NAY)
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cw_scanner, "THU_MUC_KET_QUA", Path(tmp)):
        df.drop(columns=E.COT_CK + ["Phiên chưa khớp"]).to_csv(Path(tmp) / "etf_2026-10-21.csv", index=False)
        cu, _ = E.doc_ket_qua()
        assert list(cu.columns) == E.COT and cu["Ngày NAV cuối"].eq("").all() and cu["iNAV"].isna().all()
        assert E.bao_cao(df, cu, datetime(2026, 10, 22, 15, 30), HOM_NAY)  # so với file cũ không lỗi


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
        assert 'data-href="/etf/E1VFVN30"' in trang
        with mock.patch.object(cw_scanner, "lay_gia_dong_cua", side_effect=RuntimeError("mất mạng")):
            ct = web.trang_etf_chi_tiet("E1VFVN30")
        assert "26.000 đ" in ct and "Không tải được lịch sử giá: mất mạng" in ct


def test_web_bang_chiet_khau_va_bieu_do_nav():
    import web

    df, _ = E.lap_bang(*du_lieu_chiet_khau())
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cw_scanner, "THU_MUC_KET_QUA", Path(tmp)):
        df.to_csv(Path(tmp) / f"etf_{HOM_NAY}.csv", index=False, encoding="utf-8-sig")
        assert "<td>🟢</td>" in web.trang_etf()  # E1VFVN30 đạt ngưỡng
        ngay = pd.bdate_range(end="2026-10-20", periods=30)
        pd.DataFrame({"Mã": "E1VFVN30", "Ngày": [str(d.date()) for d in ngay], "NAV": 21_000.0}).to_csv(
            Path(tmp) / "nav_etf_2026-10-21.csv.gz", index=False, compression="gzip"
        )
        pd.DataFrame(columns=["Mã", "Ngày", "NAV"]).to_csv(  # Vietcap IQ lỗi cả nguồn hôm nay: file rỗng
            Path(tmp) / "nav_etf_2026-10-22.csv.gz", index=False, compression="gzip"
        )
        gia = mock.patch.object(cw_scanner, "lay_gia_dong_cua", return_value=df_vnstock([20.0] * 40))
        with gia:
            ct = web.trang_etf_chi_tiet("E1VFVN30")
        # file mới nhất rỗng -> lấy file hôm trước; 20.000 / 21.000 − 1 = −4,76% -> "-4,8"
        assert "Chênh lệch giá/NAV E1VFVN30" in ct and '<td class="so">-4,8</td>' in ct
        (Path(tmp) / "nav_etf_2026-10-23.csv.gz").write_bytes(b"\x1f\x8b hong")  # file ghi dở / hỏng
        with gia:
            ct = web.trang_etf_chi_tiet("E1VFVN30")
        assert "Không đọc được lịch sử NAV" in ct and "Giá E1VFVN30" in ct  # biểu đồ giá vẫn còn


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - ETF đúng")
