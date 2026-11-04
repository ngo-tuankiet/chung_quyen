"""Test nút 🔄 Quét (web.VIEC_QUET, chạy nền, màn hình chờ). Không gọi mạng: các bước quét là hàm giả."""

import http.client
import io
import json
import threading
import time
from http.server import HTTPServer
from unittest import mock

import pytest

import web
import web_chung as W


@pytest.fixture(autouse=True)
def quet_sach():
    """Mỗi test bắt đầu với trạng thái quét sạch, xong thì trả lại như cũ."""
    cu = dict(W.QUET)
    W.QUET.update(dang=False, loai="", tab="", buoc="", bat_dau=None, xong=None, loi="", nhat_ky=io.StringIO())
    yield
    W.QUET.clear()
    W.QUET.update(cu)


def test_thoi_luong():
    assert W.thoi_luong(125) == "2 phút 5 giây" and W.thoi_luong(35.9) == "35 giây"


def test_nut_quet_theo_tab():
    assert set(web.TAB_QUET) == set(web.VIEC_QUET)  # mỗi loại quét có đúng 1 tab hiện nút
    canh_bao = W.trang("x", "", "/canh-bao")
    assert 'name="loai" value="tat-ca"' in canh_bao and "🔄 Quét tất cả" in canh_bao
    for dd, loai in (("/", "cw"), ("/etf", "etf"), ("/phai-sinh", "phai-sinh"), ("/danh-muc", "danh-muc")):
        assert f'name="loai" value="{loai}"' in W.trang("x", "", dd)
    huong_dan = W.trang("x", "", "/huong-dan")
    assert 'action="/quet"' not in huong_dan
    assert 'id="nut-bao"' in huong_dan and f'data-giay="{W.GIAY_HOI_CANH_BAO}"' in huong_dan  # nút 🔊 ở mọi trang
    W.QUET["dang"] = True
    assert 'action="/quet"' not in W.trang("x", "", "/etf")  # đang quét: ẩn nút


def test_huong_dan_ghi_dung_tin_discord():
    import danh_muc
    import web_huong_dan

    # mục Câu hỏi liệt kê đúng các loại trong danh_muc.BAT_THUONG (audit 04/11/2026: trước ghi cả "gần giá thực hiện", "IV bất
    # thường" vốn chỉ hiện trên web, và "không gửi số tiền" dù tin CW đắt có số tiền)
    assert set(danh_muc.BAT_THUONG) <= set(web_huong_dan.TEN_BAO)
    trang = web_huong_dan.trang_huong_dan()
    assert all(web_huong_dan.TEN_BAO[k] in trang for k in danh_muc.BAT_THUONG) and "không gửi số tiền" not in trang
    assert 'href="#canh-bao"' in trang  # mục lục có mục 11 Cảnh báo
    assert "&lt;b&gt;" not in trang  # câu trả lời được ESC: thẻ HTML trong đó hiện thành chữ


def test_quet_tat_ca_mot_buoc_loi_van_chay_buoc_sau():
    da_chay = []

    def cw():
        da_chay.append("cw")
        print("Tìm thấy 300 chứng quyền")
        raise ConnectionError("mất mạng")

    def quy():
        da_chay.append("etf")
        print("[!] quỹ FUEXX thiếu NAV")

    with (
        mock.patch.dict(web.VIEC_QUET, {"tat-ca": [("chứng quyền", cw), ("ETF", quy)]}),
        mock.patch.dict(web.phai_sinh.BO_NHO, {"du_lieu": (1.0, "giá cũ")}),
    ):
        web.bat_dau_quet("tat-ca").join(5)
        assert web.phai_sinh.BO_NHO == {}  # xong là bỏ giá đã nhớ
    q = W.QUET
    assert (
        da_chay == ["cw", "etf"] and not q["dang"] and q["tab"] == "/canh-bao" and q["loi"] == "chứng quyền: mất mạng"
    )
    trang = W.trang("Cảnh báo giá", "", "/canh-bao")
    assert "Quét tất cả lúc" in trang and "có lỗi: chứng quyền: mất mạng" in trang
    assert (
        "[!] quỹ FUEXX thiếu NAV" in trang and '<details class="ket-qua-quet" open>' in trang
    )  # có lỗi: tự mở nhật ký
    assert "có lỗi" not in W.trang("ETF", "", "/etf")  # kết quả chỉ hiện ở tab đã bấm


def test_systemexit_khong_ket_man_hinh_cho():
    def thoat():
        raise SystemExit("vnstock đòi cập nhật")

    with mock.patch.dict(web.VIEC_QUET, {"cw": [("chứng quyền", thoat)]}):
        web.bat_dau_quet("cw").join(5)
    assert not W.QUET["dang"] and W.QUET["loi"] == "chứng quyền: vnstock đòi cập nhật"


def test_phai_sinh_chi_bo_bo_nho_chay_luon():
    with mock.patch.dict(web.phai_sinh.BO_NHO, {"du_lieu": (1.0, "giá cũ")}), mock.patch.dict(W.BO_NHO_NEN, {"X": 1}):
        assert web.bat_dau_quet("phai-sinh") is None  # không có bước: không tạo luồng nền
        assert web.phai_sinh.BO_NHO == {} and W.BO_NHO_NEN == {}
    trang = W.trang("x", "", "/phai-sinh")
    assert not W.QUET["dang"] and "✓ Quét giá phái sinh xong lúc" in trang and "xem nhật ký" not in trang


@pytest.mark.parametrize(
    "referer, ve",
    [
        ("http://localhost:8000/cw/CVNM2616?von=5", "/cw/CVNM2616"),
        ("http://localhost:8000//la.com/x", "/etf"),  # chặn chuyển hướng sang trang lạ
        ("", "/etf"),
    ],
)
def test_trang_ve(referer, ve):
    assert web.trang_ve({"Referer": referer}, "etf") == ve


def test_may_chu_trong_luc_quet():
    cho, so_lan = threading.Event(), []
    may_chu = HTTPServer(("127.0.0.1", 0), web.XuLy)
    goc = f"http://localhost:{may_chu.server_port}"
    threading.Thread(target=may_chu.serve_forever, daemon=True).start()

    def goi(cach, duong, than=None):
        ket_noi = http.client.HTTPConnection("127.0.0.1", may_chu.server_port, timeout=5)
        tieu_de = {"Origin": goc, "Referer": goc + "/etf/E1VFVN30", "Content-Type": "application/x-www-form-urlencoded"}
        ket_noi.request(cach, duong, body=than, headers=tieu_de)
        tl = ket_noi.getresponse()
        return tl.status, tl.getheader("Location"), tl.read().decode("utf-8")

    tin = {
        "ngoai_gio": False,
        "tin": [{"id": "2026-11-02|cw|CVNM2616", "tieu_de": "CW rẻ", "noi_dung": "x", "link": "/"}],
    }

    def quet_etf():
        so_lan.append(1)
        print("[!] FUEXX thiếu NAV")
        cho.wait(5)

    with (
        mock.patch.dict(web.VIEC_QUET, {"etf": [("ETF", quet_etf)]}),
        mock.patch.object(web, "CONG", may_chu.server_port),
        mock.patch.object(web, "trang_etf", lambda: W.trang("Quỹ ETF", "<h1>Quỹ ETF</h1>", "/etf")),
        mock.patch.object(web.web_canh_bao, "tin_canh_bao", return_value=tin) as tin_canh_bao,
    ):
        try:
            assert goi("POST", "/quet", "loai=etf")[:2] == (303, "/etf/E1VFVN30")  # quay về trang đang xem
            trang_cho = goi("GET", "/etf")[2]
            assert "⏳ Đang quét ETF" in trang_cho and "location.reload" in trang_cho
            assert "⏳ Đang quét" not in goi("GET", "/huong-dan")[2]
            assert (
                json.loads(goi("GET", "/canh-bao/tin")[2])["dang_quet"] and not tin_canh_bao.called
            )  # không đọc file dở
            assert goi("POST", "/quet", "loai=etf")[0] == 303 and so_lan == [1]  # bấm thêm: không chạy lần 2
            assert goi("POST", "/danh-muc/them", "ma=CVNM2616")[0] == 409
            assert goi("POST", "/quet", "loai=xoa-het")[0] == 400
            cho.set()
            for _ in range(50):
                if not W.QUET["dang"]:
                    break
                time.sleep(0.1)
            trang = goi("GET", "/etf")[2]
            assert "<h1>Quỹ ETF</h1>" in trang and "✓ Quét ETF xong lúc" in trang and "1 dòng cảnh báo [!]" in trang
            assert json.loads(goi("GET", "/canh-bao/tin")[2]) == tin
        finally:
            cho.set()
            may_chu.shutdown()
