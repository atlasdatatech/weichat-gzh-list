# -*- coding: utf-8 -*-
"""诊断任务栏托盘的UIA控件名: python diag_tray.py [open]"""
import sys

try:
    import uiautomation as auto
except ImportError:
    print("UIA_NOT_INSTALLED")
    sys.exit(0)

tb = auto.PaneControl(ClassName="Shell_TrayWnd")
if not tb.Exists(2):
    print("NO_SHELL_TRAYWND")
    sys.exit(0)


def walk(c, d=0, maxd=5):
    try:
        name, cls, ctype = c.Name, c.ClassName, c.ControlTypeName
    except Exception:
        return
    if (name and name.strip()) or ctype in ("ButtonControl", "ToolBarControl"):
        print("  " * d + f"{ctype} cls={cls!r} name={name!r}")
    if d >= maxd:
        return
    for ch in c.GetChildren():
        walk(ch, d + 1, maxd)


print("==== 任务栏(Shell_TrayWnd)结构 ====")
walk(tb)

print("==== 常见V形按钮名探测 ====")
for nm in ("通知 V 形", "显示隐藏的图标", "Show Hidden Icons", "通知尖角号"):
    c = auto.ButtonControl(Name=nm)
    print(f"  {nm!r} -> 存在={c.Exists(0.3)}")

if len(sys.argv) > 1 and sys.argv[1] == "open":
    print("==== 展开隐藏图标溢出区并枚举 ====")
    chevron = None
    for nm in ("通知 V 形", "显示隐藏的图标", "Show Hidden Icons"):
        c = auto.ButtonControl(Name=nm)
        if c.Exists(1):
            chevron = c
            break
    if not chevron:
        print("没找到V形按钮")
        sys.exit(0)
    chevron.Click(simulateMove=False)
    import time
    time.sleep(1.0)
    fly = auto.PaneControl(ClassName="NotifyIconOverflowWindow")
    print("NotifyIconOverflowWindow 存在 =", fly.Exists(2))
    walk(fly, maxd=6)
