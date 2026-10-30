# 화면을 여러 장 찍어서 움직이는 GIF로 저장 (실제 실행 모습 기록용)
import sys, time
from PIL import ImageGrab
out, seconds = sys.argv[1], float(sys.argv[2])
frames, t0 = [], time.time()
while time.time() - t0 < seconds:
    t = time.time()
    frames.append(ImageGrab.grab().convert("RGB").resize((800, 600)))
    time.sleep(max(0, 0.12 - (time.time() - t)))
frames = [f.quantize(colors=128) for f in frames]
frames[0].save(out, save_all=True, append_images=frames[1:], duration=120, loop=0, optimize=True)
print("frames", len(frames))
