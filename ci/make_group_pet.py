# 여러 마리 사진 → 한 펫(캐릭터별 조각 포함)으로 만들어 펫 폴더에 넣기 + 결과 그림
import json, os, sys
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
for n, x in [("모찌", 60), ("삐약이", 270), ("토순이", 480)]:          # 서로 가까이 붙은 세 마리
    pet = Image.open(f"ci/pets/{n}.png").convert("RGBA").resize((230, 230))
    bg.paste(pet, (x, 150), pet)
bg.save("ci_group.jpg")
full, parts = bgremove.make_group("ci_group.jpg", print)
print("같이 다니는 캐릭터 수:", len(parts))
data = os.path.join(os.environ["APPDATA"], "DesktopPet")
os.makedirs(os.path.join(data, "pets"), exist_ok=True)
pd = os.path.join(data, "parts", "삼총사")
os.makedirs(pd, exist_ok=True)
info = []
for k, (piece, (x, y)) in enumerate(parts):
    piece.save(os.path.join(pd, f"{k}.png"))
    info.append({"file": f"{k}.png", "x": x, "y": y})
json.dump({"parts": info}, open(os.path.join(pd, "parts.json"), "w", encoding="utf-8"))
full.save(os.path.join(data, "pets", "삼총사.png"))
src = bg.copy(); src.thumbnail((450, 300))
c = Image.new("RGB", (src.width + full.width + 30, max(src.height, full.height + 40)), "white")
c.paste(src, (0, 0))
for i, (piece, (x, y)) in enumerate(parts):
    c.paste(piece, (src.width + 30 + x, 30 + y - (i % 2) * 25), piece)   # 조각마다 따로 띄워 보기
c.save(sys.argv[1])
