@echo off
rem Nhap dup file nay de chay giao dien web tren Windows. Lan dau tu tao moi truong rieng va cai vnstock.
rem Moi lenh kiem tra loi viet bang "if errorlevel 1" o dong rieng - cach viet chay dung tren moi phien ban cmd.
cd /d "%~dp0"
if not exist cw_scanner.py (
  echo LOI: Ban dang chay file ben trong file zip. Hay chuot phai vao file zip, chon Extract All, roi chay file nay trong thu muc vua giai nen.
  pause
  exit /b 1
)

echo [1/3] Tim Python 3.10+ va tao moi truong rieng...
rem Thu lenh "py" truoc, khong co thi thu "python"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv 2>nul
if not exist .venv\Scripts\python.exe python -m venv .venv 2>nul
if not exist .venv\Scripts\python.exe (
  echo LOI: May chua cai Python. Tai tai https://www.python.org/downloads/ - khi cai nho tick o "Add python.exe to PATH", cai xong chay lai file nay.
  pause
  exit /b 1
)
rem Kiem tra phien ban khong dung dau nho hon/lon hon vi cmd co the hieu nham la chuyen huong
.venv\Scripts\python -c "import sys; sys.exit(sys.version_info.__lt__((3, 10)))"
if errorlevel 1 (
  echo LOI: Python tren may qua cu - vnstock can Python 3.10 tro len. Cai ban moi tai https://www.python.org/downloads/ roi chay lai file nay.
  rmdir /s /q .venv
  pause
  exit /b 1
)

echo [2/3] Cai vnstock theo requirements.txt - lan dau mat vai phut...
.venv\Scripts\python -m pip install -q --extra-index-url https://vnstocks.com/api/packages -r requirements.txt
.venv\Scripts\python -m pip show vnstock >nul 2>nul
if errorlevel 1 (
  echo LOI: Cai vnstock that bai - kiem tra mang Internet, chup man hinh thong bao phia tren gui cho nguoi ho tro.
  pause
  exit /b 1
)

echo [3/3] Mo giao dien web tai http://localhost:8000 - KHONG dong cua so nay khi dang dung, dong lai de tat.
set PYTHONUTF8=1
.venv\Scripts\python web.py
pause
