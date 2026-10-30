# 방향키를 빠르게 여러 번 누르기 (숨기기 시험). 맨 앞 숫자는 누르고 있는 시간(초)
import ctypes, sys, time
VK = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
user32 = ctypes.WinDLL("user32")
hold = 0.06
args = sys.argv[1:]
if args and args[0].replace(".", "").isdigit():
    hold = float(args.pop(0))
for name in args:
    vk = VK[name]
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.12)
