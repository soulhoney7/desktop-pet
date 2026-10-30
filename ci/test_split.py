# 여러 마리 사진 나누기 시험 → 결과 그림
import sys
sys.path.insert(0, ".")
import bgremove
from PIL import Image, ImageDraw, ImageFilter
import random
random.seed(2)
bg = Image.new("RGB", (900, 420))
d = ImageDraw.Draw(bg)
for y in range(420):
    d.line([(0, y), (900, y)], fill=(225 - y // 10, 210 - y // 12, 190 - y // 14) if y < 300 else (170, 140, 110))
bg = bg.filter(ImageFilter.GaussianBlur(1))
for n, x in [("모찌", 40), ("삐약이", 330), ("토순이", 620)]:
    pet = Image.open(f"ci/pets/{n}.png").convert("RGBA").resize((240, 240))
    bg.paste(pet, (x, 140), pet)
bg.save("ci_group.jpg")
outs = bgremove.make_pet_images("ci_group.jpg", print)
print("나눈 마리 수:", len(outs))
src = bg.copy(); src.thumbnail((450, 300))
W = src.width + sum(o.width // 2 for o in outs) + 30 * (len(outs) + 1)
c = Image.new("RGB", (W, max(src.height, 160)), "white")
c.paste(src, (0, 0)); x = src.width + 30
for o in outs:
    o = o.resize((o.width // 2, o.height // 2))
    c.paste(o, (x, 20), o); x += o.width + 30
c.save(sys.argv[1])
