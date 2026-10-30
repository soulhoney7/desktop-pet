# 방향키를 빠르게 여러 번 누르기 (숨기기 시험)
import ctypes, sys, time
VK = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
user32 = ctypes.WinDLL("user32")
for name in sys.argv[1:]:
    vk = VK[name]
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.09)
