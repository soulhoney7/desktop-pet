# -*- coding: utf-8 -*-
"""자동 업데이트: GitHub의 최신 빌드를 확인하고, 받아 두고, 교체해서 다시 켜기"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = "soulhoney7/desktop-pet"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "DesktopPet.exe"

try:
    from build_info import BUILD          # GitHub에서 빌드할 때 자동으로 만들어짐
except ImportError:
    BUILD = 0                              # 개발용 실행: 업데이트 안 함


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def current_exe():
    return Path(sys.executable)


def check_latest(timeout=20):
    """최신 빌드 → (번호, 받을 주소, 크기, 바뀐 점) / 없으면 None"""
    req = urllib.request.Request(API, headers={"User-Agent": "DesktopPet", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = data.get("tag_name", "")
    if not tag.startswith("build-"):
        return None
    num = int(tag.split("-", 1)[1])
    for a in data.get("assets", []):
        if a.get("name") == ASSET:
            notes = (data.get("body") or "").strip().splitlines()
            return num, a["browser_download_url"], int(a.get("size", 0)), (notes[0] if notes else "")
    return None


def download(url, size, dest_dir, num, progress=None):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / f"DesktopPet_build{num}.exe"
    if final.exists() and (not size or final.stat().st_size == size):
        return final
    part = final.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "DesktopPet"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and size:
                progress(done * 100 // size)
            time.sleep(0.01)                # 업무 중 인터넷을 독차지하지 않게 살살
    if size and part.stat().st_size != size:
        part.unlink(missing_ok=True)
        raise IOError("다운로드가 중간에 끊겼어요")
    part.replace(final)
    return final


def launch_installer(new_exe, target_exe):
    """새 버전 exe를 '설치 모드'로 켬 → 지금 프로그램이 꺼지면 원래 자리에 덮어쓰고 다시 켜 줌"""
    flags = 0x00000008 | 0x00000200     # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(new_exe), "--install-to", str(target_exe)],
                     creationflags=flags if os.name == "nt" else 0, close_fds=True)


def run_install_mode(target, log_path=None):
    """(새 버전 exe 안에서 실행됨) 예전 exe가 풀릴 때까지 기다렸다가 덮어쓰고 다시 켬"""
    me = current_exe()
    target = Path(target)

    def log(t):
        if log_path:
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + t + "\n")
            except Exception:
                pass

    log(f"설치 시작: {me} → {target}")
    tmp = target.with_name(target.name + ".new")
    ok = False
    for _ in range(240):                     # 최대 약 60초
        try:
            shutil.copyfile(me, tmp)
            os.replace(tmp, target)          # 예전 프로그램이 아직 안 꺼졌으면 여기서 실패 → 재시도
            ok = True
            break
        except OSError:
            time.sleep(0.25)
    if not ok:
        try:
            tmp.unlink()
        except OSError:
            pass
        log("실패: 예전 파일이 계속 사용 중이에요")
        subprocess.Popen([str(target)], close_fds=True)   # 원래 버전이라도 다시 켬
        return False
    log("교체 완료, 다시 켜는 중")
    env = {k: v for k, v in os.environ.items()
           if k not in ("DESKTOPPET_FAKE_UPDATE", "DESKTOPPET_AUTO_APPLY", "DESKTOPPET_FAKE_TARGET")}
    subprocess.Popen([str(target), "--updated"], close_fds=True, env=env)
    return True


def cleanup(dest_dir, keep=None):
    """지난 업데이트 파일 정리"""
    try:
        for p in Path(dest_dir).glob("DesktopPet_build*"):
            if keep is None or p.resolve() != Path(keep).resolve():
                try:
                    p.unlink()
                except OSError:
                    pass
    except Exception:
        pass
