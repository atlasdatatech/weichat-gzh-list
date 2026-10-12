# -*- coding: utf-8 -*-
"""滚动探针: 实测每次滚轮的距离和公众号图标出现的屏数/得分"""
import sys
import time
import ctypes
from ctypes import wintypes

ctypes.windll.user32.SetProcessDPIAware()
import cv2
import numpy as np
from PIL import ImageGrab

user32 = ctypes.windll.user32
WHEEL = 0x0800
TEMPLATE = "gzh_icon.png"
SCROLL_X = 110


def window_class(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def window_title(h):
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


hwnd = None
for h in range(0, 0):  # placeholder, use EnumWindows below
    pass

import ctypes
CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
found = []


def cb(h, _):
    if window_title(h) == "微信" and window_class(h).lower().startswith("qt"):
        found.append(h)
    return True


user32.EnumWindows(CB(cb), None)
if not found:
    sys.exit("没找到微信主窗口")
hwnd = found[0]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


r = RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
W, H = r.right - r.left, r.bottom - r.top
print(f"主窗口 位置=({r.left},{r.top}) 大小={W}x{H}")

tpl = cv2.imread(TEMPLATE, 0)

# 回顶
user32.SetCursorPos(r.left + SCROLL_X, r.top + H // 2)
time.sleep(0.3)
for _ in range(15):
    user32.mouse_event(WHEEL, 0, 0, 360, 0)
    time.sleep(0.04)
time.sleep(0.6)

for screen in range(15):
    img = np.array(ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom)))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    list_img = gray[35:H - 8, 5:220]
    _, maxv, _, maxloc = cv2.minMaxLoc(cv2.matchTemplate(list_img, tpl, cv2.TM_CCOEFF_NORMED))
    mark = "  <<<<<< 找到!" if maxv >= 0.97 else ""
    print(f"第{screen + 1}屏  得分={maxv:.3f}  位置=({maxloc[0] + 5},{maxloc[1] + 35}){mark}")
    if maxv >= 0.97:
        cv2.imwrite("found_screen.png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        print("已保存 found_screen.png")
        break
    # 向下滚: 每次3格
    user32.SetCursorPos(r.left + SCROLL_X, r.top + H // 2)
    time.sleep(0.15)
    user32.mouse_event(WHEEL, 0, 0, -360, 0)
    time.sleep(0.45)
