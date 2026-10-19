"""Kiểm tra danh mục + cảnh báo. Chạy: python -m pytest -q   hoặc   python test_danh_muc.py (không cần cài pytest)."""

import io
import json
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
    assert json.loads(yeu_cau.data) == {"content": "⚠ CVPB2615: lỗ"} and yeu_cau.get_method() == "POST"


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
        D.FILE_DANH_MUC.write_text("hỏng", encoding="utf-8")  # sai tiêu đề: phải báo lỗi, KHÔNG coi là rỗng
        assert "File danh_muc.csv bị lỗi" in web.trang_danh_muc()
        form = {"ngay": ["2026-10-01"], "ma_cw": ["CVPB2615"], "loai": ["MUA"], "so_luong": ["100"], "gia": ["1000"]}
        try:
            D.them_lenh(form, {"CVPB2615"}, HOM_NAY)
            assert False, "phải từ chối ghi khi file hỏng"
        except ValueError:
            assert D.FILE_DANH_MUC.read_text(encoding="utf-8") == "hỏng"  # không bị ghi đè


if __name__ == "__main__":  # chạy không cần pytest
    for ten, ham in list(globals().items()):
        if ten.startswith("test_"):
            ham()
    print("OK - danh mục đúng")
