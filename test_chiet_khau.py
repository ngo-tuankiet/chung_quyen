"""Kiểm tra chiet_khau.py bằng dữ liệu giả (không gọi mạng). Chạy: python -m pytest -q   hoặc   python test_chiet_khau.py"""

import json
import math
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

import pandas as pd

import chiet_khau as CK
import cw_scanner


def ban_ghi(ma="FUEIP100", inav=10_000.0, chao_ban=((9_700, 300), (9_750, 500), (9_900, 1_000)), ngay="20261023"):
    bg = {"stockSymbol": ma, "tradingDate": ngay, "iNAV": inav, "prevINAV": 9_950.0, "best1Bid": 9_600}
    for i, (g, v) in enumerate(chao_ban, 1):
        bg[f"best{i}Offer"], bg[f"best{i}OfferVol"] = g, v
    return bg


def test_lai_rong_tinh_tay():
    # mua 9.700 + phí 0,15% = 9.714,55; bán ở NAV 10.000 − phí 0,15% − thuế 0,1% = 9.975 -> 9.975 / 9.714,55 − 1 = +2,681%
    assert math.isclose(CK.lai_rong_neu_ve_nav(9_700, 10_000), 9_975 / 9_714.55 - 1)
    assert math.isclose(CK.lai_rong_neu_ve_nav(9_700, 10_000), 0.026810, abs_tol=1e-6)
    # chiết khấu 2% chưa đủ lãi ròng 2%: 9.975 / (9.800 × 1,0015) − 1 = +1,63%
    assert CK.lai_rong_neu_ve_nav(9_800, 10_000) < CK.NGUONG_LAI_RONG


def test_danh_gia_quy_cong_cac_muc_dat_nguong():
    dg = CK.danh_gia_quy(ban_ghi())
    assert dg["Giá chào bán"] == 9_700 and dg["KL chào bán"] == 300
    assert dg["Chiết khấu mua được %"] == -3.0 and dg["Lãi ròng nếu về NAV %"] == 2.68
    # 9.750: 9.975 / (9.750 × 1,0015) − 1 = +2,15% đạt; 9.900: +0,61% không đạt
    # -> mua được 9.700 × 300 + 9.750 × 500 = 2.910.000 + 4.875.000 = 7.785.000 đ ≥ 5 triệu
    assert dg["Mua được đạt ngưỡng (đ)"] == 7_785_000 >= CK.MIN_GIA_TRI_CHAO_BAN
    it = CK.danh_gia_quy(ban_ghi(chao_ban=((9_700, 100),)))  # 1 lô 100 CCQ = 970.000 đ: không đáng báo
    assert it["Mua được đạt ngưỡng (đ)"] == 970_000 < CK.MIN_GIA_TRI_CHAO_BAN


def test_gia_mua_1_lenh_tinh_tay():
    # lệnh 5 triệu: 300 CCQ × 9.700 = 2.910.000; còn 2.090.000 / 9.750 = 214,36 CCQ -> 5.000.000 / 514,36 = 9.720,84 đ
    assert math.isclose(CK.gia_mua_lenh(ban_ghi(), 5_000_000), 5e6 / (300 + 2.09e6 / 9_750))
    assert math.isclose(CK.gia_mua_lenh(ban_ghi(), 5_000_000), 9_720.84, abs_tol=0.01)
    assert math.isnan(CK.gia_mua_lenh(ban_ghi()))  # 3 mức chỉ có 17.685.000 đ < 1 lệnh 50 triệu
    # sổ dày: 3.000 × 9.700 = 29,1 triệu + 20,9 triệu / 9.800 = 2.132,65 CCQ -> 50 triệu / 5.132,65 = 9.741,55 -> CK −2,58%
    # (giá chào bán tốt nhất 9.700 cho CK −3,0%: phần lệnh ăn sang mức 2 đắt hơn)
    day = CK.danh_gia_quy(ban_ghi(chao_ban=((9_700, 3_000), (9_800, 3_000))))
    assert day["CK 1 lệnh %"] == -2.58 and day["Chiết khấu mua được %"] == -3.0
    assert math.isnan(CK.danh_gia_quy(ban_ghi())["CK 1 lệnh %"])


def test_gia_tri_chao_ban_duoi_inav_tinh_tay():
    # iNAV 10.000, ngưỡng −2% -> giá ≤ 9.800: 9.700 × 300 + 9.750 × 500 = 2.910.000 + 4.875.000 = 7.785.000; 9.900 không tính
    assert CK.gia_tri_duoi_inav(ban_ghi()) == 7_785_000
    assert CK.gia_tri_duoi_inav(ban_ghi(chao_ban=((9_800, 600),))) == 5_880_000  # đúng −2,0%: tính
    assert CK.gia_tri_duoi_inav(ban_ghi(chao_ban=((9_801, 600),))) == 0  # −1,99%: chưa tới
    assert CK.gia_tri_duoi_inav(ban_ghi(inav=0)) == 0


def test_giu_may_thuc_trong_khung_gio():
    with mock.patch.object(CK.subprocess, "Popen") as p:
        CK.giu_may_thuc(datetime(2026, 10, 23, 12, 0))  # thứ Sáu nghỉ trưa: vẫn giữ để 13:00 máy còn thức
        assert p.call_args[0][0] == ["/usr/bin/caffeinate", "-i", "-t", "360"] and p.call_args[1]["start_new_session"]
        for luc in (datetime(2026, 10, 23, 8, 59), datetime(2026, 10, 23, 14, 46), datetime(2026, 10, 24, 10, 0)):
            CK.giu_may_thuc(luc)  # trước 9:00, sau 14:45, thứ Bảy
        assert p.call_count == 1


def test_danh_gia_quy_thieu_du_lieu():
    for bg in (ban_ghi(inav=0), ban_ghi(chao_ban=()), {"stockSymbol": "X"}):
        dg = CK.danh_gia_quy(bg)
        assert math.isnan(dg["Chiết khấu mua được %"]) and dg["Mua được đạt ngưỡng (đ)"] == 0


def test_lam_sach_nav_cua_vietcap():
    dong = [
        {"tradingDate": "2026-10-15", "navPerShare": 100},  # thứ Năm
        {"tradingDate": "2026-10-16", "navPerShare": 100},  # thứ Sáu: lặp số thứ Năm
        {"tradingDate": "2026-10-18", "navPerShare": 101},  # Chủ nhật: NAV thật của thứ Sáu
        {"tradingDate": "2026-10-19", "navPerShare": 102},
        {"tradingDate": "2026-10-19", "navPerShare": 102},  # trùng ngày cùng số: giữ 1
        {"tradingDate": "2026-10-20", "navPerShare": None},
        {"tradingDate": "2026-10-24", "navPerShare": 103},  # thứ Bảy: bỏ
    ]
    ky_vong = {pd.Timestamp("2026-10-15"): 100, pd.Timestamp("2026-10-16"): 101, pd.Timestamp("2026-10-19"): 102}
    assert CK.lam_sach_nav(dong).to_dict() == ky_vong
    assert CK.lam_sach_nav(dong[::-1]).to_dict() == ky_vong  # không phụ thuộc thứ tự Vietcap trả về


def test_lam_sach_nav_bo_ngay_trung_khac_so():
    # Dữ liệu thật FUEMAV30: ngày 07/10/2026 có 2 số; số sau (23.037,48) thật ra là NAV 08/10 -> không biết số nào đúng: bỏ ngày đó
    # (trước đây giữ dòng sau -> biểu đồ chênh lệch có gai giả +2,05% thay vì ≈ +1,1%)
    dong = [
        {"tradingDate": "2026-10-06", "navPerShare": 23_283.34},
        {"tradingDate": "2026-10-07", "navPerShare": 23_247.98},
        {"tradingDate": "2026-10-07", "navPerShare": 23_037.48},
        {"tradingDate": "2026-10-08", "navPerShare": 23_037.48},
    ]
    assert list(CK.lam_sach_nav(dong).index) == [pd.Timestamp("2026-10-06"), pd.Timestamp("2026-10-08")]


def test_bo_nav_loi_theo_ty_le_nav_chi_so():
    ngay = pd.bdate_range("2026-03-30", periods=9)
    cs = pd.Series([100, 100.5, 100.2, 100.85, 106.29, 106.0, 106.3, 106.1, 106.4], ngay)
    dung = cs / 10  # NAV bám chỉ số
    # Dữ liệu thật FUESSVFL: dòng 07/04/2026 là NAV của 08/04 (chỉ số 07/04 +0,85%, 08/04 +5,39%) -> tỷ lệ NAV/CS lệch 5,4%
    sai = dung.copy()
    sai[ngay[3]] = dung[ngay[4]]
    assert ngay[3] not in CK.bo_nav_loi(sai, cs).index and len(CK.bo_nav_loi(sai, cs)) == 8
    # Lệch nhỏ 1,2% (E1VFVN30 14/11/2025: NAV thứ Hai bị dời về thứ Sáu) cũng bị bỏ; quỹ bám tốt lệch ngày chỉ ~0,0x%
    nho = dung.copy()
    nho[ngay[6]] = dung[ngay[6]] * 1.012
    assert ngay[6] not in CK.bo_nav_loi(nho, cs).index
    assert len(CK.bo_nav_loi(dung * (1 + 0.001 * (ngay.dayofweek % 2)), cs)) == 9  # nhiễu 0,1%: giữ hết
    bac = dung * [1, 1, 1, 1, 1.03, 1.03, 1.03, 1.03, 1.03]  # tỷ lệ đổi hẳn từ 1 ngày (vd quỹ chia lợi tức): giữ
    assert len(CK.bo_nav_loi(bac, cs)) == 9
    gai_cuoi = dung.copy()
    gai_cuoi[ngay[-1]] = dung[ngay[-1]] * 1.05  # gai ở ngày cuối: chưa có phiên sau để xác nhận -> bỏ tạm
    assert ngay[-1] not in CK.bo_nav_loi(gai_cuoi, cs).index


def test_thong_ke_nav():
    ngay = pd.bdate_range(end="2026-10-22", periods=520)
    nav = pd.Series(10_000.0, ngay[ngay <= pd.Timestamp("2026-10-20")])  # Vietcap trễ 2 phiên
    gia = pd.Series(10_100.0, ngay)
    gia[ngay <= pd.Timestamp("2025-10-20")] = 9_900.0
    gia[pd.Timestamp("2025-10-21")] = gia[pd.Timestamp("2025-10-22")] = 10_500.0
    gia[pd.Timestamp("2026-06-01")] = 9_700.0
    cs = pd.Series(1_000.0, ngay)
    cs[ngay[-1]] = 1_100.0  # hôm nay chỉ số +10%
    tk = CK.thong_ke_nav(gia, nav, cs, ngay[-1], 10_000.0)
    # 1 năm tới NAV cuối: hầu hết 10.100 / 10.000 − 1 = +1%, sâu nhất 9.700 -> −3%
    assert tk["CL NAV trung vị 1N %"] == 1.0 and tk["CL NAV thấp nhất 1N %"] == -3.0
    # mốc giá/NAV 1 năm trước = đúng mốc của lợi nhuận giá (22/10/2026 − 12 tháng = 22/10/2025): 10.500 -> +5% (không phải 20/10/2025)
    assert tk["CL NAV 1N trước %"] == 5.0
    # NAV so CS tính tới hôm nay bằng iNAV: iNAV 10.000 / NAV 22/10/2025 10.000 − 1 = 0; chỉ số 1.100 / 1.000 − 1 = +10% -> −10 điểm
    assert tk["NAV so CS 1N"] == -10.0 and tk["Ngày NAV cuối"] == "2026-10-20"
    # không có iNAV: tính tới ngày NAV cuối (20/10/2026), chỉ số lúc đó chưa tăng -> 0
    assert CK.thong_ke_nav(gia, nav, cs, ngay[-1])["NAV so CS 1N"] == 0.0
    assert math.isnan(CK.thong_ke_nav(gia, nav, None, ngay[-1], 10_000.0)["NAV so CS 1N"])  # chưa rõ chỉ số mô phỏng
    assert CK.thong_ke_nav(gia, None, None, ngay[-1])["Ngày NAV cuối"] == ""


def test_muc_tut_va_dong_dat_nguong_voi_gia_cu():
    # FUEKIVFS 22/10/2026: không khớp từ 02/10 (14 phiên), giá khớp cuối 16.210 < iNAV 16.726 nhưng chào bán 17.330:
    # "giá/NAV −3,1%" là ảo -> mục quỹ tụt không in giá/NAV hiện tại, ghi rõ số phiên chưa khớp
    df = pd.DataFrame(
        [
            {"Loại": "Chỉ số", "Mã": "VNFINSELECT", "1N %": -9.5},
            {
                "Loại": "ETF",
                "Mã": "FUEKIVFS",
                "Chỉ số": "VNFINSELECT",
                "Giá": 16_210.0,
                "1N %": -11.0,
                "iNAV": 16_726.34,
                "Giá chào bán": 17_330.0,
                "Chiết khấu mua được %": 3.61,
                "Lãi ròng nếu về NAV %": -3.9,
                "Mua được đạt ngưỡng (đ)": 0.0,
                "CL NAV trung vị 1N %": 0.1,
                "CL NAV 1N trước %": 0.5,
                "NAV so CS 1N": -0.4,
                "Phiên chưa khớp": 14,
                "Ngày giá cuối": "2026-10-02",
                "GTGD TB20 (tỷ)": 0.004,
            },
        ]
    )
    tut = CK.muc_bao_cao(df)[1]
    assert "**FUEKIVFS**: giá -1,5 điểm so VNFINSELECT" in tut and "-3,1%" not in tut
    assert "giá/NAV +0,5% → —" in tut and "14 phiên chưa khớp (khớp cuối 02/10)" in tut


def _chay(tmp, ssi, luc, bat=True, url="https://discord.com/api/webhooks/1/x"):
    gui = mock.Mock()
    with (
        mock.patch.object(cw_scanner, "THU_MUC_KET_QUA", Path(tmp)),
        mock.patch.object(CK, "FILE_DA_BAO", Path(tmp) / "da_bao.json"),
        mock.patch.object(CK, "BAT_CANH_BAO_TRONG_PHIEN", bat),
        mock.patch.object(CK, "lay_ssi", return_value=ssi) as lay,
        mock.patch.object(CK.C, "doc_env", return_value={"DISCORD_WEBHOOK_URL": url} if url else {}),
        mock.patch.object(CK.D, "gui_discord", gui),
    ):
        return CK.kiem_tra_trong_phien(luc=luc), gui, lay


def test_kiem_tra_trong_phien():
    ssi = {"FUEIP100": ban_ghi(), "E1VFVN30": ban_ghi("E1VFVN30", inav=33_900, chao_ban=((33_980, 5_000),))}
    luc = datetime(2026, 10, 23, 10, 0)
    with tempfile.TemporaryDirectory() as tmp:
        assert _chay(tmp, ssi, datetime(2026, 10, 23, 12, 0))[2].call_count == 0  # nghỉ trưa: không gọi mạng
        assert _chay(tmp, {m: {**b, "tradingDate": "20261022"} for m, b in ssi.items()}, luc)[0] == []  # ngày nghỉ
        assert not (Path(tmp) / "inav_2026-10-23.csv").exists()
        bao, gui, _ = _chay(tmp, ssi, luc, bat=False)  # chưa bật cảnh báo: chỉ ghi iNAV
        assert bao == [] and gui.call_count == 0
        dong = (Path(tmp) / "inav_2026-10-23.csv").read_text(encoding="utf-8-sig").splitlines()
        assert dong[0].startswith("Giờ,Mã,iNAV") and dong[1].startswith("10:00:00,E1VFVN30,33900")
        assert _chay(tmp, ssi, luc, url="")[0] == []  # chưa có webhook: không lưu trạng thái
        # FUESSV30 bình thường cao hơn NAV +1,0%: chào bán 7,8 triệu ở giá ≤ iNAV −2% là bất thường -> báo.
        # FUEIP100 cùng sổ lệnh nhưng thường đã −4,6%: rẻ như vậy là bình thường của nó -> không báo
        pd.DataFrame(
            {"Mã": ["FUEIP100", "FUESSV30"], "CL NAV trung vị 1N %": [-4.6, 1.0], "GTGD TB20 (tỷ)": [0.012, 0.24]}
        ).to_csv(Path(tmp) / "etf_2026-10-22.csv", index=False, encoding="utf-8-sig")
        ssi["FUESSV30"] = ban_ghi("FUESSV30")
        bao, gui, _ = _chay(tmp, ssi, luc)
        tin = gui.call_args[0][0]
        assert bao == ["FUESSV30"] and gui.call_count == 1 and tin.startswith("**🔻 ETF giảm bất thường so với iNAV**")
        assert (
            "🔻 **FUESSV30**: chào bán 9.700 × 300 CCQ, iNAV 10.000 (-3,0%) · có 8 triệu chào bán ở giá ≤ iNAV −2%"
            " · thường lệch NAV +1,0% (trung vị 1 năm) · GTGD TB20 0,24 tỷ" in tin
        )
        assert "FUEIP100" not in tin and "E1VFVN30" not in tin  # E1VFVN30: chào bán cao hơn iNAV
        assert _chay(tmp, ssi, datetime(2026, 10, 23, 10, 5))[1].call_count == 0  # cùng ngày: không báo lại
        hom_sau = {m: {**b, "tradingDate": "20261026"} for m, b in ssi.items()}
        assert _chay(tmp, hom_sau, datetime(2026, 10, 26, 9, 30))[0] == ["FUESSV30"]
        assert json.loads((Path(tmp) / "da_bao.json").read_text(encoding="utf-8")) == {"FUESSV30": "2026-10-26"}
        assert (
            len((Path(tmp) / "inav_2026-10-23.csv").read_text(encoding="utf-8-sig").splitlines()) == 1 + 2 * 2 + 3 * 2
        )  # 2 lần 2 quỹ, 2 lần 3 quỹ


def test_lay_ssi_chi_nhan_ma_hop_le():
    du_lieu = {
        "data": [{"stockSymbol": "E1VFVN30"}, {"stockSymbol": "X<img src=x onerror=1>"}, {"stockSymbol": ""}, {}]
    }
    with mock.patch.object(CK.C, "tai_json", return_value=du_lieu):
        assert list(CK.lay_ssi()) == ["E1VFVN30"]


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - chiết khấu đúng")
