"""Kiểm tra trang 🔔 Cảnh báo giá. Chạy: python -m pytest -q   hoặc   python test_canh_bao_gia.py (không cần cài pytest)."""

import tempfile
import threading
import urllib.error
import urllib.request
from datetime import date, datetime
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

import pandas as pd

import canh_bao_gia as CB
import cw_scanner as C
import phai_sinh as P

HOM_NAY = date(2026, 10, 19)  # CW mẫu đáo hạn 17/02/2027: còn 121 ngày (như test_danh_muc)


def bang_cw(ban, kl_ban=2500, S=24000):
    """Bảng giá 1 CW (K 20.000, tỷ lệ 2:1, đáo hạn 17/02/2027, GD cuối 10/02/2027) + CS VPB đang ở S."""
    ny = {
        "underlyingSymbol": "VPB",
        "exercisePrice": 20000,
        "exerciseRatio": "2:1",
        "maturityDate": "20270217",
        "lastTradingDate": "20270210",
        "tradingDate": str(HOM_NAY),
    }
    so_lenh = {"askPrices": [{"price": ban, "volume": kl_ban}], "bidPrices": [{"price": ban - 20, "volume": 5000}]}
    return {
        "CVPB2615": (ny, {"matchPrice": ban, "accumulatedVolume": 50_000}, so_lenh),
        "VPB": ({"refPrice": 25000}, {"matchPrice": S}, {}),
    }


# lúc quét: CW chào bán 3.000 khi VPB 25.000 (IV giải ngược = 50,0%, như test_danh_muc)
DF_QUET = pd.DataFrame(
    {
        "Mã CW": ["CVPB2615"],
        "Mã CS": ["VPB"],
        "TCPH": ["TEST"],
        "Giá mua": [3000.0],
        "Giá CS": [25000.0],
        "Nguồn giá mua": ["ask"],
        "IV %": [50.0],
        "r %": [4.0],
    }
)


def test_doc_ngay_hai_dang():
    assert CB.doc_ngay("20270217") == date(2027, 2, 17) and CB.doc_ngay("19/11/2026") == date(2026, 11, 19)
    assert CB.doc_ngay("") is None and CB.doc_ngay(None) is None and CB.doc_ngay("2026-11-19") is None


def test_cw_lech_re_tinh_tay():
    # Tính tay (như test_danh_muc): IV từ giá quét (3.000 × 2 = 6.000, S 25.000, K 20.000, 121 ngày, r 4%) = 50,0%;
    # giá lẽ ra với S 24.000: call = 24.000 × 0,7948 − 20.000 × e^(−0,0133) × 0,7038 = 5.186 -> 2.593/CW.
    # Chào bán 2.000: lệch = 2.000 / 2.593 − 1 = −22,9% ≤ −15% -> có; mua được 2.000 × 2.500 = 5 triệu (đủ ngưỡng)
    ds = CB.cw_lech_re(DF_QUET, bang_cw(2000), HOM_NAY, HOM_NAY)
    assert [x["ma"] for x in ds] == ["CVPB2615"]
    x = ds[0]
    assert abs(x["lech"] - (2000 / 2592.867 - 1)) < 1e-4 and abs(x["le_ra"] - 2592.867) < 0.5
    assert x["mua_duoc"] == 5_000_000 and x["cho_mua"] == 1980 and abs(x["cs_pt"] - (24000 / 25000 - 1)) < 1e-12
    # chỉ 2.000 × 2.499 = 4.998.000 đ ở mức rẻ: lô lẻ -> không
    assert CB.cw_lech_re(DF_QUET, bang_cw(2000, kl_ban=2499), HOM_NAY, HOM_NAY) == []
    # chào bán 2.400: lệch = 2.400 / 2.593 − 1 = −7,4% (phần lớn là CS −4% × đòn bẩy) -> không
    assert CB.cw_lech_re(DF_QUET, bang_cw(2400), HOM_NAY, HOM_NAY) == []
    # còn < 20 ngày tới GD cuối -> không; lúc quét không có giá chào bán thật -> không
    assert CB.cw_lech_re(DF_QUET, bang_cw(2000), HOM_NAY, date(2027, 1, 25)) == []
    assert CB.cw_lech_re(DF_QUET.assign(**{"Nguồn giá mua": ["khớp"]}), bang_cw(2000), HOM_NAY, HOM_NAY) == []
    assert CB.cw_lech_re(None, bang_cw(2000), HOM_NAY, HOM_NAY) == []


def test_so_hd_phong_ho_tinh_tay():
    # Hull ch. 3: N* = β·V_A / V_F. Lệnh ETF 50 triệu, HĐ ở 1.858 điểm × 100.000 = 185,8 triệu -> 0,2691 HĐ
    assert abs(CB.so_hd_phong_ho(50_000_000, 1858) - 50_000_000 / 185_800_000) < 1e-12
    assert abs(CB.so_hd_phong_ho(185_800_000, 1858) - 1) < 1e-12


def test_chi_phi_hd_va_lai_khoa_tinh_tay():
    # thuế 1 lần ở 2.000 điểm: 0,1% × 2.000 × 100.000 × 17% / 2 = 17.000 đ (Thông tư 87/2026; ký quỹ VSDC 17% từ 16/10/2026)
    assert abs(P.thue_mot_lan(2000, "VN30") - 17_000) < 1e-6
    # chi phí giữ đến đáo hạn lấy đúng cách tính của phai_sinh: phí công ty × 2 + phí Sở + phí bù trừ VSDC (lúc mở) + phí vị thế ×
    # số phiên + thuế 2 lần. Theo phí đã kiểm chứng 31/10/2026 (QĐ 1541/QĐ-BTC: bù trừ 2.550 đ/HĐ khớp, phí vị thế theo ngày = 0):
    # 3.000 × 2 + 2.700 + 2.550 + 17.000 × 2 = 45.250 đ
    phi_bu_tru = getattr(P, "PHI_BU_TRU_HD", 0)  # phai_sinh trước 31/10/2026 chưa có hằng số này
    ky_vong = 2 * P.PHI_CTCK_HD + P.PHI_SO_HD + phi_bu_tru + P.PHI_VI_THE_HD_NGAY * 10 + 2 * 17_000
    assert abs(CB.chi_phi_hd_den_dao_han(2000, 10, "VN30") - ky_vong) < 1e-6
    # Bán HĐ ở 2.040, chỉ số 2.000, mua ETF ở 10.010 khi iNAV 10.000 (chờ mua 9.990), 73 ngày, r 5%: rT = 0,01.
    # vốn ETF quy ra chỉ số: 2.000 × 1,001 × e^0,01 = 2.002 × 1,010050 = 2.022,1204
    # chi phí ETF: 2.000 × (0,15% × 2 + 0,1% + 20/10.000) = 2.000 × 0,6% = 12 điểm; chi phí HĐ 80.000 đ = 0,8 điểm
    # lãi khóa = 2.040 − 2.022,1204 − 12 − 0,8 = 5,0796 điểm/HĐ (≈ 508.000 đ)
    lai = CB.lai_khoa_ban_hd_mua_etf(2040, 2000, 10010, 9990, 10000, 73, 80_000, r=0.05)
    assert abs(lai - 5.079566) < 1e-5
    assert CB.lai_khoa_ban_hd_mua_etf(2030, 2000, 10010, 9990, 10000, 73, 80_000, r=0.05) < 0  # 2.030: −4,92


def ssi_mau(ma="E1VFVN30", inav=10000, ban=9700, kl_ban=600, mua=9650):
    return {ma: {"stockSymbol": ma, "iNAV": inav, "best1Offer": ban, "best1OfferVol": kl_ban, "best1Bid": mua}}


def test_etf_duoi_inav_tinh_tay():
    # chào bán 9.700, iNAV 10.000: lãi ròng = 10.000 × (1 − 0,15% − 0,1%) / (9.700 × 1,0015) − 1 = 9.975 / 9.714,55 − 1
    # = +2,68% ≥ 2%; giá trị 9.700 × 600 = 5,82 triệu ≥ 5 triệu -> có. Phòng hộ: 50 triệu / (1.858 × 100.000) = 0,2691 HĐ
    ds = CB.etf_duoi_inav(ssi_mau(), {}, {"VN30": ("VN30F1M", 1858.0)})
    assert [x["ma"] for x in ds] == ["E1VFVN30"]
    x = ds[0]
    assert x["lai_rong"] == round((9975 / 9714.55 - 1) * 100, 2) == 2.68 and x["mua_duoc"] == 5_820_000
    assert x["chi_so"] == "VN30" and x["hd"] == "VN30F1M" and abs(x["so_hd"] - 0.26911) < 1e-5
    assert x["etf_1_hd"] == 185_800_000
    assert CB.etf_duoi_inav(ssi_mau(kl_ban=500), {}, {}) == []  # 4,85 triệu: lô lẻ
    assert CB.etf_duoi_inav(ssi_mau(ban=9800), {}, {}) == []  # lãi ròng +1,63% < 2%
    assert CB.etf_duoi_inav(ssi_mau(), {"E1VFVN30": -2.5}, {}) == []  # quỹ thường đã rẻ hơn NAV 2,5%: không bất thường
    assert (
        CB.etf_duoi_inav(ssi_mau(ma="FUEDCMID"), {}, {"VN30": ("VN30F1M", 1858.0)})[0]["hd"] == ""
    )  # VNMID: không có HĐ


def bang_hd(mua, ban, khop, ngay="2026-10-30"):
    ny = {"lastTradingDate": "19/11/2026", "mappingSymbol": "VN30F1M", "tradingDate": ngay}
    so_lenh = {"bidPrices": [{"price": mua, "volume": 5}], "askPrices": [{"price": ban, "volume": 3}]}
    return {"41I1GB000": (ny, {"matchPrice": khop, "accumulatedVolume": 1000, "openInterest": 500}, so_lenh)}


def test_hdtl_lech_tinh_tay():
    hom_nay, cs = date(2026, 10, 30), {"VN30": (2000.0, "2026-10-30")}
    ssi = ssi_mau(inav=10000, ban=10010, kl_ban=50_000, mua=9990)
    # 20 ngày tới 19/11: hợp lý = 2.000 × e^(0,05 × 20/365) = 2.000 × 1,0027435 = 2.005,487; 14 phiên (30/10–18/11)
    ds = CB.hdtl_lech(bang_hd(2040, 2040.5, 2040), cs, ssi, hom_nay, r=0.05)
    x = ds[0]
    assert x["bi_danh"] == "VN30F1M" and x["chi_so"] == "VN30" and abs(x["hop_ly"] - 2005.48696) < 1e-4
    assert (
        x["basis"] == 40
        and abs(x["lech"] - (2040 - 2005.48696)) < 1e-4
        and P.so_phien(hom_nay, date(2026, 11, 19)) == 14
    )
    # lãi khóa = 2.040 − 2.000 × 1,001 × 1,0027435 − 12 − chi phí HĐ = 2.040 − 2.007,4925 − 12 − chi phí = 20,51 − chi phí
    chi_phi = CB.chi_phi_hd_den_dao_han(2040, 14, "VN30") / P.HE_SO_NHAN
    assert (
        abs(x["lai_khoa"] - (2040 - 2007.492451 - 12 - chi_phi)) < 1e-5
        and x["tin_hieu"] == "dat"
        and x["etf"] == "E1VFVN30"
    )
    # HĐ rẻ: chào bán 1.985 < tiền bán ETF quy ra điểm 2.000 × 0,999 × (1 − 0,15% × 2 − 0,1%) − chi phí = 1.990,008 − ~0,78
    ds = CB.hdtl_lech(bang_hd(1984, 1985, 1985), cs, ssi, hom_nay, r=0.05)
    assert ds[0]["tin_hieu"] == "re" and ds[0]["lai_khoa"] < 0
    assert (
        CB.hdtl_lech(bang_hd(1989.5, 1990.5, 1990), cs, ssi, hom_nay, r=0.05)[0]["tin_hieu"] == ""
    )  # 1.990,5: chưa đủ
    # ngoài giờ khớp lệnh: sổ lệnh còn lại và iNAV không cùng thời điểm -> không cho tín hiệu
    assert CB.hdtl_lech(bang_hd(2040, 2040.5, 2040), cs, ssi, hom_nay, r=0.05, trong_phien=False)[0]["tin_hieu"] == ""
    # chỉ số khác ngày giao dịch với HĐ: không cho tín hiệu
    assert CB.hdtl_lech(bang_hd(2040, 2040.5, 2040, ngay="2026-10-29"), cs, ssi, hom_nay, r=0.05)[0]["tin_hieu"] == ""


def test_gia_xet_khop_le_dung_gia_giao_dich_duoc():
    so_lenh = {
        "askPrices": [{"price": 1050, "volume": 100}],
        "bidPrices": [{"price": 990, "volume": 100}, {"price": "ATC"}],
    }
    # khớp cuối 1.000 × 100 = 0,1 triệu < 5 triệu: khớp lẻ -> xuống tới: giá chào bán; lên tới: giá chờ mua
    bg = ({}, {"matchPrice": 1000, "matchVol": 100}, so_lenh)
    assert CB.gia_xet(bg, "duoi") == 1050 and CB.gia_xet(bg, "tren") == 990
    assert CB.gia_xet(({}, {"matchPrice": 1000, "matchVol": 5000}, so_lenh), "duoi") == 1000  # đúng 5 triệu: giá khớp
    # HĐTL: 1 HĐ ở 1.858 điểm = 185,8 triệu: giá khớp luôn dùng được
    assert CB.gia_xet(({}, {"matchPrice": 1858, "matchVol": 1}, {}), "tren", P.HE_SO_NHAN) == 1858
    assert CB.gia_xet(({}, {"matchPrice": 0}, {}), "duoi") is None


def test_doc_form_muc():
    f = lambda **k: CB.doc_form_muc({a: [b] for a, b in k.items()})
    assert f(ma="cvpb2615", chieu="duoi", muc="0,87") == (
        {"ma": "CVPB2615", "chieu": "duoi", "muc": 870, "ghi_chu": ""},
        [],
    )
    assert f(ma="VPB", chieu="tren", muc="24,5")[0]["muc"] == 24500
    assert (
        f(ma="VN30F1M", chieu="tren", muc="1.858,5")[0]["muc"]
        == 1858.5
        == f(ma="41I1GB000", chieu="duoi", muc="1858.5")[0]["muc"]
    )
    assert f(ma="<b>X", chieu="duoi", muc="1")[1] and f(ma="VPB", chieu="ngang", muc="1")[1]
    assert f(ma="VPB", chieu="duoi", muc="abc")[1] and f(ma="VPB", chieu="duoi", muc="-5")[1]
    assert f(ma="VN30", chieu="duoi", muc="1800")[1]  # chỉ số không có giá trên bảng giá Vietcap


def test_ban_ghi_cua_bi_danh_hdtl():
    bg = bang_hd(1, 2, 1)
    assert CB.ban_ghi_cua("VN30F1M", bg)[0] == "41I1GB000" and CB.ban_ghi_cua("VN30F2M", bg) == ("VN30F2M", None)
    assert CB.he_so_cua("VN30F1M") == CB.he_so_cua("41I1GB000") == P.HE_SO_NHAN and CB.he_so_cua("VPB") == 1


def test_them_xoa_muc_va_kiem_tra_lich_5_phut():
    bg = {"VPB": ({"refPrice": 25000, "tradingDate": "2026-10-19"}, {"matchPrice": 24500, "matchVol": 1000}, {})}
    luc = datetime(2026, 10, 19, 10, 0)
    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.multiple(CB, FILE_MUC_GIA=Path(tmp) / "muc_gia.csv", THU_MUC_CHAM=Path(tmp)),
        mock.patch.object(C, "lay_bang_gia", side_effect=lambda ds, cho=30: {m: bg[m] for m in ds if m in bg}),
        mock.patch.object(CB.D, "gui_discord") as gui,
    ):
        assert CB.them_muc_gia(
            {"ma": ["VPB"], "chieu": ["duoi"], "muc": ["120"]}, HOM_NAY
        )  # 120 đ: sai đơn vị, cách 99%
        assert CB.them_muc_gia({"ma": ["CABC2601"], "chieu": ["duoi"], "muc": ["1"]}, HOM_NAY)  # không có trên bảng giá
        assert CB.them_muc_gia({"ma": ["VPB"], "chieu": ["duoi"], "muc": ["24,5"]}, HOM_NAY) == []
        assert CB.them_muc_gia({"ma": ["VPB"], "chieu": ["tren"], "muc": ["26"]}, HOM_NAY) == []
        ds = CB.doc_muc_gia()
        assert [(m["id"], m["muc"], m["ngay_tao"]) for m in ds] == [(1, 24500, "2026-10-19"), (2, 26000, "2026-10-19")]
        # 24.500 ≤ 24.500 -> chạm; 24.500 chưa ≥ 26.000. Discord đang tắt: chỉ ghi file
        assert CB.kiem_tra_muc_gia(luc=luc) == [1] and gui.call_count == 0
        assert CB.doc_da_cham("2026-10-19")["1"]["luc"] == "10:00" and CB.kiem_tra_muc_gia(luc=luc) == []
        assert CB.kiem_tra_muc_gia(luc=datetime(2026, 10, 19, 12, 0)) == []  # nghỉ trưa: không chạy
        # bật Discord: gửi mức đã chạm chưa gửi; gửi lỗi thì lần sau gửi lại
        with (
            mock.patch.object(CB, "GUI_DISCORD_MUC_GIA", True),
            mock.patch.object(
                C, "doc_env", return_value={"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/abc"}
            ),
        ):
            gui.side_effect = OSError("mất mạng")
            try:
                CB.kiem_tra_muc_gia(luc=luc)
                assert False, "lỗi gửi phải hiện ra"
            except OSError:
                pass
            gui.side_effect = None
            CB.kiem_tra_muc_gia(luc=luc)
            assert gui.call_count == 2 and "VPB" in gui.call_args[0][0] and CB.doc_da_cham("2026-10-19")["1"]["da_gui"]
            CB.kiem_tra_muc_gia(luc=luc)
            assert gui.call_count == 2  # mỗi mức tối đa 1 tin/ngày
        assert CB.xoa_muc_gia(1) == "" and [m["id"] for m in CB.doc_muc_gia()] == [2] and CB.xoa_muc_gia(9)
        (Path(tmp) / "muc_gia.csv").write_text("sai,tieu,de\n", encoding="utf-8-sig")
        try:
            CB.doc_muc_gia()
            assert False, "sai tiêu đề phải báo lỗi, không coi là rỗng"
        except ValueError:
            pass


def test_trang_mo_duoc_khi_mat_mang_va_chan_post_trang_la():
    import web
    import web_canh_bao
    import web_chung

    loi = RuntimeError("mất mạng")
    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.multiple(CB, FILE_MUC_GIA=Path(tmp) / "muc_gia.csv", THU_MUC_CHAM=Path(tmp)),
        mock.patch.object(web_chung, "doc_ket_qua", return_value=(DF_QUET, HOM_NAY)),
        mock.patch.object(CB, "ma_hdtl", side_effect=loi),
        mock.patch.object(C, "lay_bang_gia", side_effect=loi),
        mock.patch.object(CB.CK, "lay_ssi", side_effect=loi),
        mock.patch.object(CB, "gia_chi_so", side_effect=loi),
    ):
        html = web_canh_bao.trang_canh_bao()
        assert (
            "Không tải được bảng giá Vietcap" in html and "Không tải được iNAV SSI" in html and "Cảnh báo giá" in html
        )
        may_chu = HTTPServer(("127.0.0.1", 0), web.XuLy)
        threading.Thread(target=may_chu.serve_forever, daemon=True).start()
        goc = f"http://127.0.0.1:{may_chu.server_port}"
        try:
            assert urllib.request.urlopen(goc + "/canh-bao", timeout=10).status == 200
            yeu_cau = urllib.request.Request(
                goc + "/canh-bao/them", data=b"ma=VPB&chieu=duoi&muc=24", headers={"Origin": "https://la.com"}
            )
            try:
                urllib.request.urlopen(yeu_cau, timeout=5)
                assert False, "phải bị chặn"
            except urllib.error.HTTPError as e:
                assert e.code == 403
            assert CB.doc_muc_gia() == []
        finally:
            may_chu.shutdown()


def test_trang_co_du_lieu():
    import web_canh_bao
    import web_chung

    hd = bang_hd(2040, 2040.5, 2040, ngay=str(HOM_NAY))
    hd["41I1GB000"][0]["lastTradingDate"] = "19/11/2026"
    bg = {**bang_cw(2000), **hd}
    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.multiple(CB, FILE_MUC_GIA=Path(tmp) / "muc_gia.csv", THU_MUC_CHAM=Path(tmp)),
        mock.patch.object(web_chung, "doc_ket_qua", return_value=(DF_QUET, HOM_NAY)),
        mock.patch.object(CB, "ma_hdtl", return_value=["41I1GB000"]),
        mock.patch.object(C, "lay_bang_gia", return_value=bg),
        mock.patch.object(CB.CK, "lay_ssi", return_value=ssi_mau()),
        mock.patch.object(CB, "gia_chi_so", return_value=(2000.0, str(HOM_NAY))),
        mock.patch.object(web_canh_bao, "date", mock.Mock(today=mock.Mock(return_value=HOM_NAY))),
        mock.patch.object(web_canh_bao.danh_muc, "trong_gio_khop_lenh", return_value=True),
    ):
        html = web_canh_bao.trang_canh_bao()
    assert "Ngoài giờ khớp lệnh" not in html
    assert "CVPB2615" in html and "-22,9%" in html  # CW rẻ bất thường
    assert (
        "E1VFVN30" in html and "+2,68%" in html and "0,25 HĐ VN30F1M" in html
    )  # phòng hộ: 50 triệu / (2.040 × 100.000) = 0,245 HĐ
    assert "VN30F1M" in html and "41I1GB000" in html and "Đắt: bán HĐ + mua ETF" in html  # HĐTL đắt
    assert "<script>alert" not in html


if __name__ == "__main__":
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - cảnh báo giá đúng")
