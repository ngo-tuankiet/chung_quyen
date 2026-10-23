"""Kiểm tra danh mục + cảnh báo. Chạy: python -m pytest -q   hoặc   python test_danh_muc.py (không cần cài pytest)."""

import io
import json
import math
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

import cw_scanner
import danh_muc as D

HOM_NAY = date(2026, 10, 19)


def lenh(id_, ngay, loai, so_luong, gia, ma="CVPB2615", chot_loi=None, cat_lo=None):
    return {
        "id": id_,
        "ngay": ngay,
        "ma_cw": ma,
        "loai": loai,
        "so_luong": so_luong,
        "gia": gia,
        "chot_loi": chot_loi,
        "cat_lo": cat_lo,
        "ghi_chu": "",
    }


def test_gia_von_binh_quan_va_lai_da_chot():
    # Mua 1.000 @1.200 + 1.000 @1.000, phí 0,15%: vốn 1.201.800 + 1.001.500 = 2.203.300 -> giá vốn 1.101,65 đ/CW
    # Bán 500 @1.300 (trừ phí 0,15% + thuế 0,1%): lãi = 500 × (1.300 × 0,9975 − 1.101,65) = 500 × 195,1 = 97.550 đ
    vt = D.tinh_vi_the(
        [
            lenh(1, "2026-10-01", "MUA", 1000, 1200),
            lenh(2, "2026-10-05", "MUA", 1000, 1000),
            lenh(3, "2026-10-10", "BAN", 500, 1300),
        ]
    )["CVPB2615"]
    assert vt["so_luong"] == 1500 and abs(vt["gia_von"] - 1101.65) < 1e-9 and abs(vt["lai_da_chot"] - 97_550) < 1e-6


def test_ban_qua_so_dang_nam_bao_loi():
    try:
        D.tinh_vi_the([lenh(1, "2026-10-01", "MUA", 100, 1000), lenh(2, "2026-10-02", "BAN", 200, 1000)])
        assert False, "phải báo lỗi"
    except ValueError as e:
        assert "chỉ nắm 100" in str(e)


def test_doc_form_va_kiem_tra_lenh():
    form = {
        "ngay": ["2026-10-19"],
        "ma_cw": ["cvpb2615"],
        "loai": ["MUA"],
        "so_luong": ["1000"],
        "gia": ["1250"],
        "chot_loi": ["40"],
        "cat_lo": [""],
    }
    l, loi = D.doc_form(form)
    assert not loi and l["ma_cw"] == "CVPB2615" and l["chot_loi"] == 0.4 and l["cat_lo"] is None
    assert D.kiem_tra_lenh(l, [], {"CVPB2615"}, HOM_NAY) == []
    assert D.doc_form({**form, "gia": ["abc"]})[1]  # chữ ở ô giá
    sai = {**l, "ma_cw": "CVPB26", "so_luong": 150, "gia": 0, "ngay": "2026-10-20", "loai": "XX"}
    assert len(D.kiem_tra_lenh(sai, [], {"CVPB2615"}, HOM_NAY)) == 5
    assert D.kiem_tra_lenh({**l, "ma_cw": "CVPB2699"}, [], {"CVPB2615"}, HOM_NAY) == [
        "CVPB2699 không có trong lần quét gần nhất"
    ]
    assert "chỉ đang nắm 0" in D.kiem_tra_lenh({**l, "loai": "BAN"}, [], {"CVPB2615"}, HOM_NAY)[0]


def test_doc_gia_nghin_dong_va_dong():
    # App CTCK hiện giá CW theo nghìn đồng: 0,87 = 870 đ
    assert D.doc_gia("0.87") == D.doc_gia("0,87") == D.doc_gia("870") == 870 and D.doc_gia("0.01") == 10
    l, _ = D.doc_form(
        {"ngay": ["2026-10-19"], "ma_cw": ["CVPB2615"], "loai": ["MUA"], "so_luong": ["100"], "gia": ["0,875"]}
    )
    assert "bước giá 10 đ" in D.kiem_tra_lenh(l, [], {"CVPB2615"}, HOM_NAY)[0]


def test_ghi_lenh_an_toan_va_them_xoa():
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(D, "FILE_DANH_MUC", Path(tmp) / "danh_muc.csv"):
        form = {"ngay": ["2026-10-01"], "ma_cw": ["CVPB2615"], "loai": ["MUA"], "so_luong": ["1000"], "gia": ["1200"]}
        assert D.them_lenh(form, {"CVPB2615"}, HOM_NAY) == []
        assert (
            D.them_lenh({**form, "loai": ["BAN"], "so_luong": ["500"], "ngay": ["2026-10-02"]}, {"CVPB2615"}, HOM_NAY)
            == []
        )
        ds = D.doc_lenh()
        assert [d["id"] for d in ds] == [1, 2] and ds[0]["gia"] == 1200 and ds[0]["chot_loi"] is None
        assert (Path(tmp) / "danh_muc.csv.bak").exists() and not (Path(tmp) / "danh_muc.tmp").exists()
        assert "không xóa được" in D.xoa_lenh(1)  # xóa lệnh mua thì lệnh bán sau đó thành bán khống
        assert D.xoa_lenh(2) == "" and D.xoa_lenh(2) == "không có lệnh số 2" and len(D.doc_lenh()) == 1


def bang_gia_mau(bid, S, ngay_gd_cuoi, kl_niem_yet=18_000_000):
    so_lenh = {
        "bidPrices": [{"price": bid, "volume": 1000}] if bid else [],
        "askPrices": [{"price": (bid or 1000) + 10, "volume": 1000}],
    }
    ny = {
        "underlyingSymbol": "VPB",
        "exercisePrice": 20000,
        "exerciseRatio": "2:1",
        "maturityDate": "20270217",
        "lastTradingDate": ngay_gd_cuoi.strftime("%Y%m%d"),
        "tradingDate": str(HOM_NAY),  # phiên hôm nay (ngày nghỉ lễ thì bảng giá vẫn ghi phiên trước)
        "refPrice": 1000,
        "issuerName": "TEST",
        "listedShare": kl_niem_yet,
    }
    return {
        "CVPB2615": (ny, {"matchPrice": bid or 1000, "accumulatedVolume": 50_000}, so_lenh),
        "VPB": ({"refPrice": S}, {"matchPrice": S}, {}),
    }


DF = pd.DataFrame({"Mã CW": ["CVPB2615"], "Mã CS": ["VPB"], "IV %": [30.0], "Biến động %/năm": [30.0], "r %": [4.0]})


def canh_bao(bid, S, con_ngay, kl_truoc=None, kl=18_000_000, **nguong):
    # Mua 1.000 @1.000 -> giá vốn 1.001,5 đ/CW (đã gồm phí mua 0,15%)
    vt = D.tinh_vi_the([lenh(1, "2026-10-01", "MUA", 1000, 1000, **nguong)])
    _, cb, kl_moi = D.danh_gia_danh_muc(
        vt, bang_gia_mau(bid, S, HOM_NAY + timedelta(days=con_ngay), kl), DF, HOM_NAY, kl_truoc or {}
    )
    return {l for _, l, _ in cb}, kl_moi


def test_canh_bao_tai_bien_nguong():
    # Ngày GD cuối: còn 20 ngày -> báo, 21 ngày -> không
    assert "gd_cuoi" in canh_bao(1000, 25000, 20)[0] and "gd_cuoi" not in canh_bao(1000, 25000, 21)[0]
    # CS cách giá thực hiện 20.000: 20.600 (= +3,0%) -> báo; 20.700 (+3,5%) -> không; 19.900 (dưới) -> báo
    assert "gan_gia_th" in canh_bao(1000, 20600, 60)[0] and "gan_gia_th" not in canh_bao(1000, 20700, 60)[0]
    assert "gan_gia_th" in canh_bao(1000, 19900, 60)[0]
    # Chốt lời +50%: bid × 0,9975 / 1.001,5 − 1 ≥ 0,5 <=> bid ≥ 1.506 -> 1.510 báo, 1.500 không
    assert "chot_loi" in canh_bao(1510, 25000, 60)[0] and "chot_loi" not in canh_bao(1500, 25000, 60)[0]
    # Cắt lỗ −30%: bid ≤ 702,8 -> 700 báo, 710 không; ngưỡng riêng của lệnh (cắt lỗ 10%) -> 900 đã báo
    assert "cat_lo" in canh_bao(700, 25000, 60)[0] and "cat_lo" not in canh_bao(710, 25000, 60)[0]
    assert "cat_lo" in canh_bao(890, 25000, 60, cat_lo=0.10)[0]
    # Không ai đặt mua; khối lượng niêm yết tăng (phát hành thêm)
    assert "khong_nguoi_mua" in canh_bao(None, 25000, 60)[0]
    loai, kl_moi = canh_bao(1000, 25000, 60, kl_truoc={"CVPB2615": 15_000_000}, kl=20_000_000)
    assert "phat_hanh_them" in loai and kl_moi == {"CVPB2615": 20_000_000}
    assert canh_bao(1000, 25000, 60)[0] == set()  # bình thường: không báo gì


def test_canh_bao_lech_so_voi_cs():
    # Mua 01/10 đúng giá Black-Scholes (sigma 30%, VPB 24.000, K 20.000, tỷ lệ 2). 19/10 VPB 25.000:
    # giá khớp = giá lẽ ra -> lệch ~0, không báo; = 80% giá lẽ ra -> lệch −20% -> "lech_am"; = 120% -> "lech_duong"
    dh = date(2027, 2, 17)
    P0 = cw_scanner.black_scholes_call(24000, 20000, (dh - date(2026, 10, 1)).days / 365, 0.04, 0.30)[0] / 2
    le_ra = cw_scanner.black_scholes_call(25000, 20000, (dh - HOM_NAY).days / 365, 0.04, 0.30)[0] / 2
    vt = D.tinh_vi_the([lenh(1, "2026-10-01", "MUA", 1000, P0)])
    ls = {
        "VPB": [["2026-09-30", 23500], ["2026-10-01", 24000], ["2026-10-02", 24100]]
    }  # lấy giá ngày mua, không lấy ngày sau
    loai = lambda gia: {
        l
        for _, l, _ in D.danh_gia_danh_muc(
            vt, bang_gia_mau(gia, 25000, HOM_NAY + timedelta(days=60)), DF, HOM_NAY, {}, ls
        )[1]
    }
    dong = D.danh_gia_danh_muc(
        vt, bang_gia_mau(round(le_ra), 25000, HOM_NAY + timedelta(days=60)), DF, HOM_NAY, {}, ls
    )[0]
    assert abs(dong[0]["lech"]) < 0.002 and not loai(round(le_ra)) & {"lech_am", "lech_duong"}
    assert "lech_am" in loai(round(0.8 * le_ra)) and "lech_duong" in loai(round(1.2 * le_ra))
    assert math.isnan(
        D.danh_gia_danh_muc(vt, bang_gia_mau(900, 25000, HOM_NAY), DF, HOM_NAY, {})[0][0]["lech"]
    )  # không có lịch sử


def test_ngay_ban_duoc_va_san_ly_thuyet():
    # Mua phiên T bán được từ phiên T+2 (chưa trừ ngày lễ): mua thứ Năm 22/10 -> thứ Hai 26/10; mua thứ Hai 19/10 -> 21/10
    assert D.ngay_ban_duoc("2026-10-22") == date(2026, 10, 26) and D.ngay_ban_duoc("2026-10-19") == date(2026, 10, 21)
    # Sàn: S 40.000, K 32.000, tỷ lệ 3, r 4%, còn 115 ngày tới đáo hạn thứ Hai 15/02/2027; 5 phiên thanh toán 08–12/02
    # cách đáo hạn 3…7 ngày -> chiết khấu TB 0,999452; (0,999 × 40.000 × 0,999452 − 32.000 × e^(−0,04 × 115/365)) / 3
    san = D.san_ly_thuyet(40000, 32000, 3, 0.04, date(2026, 10, 23), date(2027, 2, 15))
    assert math.isclose(san, 2779.6225, abs_tol=1e-3)
    # bid 2.790 -> bán được 2.783,03 > sàn; bid 2.780 -> 2.773,05 < sàn (bán dưới giá trị tối thiểu nếu giữ tới đáo hạn)
    assert 2790 * 0.9975 > san > 2780 * 0.9975


def test_trang_thai_gop_muc():
    tt = D.trang_thai_vi_the
    assert tt(set(), False, False, -0.004) == (D.MUC_KHONG, [])  # mất giá 0,4%/ngày: chưa tới ngưỡng
    assert tt({"gan_gia_th", "iv_bat_thuong", "lech_am"}, False, False, math.nan) == (D.MUC_KHONG, [])  # chỉ thông tin
    assert tt({"lech_duong"}, False, False, math.nan) == (D.MUC_CAN_NHAC, ["lech_duong"])
    # chốt lời do người dùng tự đặt -> Nên bán, đứng trước; ngưỡng mặc định -> chỉ Cân nhắc
    assert tt({"lech_duong", "chot_loi"}, True, False, math.nan) == (D.MUC_NEN_BAN, ["chot_loi", "lech_duong"])
    assert tt({"chot_loi"}, False, False, math.nan) == (D.MUC_CAN_NHAC, ["chot_loi"])
    assert tt({"chot_loi", "cat_lo"}, True, True, math.nan)[1] == ["cat_lo", "chot_loi"]  # cắt lỗ ưu tiên hơn
    assert tt({"cw_dat", "gd_cuoi"}, False, False, math.nan) == (D.MUC_NEN_BAN, ["cw_dat", "gd_cuoi"])
    # theta: mất 2,5%/ngày -> Nên bán; 1,5% -> Cân nhắc (xếp sau các lý do Cân nhắc khác)
    assert tt(set(), False, False, -0.025) == (D.MUC_NEN_BAN, ["theta_cao"])
    assert tt({"phat_hanh_them"}, False, False, -0.015) == (D.MUC_CAN_NHAC, ["phat_hanh_them", "theta"])


def test_trang_thai_trong_danh_muc():
    # Mua 01/10 @1.000, tự đặt chốt lời 50%: bid 1.510 -> Nên bán (chot_loi); không đổi danh sách cảnh báo gửi Discord
    vt = D.tinh_vi_the([lenh(1, "2026-10-01", "MUA", 1000, 1000, chot_loi=0.5)])
    dong, cb, _ = D.danh_gia_danh_muc(vt, bang_gia_mau(1510, 25000, HOM_NAY + timedelta(days=60)), DF, HOM_NAY, {})
    t = dong[0]["trang_thai"]
    assert t["muc"] == D.MUC_NEN_BAN and t["ly_do"][0][0] == "chot_loi" and t["ban_duoc_tu"] is None
    assert {l for _, l, _ in cb} == {"chot_loi"}
    # Mua đúng hôm nay (19/10): chưa bán được tới 21/10
    vt = D.tinh_vi_the([lenh(1, str(HOM_NAY), "MUA", 1000, 1000)])
    t = D.danh_gia_danh_muc(vt, bang_gia_mau(1000, 25000, HOM_NAY + timedelta(days=60)), DF, HOM_NAY, {})[0][0]
    assert t["trang_thai"]["ban_duoc_tu"] == date(2026, 10, 21) and t["trang_thai"]["muc"] == D.MUC_KHONG


def test_cw_moi_vao_nhom_va_muc_bao_cao():
    # A: Theo dõi -> Nên xem xét (có); B: Bỏ qua -> Nên xem xét (có); C: đã Nên xem xét từ trước (không);
    # D: mới niêm yết, chưa có ở lần trước (không, đã có mục CW mới); E: Nên xem xét -> Theo dõi (không)
    truoc = pd.DataFrame({"Mã CW": list("ABCE"), "Đánh giá": ["THEO DÕI", "BỎ QUA", "NÊN XEM XÉT", "NÊN XEM XÉT"]})
    nay = pd.DataFrame(
        {
            "Mã CW": list("ABCDE"),
            "Mã CS": ["VPB"] * 5,
            "TCPH": ["SSI"] * 5,
            "Mới": ["", "", "", "MỚI", ""],
            "Đánh giá": ["NÊN XEM XÉT"] * 4 + ["THEO DÕI"],
            "Ngày còn lại": [100] * 5,
            "Giá CS": [24000] * 5,
            "Giá thực hiện": [22000] * 5,
            "Tỷ lệ CĐ": [2.0] * 5,
            "Giá mua": [1200] * 5,
            "Giá hợp lý": [1300] * 5,
            "Đắt/rẻ %": [-7.7] * 5,
            "IV − HV": [-2.0] * 5,
            "CS tăng % để hòa vốn": [1.7] * 5,
            "Đòn bẩy": [8.5] * 5,
            "IV %": [27.0, 30.0, 31.0, 32.0, 33.0],
            "IV cùng mã %": [47.0, float("nan"), 45.0, 45.0, 45.0],
            "Cảnh báo": [""] * 5,
        }
    )
    moi = D.cw_moi_vao_nhom(nay, truoc)
    assert list(moi["Mã CW"]) == ["A", "B"] and list(moi["Từ nhóm"]) == ["THEO DÕI", "BỎ QUA"]
    assert D.cw_moi_vao_nhom(nay, None).empty  # lần quét đầu: chưa có gì để so
    bc = D.bao_cao_ngay(nay, HOM_NAY, [], [], 0, datetime(2026, 10, 20, 14, 0), moi, {"A": -0.032})
    assert bc.index("🔔") < bc.index("💼")  # mục đầu tiên
    dong = {d.split()[0]: d.split() for d in bc.split("🔔")[1].split("💼")[0].splitlines() if d[:1] in ("A", "B")}
    assert dong["A"][-3:] == ["TD", "27/47", "-3,2%"] and dong["B"][-3:] == ["BQ", "—", "—"]  # thiếu số liệu -> "—"
    with mock.patch.object(D, "MAX_MA_MOI_VAO", 1):
        assert "và 1 mã khác" in D.bao_cao_ngay(nay, HOM_NAY, [], [], 0, datetime(2026, 10, 20, 14, 0), moi, {})
    assert "🔔" not in D.bao_cao_ngay(nay, HOM_NAY, [], [], 0, datetime(2026, 10, 20, 14, 0), moi.iloc[0:0], {})


def test_doc_ket_qua_truoc():
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cw_scanner, "THU_MUC_KET_QUA", Path(tmp)):
        for ngay, nhom in (("2026-10-16", "BỎ QUA"), ("2026-10-19", "THEO DÕI"), ("2026-10-20", "NÊN XEM XÉT")):
            pd.DataFrame({"Mã CW": ["A"], "Đánh giá": [nhom]}).to_csv(
                Path(tmp) / f"cw_{ngay}.csv", index=False, encoding="utf-8-sig"
            )
        assert D.doc_ket_qua_truoc(date(2026, 10, 20))["Đánh giá"][0] == "THEO DÕI"  # bỏ qua file của chính hôm nay
        assert D.doc_ket_qua_truoc(date(2026, 10, 16)) is None


def test_giu_hay_ban_tinh_tay():
    # CVPB2608 ngày 19/10/2026: VPB 24.000, K 23.379, tỷ lệ 1,5586, giá chờ mua 830
    # bán ngay = 830 × (1 − 0,0015 − 0,001) = 827,925; CS cần = 23.379 + 1,5586 × 827,925 / 0,999 = 24.670,7 (+2,79%)
    g = D.giu_hay_ban(24000, 23379, 1.5586, 118 / 365, 0.04, 0.318, 830)
    assert abs(g["ban_ngay"] - 827.925) < 1e-9 and abs(g["cs_can"] - 24670.7) < 0.1 and abs(g["cach"] - 0.02795) < 1e-4
    assert abs(g["ve_0"] - (23379 / 24000 - 1)) < 1e-12
    # giữ theo mô hình = Black-Scholes / tỷ lệ × (1 − thuế 0,1%)
    gt = cw_scanner.black_scholes_call(24000, 23379, 118 / 365, 0.04, 0.318)[0] / 1.5586 * 0.999
    assert abs(g["giu_mh"] - gt) < 1e-9 and math.isnan(
        D.giu_hay_ban(24000, 23379, 1.5586, 0.3, 0.04, math.nan, 830)["giu_mh"]
    )


def test_muc_sap_het_han_chi_hien_khi_con_20_ngay():
    vt = D.tinh_vi_the([lenh(1, "2026-10-01", "MUA", 1000, 1000)])
    df = pd.DataFrame(
        {
            "Mã CW": ["CVPB2615"],
            "Mã CS": ["VPB"],
            "Đánh giá": ["THEO DÕI"],
            "Mới": [""],
            "IV − HV": [1.0],
            "Cảnh báo": [""],
        }
    )
    bc = lambda con: D.bao_cao_ngay(
        df,
        HOM_NAY,
        D.danh_gia_danh_muc(vt, bang_gia_mau(1000, 25000, HOM_NAY + timedelta(days=con)), DF, HOM_NAY, {})[0],
        [],
        0,
        datetime(2026, 10, 19, 14),
    )
    co, khong = bc(20), bc(21)
    assert "⏳" in co and "⏳" not in khong
    # CS cần = 20.000 + 2 × (1.000 × 0,9975) / 0,999 = 21.997 (+... so với VPB 25.000: −12,0%)
    hang = next(d for d in co.split("⏳")[1].splitlines() if d.startswith("CVPB2615"))
    assert (
        hang.split()[0] == "CVPB2615"
        and hang.split()[1] == "998"
        and hang.split()[3] == "21.997"
        and hang.split()[4] == "-12,0%"
    )


def test_canh_bao_cw_dat_chuyen_sang_co_phieu():
    # VPB 25.000, K 20.000, tỷ lệ 2, còn 60 ngày tới GD cuối (đáo hạn 17/02/2027), sigma lịch sử 30%, r 4%
    T = (date(2027, 2, 17) - HOM_NAY).days / 365
    giu_mh = cw_scanner.black_scholes_call(25000, 20000, T, 0.04, 0.30)[0] / 2 * 0.999  # giá trị giữ theo mô hình
    bid = (
        lambda he_so: math.ceil(giu_mh * he_so / 0.9975 / 10) * 10
    )  # giá chờ mua để bán ngay ≈ mô hình × he_so (bước 10 đ)
    vt = D.tinh_vi_the([lenh(1, "2026-10-01", "MUA", 1000, 1000)])
    cung_ma = lambda ivs: pd.concat(
        [DF] + [DF.assign(**{"Mã CW": f"CVPB26{i}", "IV %": x}) for i, x in enumerate(ivs, 50)]
    )
    cb = lambda gia, df: next(
        (
            nd
            for m, l, nd in D.danh_gia_danh_muc(
                vt, bang_gia_mau(gia, 25000, HOM_NAY + timedelta(days=60)), df, HOM_NAY, {}
            )[1]
            if l == "cw_dat"
        ),
        "",
    )
    noi_dung = cb(bid(1.2), cung_ma([20, 25, 30]))  # +20% so với mô hình, IV > trung vị 25% -> báo
    assert noi_dung.startswith("CW đắt hơn mô hình +2") and "trung vị 25% của 3 CW VPB" in noi_dung
    # 1.000 CW / tỷ lệ 2 = 500 cp ≈ 12.500.000 đ; theo delta N(d1) × 500 làm tròn lô 100
    delta = cw_scanner.black_scholes_call(25000, 20000, T, 0.04, 0.30)[1]
    assert "đủ số 500 cp ≈ 12.500.000 đ" in noi_dung and f"theo delta {D.so(D.lo_100(500 * delta))} cp" in noi_dung
    assert f"Bán hết thu ≈ {D.so(1000 * bid(1.2) * 0.9975)} đ" in noi_dung
    assert cb(bid(1.1), cung_ma([20, 25, 30])) == ""  # chỉ +10%
    assert cb(bid(1.2), cung_ma([60, 70, 80])) == ""  # IV thấp hơn trung vị cùng mã
    assert cb(bid(1.2), cung_ma([20, 25])) == ""  # < 3 CW cùng mã để so
    assert cb(None, cung_ma([20, 25, 30])) == ""  # không ai đặt mua
    assert D.lo_100(450) == 500 and D.lo_100(449) == 400


def test_chi_gui_canh_bao_vua_xuat_hien():
    a, b = ("CVPB2615", "cat_lo", "..."), ("CVPB2615", "gd_cuoi", "...")
    moi, dang_bao = D.chon_canh_bao_moi([a], [])
    assert moi == [a] and dang_bao == ["CVPB2615|cat_lo"]
    assert D.chon_canh_bao_moi([a, b], dang_bao)[0] == [b]  # cắt lỗ đã báo -> chỉ gửi ngày GD cuối
    assert D.chon_canh_bao_moi([], dang_bao) == (
        [],
        [],
    )  # hết cắt lỗ -> xóa khỏi danh sách, lần sau xảy ra lại sẽ báo lại


def test_gui_discord():
    try:
        D.gui_discord("x", "https://vi-du.com/hook")
        assert False, "phải từ chối URL không phải Discord"
    except ValueError:
        pass
    with mock.patch("urllib.request.urlopen") as mo:
        D.gui_discord("⚠ CVPB2615: lỗ", "https://discord.com/api/webhooks/1/abc")
    yeu_cau = mo.call_args[0][0]
    # allowed_mentions rỗng: chữ lấy từ API ngoài (mã, tên quỹ) không biến thành "@everyone" thông báo cả server
    goi = json.loads(yeu_cau.data)
    assert goi == {"content": "⚠ CVPB2615: lỗ", "allowed_mentions": {"parse": []}} and yeu_cau.get_method() == "POST"


def test_kiem_tra_ngoai_gio_khong_goi_mang():
    with mock.patch.object(cw_scanner, "lay_bang_gia", side_effect=AssertionError("không được gọi mạng")):
        assert D.kiem_tra(luc=datetime(2026, 10, 18, 10, 0)) == []  # Chủ nhật
        assert D.kiem_tra(luc=datetime(2026, 10, 19, 12, 0)) == []  # nghỉ trưa


def test_kiem_tra_chi_gui_mot_lan():
    import web

    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.multiple(D, FILE_DANH_MUC=Path(tmp) / "dm.csv", FILE_TRANG_THAI=Path(tmp) / "tt.json"),
        mock.patch.object(web, "doc_ket_qua", return_value=(DF, HOM_NAY)),
        mock.patch.object(
            cw_scanner, "doc_env", return_value={"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/abc"}
        ),
        mock.patch.object(
            cw_scanner,
            "lay_bang_gia",
            side_effect=lambda ds, cho=30: {
                m: v for m, v in bang_gia_mau(700, 25000, HOM_NAY + timedelta(days=60)).items() if m in ds
            },
        ),
        mock.patch.object(D, "gui_discord") as gui,
        mock.patch("sys.stdout", new=io.StringIO()),
    ):
        D.ghi_lenh([lenh(1, "2026-10-01", "MUA", 1000, 1000)])
        luc = datetime(2026, 10, 19, 10, 0)
        assert [l for _, l, _ in D.kiem_tra(luc=luc)] == ["cat_lo"] and gui.call_count == 1
        noi_dung = gui.call_args[0][0]
        assert "CVPB2615" in noi_dung and "1.000" not in noi_dung  # không gửi khối lượng / số tiền lên Discord
        assert D.kiem_tra(luc=luc) == [] and gui.call_count == 1  # lần 2: cảnh báo cũ, không gửi lại


def _chay_kiem_tra(tmp, cac_lan, ngay_phien=None):
    """Chạy kiem_tra() lần lượt với các giá chờ mua trong cac_lan [(thời điểm, giá)]; trả về số tin đã gửi."""
    import web

    gia = [0]  # giá chờ mua của lần chạy hiện tại

    def bang(ds, cho=30):
        b = {m: v for m, v in bang_gia_mau(gia[0], 25000, HOM_NAY + timedelta(days=60)).items() if m in ds}
        for ny, *_ in b.values():
            ny["tradingDate"] = ngay_phien or str(_chay_kiem_tra.luc.date())
        return b

    with (
        mock.patch.multiple(D, FILE_DANH_MUC=Path(tmp) / "dm.csv", FILE_TRANG_THAI=Path(tmp) / "tt.json"),
        mock.patch.object(web, "doc_ket_qua", return_value=(DF, HOM_NAY)),
        mock.patch.object(
            cw_scanner, "doc_env", return_value={"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/a"}
        ),
        mock.patch.object(cw_scanner, "lay_bang_gia", side_effect=bang),
        mock.patch.object(D, "gui_discord") as gui,
        mock.patch("sys.stdout", new=io.StringIO()),
    ):
        D.ghi_lenh([lenh(1, "2026-10-01", "MUA", 1000, 1000)])
        for luc, gia_lan in cac_lan:
            _chay_kiem_tra.luc = luc
            gia[0] = gia_lan
            D.kiem_tra(luc=luc)
        return gui.call_count


def test_canh_bao_dao_dong_quanh_nguong_chi_gui_1_lan_moi_ngay():
    # Lỗi thật 22/10/2026: CVPB2608 dao động quanh ngưỡng -> "lech_duong" gửi 4 lần trong ngày.
    # Cắt lỗ (giá 700) xuất hiện 10:00, hết 10:05 (giá 1.000), lại xuất hiện 10:10 -> chỉ 1 tin; hôm sau lại xuất hiện -> gửi tiếp
    with tempfile.TemporaryDirectory() as tmp:
        lan = [
            (datetime(2026, 10, 19, 10, 0), 700),
            (datetime(2026, 10, 19, 10, 5), 1000),
            (datetime(2026, 10, 19, 10, 10), 700),
        ]
        assert _chay_kiem_tra(tmp, lan) == 1
    with tempfile.TemporaryDirectory() as tmp:
        lan = [
            (datetime(2026, 10, 19, 10, 0), 700),
            (datetime(2026, 10, 20, 10, 0), 1000),
            (datetime(2026, 10, 20, 10, 5), 700),
        ]
        assert _chay_kiem_tra(tmp, lan) == 2


def test_ngay_nghi_le_khong_kiem_tra():
    # Thứ Hai 19/10 nhưng bảng giá vẫn ghi phiên 16/10 (giả lập ngày nghỉ lễ) -> không gửi gì
    with tempfile.TemporaryDirectory() as tmp:
        assert _chay_kiem_tra(tmp, [(datetime(2026, 10, 19, 10, 0), 700)], ngay_phien="2026-10-16") == 0


def test_la_ngay_giao_dich():
    phien = lambda ngay: {"VPB": ({"tradingDate": ngay}, {}, {})}
    with mock.patch.object(cw_scanner, "lay_bang_gia", return_value=phien("2026-10-22")):
        assert cw_scanner.la_ngay_giao_dich(date(2026, 10, 22)) is True
    with mock.patch.object(cw_scanner, "lay_bang_gia", return_value=phien("2026-10-16")):
        assert cw_scanner.la_ngay_giao_dich(date(2026, 10, 19)) is False


def test_bao_cao_ghi_ro_khi_quet_loi():
    df = pd.DataFrame(
        {"Mã CW": ["A"], "Mã CS": ["VPB"], "Đánh giá": ["THEO DÕI"], "Mới": [""], "IV − HV": [1.0], "Cảnh báo": [""]}
    )
    bc = D.bao_cao_ngay(
        df, HOM_NAY, [], [], 0, datetime(2026, 10, 21, 14, 14), quet_loi=("NetworkError: không kết nối", "19/10 09:02")
    )
    dong2 = bc.split("\n\n")[0].splitlines()[1]
    assert dong2.startswith("⚠ **Quét hôm nay lỗi**") and "NetworkError" in dong2 and "19/10 09:02" in dong2
    assert "Quét hôm nay lỗi" not in D.bao_cao_ngay(df, HOM_NAY, [], [], 0, datetime(2026, 10, 21, 14, 0))


def test_lay_bang_gia_bo_ma_khong_ton_tai():
    tra_ve = io.BytesIO(
        json.dumps([{"listingInfo": None}, {"listingInfo": {"symbol": "VPB"}, "matchPrice": {}}]).encode()
    )
    with mock.patch(
        "urllib.request.urlopen", return_value=mock.MagicMock(__enter__=lambda s: tra_ve, __exit__=lambda *a: None)
    ):
        assert list(cw_scanner.lay_bang_gia(["CVPB2401", "VPB"])) == ["VPB"]


def test_nguon_hop_le():
    import web

    assert web.nguon_hop_le({"Origin": "http://localhost:8000"}) and web.nguon_hop_le(
        {"Referer": "http://127.0.0.1:8000/danh-muc"}
    )
    assert not any(
        web.nguon_hop_le(h)
        for h in (
            {},
            {"Origin": "null"},
            {"Origin": "https://trang-la.com"},
            {"Origin": "http://localhost:8000.trang-la.com"},
            {"Referer": "http://localhost:80001/"},
        )
    )


def test_post_tu_trang_la_bi_chan_tu_trang_minh_thi_luu():
    # Máy chủ thật (cổng ngẫu nhiên): POST có Origin lạ -> 403, không ghi gì; Origin của chính trang -> 303 và lưu lệnh
    import threading
    import urllib.error
    import urllib.request
    from http.server import HTTPServer

    import web

    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.object(D, "FILE_DANH_MUC", Path(tmp) / "dm.csv"),
        mock.patch.object(web, "doc_ket_qua", return_value=(DF, HOM_NAY)),
    ):
        may_chu = HTTPServer(("127.0.0.1", 0), web.XuLy)
        threading.Thread(target=may_chu.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{may_chu.server_port}/danh-muc/them"
        than = b"ngay=2026-10-01&ma_cw=CVPB2615&loai=MUA&so_luong=1000&gia=1200"
        gui = lambda nguon: urllib.request.urlopen(
            urllib.request.Request(url, data=than, headers={"Origin": nguon}), timeout=5
        )
        try:
            gui("https://trang-la.com")
            assert False, "phải bị chặn"
        except urllib.error.HTTPError as e:
            assert e.code == 403
        assert D.doc_lenh() == []
        with mock.patch.object(urllib.request.HTTPRedirectHandler, "redirect_request", return_value=None):
            try:
                gui("http://localhost:8000")
            except urllib.error.HTTPError as e:
                assert e.code == 303 and e.headers["Location"] == "/danh-muc"
        may_chu.shutdown()
        assert [(d["ma_cw"], d["so_luong"]) for d in D.doc_lenh()] == [("CVPB2615", 1000)] and web.LOI_DANH_MUC == ""


def test_trang_danh_muc():
    import web

    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.multiple(D, FILE_DANH_MUC=Path(tmp) / "dm.csv", FILE_TRANG_THAI=Path(tmp) / "tt.json"),
        mock.patch.object(web, "doc_ket_qua", return_value=(DF, HOM_NAY)),
        mock.patch.object(
            cw_scanner,
            "lay_bang_gia",
            side_effect=lambda ds, cho=30: {
                m: v for m, v in bang_gia_mau(700, 25000, HOM_NAY + timedelta(days=60)).items() if m in ds
            },
        ),
    ):
        assert "Thêm lệnh" in web.trang_danh_muc() and "Đang nắm" not in web.trang_danh_muc()  # chưa có lệnh
        D.ghi_lenh([lenh(1, "2026-10-01", "MUA", 1000, 1000), lenh(2, "2026-10-02", "BAN", 0 + 100, 1200)])
        trang = web.trang_danh_muc()
        # còn 900 CW, giá vốn 1.001,5; bán được 700 -> lỗ (700 × 0,9975 − 1.001,5) × 900 = −303,25 × 900 = −272.925 đ (−30,3%)
        assert "Đang nắm (1 mã)" in trang and "-272.925" in trang and "lỗ nếu bán ngay" in trang
        # đã chốt: bán 100 @1.200 -> 100 × (1.200 × 0,9975 − 1.001,5) = +19.550 đ
        assert "Lịch sử lệnh (2)" in trang and "+19.550 đ" in trang
        # lỗ −30,3% chạm cắt lỗ mặc định 30% (không tự đặt) -> Cân nhắc; giá mẫu dưới giá trị nội tại (S 25.000, K 20.000, tỷ lệ 2)
        assert "🟡 Cân nhắc bán" in trang and "chạm cắt lỗ" in trang and "🛑" in trang
        D.FILE_DANH_MUC.write_text("hỏng", encoding="utf-8")  # sai tiêu đề: phải báo lỗi, KHÔNG coi là rỗng
        assert "File danh_muc.csv bị lỗi" in web.trang_danh_muc()
        form = {"ngay": ["2026-10-01"], "ma_cw": ["CVPB2615"], "loai": ["MUA"], "so_luong": ["100"], "gia": ["1000"]}
        try:
            D.them_lenh(form, {"CVPB2615"}, HOM_NAY)
            assert False, "phải từ chối ghi khi file hỏng"
        except ValueError:
            assert D.FILE_DANH_MUC.read_text(encoding="utf-8") == "hỏng"  # không bị ghi đè


def test_bao_cao_ngay():
    # Vị thế lỗ 30,3% (giá vốn 1.001,5; bán được 700) -> có trong "Gần ngưỡng" và báo ĐÃ CHẠM cắt lỗ −30%
    vt = D.tinh_vi_the([lenh(1, "2026-10-01", "MUA", 1000, 1000)])
    dong, cb, _ = D.danh_gia_danh_muc(vt, bang_gia_mau(700, 25000, HOM_NAY + timedelta(days=60)), DF, HOM_NAY, {})
    df = pd.DataFrame(
        {
            "Mã CW": ["CNEW2601", "CXXX2601"],
            "Mã CS": ["VPB", "VPB"],
            "TCPH": ["SSI", "SSI"],
            "Mới": ["MỚI", ""],
            "Ngày còn lại": [120, 90],
            "Giá CS": [24000, 24000],
            "Giá thực hiện": [22000, 23000],
            "Tỷ lệ CĐ": [2.0, 2.0],
            "Giá mua": [1200, 900],
            "Giá hợp lý": [1300, 950],
            "Đắt/rẻ %": [-7.7, -5.3],
            "IV − HV": [-2.0, 1.0],
            "CS tăng % để hòa vốn": [1.7, 3.3],
            "Đòn bẩy": [8.5, float("nan")],
            "Đánh giá": ["NÊN XEM XÉT", "THEO DÕI"],
            "Cảnh báo": ["", ""],
        }
    )
    bc = D.bao_cao_ngay(df, HOM_NAY, dong, cb, 19_550, datetime(2026, 10, 19, 14, 0))
    # hàng CNEW2601: giá 1.200, hợp lý 1.300, -7,7%, IV-HV -2,0, hòa vốn 22.000 + 1.200 × 2 = 24.400 (+1,7%), đòn bẩy 8,5x
    hang = next(d for d in bc.splitlines() if d.startswith("CNEW2601"))
    assert hang.split() == ["CNEW2601", "1.200", "1.300", "-7,7", "-2,0", "+1,7", "8,5x"]
    assert "CXXX2601" not in bc.split("⭐")[0].split("🆕")[1]  # IV-HV +1 nhưng không phải mã mới
    # danh mục: 1.000 CW, vốn 1.001,5, bán được 700 -> -30,3%, (700 × 0,9975 − 1.001,5) × 1.000 = -303.250 đ
    assert next(d for d in bc.splitlines() if d.startswith("CVPB2615")).split()[-2:] == ["-30,3", "-303.250"]
    assert "ĐÃ CHẠM" in bc and "đã chốt +19.550 đ" in bc and bc.count("```") % 2 == 0
    tin = D.chia_tin(bc * 5, 500)
    assert all(len(t) <= 500 for t in tin) and "\n".join(tin).replace("\n", "") == (bc * 5).replace("\n", "")


def test_bao_cao_co_top_luot():
    df = pd.DataFrame(
        {
            "Mã CW": ["CA", "CB", "CC"],
            "Mã CS": ["VPB", "HPG", "FPT"],
            "Đánh giá": ["THEO DÕI"] * 3,
            "Giá mua": [1_200, 800, 500],
            "Nguồn giá mua": ["ask", "ask", "ask"],
            "Giá chờ mua": [1_190, 790, 480],
            "Spread %": [0.8, 1.3, 4.1],
            "Bên mua 3 bước (triệu)": [80.0, 50.0, 5.0],  # CC: bên mua 5 triệu < 20 triệu -> loại
            "Ngày GD cuối": ["2027-01-15"] * 3,
            "Ngày còn lại": [90] * 3,
            "Lướt: CS cần tăng %": [1.25, 0.9, 0.5],
            "Lướt: lãi kịch bản %": [30.0, 38.5, 60.0],
            "Đòn bẩy": [8.0, 9.5, 14.0],
        }
    )
    bc = D.bao_cao_ngay(df, HOM_NAY, [], [], 0, datetime(2026, 10, 19, 14, 0))
    muc = bc[bc.index("⚡ **Top 2 CW lướt 5 phiên**") :]
    hang = [d.split() for d in muc.splitlines() if d[:2] in ("CA", "CB", "CC")]
    assert hang == [["CB", "HPG", "800", "+0,9%", "+38,5%", "9,5x"], ["CA", "VPB", "1.200", "+1,2%", "+30,0%", "8,0x"]]
    assert "bên mua < 20 triệu" in muc and muc.count("```") % 2 == 0
    assert "⚡" not in D.bao_cao_ngay(
        df.drop(columns=["Lướt: CS cần tăng %"]), HOM_NAY, [], [], 0, datetime(2026, 10, 19, 14, 0)
    )


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - danh mục đúng")
