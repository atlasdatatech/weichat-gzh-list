# -*- coding: utf-8 -*-
"""
微信公众号关注列表自动开启工具(采集程序前置处理)

目标态: "公众号关注列表"独立窗口处于打开且显示状态, 供下游 UIA 采集。

用法:
  python gzh_list_tool.py capture  一次性: 截屏框选"公众号"图标, 保存匹配模板 gzh_icon.png
  python gzh_list_tool.py test     验证: 当前屏幕找图标, 打印得分和位置(不点击)
  python gzh_list_tool.py click    验证: 找到图标就真实点击
  python gzh_list_tool.py open     完整前置流程(采集前调用), 见下

open 完整流程:
  1. 公众号独立窗口已存在 -> 直接点它的关注列表小图标, 完成(不碰主窗)
  2. 不存在 -> 调出微信主窗:
       主窗存在   -> 前台化 + 点左侧聊天图标(30,110)切到聊天列表视图
       主窗不存在 -> 双击托盘"微信"图标唤出(托盘也没有 = 微信没登录, 报错退出)
  3. 打开公众号独立窗口(双保险):
       路由1: 搜索框输入"公众号" -> 回车 -> 公众号会话顶到列表首位(110,110)
              -> 右键 -> 菜单第一项"独立窗口显示"(右键点+40,+20)
       路由2: 路由1未命中 -> 列表回顶 -> 逐屏图标模板匹配 -> 同款右键流程
  4. 点公众号窗口右上角人像(-28,+56) -> 出现新增"微信+Chrome"窗口 = 关注列表已显示

窗口识别(实测):
  微信主窗          标题"微信"  + Qt类(Qt51514QWindowIcon)    可能藏在托盘(不可见)
  公众号独立窗口     标题"公众号"
  关注列表/文章页    标题"微信"  + Chrome类(Chromium内核)   两者同款, 只能靠点击前后"新增"区分

托盘(实测):
  主窗收在托盘(不可见)时, 双击任务栏隐藏图标里的"微信"即可正常唤出。
  不要用 ShowWindow: 只会得到灰色空壳(渲染逻辑在微信自己的托盘点击处理里)。
  也不要对微信窗口发 Esc: 主窗收到 Esc 会隐藏回托盘。

依赖: pip install opencv-python pillow uiautomation
      (Python 3.8 环境另需 comtypes==1.2.0, 更高版本 comtypes 不支持 3.8)
"""
import sys
import time
import ctypes
from ctypes import wintypes

# 关键: 按物理像素工作, 否则高DPI(125%/150%缩放)时截图和点击坐标会错位
ctypes.windll.user32.SetProcessDPIAware()

import cv2
import numpy as np
from PIL import ImageGrab

# ---------------- 可校准常量(单位: 物理像素, 窗口坐标均以窗口左上角为原点) ----------------

TEMPLATE = "gzh_icon.png"
THRESHOLD = 0.97        # 图标匹配得分下限。实测: 真图标≈1.0, 最近干扰项(服务号)≈0.919
MAX_SCREENS = 15        # 图标扫描最多向下找几屏(实测公众号会沉到10+个会话以下)
LIST_WIDTH = 220        # 公众号图标只出现在主窗最左侧这一列
SCROLL_X = 110          # 滚动聊天列表时鼠标所在的窗口x坐标
SEARCH_BOX = (150, 57)      # 主窗搜索框中心
CHAT_ICON = (30, 110)       # 主窗左侧聊天列表图标(切回聊天视图用)
SEARCH_ITEM = (110, 110)    # 搜索回车后公众号会话(列表第一位)的位置
MENU_ITEM_OFFSET = (40, 20)     # 右键菜单第一项"独立窗口显示"相对右键点的偏移
AVATAR_OFFSET = (-28, 56)       # 公众号窗口右上角人像图标, 相对窗口右上角

user32 = ctypes.windll.user32
WHEEL = 0x0800


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


# ---------------- 窗口基础 ----------------

def enum_all_windows():
    """所有顶层窗口句柄(含隐藏的, 托盘里的微信主窗要靠它找)"""
    out = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        out.append(h)
        return True

    user32.EnumWindows(CB(cb), None)
    return out


def window_title(h):
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def window_class(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, buf, 256)
    return buf.value


def get_rect(h):
    r = RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r


def is_visible(h):
    return bool(user32.IsWindowVisible(h))


def is_minimized(h):
    return bool(user32.IsIconic(h))


def is_main_window(h):
    """微信主窗: 标题'微信'+Qt类"""
    return window_title(h) == "微信" and window_class(h).lower().startswith("qt")


def activate(hwnd):
    """前台化(ALT技巧绕过前台锁定)"""
    user32.keybd_event(0x12, 0, 0, 0)   # ALT按下
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 2, 0)   # ALT抬起
    time.sleep(0.5)


def find_main_window():
    """找微信主窗。找不到说明缩在托盘(窗口被销毁), 直接托盘双击唤出;
    托盘也没有微信图标 = 微信没登录"""
    for h in enum_all_windows():
        if is_main_window(h):
            print(f"主窗口已找到: 可见={is_visible(h)} 位置={get_rect(h).left},{get_rect(h).top}")
            return h, get_rect(h)
    print("微信主窗口不存在, 双击托盘微信图标唤出 ...")
    if not click_tray_wechat():
        sys.exit("托盘里没找到微信图标: 微信可能没登录")
    for _ in range(10):
        time.sleep(1.0)
        for h in enum_all_windows():
            if is_main_window(h):
                print("主窗口已唤出")
                return h, get_rect(h)
    sys.exit("托盘双击后仍没出现微信主窗口: 微信可能没登录")


def show_main_window(hwnd):
    """确保主窗显示且停在聊天列表视图。
    缩在托盘(不可见)时先托盘双击唤出; 然后前台化并点左侧聊天图标"""
    if not is_visible(hwnd):
        print("微信主窗口缩在托盘, 双击托盘微信图标唤出 ...")
        if not click_tray_wechat():
            sys.exit("托盘里没找到微信图标: 微信可能没登录")
        for _ in range(6):
            time.sleep(1.0)
            if is_visible(hwnd):
                break
        else:
            sys.exit("托盘双击后主窗口仍未显示")
    activate(hwnd)
    r = get_rect(hwnd)
    click_at(r.left + CHAT_ICON[0], r.top + CHAT_ICON[1])
    time.sleep(0.5)


def chrome_windows():
    """所有可见的 标题'微信'+Chrome类 窗口(关注列表、文章页都是这种, 标题/类分不清)"""
    return {h for h in enum_all_windows()
            if window_title(h) == "微信"
            and "chrome" in window_class(h).lower()
            and is_visible(h)}


def gzh_window_open():
    """公众号独立窗口: 标题'公众号'"""
    for h in enum_all_windows():
        if window_title(h) == "公众号" and is_visible(h):
            return True
    return False


def dump_windows(tag):
    """失败诊断: 打印标题为 微信/公众号 的所有窗口(含托盘隐藏的)"""
    print(f"--- {tag}: 微信相关窗口 ---")
    for h in enum_all_windows():
        title = window_title(h)
        if title in ("微信", "公众号"):
            r = get_rect(h)
            print(f"  类名={window_class(h)!r} 标题={title!r} 可见={is_visible(h)} "
                  f"最小化={is_minimized(h)} 位置=({r.left},{r.top}) "
                  f"大小={r.right - r.left}x{r.bottom - r.top}")
    print("---")


# ---------------- 托盘 ----------------

def _load_uia():
    """延迟导入uiautomation(只有托盘双击和搜索打字需要); 缺失时返回None, 由调用方降级"""
    try:
        import uiautomation as auto
        return auto
    except ImportError:
        print("缺少依赖 uiautomation: pip install uiautomation")
        return None


def click_tray_wechat():
    """在任务栏通知区双击微信托盘图标(完全复刻手动操作)。
    图标在'隐藏图标'区: 先点任务栏V形按钮展开溢出区, 再双击其中的微信图标"""
    auto = _load_uia()
    if auto is None:
        return False

    # 1. 点任务栏的"显示隐藏图标"V形按钮, 展开溢出区
    chevron = None
    for name in ("通知 V 形", "显示隐藏的图标", "Show Hidden Icons"):
        c = auto.ButtonControl(Name=name)
        if c.Exists(0.5):
            chevron = c
            break
    if not chevron:
        print("  任务栏没找到'显示隐藏图标'按钮")
        return False
    chevron.Click(simulateMove=False)
    time.sleep(1.0)

    # 2. 在溢出弹窗里找微信图标; 弹窗没出现就再点V形, 最多重试2次
    flyout = auto.PaneControl(ClassName="NotifyIconOverflowWindow")
    tries = 0
    while not flyout.Exists(2) and tries < 2:
        tries += 1
        print(f"  溢出窗口没出现({tries}/2), 再点一次V形")
        chevron.Click(simulateMove=False)
    if not flyout.Exists(2):
        print("  溢出窗口仍未出现, 放弃")
        return False
    icon = flyout.ButtonControl(Name="微信")
    if not icon.Exists(3):
        names = []
        for b in flyout.GetChildren():
            for bb in b.GetChildren():
                if bb.Name:
                    names.append(bb.Name)
        print(f"  溢出区里没找到微信托盘图标, 当前图标: {names}")
        return False

    # 3. 双击(两次快速单击)
    rect = icon.BoundingRectangle
    cx, cy = int((rect.left + rect.right) / 2), int((rect.top + rect.bottom) / 2)
    click_at(cx, cy)
    time.sleep(0.06)
    click_at(cx, cy)
    time.sleep(1.0)
    return True


# ---------------- 鼠标/找图 ----------------

def click_at(x, y, button="left"):
    down, up = (2, 4) if button == "left" else (8, 16)   # 左键 / 右键
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    user32.mouse_event(down, 0, 0, 0, 0)
    user32.mouse_event(up, 0, 0, 0, 0)


def grab_screen_gray(bbox=None):
    img = np.array(ImageGrab.grab(bbox=bbox))  # 全屏/区域截图(物理像素)
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)


def find_icon_in_gray(img, tpl):
    _, maxv, _, maxloc = cv2.minMaxLoc(cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED))
    cx = maxloc[0] + tpl.shape[1] // 2
    cy = maxloc[1] + tpl.shape[0] // 2
    return maxv, (cx, cy), maxloc, tpl.shape


def load_template():
    tpl = cv2.imread(TEMPLATE, 0)
    if tpl is None:
        sys.exit(f"模板 {TEMPLATE} 不存在, 请先运行: python {sys.argv[0]} capture")
    return tpl


# ---------------- 流程步骤 ----------------

def open_via_menu(cx, cy):
    """右键公众号会话项, 点菜单第一项'独立窗口显示'(相对右键点 MENU_ITEM_OFFSET)"""
    click_at(cx, cy, button="right")
    time.sleep(0.6)
    click_at(cx + MENU_ITEM_OFFSET[0], cy + MENU_ITEM_OFFSET[1])
    time.sleep(2.0)
    return gzh_window_open()


def open_gzh_via_search(r):
    """路由1: 搜索框输入'公众号'回车 -> 公众号会话顶到列表第一位(SEARCH_ITEM)
    -> 右键 -> 菜单第一项'独立窗口显示'。失败返回False交给路由2"""
    click_at(r.left + SEARCH_BOX[0], r.top + SEARCH_BOX[1])
    time.sleep(0.6)
    auto = _load_uia()
    if auto is None:
        return False
    auto.SendKeys("{Ctrl}a")
    auto.SendKeys("公众号")
    time.sleep(0.8)
    auto.SendKeys("{Enter}")
    time.sleep(2.0)                      # 回车后公众号会话顶到列表第一位
    rx, ry = r.left + SEARCH_ITEM[0], r.top + SEARCH_ITEM[1]
    if open_via_menu(rx, ry):
        return True
    # 失败现场存图(注意不能用Esc收尾: 微信主窗收到Esc会隐藏回托盘)
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom)).save("search_debug.png")
    print("  搜索未命中, 已存现场截图 search_debug.png")
    click_at((r.left + r.right) // 2, r.top + 15)   # 点标题栏空白收起菜单/下拉
    time.sleep(0.3)
    return False


def icon_scan_route(tpl, r):
    """路由2: 聊天列表回顶 -> 逐屏图标模板匹配 -> 右键'独立窗口显示'。成功返回True"""
    W, H = r.right - r.left, r.bottom - r.top

    def to_screen(x, y):
        return r.left + x, r.top + y

    # 鼠标放在列表上, 连续向上滚回到列表顶部
    user32.SetCursorPos(*to_screen(SCROLL_X, H // 2))
    time.sleep(0.2)
    for _ in range(25):
        user32.mouse_event(WHEEL, 0, 0, 360, 0)
        time.sleep(0.05)
    time.sleep(0.5)

    for screen in range(MAX_SCREENS):
        win = grab_screen_gray(bbox=(r.left, r.top, r.right, r.bottom))
        list_img = win[35:H - 8, 5:LIST_WIDTH]     # 只看标题栏以下、最左侧列表列
        maxv, (lx, ly), *_ = find_icon_in_gray(list_img, tpl)
        if maxv >= THRESHOLD:
            wx, wy = 5 + lx, 35 + ly               # 图标的窗口坐标
            sx, sy = to_screen(wx, wy)             # 点击用的屏幕坐标
            print(f"第{screen + 1}屏找到图标, 得分 {maxv:.3f}, "
                  f"窗口坐标({wx},{wy}), 屏幕坐标({sx},{sy})")
            for attempt in (1, 2):
                if open_via_menu(sx, sy):
                    print(f"“公众号”独立窗口已打开(第{attempt}次尝试)")
                    return True
                print(f"第{attempt}次尝试后窗口未出现, 重试")
            ImageGrab.grab().save("menu_debug.png")
            print("已保存失败现场截图 menu_debug.png")
            print("右键路由失败, 继续滚动查找")
        # 列表向下滚一屏
        user32.SetCursorPos(*to_screen(SCROLL_X, H // 2))
        time.sleep(0.2)
        user32.mouse_event(WHEEL, 0, 0, -360 * 3, 0)
        time.sleep(0.6)
    return False


def ensure_gzh_window(tpl, r, hwnd):
    """双保险: 先搜索路由(快), 未命中再图标扫描(稳)"""
    if open_gzh_via_search(r):
        print("搜索路由: “公众号”独立窗口已打开")
        return True
    print("搜索路由未命中, 改用图标扫描 ...")
    show_main_window(hwnd)               # 搜索失败后确保主窗仍显示且在聊天页
    r = get_rect(hwnd)
    return icon_scan_route(tpl, r)


def open_follow_list():
    """在公众号窗口右上角人像图标(AVATAR_OFFSET)点击, 弹出关注列表独立窗口。
    成功判据: 点击后新增了一个 微信+Chrome 窗口(文章页同款, 只能和点击前比新增);
    若关注列表本就开着, 这次点击确保它处于显示状态(点击不是开关), 同样算成功"""
    hwnd = None
    for h in enum_all_windows():
        if window_title(h) == "公众号" and is_visible(h):
            hwnd = h
            break
    if not hwnd:
        print("找不到公众号窗口")
        return False
    activate(hwnd)
    before = chrome_windows()
    r = get_rect(hwnd)
    click_at(r.right + AVATAR_OFFSET[0], r.top + AVATAR_OFFSET[1])   # 人像图标
    time.sleep(2.0)
    new = chrome_windows() - before
    if not new:                        # 偶发加载慢, 再等一次
        time.sleep(1.5)
        new = chrome_windows() - before
    if new:
        h = sorted(new)[0]
        rr = get_rect(h)
        print(f"关注列表窗口已弹出: 类名={window_class(h)!r} 标题={window_title(h)!r} "
              f"位置=({rr.left},{rr.top}) 大小={rr.right - rr.left}x{rr.bottom - rr.top}")
        return True
    if chrome_windows():
        print("关注列表窗口已处于显示状态")
        return True
    return False


# ---------------- 命令 ----------------

def cmd_capture():
    img = cv2.cvtColor(np.array(ImageGrab.grab()), cv2.COLOR_RGB2BGR)
    print('在弹出的窗口里用鼠标框选"公众号"图标(只框图标方块本身, 不要带文字), 回车确认, Esc 重选')
    x, y, w, h = cv2.selectROI("框选公众号图标后按回车", img, showCrosshair=True)
    cv2.destroyAllWindows()
    if w == 0 or h == 0:
        print("未选择区域, 退出")
        return
    cv2.imwrite(TEMPLATE, img[y:y + h, x:x + w])
    print(f"模板已保存: {TEMPLATE} ({w}x{h})")


def cmd_test():
    tpl = load_template()
    img = grab_screen_gray()
    maxv, (cx, cy), maxloc, shape = find_icon_in_gray(img, tpl)
    print(f"最佳匹配得分: {maxv:.3f} (阈值 {THRESHOLD})  图标中心: ({cx}, {cy})")
    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if maxv >= THRESHOLD:
        cv2.rectangle(vis, maxloc,
                      (maxloc[0] + shape[1], maxloc[1] + shape[0]), (0, 255, 0), 3)
    cv2.imshow("match - 按任意键关闭", vis)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    if maxv < THRESHOLD:
        print("没找到: 确认微信聊天列表在屏幕上可见、模板是当前主题/缩放下截的; 或重新 capture")


def cmd_click():
    tpl = load_template()
    img = grab_screen_gray()
    maxv, (cx, cy), *_ = find_icon_in_gray(img, tpl)
    print(f"最佳匹配得分: {maxv:.3f}  图标中心: ({cx}, {cy})")
    if maxv < THRESHOLD:
        print("没找到, 不点击")
        return
    click_at(cx, cy)
    print("已点击")


def cmd_open():
    # 1. 公众号独立窗口可独立于主窗存在: 它在就直接点关注列表小图标, 不碰主窗(也不需要模板)
    if gzh_window_open():
        print("公众号独立窗口已存在, 直接点关注列表小图标 ...")
        if open_follow_list() or open_follow_list():
            print("完成: 公众号关注列表独立窗口已打开且处于显示状态")
        else:
            print("点击后关注列表未确认弹出")
            dump_windows("关注列表诊断")
        return

    # 2. 公众号窗口不在 -> 需要主窗: 没有就走托盘, 调出并切到聊天列表
    tpl = load_template()
    hwnd, r = find_main_window()
    show_main_window(hwnd)
    r = get_rect(hwnd)          # 唤出后重新取位置, 防止窗口移动过
    print(f"主窗口就绪: 位置=({r.left},{r.top}) 大小={r.right - r.left}x{r.bottom - r.top}")

    # 3. 打开公众号独立窗口(搜索路由优先, 图标扫描兜底)
    if not ensure_gzh_window(tpl, r, hwnd):
        print("搜索+图标扫描都没能打开公众号窗口")
        dump_windows("诊断")
        return
    time.sleep(0.5)

    # 4. 公众号窗口右上角人像 -> 关注列表独立窗口
    if open_follow_list() or open_follow_list():
        print("完成: 公众号关注列表独立窗口已打开")
    else:
        print("关注列表独立窗口未弹出")
        dump_windows("关注列表诊断")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    actions = {"capture": cmd_capture, "test": cmd_test,
               "click": cmd_click, "open": cmd_open}
    actions.get(cmd, lambda: print(__doc__))()
