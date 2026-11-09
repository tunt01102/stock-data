"""Build the standalone, no-install distribution.

Creates dist/BDS-HOSE-App/ (+ a .zip) containing:
  - app/                 the code, web UI and pre-downloaded CSV data
  - runtime/<platform>/  a portable Python (python-build-standalone) per OS
  - double-click launchers for Windows and macOS, and a Vietnamese guide

Run on any machine with Python 3.8+ and internet:  python tools/build_dist.py
"""
import hashlib
import os
import shutil
import stat
import sys
import tarfile
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(DIST, "BDS-HOSE-App")
CACHE = os.path.join(DIST, "_cache")

PBS_TAG = "20261026"
PBS_PY = "3.12.16"
BASE = "https://github.com/astral-sh/python-build-standalone/releases/download/%s/" % PBS_TAG
RUNTIMES = {
    "mac-arm64": "cpython-%s+%s-aarch64-apple-darwin-install_only_stripped.tar.gz",
    "mac-x64": "cpython-%s+%s-x86_64-apple-darwin-install_only_stripped.tar.gz",
    "windows-x64": "cpython-%s+%s-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
}
# parts of the stdlib the app never uses (keeps the download small)
PRUNE = {"test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3",
         "pydoc_data", "__pycache__", "include", "share", "tcl", "tk", "Tools"}

sys.path.insert(0, os.path.join(ROOT, "app"))
from core.net import ssl_context  # noqa: E402  (bundled CA certificates)


def download(name):
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, name)
    if not os.path.exists(dst):
        print("  tải", name)
        req = urllib.request.Request(BASE + name, headers={"User-Agent": "bds-build"})
        with urllib.request.urlopen(req, context=ssl_context(), timeout=300) as r, open(dst + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(dst + ".part", dst)
    return dst


def checksums():
    p = download("SHA256SUMS")
    out = {}
    for line in open(p, encoding="utf-8"):
        parts = line.split()
        if len(parts) == 2:
            out[parts[1]] = parts[0]
    return out


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prune(tree):
    for dirpath, dirnames, _ in os.walk(tree, topdown=True):
        for d in list(dirnames):
            if d in PRUNE or d.startswith("tk8") or d.startswith("tcl8"):
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)


def safe_extract(tar, dest):
    base = os.path.realpath(dest)
    for m in tar.getmembers():
        target = os.path.realpath(os.path.join(dest, m.name))
        if not target.startswith(base + os.sep) and target != base:
            raise RuntimeError("unsafe path in archive: %s" % m.name)
    tar.extractall(dest)


def copy_app():
    src = os.path.join(ROOT, "app")
    dst = os.path.join(OUT, "app")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "settings.json", "*.tmp", ".DS_Store")
    shutil.copytree(src, dst, ignore=ignore)


MAC_LAUNCHER = r'''#!/bin/bash
# Mở ứng dụng Phân tích BĐS HOSE trên macOS (bấm đúp vào file này).
cd "$(dirname "$0")"
DIR="$(pwd)"
# Gỡ cờ "tải từ internet" để macOS cho phép chạy Python đi kèm
xattr -dr com.apple.quarantine "$DIR" 2>/dev/null
if [ "$(uname -m)" = "arm64" ]; then PY="$DIR/runtime/mac-arm64/python/bin/python3"; else PY="$DIR/runtime/mac-x64/python/bin/python3"; fi
if [ ! -x "$PY" ]; then PY="$(command -v python3)"; fi
if [ -z "$PY" ]; then echo "Không tìm thấy Python đi kèm. Hãy tải lại bản đầy đủ."; read -n 1; exit 1; fi
echo "Đang khởi động... (đóng cửa sổ này để tắt ứng dụng)"
"$PY" "$DIR/app/server.py"
'''

WIN_LAUNCHER = "\r\n".join([
    "@echo off",
    "rem Mo ung dung Phan tich BDS HOSE tren Windows (bam dup vao file nay).",
    "rem Luu duong dan thu muc NGAY DAU TIEN: %~dp0 co the bi tinh lai sai sau lenh cd.",
    "set \"HERE=%~dp0\"",
    "chcp 65001 >nul",
    "cd /d \"%HERE%\"",
    "set \"PY=%HERE%runtime\\windows-x64\\python\\python.exe\"",
    "if not exist \"%PY%\" (",
    "  echo Khong tim thay Python di kem trong thu muc runtime. Hay giai nen lai ban day du.",
    "  pause",
    "  exit /b 1",
    ")",
    "echo Dang khoi dong... (dong cua so nay de tat ung dung)",
    "\"%PY%\" \"%HERE%app\\server.py\"",
    "if errorlevel 1 pause",
    ""])

GUIDE = """HƯỚNG DẪN SỬ DỤNG – Ứng dụng Phân tích 55 cổ phiếu BĐS sàn HOSE
=================================================================

Không cần cài đặt gì. Chỉ cần giải nén thư mục này ra máy.

1) MỞ ỨNG DỤNG
   • Windows: bấm đúp "Mo ung dung (Windows).bat".
     Nếu Windows hiện "Windows protected your PC": bấm "More info" → "Run anyway".
   • macOS:   lần đầu, bấm CHUỘT PHẢI vào "Mo ung dung (Mac).command" → chọn "Open" → "Open".
     (Các lần sau chỉ cần bấm đúp.) Nếu macOS vẫn chặn: System Settings → Privacy & Security
     → kéo xuống, bấm "Open Anyway".
   Trình duyệt sẽ tự mở trang http://127.0.0.1:8686 (hoặc cổng kế tiếp nếu cổng này bận).
   Giữ cửa sổ đen (Terminal/Command Prompt) mở trong lúc dùng; đóng nó để tắt ứng dụng.

2) DỮ LIỆU
   • Đã có sẵn dữ liệu từ 01/2018 đến ngày đóng gói. Mỗi lần mở ứng dụng (có internet),
     các ngày còn thiếu sẽ tự được tải thêm. Có thể bấm "Làm mới dữ liệu" bất kỳ lúc nào.
   • Nếu không tải được dữ liệu mới, ứng dụng hiện KHUNG ĐỎ ghi rõ dữ liệu tính đến ngày nào.
   • Toàn bộ dữ liệu là file CSV trong thư mục app/data (mở được bằng Excel).
     Tab "Tải dữ liệu" cho phép tải CSV từng mã, một nhóm, hoặc tất cả.

3) AI (không bắt buộc)
   Tab "Cài đặt": nhập API key của Claude, Gemini hoặc OpenAI nếu muốn AI giải thích số liệu.
   Không có key ứng dụng vẫn chạy đầy đủ.

4) LƯU Ý
   • Dữ liệu chỉ phục vụ học tập, không phải khuyến nghị đầu tư.
   • Ứng dụng chỉ chạy trên máy của bạn, không chia sẻ dữ liệu ra ngoài
     (trừ khi bạn dùng AI: câu hỏi và bảng số liệu tóm tắt được gửi tới nhà cung cấp AI bạn chọn).
"""


def main():
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    for _ in range(5):  # Finder/Explorer may recreate .DS_Store/Thumbs.db while deleting
        if not os.path.exists(OUT):
            break
        shutil.rmtree(OUT, ignore_errors=True)
        time.sleep(0.5)
    if os.path.exists(OUT):
        raise SystemExit("Không xoá được %s – hãy đóng cửa sổ thư mục đó rồi chạy lại." % OUT)
    os.makedirs(OUT)
    sums = checksums()
    for plat, pattern in RUNTIMES.items():
        name = pattern % (PBS_PY, PBS_TAG)
        tgz = download(name)
        if sums.get(name) and sha256(tgz) != sums[name]:
            raise SystemExit("Sai checksum: %s" % name)
        dest = os.path.join(OUT, "runtime", plat)
        os.makedirs(dest)
        with tarfile.open(tgz) as t:
            safe_extract(t, dest)
        prune(os.path.join(dest, "python"))
        print("  runtime", plat, "OK")
    copy_app()
    mac = os.path.join(OUT, "Mo ung dung (Mac).command")
    with open(mac, "w", encoding="utf-8", newline="\n") as f:
        f.write(MAC_LAUNCHER)
    os.chmod(mac, os.stat(mac).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    with open(os.path.join(OUT, "Mo ung dung (Windows).bat"), "w", encoding="utf-8", newline="") as f:
        f.write(WIN_LAUNCHER)
    with open(os.path.join(OUT, "HUONG_DAN.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(GUIDE)
    shutil.copy(os.path.join(ROOT, "docs", "SDD.md"), os.path.join(OUT, "SDD.md"))
    # zip, keeping the executable bit for macOS files
    zpath = os.path.join(DIST, "BDS-HOSE-App.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, files in os.walk(OUT):
            for fn in files:
                full = os.path.join(dirpath, fn)
                arc = os.path.relpath(full, DIST)
                zi = zipfile.ZipInfo.from_file(full, arc)
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as f:
                    z.writestr(zi, f.read())
    print("Xong:", OUT)
    print("ZIP :", zpath, "%.0f MB" % (os.path.getsize(zpath) / 1e6))


if __name__ == "__main__":
    main()
