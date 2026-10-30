# 화면을 여러 장 찍어서 움직이는 GIF로 저장 (실제 실행 모습 기록용)
import sys, time
from PIL import ImageGrab
out, seconds = sys.argv[1], float(sys.argv[2])
trigger = sys.argv[3] if len(sys.argv) > 3 else None
what = sys.argv[4] if len(sys.argv) > 4 else "bump"
frames, t0 = [], time.time()
while time.time() - t0 < seconds:
    t = time.time()
    frames.append(ImageGrab.grab().convert("RGB").resize((800, 600)))
    if trigger and len(frames) == 3:
        with open(trigger, "w", encoding="utf-8") as f:   # 녹화 시작 후 연출 신호
            f.write(what)
    time.sleep(max(0, 0.12 - (time.time() - t)))
frames = [f.quantize(colors=128) for f in frames]
frames[0].save(out, save_all=True, append_images=frames[1:], duration=120, loop=0, optimize=True)
print("frames", len(frames))
