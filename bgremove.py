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


def label_parts(m, small=200):
    """마스크를 작게 줄여서 서로 떨어진 덩어리마다 번호 매기기 → (번호판, 덩어리별 크기)"""
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
    return labels, sizes


def part_mask(labels, ids, shape):
    """번호판에서 고른 덩어리만 원래 크기 마스크로 (살짝 넓혀서 가장자리 안 잘리게)"""
    h, w = shape
    sel = np.isin(labels, list(ids))
    lo = Image.fromarray((sel * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
    return np.asarray(lo.resize((w, h), Image.BILINEAR)) > 0


def keep_main_parts(m, small=200):
    """마스크에서 큰 덩어리(주인공)만 남기고, 떨어져 있는 작은 조각은 지움"""
    labels, sizes = label_parts(m, small)
    if len(sizes) <= 2:
        return m
    biggest = max(sizes)
    ids = [i for i, n in enumerate(sizes) if i and n >= biggest * 0.15]
    return np.where(part_mask(labels, ids, m.shape), m, 0).astype(np.uint8)


def _label_bool(lo):
    labels = np.zeros(lo.shape, np.int32)
    sizes = [0]
    sh, sw = lo.shape
    cur = 0
    for y0, x0 in zip(*np.nonzero(lo)):
        if labels[y0, x0]:
            continue
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
    return labels, sizes


def _grow(seeds, lo):
    """씨앗 덩어리를 원래 모양 안에서 조금씩 넓혀서 모든 픽셀을 가장 가까운 씨앗에 배정"""
    lab = seeds.copy()
    for _ in range(400):
        empty = lo & (lab == 0)
        if not empty.any():
            break
        grown = lab.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(lab, (dy, dx), axis=(0, 1))
            fill = empty & (grown == 0) & (sh > 0)
            grown[fill] = sh[fill]
        if (grown == lab).all():
            break
        lab = grown
    return lab


def split_parts(m, small=200):
    """여러 마리면 마리별 마스크 목록 (왼쪽부터). 한 마리면 None
    떨어져 있으면 그대로 나누고, 손잡기처럼 가늘게 붙어 있으면 살짝 깎아서 나눔"""
    h, w = m.shape
    scale = min(1.0, small / max(h, w))
    sh, sw = max(1, int(h * scale)), max(1, int(w * scale))
    lo_img = Image.fromarray(m).resize((sw, sh), Image.BILINEAR)
    lo = np.asarray(lo_img) > 100
    total = max(1, int(lo.sum()))
    eroded = lo_img
    best = None
    for depth in range(0, 7):                    # 0번: 그대로 / 1~6번: 가는 연결 부분 깎기
        if depth:
            eroded = eroded.filter(ImageFilter.MinFilter(3))
        e = np.asarray(eroded) > 100
        if not e.any():
            break
        labels, sizes = _label_bool(e)
        if len(sizes) <= 2:
            continue
        biggest = max(sizes)
        need = 0.25 if depth == 0 else 0.4       # 깎아서 나눌 땐 더 엄격하게 (한 마리를 쪼개지 않게)
        ids = [i for i, n in enumerate(sizes) if i and n >= biggest * need and n >= total * 0.04]
        if len(ids) >= 2 and (best is None or len(ids) > len(best[2])):
            best = (depth, labels, ids)
        if depth == 0 and best is not None:
            break                                # 이미 떨어져 있으면 깎을 필요 없음
    if best is not None:
        depth, labels, ids = best
        seeds = np.where(np.isin(labels, ids), labels, 0)
        full = _grow(seeds, lo) if depth else seeds
        ids.sort(key=lambda i: np.nonzero(full == i)[1].mean())
        return [part_mask(full, [i], m.shape) for i in ids[:12]]
    return None


def has_transparent_background(img):
    """이미 배경이 투명한 PNG인지 (테두리 픽셀 대부분이 투명한지)"""
    a = np.asarray(img.getchannel("A"))
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    return (border < 20).mean() > 0.6


def _load(path):
    img = Image.open(path)
    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)                   # 움직이는 GIF는 첫 장면 사용
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    return ImageOps.exif_transpose(img).convert("RGBA")


def _crop(img, max_side):
    a = np.asarray(img.getchannel("A"))
    ys, xs = np.where(a > 15)
    if len(xs) == 0:
        return None
    pad = 2
    img = img.crop((max(0, xs.min() - pad), max(0, ys.min() - pad),
                    min(img.width, xs.max() + 1 + pad), min(img.height, ys.max() + 1 + pad)))
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img


def make_pet_images(path, progress=None, split=True, max_side=512):
    """사진 → 배경 지운 펫 이미지 목록. split이면 떨어져 있는 여러 마리를 한 마리씩 나눔"""
    img = _load(path)
    if has_transparent_background(img):
        m = np.asarray(img.getchannel("A")).astype(np.uint8)
        alpha_src = m
        parts = split_parts(m) if split else None
    else:
        mask = predict_mask(img, progress)
        # 가장자리 살짝 정리: 아주 옅은 부분은 지우고, 진한 부분은 완전 불투명
        m = np.asarray(mask).astype(np.float32)
        m = np.clip((m - 20) * 255 / (235 - 20), 0, 255).astype(np.uint8)
        parts = split_parts(m) if split else None
        if parts is None:
            m = keep_main_parts(m)
        soft = np.asarray(Image.fromarray(m, "L").filter(ImageFilter.GaussianBlur(0.6)))
        alpha_src = np.minimum(np.asarray(img.getchannel("A")), soft)

    outs = []
    for pm in (parts or [None]):
        one = img.copy()
        a = alpha_src if pm is None else np.where(pm, alpha_src, 0).astype(np.uint8)
        one.putalpha(Image.fromarray(a.astype(np.uint8), "L"))
        one = _crop(one, max_side)
        if one is not None and one.width >= 8 and one.height >= 8:
            outs.append(one)
    if not outs:
        raise ValueError("배경을 지우고 나니 남은 부분이 없어요. 다른 사진으로 해 보세요.")
    if len(outs) > 1:                            # 납작한 조각(막대, 글자 줄 등)은 펫에서 뺌
        tall = max(o.height for o in outs)
        outs = [o for o in outs if o.height >= tall * 0.45 and o.height >= o.width * 0.35] or outs[:1]
    return outs


def make_pet_image(path, progress=None, max_side=512):
    """사진 파일 → 배경 지우고 여백 잘라낸 RGBA 이미지 한 장"""
    return make_pet_images(path, progress, split=False, max_side=max_side)[0]


def release():
    """모델을 메모리에서 내림 (다음에 사진 넣을 때 다시 불러옴, 1~2초)"""
    global _session
    _session = None
    import gc
    gc.collect()
