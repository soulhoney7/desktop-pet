# 윈도우에서 배경 제거가 실제로 되는지 확인 → 원본/결과 비교 그림 저장
import sys, time
sys.path.insert(0, ".")
import bgremove
from PIL import Image
t = time.time()
out = bgremove.make_pet_image("ci/test_photo.jpg", print)
print("배경 제거 시간: %.1f초" % (time.time() - t))
src = Image.open("ci/test_photo.jpg").convert("RGB")
src.thumbnail((400, 400))
res = out.copy(); res.thumbnail((300, 300))
check = Image.new("RGB", (res.width, res.height))
for y in range(0, res.height, 16):
    for x in range(0, res.width, 16):
        c = (230, 230, 230) if (x // 16 + y // 16) % 2 else (255, 255, 255)
        check.paste(c, (x, y, x + 16, y + 16))
check.paste(res, (0, 0), res)
canvas = Image.new("RGB", (src.width + check.width + 30, max(src.height, check.height)), "white")
canvas.paste(src, (0, 0)); canvas.paste(check, (src.width + 30, 0))
canvas.save(sys.argv[1])
