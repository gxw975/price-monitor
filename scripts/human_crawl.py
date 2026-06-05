#!/usr/bin/env python3
"""
纯xdotool物理操作爬虫 — 零CDP，彻底绕过淘宝检测
流程：Chrome启动 → 搜索关键词 → DTS导出Excel → 读取数据
"""
import os
import sys
import csv
import time
import random
import shutil
import subprocess
import logging
from pathlib import Path
from datetime import datetime

try:
    from openpyxl import load_workbook
except ImportError:
    print("请安装openpyxl: pip install openpyxl")
    sys.exit(1)

# ─── 配置 ───────────────────────────────────────────────
CHROME_BIN = "/opt/google/chrome/chrome"
CHROME_PROFILE = os.path.expanduser("~/.config/google-chrome")
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "downloads")
os.makedirs(OUTPUT_DIR, exist_ok=True)

LOG_FMT = "%(asctime)s %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FMT)
log = logging.getLogger("crawl")

# ─── 工具函数 ────────────────────────────────────────────
def run(cmd, timeout=30):
    """执行shell命令，返回stdout"""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()

def xd(*args):
    """执行xdotool命令"""
    env = os.environ.copy()
    env["DISPLAY"] = ":0"
    return run(f"xdotool {' '.join(str(a) for a in args)}", timeout=10)

def paste(text):
    """通过剪贴板粘贴中文文本"""
    env = os.environ.copy()
    env["DISPLAY"] = ":0"
    # 用Popen避免xclip阻塞
    p = subprocess.Popen(["xclip", "-selection", "clipboard"],
                         stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=env)
    p.communicate(input=text.encode(), timeout=10)
    time.sleep(0.3)
    xd("key", "ctrl+v")
    time.sleep(0.5)

def click(x, y):
    """物理点击坐标"""
    xd("mousemove", "--sync", x, y)
    time.sleep(0.1 + random.random() * 0.2)
    xd("click", "1")
    time.sleep(0.3)

def click_dts_icon():
    """点击DTS扩展图标（Chrome工具栏）"""
    # DTS图标通常在Chrome工具栏右侧，需要手动获取坐标
    # 先尝试通过xdotool查找
    wid = find_chrome_wid()
    if not wid:
        log.warning("未找到Chrome窗口")
        return False
    # 获取窗口几何信息
    geo = xd("getwindowgeometry", "--shell", wid)
    w = int(run(f"echo '{geo}' | grep WIDTH | cut -d= -f2") or "1920")
    # DTS图标通常在工具栏右上角区域
    # Chrome工具栏高度约80px，DTS图标在右侧约200px处
    dts_x = w - 200
    dts_y = 45
    log.info(f"    点击DTS图标 ({dts_x}, {dts_y})")
    click(dts_x, dts_y)
    time.sleep(2)
    return True

def find_chrome_wid():
    """查找Chrome窗口ID"""
    result = xd("search", "--class", "google-chrome")
    wids = [w.strip() for w in result.split("\n") if w.strip()]
    if wids:
        return wids[0]
    # 备用：按名称搜索
    result = xd("search", "--name", "淘宝")
    wids = [w.strip() for w in result.split("\n") if w.strip()]
    return wids[0] if wids else None

def activate_chrome(wid):
    """激活Chrome窗口"""
    xd("windowactivate", "--sync", wid)
    xd("windowfocus", "--sync", wid)
    time.sleep(0.5)

def wait_for_file(directory, pattern="*.xlsx", timeout=120):
    """等待下载文件出现"""
    import glob
    start = time.time()
    while time.time() - start < timeout:
        files = glob.glob(os.path.join(directory, pattern))
        if files:
            # 检查文件是否还在写入（大小不再变化）
            f = max(files, key=os.path.getmtime)
            size1 = os.path.getsize(f)
            time.sleep(2)
            size2 = os.path.getsize(f)
            if size1 == size2 and size2 > 0:
                return f
        time.sleep(2)
    return None

def close_chrome():
    """优雅关闭Chrome"""
    log.info("  关闭Chrome...")
    wid = find_chrome_wid()
    if wid:
        activate_chrome(wid)
        xd("key", "alt+F4")
        time.sleep(3)
    # 确保Chrome已退出
    if subprocess.run(["pgrep", "-c", "chrome"], capture_output=True, text=True).stdout.strip() not in ("", "0"):
        subprocess.run(["pkill", "-TERM", "chrome"], check=False)
        time.sleep(3)
    if subprocess.run(["pgrep", "-c", "chrome"], capture_output=True, text=True).stdout.strip() not in ("", "0"):
        subprocess.run(["pkill", "-KILL", "chrome"], check=False)
        time.sleep(2)
    log.info("  Chrome已关闭")

def cleanup_crash_markers():
    """清理Chrome崩溃标记"""
    for f in ["Last Session", "Last Tabs", "Current Session", "Current Tabs"]:
        fp = os.path.join(CHROME_PROFILE, f)
        if os.path.exists(fp):
            try: os.remove(fp)
            except: pass

def handle_popups(wid):
    """处理Chrome弹窗（恢复页面、DTS权限等）"""
    activate_chrome(wid)
    time.sleep(1)
    # 检查是否有"要恢复页面吗"弹窗
    result = xd("search", "--name", "恢复")
    if result.strip():
        log.info("    检测到恢复弹窗，关闭")
        xd("key", "Escape")
        time.sleep(1)
    # 检查DTS权限弹窗
    result = xd("search", "--name", "已被禁用")
    if result.strip():
        log.info("    检测到DTS权限弹窗，接受")
        # 点击"接受权限"按钮（通常在弹窗右下角）
        xd("key", "Tab")
        time.sleep(0.3)
        xd("key", "Return")
        time.sleep(2)

def check_captcha(wid):
    """检查是否有验证码页面"""
    activate_chrome(wid)
    # 检查当前窗口标题是否包含验证码特征
    title = xd("getwindowname", wid)
    captcha_keywords = ["验证", "captcha", "安全验证", "滑动"]
    for kw in captcha_keywords:
        if kw in title:
            log.warning(f"    ⚠️ 检测到验证码页面: {title}")
            return True
    return False

def read_xlsx_data(filepath):
    """读取xlsx文件，提取商品数据"""
    wb = load_workbook(filepath, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    headers = [str(h).strip() if h else "" for h in rows[0]]
    data = []
    for row in rows[1:]:
        record = {}
        for i, val in enumerate(row):
            if i < len(headers):
                record[headers[i]] = str(val).strip() if val else ""
        data.append(record)
    return headers, data

def extract_item_id(url):
    """从URL提取商品ID"""
    import re
    m = re.search(r'id=(\d+)', str(url))
    return m.group(1) if m else ""

def save_csv(data, keyword, headers_map):
    """保存商品数据到CSV"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(OUTPUT_DIR, f"human_{keyword}_{ts}.csv")
    fieldnames = ["商品ID", "标题", "价格", "销量", "链接"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in data:
            url = item.get(headers_map.get("链接", ""), "")
            writer.writerow({
                "商品ID": extract_item_id(url),
                "标题": item.get(headers_map.get("标题", ""), ""),
                "价格": item.get(headers_map.get("价格", ""), ""),
                "销量": item.get(headers_map.get("销量", ""), ""),
                "链接": url,
            })
    return filepath

def find_column_mapping(headers):
    """自动识别xlsx列名映射"""
    mapping = {}
    for h in headers:
        hl = h.lower()
        if "标题" in hl or "title" in hl or "商品名" in hl:
            mapping["标题"] = h
        elif "价格" in hl or "price" in hl or "成交价" in hl:
            mapping["价格"] = h
        elif "销量" in hl or "sales" in hl or "月销" in hl or "付款" in hl:
            mapping["销量"] = h
        elif "链接" in hl or "url" in hl or "商品" in hl:
            mapping["链接"] = h
    return mapping

# ─── 主流程 ──────────────────────────────────────────────
def human_like_crawl(keyword: str):
    """纯xdotool物理操作爬取"""
    log.info("=" * 60)
    log.info(f"纯物理模式抓取 — {keyword}")
    log.info("=" * 60)

    # ─── Step 1: 清理环境 ───
    log.info("\n=== 1. 清理环境 ===")
    close_chrome()
    cleanup_crash_markers()
    # 清理旧下载文件
    import glob
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*.xlsx")):
        try: os.remove(f)
        except: pass
    log.info("  环境就绪")

    # ─── Step 2: 启动Chrome（无CDP） ───
    log.info("\n=== 2. 启动Chrome ===")
    subprocess.Popen([
        CHROME_BIN,
        f"--user-data-dir={CHROME_PROFILE}",
        "--disable-gpu",
        "--start-maximized",
        "--no-first-run",
        "https://www.taobao.com",
    ], env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("  Chrome启动中...")
    time.sleep(8)

    wid = find_chrome_wid()
    if not wid:
        log.error("  ❌ 未找到Chrome窗口")
        return False
    activate_chrome(wid)
    log.info(f"  Chrome窗口: {wid}")

    # ─── Step 3: 处理弹窗 ───
    log.info("\n=== 3. 处理弹窗 ===")
    handle_popups(wid)

    # ─── Step 4: 检查验证码 ───
    log.info("\n=== 4. 检查验证码 ===")
    if check_captcha(wid):
        log.error("  ❌ 检测到验证码，需要手动处理")
        return False
    log.info("  ✅ 无验证码")

    # ─── Step 5: 导航到搜索页 ───
    log.info(f"\n=== 5. 搜索: {keyword} ===")
    activate_chrome(wid)
    # 用地址栏导航（最可靠）
    xd("key", "ctrl+l")
    time.sleep(0.5)
    import urllib.request
    search_url = f"https://s.taobao.com/search?q={urllib.request.quote(keyword)}"
    paste(search_url)
    time.sleep(0.3)
    xd("key", "Return")
    log.info(f"  已导航到搜索页")
    time.sleep(8)  # 等待页面加载

    # ─── Step 6: 检查验证码（搜索后） ───
    log.info("\n=== 6. 搜索后验证码检查 ===")
    if check_captcha(wid):
        log.error("  ❌ 搜索后触发验证码，需要手动处理")
        return False
    log.info("  ✅ 无验证码")

    # ─── Step 7: 等待页面完全加载 ───
    log.info("\n=== 7. 等待页面加载 ===")
    time.sleep(5)
    log.info("  页面加载完成")

    # ─── Step 8: 点击DTS"市场分析" → "导出表格" ───
    log.info("\n=== 8. DTS导出 ===")
    activate_chrome(wid)

    # 8a: 点击DTS扩展图标打开面板
    log.info("    点击DTS扩展图标...")
    click_dts_icon()
    time.sleep(3)

    # 8b: 查找并点击"市场分析"按钮
    # DTS面板打开后，"市场分析"通常在面板中
    # 需要用鼠标定位（这里用相对坐标估算）
    geo = xd("getwindowgeometry", "--shell", wid)
    w = int(run(f"echo '{geo}' | grep WIDTH | cut -d= -f2") or "1920")
    h = int(run(f"echo '{geo}' | grep HEIGHT | cut -d= -f2") or "1080")

    # DTS面板通常在页面左侧，"市场分析"按钮在面板中部
    ma_x = 150  # 左侧面板
    ma_y = h // 3  # 约1/3高度处
    log.info(f"    点击市场分析 ({ma_x}, {ma_y})")
    click(ma_x, ma_y)
    time.sleep(5)

    # 8c: 查找并点击"导出表格"按钮
    log.info("    点击导出表格...")
    # "导出表格"通常在市场分析面板的底部
    export_x = 150
    export_y = h * 2 // 3
    click(export_x, export_y)
    time.sleep(3)

    # ─── Step 9: 等待xlsx下载 ───
    log.info("\n=== 9. 等待下载 ===")
    xlsx_file = wait_for_file(DOWNLOAD_DIR, "*.xlsx", timeout=120)
    if not xlsx_file:
        log.error("  ❌ 未检测到xlsx下载")
        log.info("  尝试用键盘快捷键导出...")
        # 尝试Ctrl+E或其他快捷键
        xd("key", "ctrl+e")
        time.sleep(5)
        xlsx_file = wait_for_file(DOWNLOAD_DIR, "*.xlsx", timeout=60)

    if not xlsx_file:
        log.error("  ❌ 导出失败")
        close_chrome()
        return False
    log.info(f"  ✅ 下载完成: {xlsx_file}")

    # ─── Step 10: 读取并解析xlsx ───
    log.info("\n=== 10. 解析数据 ===")
    headers, data = read_xlsx_data(xlsx_file)
    if not data:
        log.error("  ❌ xlsx无数据")
        close_chrome()
        return False
    log.info(f"  表头: {headers}")
    log.info(f"  数据: {len(data)}行")

    mapping = find_column_mapping(headers)
    log.info(f"  列映射: {mapping}")

    # ─── Step 11: 保存CSV ───
    log.info("\n=== 11. 导出CSV ===")
    csv_file = save_csv(data, keyword, mapping)
    log.info(f"  文件: {csv_file}")

    # ─── Step 12: 清理 ───
    log.info("\n=== 12. 清理 ===")
    close_chrome()
    # 移动xlsx到data目录
    dest_xlsx = os.path.join(OUTPUT_DIR, os.path.basename(xlsx_file))
    shutil.move(xlsx_file, dest_xlsx)
    log.info(f"  xlsx已保存: {dest_xlsx}")

    log.info(f"\n✅ 完成: {len(data)}条 → {csv_file}")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <关键词>")
        sys.exit(1)
    keyword = sys.argv[1]
    success = human_like_crawl(keyword)
    sys.exit(0 if success else 1)
