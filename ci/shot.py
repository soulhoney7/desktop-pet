# GitHub 빌드 서버에서 화면 캡처 (실행 확인용)
import sys
from PIL import ImageGrab
ImageGrab.grab(all_screens=True).save(sys.argv[1])
print("saved", sys.argv[1])
