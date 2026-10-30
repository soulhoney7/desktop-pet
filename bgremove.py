# -*- coding: utf-8 -*-
"""사진 배경 자동 제거 (rembg 없이 onnxruntime으로 직접 실행 → exe가 가볍고 안정적)"""
import os
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

try:                                  # 아이폰 사진(HEIC) 지원
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

MODEL_NAME = "isnet-general-use.onnx"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/" + MODEL_NAME
MODEL_DIR = Path(os.environ.get("U2NET_HOME", Path.home() / ".u2net"))
MODEL_SIZE = 1024

_session = None


def model_path():
    return MODEL_DIR / MODEL_NAME


def ensure_model(progress=None):
    path = model_path()
    if path.exists() and path.stat().st_size > 100_000_000:
        return path
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with urllib.request.urlopen(MODEL_URL, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0)) or 178_648_008
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(f"배경 제거 모델 내려받는 중… {done * 100 // total}% (처음 한 번만)")
    tmp.replace(path)
    return path


def get_session(progress=None):
    global _session
    if _session is None:
        import onnxruntime as ort
        path = ensure_model(progress)
        if progress:
            progress("배경 제거 모델 불러오는 중…")
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
    return _session


def predict_mask(img, progress=None):
    """RGBA/RGB PIL 이미지 → 0~255 마스크(L)"""
    sess = get_session(progress)
    rgb = img.convert("RGB")
    x = np.asarray(rgb.resize((MODEL_SIZE, MODEL_SIZE), Image.LANCZOS), dtype=np.float32) / 255.0
    x = (x - 0.5) / 1.0                      # isnet: mean 0.5, std 1.0
    x = x.transpose(2, 0, 1)[None]
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    lo, hi = float(out.min()), float(out.max())
    out = (out - lo) / (hi - lo + 1e-8)
    mask = Image.fromarray((out * 255).astype(np.uint8), "L").resize(img.size, Image.LANCZOS)
    return mask


def keep_main_parts(m, small=200):
    """마스크에서 큰 덩어리(주인공)만 남기고, 떨어져 있는 작은 조각은 지움"""
    h, w = m.shape
    scale = min(1.0, small / max(h, w))
    sh, sw = max(1, int(h * scale)), max(1, int(w * scale))
    lo = np.asarray(Image.fromarray(m).resize((sw, sh), Image.BILINEAR)) > 100
    labels = np.zeros((sh, sw), np.int32)
    sizes = [0]
    cur = 0
    for y0 in range(sh):
        for x0 in range(sw):
            if lo[y0, x0] and not labels[y0, x0]:
                cur += 1
                labels[y0, x0] = cur
                stack, n = [(y0, x0)], 0
                while stack:
                    y, x = stack.pop()
                    n += 1
                    for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                        if 0 <= ny < sh and 0 <= nx < sw and lo[ny, nx] and not labels[ny, nx]:
                            labels[ny, nx] = cur
                            stack.append((ny, nx))
                sizes.append(n)
    if cur <= 1:
        return m
    biggest = max(sizes)
    keep = np.array([s >= biggest * 0.15 for s in sizes])
    keep[0] = False
    # 남길 덩어리를 살짝 넓혀서 원래 크기로 되돌림 (가장자리 잘림 방지)
    keep_lo = Image.fromarray((keep[labels] * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
    keep_full = np.asarray(keep_lo.resize((w, h), Image.BILINEAR)) > 0
    return np.where(keep_full, m, 0).astype(np.uint8)


def has_transparent_background(img):
    """이미 배경이 투명한 PNG인지 (테두리 픽셀 대부분이 투명한지)"""
    a = np.asarray(img.getchannel("A"))
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    return (border < 20).mean() > 0.6


def make_pet_image(path, progress=None, max_side=512):
    """사진 파일 → 배경 지우고 여백 잘라낸 RGBA 이미지"""
    img = Image.open(path)
    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)                   # 움직이는 GIF는 첫 장면 사용
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    img = ImageOps.exif_transpose(img).convert("RGBA")

    if not has_transparent_background(img):
        mask = predict_mask(img, progress)
        # 가장자리 살짝 정리: 아주 옅은 부분은 지우고, 진한 부분은 완전 불투명
        m = np.asarray(mask).astype(np.float32)
        m = np.clip((m - 20) * 255 / (235 - 20), 0, 255).astype(np.uint8)
        m = keep_main_parts(m)
        mask = Image.fromarray(m, "L").filter(ImageFilter.GaussianBlur(0.6))
        alpha = np.minimum(np.asarray(img.getchannel("A")), np.asarray(mask))
        img.putalpha(Image.fromarray(alpha, "L"))

    a = np.asarray(img.getchannel("A"))
    ys, xs = np.where(a > 15)
    if len(xs) == 0:
        raise ValueError("배경을 지우고 나니 남은 부분이 없어요. 다른 사진으로 해 보세요.")
    pad = 2
    img = img.crop((max(0, xs.min() - pad), max(0, ys.min() - pad),
                    min(img.width, xs.max() + 1 + pad), min(img.height, ys.max() + 1 + pad)))
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img
