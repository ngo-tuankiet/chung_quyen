"""Cấu hình chung của pytest: không test nào ghi file nhớ lịch sử CW vào ket_qua/ thật."""

import pytest

import danh_muc


@pytest.fixture(autouse=True)
def nho_lich_su_cw_tam(tmp_path, monkeypatch):
    monkeypatch.setattr(danh_muc, "THU_MUC_NHO_CW", tmp_path)
