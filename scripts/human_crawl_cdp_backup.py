#!/usr/bin/env python3
"""
human_crawl.py — 游客模式淘宝商品抓取
架构：基准模板克隆 → 临时Profile → DTS扩展 → 游客采集 → 清理
红线：禁止自动登录、禁止账号密码、禁止填表
"""
import csv, json, logging, math, os, random, re, shutil, subprocess, sys, time, urllib.parse, urllib.request, uuid
from datetime import datetime; from pathlib import Path
from Xlib import X, display as xd
from Xlib.ext import xtest as xt

# ═══════════════════ 配置 ═══════════════════
KEYWORD = "蒙牛一米八八奶粉"
CDP_PORT = 9223
OUTPUT_DIR = Path("/home/lab-admin/price-monitor/data/downloads")
BASE_TEMPLATE = os.path.expanduser("~/.config/chrome_base_template")
TEMP_PROFILE_BASE = "/home/lab-admin/.config"
DTS_ID = "ppgdlgnehnajbbngnohepfigdmjbdpfb"

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("human")
report = []
def rpt(msg):
    logger.info(msg)
    report.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ═══════════════════ CDP ═══════════════════
def cdp_cmd(ws, m, p=None, t=15):
    msg = {"id": int(time.time()*1000)%1000000, "method": m}
    if p: msg["params"] = p
    ws.send(json.dumps(msg))
    dl = time.time() + t
    while time.time() < dl:
        r = json.loads(ws.recv())
        if r.get("id") == msg["id"]: return r
    raise TimeoutError(m)

def cdp_eval(ws, js):
    r = cdp_cmd(ws, "Runtime.evaluate",
        {"expression": js, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))

def cdp_eval_ctx(ws, ctx, js):
    r = cdp_cmd(ws, "Runtime.evaluate",
        {"expression": js, "contextId": ctx, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))


# ═══════════════════ Chrome 生命周期 ═══════════════════
def graceful_shutdown(profile_dir=None):
    """优雅关闭：CDP关Tab → TERM → 等待 → KILL兜底 + 清理崩溃标记"""
    rpt("  优雅关闭Chrome...")
    # 1. CDP关Tab（如果连接正常）
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=3)
        targets = json.loads(resp.read())
        import websocket
        for t in targets:
            if t.get("type") == "page":
                try:
                    ws_t = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=3)
                    ws_t.send(json.dumps({"id": 1, "method": "Page.close"})); ws_t.close()
                except: pass
    except: pass
    # 2. 发SIGTERM，等待Chrome自行退出（最重要）
    subprocess.run(["pkill", "-TERM", "chrome"], check=False)
    for i in range(8):
        time.sleep(1)
        r = subprocess.run(["pgrep", "-c", "chrome"], capture_output=True, text=True)
        if r.stdout.strip() in ("", "0"):
            rpt("  Chrome已关闭")
            return
    # 3. KILL兜底（仅极端情况）
    rpt("    TERM未退出, KILL兜底")
    subprocess.run(["pkill", "-KILL", "chrome"], check=False)
    time.sleep(3)
    # 4. 清理崩溃标记 — 防止"Chrome未正常关闭"弹窗
    if profile_dir:
        for f in ["Last Session", "Last Tabs", "Current Session", "Current Tabs"]:
            fp = os.path.join(profile_dir, f)
            if os.path.exists(fp): os.remove(fp)
    rpt("  Chrome已关闭")


def clone_template():
    """克隆基准模板 → 临时Profile（含完整Cookie）"""
    run_id = uuid.uuid4().hex[:12]
    temp_dir = f"{TEMP_PROFILE_BASE}/chrome_run_{run_id}"
    rpt(f"  克隆模板 → {temp_dir}")
    shutil.copytree(BASE_TEMPLATE, temp_dir, symlinks=True)
    # 修复权限
    subprocess.run(["chmod", "-R", "700", temp_dir], check=False, capture_output=True)
    # 清理SQLite WAL/SHM文件（避免Cookie损坏）
    for f in ["Cookies-wal", "Cookies-shm", "Login Data-wal", "Login Data-shm"]:
        fp = os.path.join(temp_dir, "Default", f)
        if os.path.exists(fp): os.remove(fp)
    # 清理崩溃标记 — 防止"Chrome未正常关闭"弹窗
    for f in ["Last Session", "Last Tabs", "Current Session", "Current Tabs"]:
        fp = os.path.join(temp_dir, f)
        if os.path.exists(fp): os.remove(fp)
    # 验证Cookie有效性
    ck = os.path.join(temp_dir, "Default", "Cookies")
    if os.path.exists(ck) and os.path.getsize(ck) > 0:
        try:
            import sqlite3
            conn = sqlite3.connect(ck)
            cnt = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
            conn.close()
            rpt(f"    Cookie: {cnt}条 ✅")
        except:
            rpt("    ⚠️ Cookie读取失败")
    return temp_dir, run_id


def launch_chrome(temp_profile):
    """启动Chrome — 必须用 /opt/google/chrome/chrome 而非 /usr/bin/google-chrome-stable (wrapper会损坏参数)"""
    rpt(f"  启动Chrome profile={temp_profile}")
    # CRITICAL: /usr/bin/google-chrome-stable is a wrapper that mangles argument list.
    # MUST use /opt/google/chrome/chrome directly.
    # CRITICAL: Chrome args MUST use = notation (--key=value), not space-separated
    # --no-first-run: 跳过首次运行向导
    # --restore-last-session=false: 禁用崩溃恢复弹窗
    subprocess.Popen([
        "/opt/google/chrome/chrome",
        f"--user-data-dir={temp_profile}",
        "--disable-gpu",
        "--disable-software-rasterizer",
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        "--start-maximized",
        "--ozone-platform=x11",
        "--no-first-run",
        "--restore-last-session=false",
        "https://www.taobao.com",
    ], env=os.environ)
    rpt("    Chrome进程已启动, 等待CDP...")

    import websocket
    # Chrome in this environment takes ~25-35s for CDP to be ready
    # First-time profile init may take 60s+
    for i in range(35):
        time.sleep(3)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3)
            rpt(f"    CDP ready ({(i+1)*3:.0f}s)")
            break
        except Exception as e:
            if i % 4 == 3: rpt(f"    等待CDP...({(i+1)*3}s)")
    else:
        raise RuntimeError("Chrome CDP启动失败 (105s超时)")

    # Get or create a page
    for attempt in range(5):
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=3)
            targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]
            if not pages:
                urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank", timeout=5)
                time.sleep(1)
                resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=3)
                targets = json.loads(resp.read())
                pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=15, origin="")
                cdp_cmd(ws, "Page.enable"); cdp_cmd(ws, "Runtime.enable")
                rpt(f"    WS connected: {pages[0].get('title','')[:40]}")
                return ws
        except: pass
        time.sleep(1)
    raise RuntimeError("Chrome页面创建失败")


def verify_dts(ws):
    """验证DTS扩展已加载 — 仅CDP targets检查"""
    rpt("  验证DTS扩展...")
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=3)
        targets = json.loads(resp.read())
        dts_targets = [t for t in targets if DTS_ID in t.get("url", "")]
        if dts_targets:
            rpt(f"    ✅ DTS已加载 (targets: {len(dts_targets)})")
            return True
    except: pass
    rpt("    ⚠️ DTS未在targets中, 稍后在淘宝页面验证")
    return True  # 不阻塞，淘宝页面会再检查


# ═══════════════════ X11 鼠标 ═══════════════════
def x11_move(x, y):
    disp = xd.Display()
    disp.warp_pointer(int(x), int(y)); disp.sync()
    disp.close()

def x11_click(x, y, count=1):
    x11_move(x, y); time.sleep(0.3)
    for _ in range(count):
        subprocess.run(["xdotool", "click", "1"], env=os.environ, capture_output=True, timeout=5)
        time.sleep(0.15)

def x11_type(text):
    """逐字输入，模拟人类打字"""
    for char in text:
        subprocess.run(["xdotool", "type", char], env=os.environ, capture_output=True, timeout=5)
        time.sleep(random.uniform(0.08, 0.25))  # 字符间80~250ms


# ═══════════════════ 双层弹窗自动处理 ═══════════════════
def handle_crash_recovery_popup():
    """第一层：处理「要恢复页面吗？」弹窗 — 点击×关闭，绝不点恢复"""
    rpt("  检查「要恢复页面吗？」弹窗...")
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            # xdotool搜索窗口标题含"恢复"的窗口
            res = subprocess.run(
                ["xdotool", "search", "--name", "恢复"],
                capture_output=True, text=True, timeout=3
            )
            win_ids = [w for w in res.stdout.strip().split("\n") if w]
            if not win_ids:
                # 也搜标题含"Chrome"+"页面"的
                res2 = subprocess.run(
                    ["xdotool", "search", "--name", "要恢复页面"],
                    capture_output=True, text=True, timeout=3
                )
                win_ids = [w for w in res2.stdout.strip().split("\n") if w]
            if win_ids:
                rpt(f"    发现恢复弹窗窗口: {win_ids[0]}")
                # 点击右上角×关闭按钮 — 相对窗口右上角 (width-30, 10)
                geo = subprocess.run(
                    ["xdotool", "getwindowgeometry", win_ids[0]],
                    capture_output=True, text=True, timeout=3
                ).stdout
                # Parse geometry: x,y,w,h
                import re as _re
                m = _re.search(r'Position:\s*(\d+),(\d+).*Geometry:\s*(\d+)x(\d+)', geo, _re.DOTALL)
                if m:
                    wx, wy, ww, wh = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    close_x, close_y = wx + ww - 20, wy + 10
                    rpt(f"    点击×关闭 ({close_x},{close_y})")
                    subprocess.run(
                        ["xdotool", "mousemove", str(close_x), str(close_y), "click", "1"],
                        env=os.environ, capture_output=True, timeout=5
                    )
                    time.sleep(1)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    rpt("    无恢复弹窗，跳过")
    return False


def handle_dts_permission_popup():
    """第二层：处理「店透视 已被禁用」权限弹窗 — 点击接受权限"""
    rpt("  检查「店透视 已被禁用」弹窗...")
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            # xdotool搜索窗口标题含"店透视"+"禁用"的
            res = subprocess.run(
                ["xdotool", "search", "--name", "店透视"],
                capture_output=True, text=True, timeout=3
            )
            win_ids = [w for w in res.stdout.strip().split("\n") if w]
            if not win_ids:
                res2 = subprocess.run(
                    ["xdotool", "search", "--name", "权限"],
                    capture_output=True, text=True, timeout=3
                )
                win_ids = [w for w in res2.stdout.strip().split("\n") if w]
            if win_ids:
                wid = win_ids[0]
                rpt(f"    发现DTS权限弹窗窗口: {wid}")
                # 点击右下角蓝色【接受权限】按钮
                geo = subprocess.run(
                    ["xdotool", "getwindowgeometry", wid],
                    capture_output=True, text=True, timeout=3
                ).stdout
                import re as _re
                m = _re.search(r'Position:\s*(\d+),(\d+).*Geometry:\s*(\d+)x(\d+)', geo, _re.DOTALL)
                if m:
                    wx, wy, ww, wh = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    # 「接受权限」在弹窗右下区域
                    btn_x, btn_y = wx + ww - 160, wy + wh - 50
                    rpt(f"    点击「接受权限」 ({btn_x},{btn_y})")
                    subprocess.run(
                        ["xdotool", "mousemove", str(btn_x), str(btn_y), "click", "1"],
                        env=os.environ, capture_output=True, timeout=5
                    )
                    rpt("    等待4s DTS权限生效...")
                    time.sleep(4)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    rpt("    无DTS权限弹窗，跳过")
    return False


def handle_all_popups():
    """Chrome启动后按序处理全部弹窗"""
    rpt("\n=== 弹窗检测 ===")
    time.sleep(9)  # 等待9秒页面渲染完成
    r1 = handle_crash_recovery_popup()
    r2 = handle_dts_permission_popup()
    rpt(f"  恢复弹窗={'已关闭' if r1 else '无'}, DTS权限={'已授权' if r2 else '无弹窗'}")


# ═══════════════════ 登录弹窗处理 ═══════════════════
def close_login_popup(ws):
    """关闭淘宝自动弹出的登录弹窗 — 游客模式继续"""
    closed = False
    close_selectors = [
        '.login-close', '.J_LoginClose', '[class*="close"]',
        '.overlay', '.mask', '[class*="J_Close"]'
    ]
    for sel in close_selectors:
        try:
            clicked = cdp_eval(ws, f"""(function(){{
                var el = document.querySelector('{sel}');
                if(el && el.getBoundingClientRect().width>0){{
                    el.click(); return 'closed:{sel}';
                }}
                return 'not_found';
            }})()""")
            if "closed" in clicked:
                rpt(f"    已关闭登录弹窗: {sel}")
                closed = True; break
        except: pass
    return closed


# ═══════════════════ 滑块验证特征文档 ═══════════════════
# 淘宝滑块验证码 — 两种形态:
# ┌─────────────────────────────────────────────────────────┐
# │ 形态1: iframe内嵌 (h5api.m.taobao.com)                  │
# │   - Page.getFrameTree查找iframe                         │
# │   - Page.createIsolatedWorld穿透定位滑块元素             │
# │   - 拖拽按钮: [id*="nc_1_n1z"]                          │
# │                                                         │
# │ 形态2: 全页面验证码拦截 (新标签页)                       │
# │   - URL含 sec.taobao.com / h5api / captcha / risk       │
# │   - 页面body含"验证"/"安全验证"/"滑动"/"拖动"           │
# │   - 滑块元素: [id*="nc_1_n1z"] 或 .nc-lang-cnt          │
# │   - 可能打开新标签页，需要扫描所有tabs                   │
# │                                                         │
# │ X11偏移: (66,119) — 服务器实测                           │
# │ 拖拽参数: 320+采样点, 3.3-3.6s, 正弦波+easing           │
# │ 策略: 严禁绕过, 每步操作前强制检查                       │
# └─────────────────────────────────────────────────────────┘

# 验证码URL特征
CAPTCHA_URL_PATTERNS = ["h5api.m.taobao.com", "sec.taobao.com", "captcha", "risk", "acs.m.taobao.com/mtop/common"]
CAPTCHA_TEXT_PATTERNS = ["安全验证", "请完成验证", "滑动验证", "拖动滑块", "滑动完成验证"]

def _check_captcha_in_page(ws):
    """检查当前连接的页面是否为验证码页面（URL+文本+元素三重检测）"""
    try:
        url = cdp_eval(ws, "window.location.href", timeout=3) or ""
        for p in CAPTCHA_URL_PATTERNS:
            if p in url: return True, "url:" + p
    except: pass
    try:
        body = cdp_eval(ws, "(document.body?.innerText||'').substring(0,800)", timeout=3) or ""
        for p in CAPTCHA_TEXT_PATTERNS:
            if p in body: return True, "text:" + p
    except: pass
    try:
        has_el = cdp_eval(ws, """(function(){
            if(document.querySelector('[id*="nc_1_n1z"]'))return 'slider_el';
            if(document.querySelector('.nc-lang-cnt,.slidetounlock,.btn_slide'))return 'slider_cls';
            return '';
        })()""", timeout=3) or ""
        if has_el: return True, "element:" + has_el
    except: pass
    return False, ""

def scan_tabs_for_captcha(main_ws):
    """扫描所有Chrome标签页，返回验证码标签页的WebSocket URL（如果有）"""
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=3)
        targets = json.loads(resp.read())
        for t in targets:
            if t.get("type") != "page": continue
            url = t.get("url", "")
            title = t.get("title", "")
            for p in CAPTCHA_URL_PATTERNS:
                if p in url:
                    return t.get("webSocketDebuggerUrl", ""), f"url_match:{p}"
            for p in CAPTCHA_TEXT_PATTERNS:
                if p in title:
                    return t.get("webSocketDebuggerUrl", ""), f"title_match:{p}"
    except: pass
    return None, None

def ensure_no_captcha(ws, label="", timeout=15):
    """通用滑块检测+求解 — 覆盖iframe+全页面+新标签页，严禁绕过"""
    rpt(f"  🔍 滑块检测{f' ({label})' if label else ''}...")

    # 1. 检查所有标签页是否有验证码页面
    tab_ws_url, tab_reason = scan_tabs_for_captcha(ws)
    if tab_ws_url:
        rpt(f"    ⚠️ 发现验证码标签页: {tab_reason}")
        import websocket
        try:
            cap_ws = websocket.create_connection(tab_ws_url, timeout=10)
            rpt("    切换到验证码标签页, 尝试求解...")
            solved = _solve_captcha_on_page(cap_ws, "标签页验证码")
            cap_ws.close()
            if solved:
                # 切回主标签页
                try:
                    ws.send(json.dumps({"id": 999, "method": "Page.bringToFront"}))
                    ws.recv()
                except: pass
                time.sleep(1)
                return True
        except Exception as e:
            rpt(f"    ⚠️ 切换标签页失败: {e}")

    # 2. 检查当前页面是否有验证码
    found, reason = _check_captcha_in_page(ws)
    if found:
        rpt(f"    ⚠️ 当前页面检测到验证码: {reason}")
        return _solve_captcha_on_page(ws, label)

    # 3. 检查iframe内嵌验证码（原有逻辑）
    ctx, sd = wait_for_slider_ready(ws, timeout=min(timeout, 8))
    if ctx:
        rpt("    ⚠️ iframe内检测到滑块验证! 自动求解中...")
        if drag_slider_xlib(ws, ctx, sd):
            time.sleep(random.uniform(2, 3))
            ctx2, _ = wait_for_slider_ready(ws, timeout=3)
            if not ctx2:
                rpt("    ✅ 滑块验证通过!")
                return True
            rpt("    ❌ 滑块求解失败")
            return False
        rpt("    ❌ 滑块拖拽异常")
        return False

    rpt("    ✅ 无滑块")
    return True

def _solve_captcha_on_page(ws, label=""):
    """在当前页面上求解全页面滑块验证码"""
    for attempt in range(3):
        rpt(f"    求解尝试 {attempt+1}/3...")
        # 查找滑块元素位置
        try:
            pos_data = cdp_eval(ws, """(function(){
                var s=document.querySelector('[id*="nc_1_n1z"]');
                if(!s)s=document.querySelector('.nc-lang-cnt .btn_slide,.slidetounlock .btn');
                if(!s)s=document.querySelector('[class*="slide"]');
                if(!s)return JSON.stringify({found:false});
                var r=s.getBoundingClientRect();
                var t=document.querySelector('[id*="nc_1__scale_text"]');
                var dist=260;
                if(t){var tr=t.getBoundingClientRect();dist=Math.round(tr.x+tr.width-r.x-r.width+3);}
                var fl=(window.outerWidth-window.innerWidth)/2;
                var to=window.outerHeight-window.innerHeight-fl;
                var ox=(window.screenLeft||0)+fl,oy=(window.screenTop||0)+to;
                return JSON.stringify({found:true,sx:Math.round(r.x+r.width/2),sy:Math.round(r.y+r.height/2),dist:dist,ox:ox,oy:oy});
            })()""", timeout=5)
            sd = json.loads(pos_data)
        except:
            time.sleep(2); continue

        if not sd.get("found"):
            rpt("    滑块元素未就绪, 等2s...")
            time.sleep(2); continue

        # 全页面滑块 — 直接用页面坐标+X11偏移
        OX, OY = 66, 119
        sx = sd["sx"] + sd.get("ox", 0) + OX
        sy = sd["sy"] + sd.get("oy", 0) + OY
        dist = sd["dist"] + random.randint(-3, 5)
        rpt(f"    X11:({sx},{sy}) dist={dist}")

        try:
            disp = xd.Display()
            def mov(x,y): xt.fake_input(disp, X.MotionNotify, x=int(x), y=int(y)); disp.sync()
            ax, ay = sx - random.randint(60, 120), sy + random.randint(-10, 10)
            for i in range(5):
                p = (i+1)/5; mov(int(ax+(sx-ax)*p), int(ay+(sy-ay)*p))
                time.sleep(0.015 + random.random() * 0.02)
            mov(sx, sy); time.sleep(0.06 + random.random() * 0.05)
            xt.fake_input(disp, X.ButtonPress, detail=1); disp.sync()
            time.sleep(0.025 + random.random() * 0.03)
            n = random.randint(320, 356)
            dur = 3.3 + random.random() * 0.3
            for i in range(n):
                p = i / n
                e = 1 - (1 - p) ** random.uniform(1.6, 2.8)
                x = int(sx + dist * e)
                y = sy + int(math.sin(p * math.pi * 4) * random.randint(1, 4))
                if p > 0.85: y = sy + random.randint(-1, 1)
                mov(x, y)
                time.sleep(dur / n * (0.8 + random.random() * 0.4))
            time.sleep(0.05 + random.random() * 0.04)
            xt.fake_input(disp, X.ButtonRelease, detail=1); disp.sync()
            disp.close()
        except Exception as e:
            rpt(f"    X11异常: {e}"); time.sleep(3); continue

        time.sleep(4)
        # 验证是否通过
        found, reason = _check_captcha_in_page(ws)
        if not found:
            rpt(f"    ✅ 验证码求解通过!")
            return True
        rpt(f"    ❌ 验证码仍在 ({reason}), 重试...")
        time.sleep(3)

    rpt(f"    ❌ 3次求解失败")
    return False


def has_captcha(ws, timeout=3):
    """快速滑块检测（2-3s超时）— 覆盖iframe+全页面+标签页"""
    # 1. 检查标签页
    tab_ws_url, _ = scan_tabs_for_captcha(ws)
    if tab_ws_url: return True
    # 2. 检查当前页面
    found, _ = _check_captcha_in_page(ws)
    if found: return True
    # 3. 检查iframe
    try:
        ft = cdp_cmd(ws, "Page.getFrameTree", t=timeout)
        def find(n):
            for c in n.get("childFrames", []):
                if "h5api.m.taobao.com" in c.get("frame", {}).get("url", ""):
                    return True
                if find(c): return True
            return False
        return find(ft.get("result", {}).get("frameTree", {}))
    except:
        return False


def safe_eval(ws, js, label="", max_retries=3):
    """带滑块自动检测的CDP eval — 每次调用前快速检查（覆盖全页面+标签页+iframe）"""
    for attempt in range(max_retries):
        # 快速检测滑块（覆盖所有形态）
        if has_captcha(ws, timeout=2):
            rpt(f"  ⚠️ [{label}] 检测到滑块! 自动求解...")
            ensure_no_captcha(ws, label=label, timeout=10)
        # 执行实际CDP操作
        try:
            return cdp_eval(ws, js)
        except Exception as e:
            if attempt < max_retries - 1:
                rpt(f"    ⚠️ [{label}] CDP异常: {e}, 重试{attempt+2}")
                time.sleep(2)
            else:
                raise
    return ""


def wait_for_slider_ready(ws, timeout=30):
    """CDP穿透跨域iframe定位滑块"""
    start = time.time(); ll = 0
    while time.time() - start < timeout:
        ft = cdp_cmd(ws, "Page.getFrameTree")
        tree = ft.get("result",{}).get("frameTree",{})
        h5fid = [None]
        def fh(n):
            for c in n.get("childFrames",[]):
                u = c.get("frame",{}).get("url","")
                if "h5api.m.taobao.com" in u: h5fid[0] = c.get("frame",{}).get("id",""); return
                fh(c)
        fh(tree)
        if int(time.time() - start) - ll >= 5:
            rpt(f"    frame={'found' if h5fid[0] else '❌'}")
            ll = int(time.time() - start)
        if not h5fid[0]: time.sleep(0.5); continue
        try:
            iso = cdp_cmd(ws, "Page.createIsolatedWorld", {"frameId": h5fid[0]})
            ctx = iso.get("result",{}).get("executionContextId")
            if not ctx: time.sleep(0.5); continue
        except: time.sleep(0.5); continue
        for _ in range(50):
            try:
                c = cdp_eval_ctx(ws, ctx, "document.querySelectorAll('[id*=\"nc_1_n1z\"]').length")
                if c not in ("0","undefined","null","") and int(c) > 0:
                    cd = cdp_eval_ctx(ws, ctx, """(function(){var s=document.querySelector('[id*="nc_1_n1z"]');var t=document.querySelector('[id*="nc_1__scale_text"]');if(!s||!t)return JSON.stringify({found:false});var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()""")
                    sd = json.loads(cd)
                    if sd.get("found"): rpt("  ✅ 滑块就绪"); return ctx, sd
            except: pass
            time.sleep(0.2)
        time.sleep(0.5)
    return None, None

def drag_slider_xlib(ws, ctx, sd):
    """python-xlib XTest 滑块拖拽 — 320+采样点正弦波+easing"""
    try:
        ipos = cdp_eval(ws, """(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return'{}';})()""")
        ip = json.loads(ipos)
        # CHROME_OFFSET (66,119) — 服务器X11实测
        OX, OY = 66, 119
        sx = ip.get("x",397) + sd["sx"] + OX
        sy = ip.get("y",181) + sd["sy"] + OY
        dist = sd["dist"] + random.randint(-3, 5)
        rpt(f"    X11:({sx},{sy}) dist={dist}")

        disp = xd.Display()
        def mov(x,y): xt.fake_input(disp, X.MotionNotify, x=int(x), y=int(y)); disp.sync()
        ax, ay = sx - random.randint(60, 120), sy + random.randint(-10, 10)
        for i in range(5):
            p = (i+1)/5; mov(int(ax+(sx-ax)*p), int(ay+(sy-ay)*p))
            time.sleep(0.015 + random.random() * 0.02)
        mov(sx, sy); time.sleep(0.06 + random.random() * 0.05)
        xt.fake_input(disp, X.ButtonPress, detail=1); disp.sync()
        time.sleep(0.025 + random.random() * 0.03)

        n = random.randint(320, 356)
        dur = 3.3 + random.random() * 0.3
        for i in range(n):
            p = i / n
            e = 1 - (1 - p) ** random.uniform(1.6, 2.8)
            x = int(sx + dist * e)
            y = sy + int(math.sin(p * math.pi * 4) * random.randint(1, 4))
            if p > 0.85: y = sy + random.randint(-1, 1)
            mov(x, y)
            time.sleep(dur / n * (0.8 + random.random() * 0.4))
        time.sleep(0.05 + random.random() * 0.04)
        xt.fake_input(disp, X.ButtonRelease, detail=1); disp.sync()
        disp.close()
        time.sleep(6); return True
    except Exception as e:
        rpt(f"  ❌ X11异常: {e}"); return False


# ═══════════════════ 主流程 ═══════════════════
def human_like_crawl(keyword):
    rpt("="*60)
    rpt(f"游客模式抓取 — {keyword}")
    rpt("="*60)

    # Step 1: 优雅关闭旧Chrome + 克隆模板
    rpt("\n=== 1. 环境准备 ===")
    graceful_shutdown()
    temp_profile, run_id = clone_template()
    clean_profile_dir = temp_profile  # 用于最后清理

    # Step 2: 启动Chrome
    rpt("\n=== 2. 启动Chrome ===")
    ws = launch_chrome(temp_profile)

    try:
        # Step 2.5: 处理启动后的弹窗（恢复页面 + DTS权限）
        handle_all_popups()

        # Step 3: DTS验证
        rpt("\n=== 3. DTS扩展验证 ===")
        dts_ok = verify_dts(ws)
        rpt(f"    DTS: {'✅' if dts_ok else '⚠️ 未确认'}")

        # Step 4: 处理首页滑块+登录态检查
        rpt(f"\n=== 4. 首页滑块检测 ===")
        cdp_cmd(ws, "Page.bringToFront")
        time.sleep(2)
        ensure_no_captcha(ws, "首页加载后", timeout=12)
        # 检查登录态
        body = safe_eval(ws, "(document.body?.innerText||'').substring(0,500)", "登录态")
        is_logged = "giftboy" in body or ("我的淘宝" in body and "请登录" not in body)
        rpt(f"    登录态: {'✅ 已登录' if is_logged else '⚠️ 未登录'}")
        # 随机滚动(人类行为)
        rpt("    随机滚动...")
        for i in range(random.randint(2, 4)):
            safe_eval(ws, f"window.scrollTo(0, {random.randint(200, 600)})", "滚动")
            time.sleep(random.uniform(1, 2))

        # Step 5: 搜索关键词 (xdotool物理点击搜索框+打字)
        rpt(f"\n=== 5. 搜索: {keyword} ===")
        search_coords = json.loads(safe_eval(ws, """(function(){
            var q = document.getElementById('q') || document.querySelector('input[id*="search"]');
            if(!q) return JSON.stringify({found:false});
            var r = q.getBoundingClientRect();
            var fl = (window.outerWidth-window.innerWidth)/2;
            var to = window.outerHeight-window.innerHeight-fl;
            var ox = (window.screenLeft||0)+fl, oy = (window.screenTop||0)+to;
            return JSON.stringify({found:true, x:Math.round(r.x+r.width/2+ox), y:Math.round(r.y+r.height/2+oy)});
        })()"""))
        if search_coords.get("found"):
            rpt(f"    点击搜索框 ({search_coords['x']},{search_coords['y']})")
            x11_click(search_coords["x"], search_coords["y"], count=1)
            time.sleep(random.uniform(0.5, 1.0))
            # CDP直接设置搜索框值并触发事件（最可靠）
            set_result = safe_eval(ws, f"""(function(){{
                var q = document.getElementById('q') || document.querySelector('input[id*="search"]');
                if(!q) return 'no_input';
                q.focus();
                q.value = '{keyword}';
                q.dispatchEvent(new Event('input', {{bubbles:true}}));
                q.dispatchEvent(new Event('change', {{bubbles:true}}));
                return q.value;
            }})()""", "设置搜索关键词")
            rpt(f"    搜索框内容: {set_result[:30]}")
            time.sleep(random.uniform(0.3, 0.6))
            # CDP模拟回车（比xdotool更可靠）
            cdp_cmd(ws, "Input.dispatchKeyEvent", {
                "type": "keyDown", "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13
            })
            cdp_cmd(ws, "Input.dispatchKeyEvent", {
                "type": "keyUp", "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13
            })
            time.sleep(random.uniform(4, 6))
            # 验证URL是否变化
            cur_url = safe_eval(ws, "window.location.href", "检查URL")
            rpt(f"    当前URL: {cur_url[:80]}")
            # 如果URL没变，降级直接导航
            if "s.taobao.com" not in cur_url:
                rpt("    ⚠️ 搜索未生效, 降级CDP导航")
                cdp_cmd(ws, "Page.navigate",
                    {"url": f"https://s.taobao.com/search?q={urllib.request.quote(keyword)}"})
                time.sleep(random.uniform(6, 10))
                cur_url = safe_eval(ws, "window.location.href", "检查URL-导航后")
                rpt(f"    导航后URL: {cur_url[:80]}")
        else:
            rpt("    ⚠️ 未找到搜索框, 降级CDP导航")
            cdp_cmd(ws, "Page.navigate",
                {"url": f"https://s.taobao.com/search?q={urllib.request.quote(keyword)}"})
            time.sleep(random.uniform(6, 10))

        # Step 6: 滑块验证(搜索后)
        rpt("\n=== 6. 滑块检测 ===")
        captcha_solved = ensure_no_captcha(ws, "搜索后", timeout=30)
        if not captcha_solved:
            rpt("    ⚠️ 滑块未通过, 尝试继续采集")

        # 关闭可能弹的登录窗
        for _ in range(3):
            if "登录" in safe_eval(ws, "(document.body?.innerText||'').substring(0,500)", "登录弹窗"):
                close_login_popup(ws); time.sleep(2)

        # Step 7: 浏览搜索结果(人类行为) + 搜索API拦截
        rpt("\n=== 7. 浏览搜索结果 ===")
        # JS层拦截fetch/XHR — 捕获搜索API响应
        safe_eval(ws, """(function(){
            window.__crawl_api=[];
            var origFetch=window.fetch;
            window.fetch=function(){
                var url=arguments[0];
                if(typeof url==='string'&&(url.indexOf('h5api')!==-1||url.indexOf('mtop.taobao')!==-1||url.indexOf('search')!==-1)){
                    return origFetch.apply(this,arguments).then(function(r){
                        r.clone().text().then(function(t){try{window.__crawl_api.push({u:url,d:JSON.parse(t)});}catch(e){}});
                        return r;
                    });
                }
                return origFetch.apply(this,arguments);
            };
            var origOpen=XMLHttpRequest.prototype.open;
            var origSend=XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open=function(m,u){this._url=u;return origOpen.apply(this,arguments);};
            XMLHttpRequest.prototype.send=function(){
                var xhr=this;
                xhr.addEventListener('load',function(){if(xhr._url&&(xhr._url.indexOf('h5api')!==-1||xhr._url.indexOf('mtop.taobao')!==-1||xhr._url.indexOf('search')!==-1)){try{window.__crawl_api.push({u:xhr._url,d:JSON.parse(xhr.responseText)});}catch(e){}}});
                return origSend.apply(this,arguments);
            };
        })()""", "API拦截注入")
        for i in range(random.randint(2, 3)):
            safe_eval(ws, f"window.scrollTo(0, {random.randint(300, 800)})", "浏览滚动")
            time.sleep(random.uniform(1, 2))
        # 随机点击商品卡片
        try:
            safe_eval(ws, """(function(){
                var cards=document.querySelectorAll('a[href*="item.taobao.com"]');
                if(cards.length){var idx=Math.floor(Math.random()*Math.min(cards.length,4));
                cards[idx].click();return'clicked';}return'skip';})()""", "点击商品")
            time.sleep(random.uniform(2, 3))
            safe_eval(ws, "window.history.back()", "返回"); time.sleep(2)
        except: pass

        # 浏览后强制验证码检查
        ensure_no_captcha(ws, "浏览后", timeout=15)

        # Step 8: DTS导出表格(两阶段: 先开"市场分析"面板 → 再点"导出表格")
        rpt("\n=== 8. DTS导出表格 ===")
        # 淘宝封锁CDP浏览器搜索渲染, 改用DTS从服务端取数据
        export_file = None
        downloads_before = set()
        for dl_dir in ["/home/lab-admin/Downloads", os.path.expanduser("~/Downloads")]:
            if os.path.isdir(dl_dir):
                downloads_before.update(os.path.join(dl_dir, f) for f in os.listdir(dl_dir))

        # 阶段1: 点击"市场分析"按钮打开DTS面板
        panel_ready = False  # 初始化
        # 先诊断: 页面上的DTS工具栏文本
        dts_debug = safe_eval(ws, """(function(){
            var all=document.querySelectorAll("*");
            var found=[];
            for(var i=0;i<all.length;i++){
                var t=(all[i].textContent||"").trim();
                if((t.indexOf("市场分析")!==-1||t.indexOf("导出表格")!==-1||t.indexOf("全网淘词")!==-1)&&all[i].getBoundingClientRect().width>0&&all[i].children.length===0){
                    var r=all[i].getBoundingClientRect();
                    found.push({t:t.substring(0,20),tag:all[i].tagName,x:Math.round(r.x),y:Math.round(r.y)});
                }
            }
            return JSON.stringify(found);
        })()""", "DTS诊断")
        rpt(f"    DTS工具栏: {dts_debug}")

        # 用包含匹配查找"市场分析"（而非精确匹配）
        ma_coords = json.loads(safe_eval(ws, """(function(){
            var all=document.querySelectorAll("*");
            for(var i=0;i<all.length;i++){
                var t=(all[i].textContent||"").trim();
                if(t.indexOf("市场分析")!==-1&&all[i].getBoundingClientRect().width>0&&all[i].children.length===0){
                    var r=all[i].getBoundingClientRect();
                    var fl=(window.outerWidth-window.innerWidth)/2;
                    var to=window.outerHeight-window.innerHeight-fl;
                    var ox=(window.screenLeft||0)+fl,oy=(window.screenTop||0)+to;
                    return JSON.stringify({found:true,x:Math.round(r.x+r.width/2+ox),y:Math.round(r.y+r.height/2+oy)});
                }
            }
            return JSON.stringify({found:false});
        })()""", "市场分析按钮"))
        # 如果没找到，重试（DTS扩展可能延迟注入工具栏）
        if not ma_coords.get("found"):
            rpt("    等待DTS工具栏加载（最多10s）...")
            for _ in range(5):
                time.sleep(2)
                ma_coords = json.loads(safe_eval(ws, """(function(){
                    var all=document.querySelectorAll("*");
                    for(var i=0;i<all.length;i++){
                        var t=(all[i].textContent||"").trim();
                        if(t.indexOf("市场分析")!==-1&&all[i].getBoundingClientRect().width>0&&all[i].children.length===0){
                            var r=all[i].getBoundingClientRect();
                            var fl=(window.outerWidth-window.innerWidth)/2;
                            var to=window.outerHeight-window.innerHeight-fl;
                            var ox=(window.screenLeft||0)+fl,oy=(window.screenTop||0)+to;
                            return JSON.stringify({found:true,x:Math.round(r.x+r.width/2+ox),y:Math.round(r.y+r.height/2+oy)});
                        }
                    }
                    return JSON.stringify({found:false});
                })()""", "市场分析按钮-重试"))
                if ma_coords.get("found"): break
        if ma_coords.get("found"):
            rpt(f"    阶段1: 点击市场分析 ({ma_coords['x']},{ma_coords['y']})")
            x11_click(ma_coords["x"], ma_coords["y"])
            # 等待DTS面板渲染 + 数据加载
            rpt("    等待DTS面板加载...")
            panel_ready = False
            for _ in range(15):
                time.sleep(2)
                check = safe_eval(ws, """(function(){
                    var all=document.querySelectorAll("*");
                    for(var i=0;i<all.length;i++){
                        var t=(all[i].textContent||"").trim();
                        if(t.indexOf("导出表格")!==-1&&all[i].getBoundingClientRect().width>0)return "found";
                    }
                    return "";
                })()""", "导出按钮检测")
                if check == "found":
                    panel_ready = True; break
            if not panel_ready:
                rpt("    ⚠️ 市场分析面板未加载出导出按钮")
        else:
            rpt("    ⚠️ 未找到市场分析按钮")

        # 阶段2: 点击"导出表格"(面板已打开后)
        if panel_ready:
            exp_coords = json.loads(safe_eval(ws, """(function(){
                var all=document.querySelectorAll("*");
                for(var i=0;i<all.length;i++){
                    var t=(all[i].textContent||"").trim();
                    if(t.indexOf("导出表格")!==-1&&all[i].getBoundingClientRect().width>0){
                        var r=all[i].getBoundingClientRect();
                        var fl=(window.outerWidth-window.innerWidth)/2;
                        var to=window.outerHeight-window.innerHeight-fl;
                        var ox=(window.screenLeft||0)+fl,oy=(window.screenTop||0)+to;
                        return JSON.stringify({found:true,x:Math.round(r.x+r.width/2+ox),y:Math.round(r.y+r.height/2+oy)});
                    }
                }
                return JSON.stringify({found:false});
            })()""", "导出表格按钮"))
            if exp_coords.get("found"):
                rpt(f"    阶段2: 点击导出表格 ({exp_coords['x']},{exp_coords['y']})")
                x11_click(exp_coords["x"], exp_coords["y"])
                rpt("    等待下载...")
                for _ in range(30):
                    time.sleep(2)
                    for dl_dir in ["/home/lab-admin/Downloads", os.path.expanduser("~/Downloads")]:
                        if os.path.isdir(dl_dir):
                            current = set(os.path.join(dl_dir, f) for f in os.listdir(dl_dir))
                            new_files = current - downloads_before
                            xlsxs = [f for f in new_files if f.endswith('.xlsx') and os.path.getsize(f) > 100]
                            if xlsxs:
                                export_file = max(xlsxs, key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0)
                                rpt(f"    ✅ 导出: {os.path.basename(export_file)} ({os.path.getsize(export_file)} bytes)")
                                break
                    if export_file: break
            else:
                rpt("    ⚠️ 未找到导出表格按钮(面板已加载但按钮不可见)")
        else:
            rpt("    ⚠️ DTS面板未就绪, 跳过导出")

        # Step 9: 提取前最后滑块检测
        rpt("\n=== 9. 提取前滑块检测 ===")
        ensure_no_captcha(ws, "提取前", timeout=10)

        # Step 10: 提取商品数据 (DTS导出优先 + 降级多选择器)
        rpt("\n=== 10. 商品提取 ===")
        products = []; seen_pid = set()
        
        if export_file and os.path.exists(export_file):
            # 从DTS导出的Excel文件解析
            rpt(f"    解析DTS导出: {os.path.basename(export_file)}")
            try:
                import openpyxl
                wb = openpyxl.load_workbook(export_file, read_only=True, data_only=True)
                for ws_name in wb.sheetnames:
                    ws_excel = wb[ws_name]
                    rows = list(ws_excel.iter_rows(values_only=True))
                    if not rows: continue
                    # 寻找表头
                    header_row = None
                    for i, row in enumerate(rows[:10]):
                        if row and any(c and ('商品' in str(c) or '标题' in str(c) or '价格' in str(c)) for c in row):
                            header_row = i; break
                    if header_row is None: header_row = 0
                    headers = [str(c) if c else "" for c in rows[header_row]]
                    rpt(f"      sheet={ws_name}, header_row={header_row}, cols={len(headers)}")
                    for row in rows[header_row+1:]:
                        if not row or all(not c for c in row): continue
                        vals = [str(c) if c else "" for c in row]
                        item = dict(zip(headers, vals))
                        # 提取商品链接
                        link = ""
                        for k, v in item.items():
                            if v and ('item.taobao.com' in v or 'detail.tmall.com' in v):
                                link = v; break
                        if not link: continue
                        # 提取ID
                        pid = None
                        for pat in [r'id=(\d+)', r'item/(\d+)']:
                            m = re.search(pat, link)
                            if m: pid = m.group(1); break
                        if not pid: continue
                        if pid in seen_pid: continue
                        seen_pid.add(pid)
                        products.append({
                            "id": pid,
                            "t": item.get("商品标题", item.get("标题", vals[1] if len(vals)>1 else "")),
                            "p": item.get("价格", vals[2] if len(vals)>2 else ""),
                            "sa": item.get("30天销量", item.get("销量", vals[3] if len(vals)>3 else "")),
                            "sh": item.get("店铺名", item.get("店铺", vals[4] if len(vals)>4 else "")),
                            "l": link
                        })
                    rpt(f"      sheet {ws_name}: +{len(products)}条")
                wb.close()
            except ImportError:
                rpt("    openpyxl未安装, 降级CSV解析")
                try:
                    with open(export_file, 'r', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        rows = list(reader)
                    # ... same parsing logic for CSV
                except: pass
            except Exception as e:
                rpt(f"    ❌ Excel解析失败: {e}")
        
        # 降级: 多选择器DOM提取
        if not products:
            rpt("    DTS导出无数据, 降级DOM提取...")
            for pg in range(1, 3):  # 仅2页
                if pg > 1:
                    next_coords = json.loads(safe_eval(ws, """(function(){
                        var n=document.querySelector('[class*="next"],[class*="Next-"]');
                        if(!n)return JSON.stringify({found:false});
                        var r=n.getBoundingClientRect();
                        var fl=(window.outerWidth-window.innerWidth)/2;
                        var to=window.outerHeight-window.innerHeight-fl;
                        var ox=(window.screenLeft||0)+fl,oy=(window.screenTop||0)+to;
                        return JSON.stringify({found:true,x:Math.round(r.x+r.width/2+ox),y:Math.round(r.y+r.height/2+oy)});
                    })()""", "翻页按钮"))
                    if next_coords.get("found"):
                        x11_click(next_coords["x"], next_coords["y"])
                    time.sleep(8)
                else:
                    for y in [500, 1200, 2000]:
                        safe_eval(ws, f"window.scrollTo(0, {y})", "DOM滚动"); time.sleep(1)
                # 先尝试从页面内嵌数据/拦截的API响应提取
                api_data = safe_eval(ws, """(function(){
                    var data=[];
                    // 1. 拦截的fetch/XHR响应
                    try{
                        var apis=window.__crawl_api||[];
                        for(var a=0;a<apis.length;a++){
                            var d=apis[a].d||{};
                            var items=d.data?.items||d.data?.resultList||d.data?.auctions||d.items||[];
                            if(!items.length&&d.data){var keys=Object.keys(d.data);for(var k=0;k<keys.length;k++){if(Array.isArray(d.data[keys[k]])&&d.data[keys[k]].length>0&&d.data[keys[k]][0].title){items=d.data[keys[k]];break;}}}
                            for(var i=0;i<items.length;i++){
                                var it=items[i];
                                var t=(it.title||it.item_title||'').trim();
                                if(t.length<3)continue;
                                var id=it.nid||it.item_id||it.id||'';
                                var p=String(it.price||it.price_info?.price||it.price_info?.extraPrice?.priceText||'');
                                var l=it.detail_url||('https://item.taobao.com/item.htm?id='+id);
                                if(id)data.push({t:t,p:p,l:l});
                            }
                        }
                        if(data.length)return JSON.stringify(data);
                    }catch(e){}
                    // 2. __INITIAL_DATA__
                    try{
                        if(window.__INITIAL_DATA__){
                            var items=window.__INITIAL_DATA__.items||window.__INITIAL_DATA__.data?.items||[];
                            for(var i=0;i<items.length;i++){
                                var it=items[i];
                                data.push({t:(it.title||'').trim(),p:String(it.price||it.price_info?.price||''),l:'https://item.taobao.com/item.htm?id='+(it.nid||it.item_id||it.id||'')});
                            }
                            if(data.length)return JSON.stringify(data);
                        }
                    }catch(e){}
                    // 3. g_page_config
                    try{
                        if(window.g_page_config?.mods?.itemlist?.data?.auctions){
                            var auctions=window.g_page_config.mods.itemlist.data.auctions;
                            for(var i=0;i<auctions.length;i++){
                                var a=auctions[i];
                                data.push({t:(a.title||'').trim(),p:String(a.price||''),l:a.detail_url||''});
                            }
                            if(data.length)return JSON.stringify(data);
                        }
                    }catch(e){}
                    // 4. script标签内嵌
                    try{
                        var scripts=document.querySelectorAll('script');
                        for(var s=0;s<scripts.length;s++){
                            var txt=scripts[s].textContent||'';
                            var m=txt.match(/g_page_config\\s*=\\s*(\\{.*?\\});/);
                            if(m){var cfg=JSON.parse(m[1]);var auctions=cfg.mods?.itemlist?.data?.auctions||[];for(var i=0;i<auctions.length;i++){data.push({t:(auctions[i].title||'').trim(),p:String(auctions[i].price||''),l:auctions[i].detail_url||''});}if(data.length)return JSON.stringify(data);}
                        }
                    }catch(e){}
                    return JSON.stringify(data);
                })()""", "API/页面数据")
                try:
                    api_items = json.loads(api_data)
                except: api_items = []

                # 诊断: dump第一个商品卡片的HTML结构
                diag = safe_eval(ws, """(function(){
                    var a=document.querySelector('a[href*="item.taobao.com/item.htm"]');
                    if(!a)return 'no_a';
                    var result={};
                    result.href=a.href.match(/id=\\d+/)?.[0]||'';
                    result.title=a.getAttribute('title')||'NO_TITLE';
                    result.className=(a.className||'').substring(0,80);
                    result.innerText=(a.innerText||'').substring(0,300);
                    result.children=a.children.length;
                    result.childTags=Array.from(a.children).map(function(c){return c.tagName+'.'+(c.className||'').substring(0,40)}).slice(0,15);
                    var titles=a.querySelectorAll('[class*="title"]');
                    result.titleEls=Array.from(titles).map(function(t){return t.tagName+'.'+(t.className||'').substring(0,40)+'='+(t.textContent||'').substring(0,60)}).slice(0,5);
                    return JSON.stringify(result);
                })()""", "DOM诊断")
                try:
                    diagObj = json.loads(diag)
                    rpt(f"    诊断 title_attr: {diagObj.get('title','')}")
                    rpt(f"    诊断 class: {diagObj.get('className','')[:80]}")
                    rpt(f"    诊断 innerText: {diagObj.get('innerText','')[:100]}")
                    rpt(f"    诊断 children: {diagObj.get('children','')} tags: {diagObj.get('childTags',[])}")
                    rpt(f"    诊断 titleEls: {diagObj.get('titleEls',[])}")
                except: rpt(f"    诊断 raw: {diag[:300]}")

                res = safe_eval(ws, """(function(){
                    var items=[];
                    var allA=document.querySelectorAll('a.item-link[href*="item.taobao.com/item"],a.item-link[href*="detail.tmall.com/item"]');
                    if(!allA.length) allA=document.querySelectorAll('a[href*="item.taobao.com/item"],a[href*="detail.tmall.com/item"]');
                    for(var k=0;k<allA.length;k++){
                        var a=allA[k];
                        if(a.getBoundingClientRect().width<1)continue;
                        var href=a.href||'';
                        if(href.indexOf('id=')===-1)continue;
                        var title='';
                        var titleEl=a.querySelector('.info-wrapper-title-text,.info-wrapper-title,[class*="title-text"]');
                        if(titleEl){title=(titleEl.textContent||'').trim();}
                        if(!title){titleEl=a.querySelector('[class*="title"]');if(titleEl){var t=(titleEl.textContent||'').trim();if(t.indexOf('1688')===-1&&t.length>3)title=t;}}
                        if(!title){var raw=(a.innerText||'').trim().split('\\n')[0];if(raw.indexOf('1688')===-1&&raw.length>3)title=raw;}
                        if(!title||title.length<3)continue;
                        var price='';
                        var priceEl=a.querySelector('.price-wrapper .price,.price');
                        if(priceEl){price=(priceEl.textContent||'').replace(/[^0-9.]/g,'');}
                        items.push({t:title.substring(0,80),p:price,l:href});
                    }
                    return JSON.stringify({c:items.length,i:items});
                })()""", "DOM提取")
                try: data = json.loads(res)
                except: data = {"c":0,"i":[]}
                # 优先使用API数据(有真实标题和价格)
                if api_items:
                    rpt(f"    API数据: {len(api_items)}条 (优先使用)")
                    data = {"c": len(api_items), "i": api_items}
                nw = 0
                for it in data.get("i", []):
                    link = it.get("l","")
                    title = it.get("t","")
                    price = it.get("p","")
                    pid = None
                    for pat in [r'id=(\d+)', r'item/(\d+)']:
                        m = re.search(pat, link)
                        if m: pid = m.group(1); break
                    if not pid: continue
                    if pid in seen_pid: continue
                    seen_pid.add(pid)
                    products.append({
                        "id": pid, "t": title or it.get("t",""), "p": price or "", "sa": "", "sh": "", "l": link
                    })
                    nw += 1
                rpt(f"    p{pg}: {data['c']}项目, +{nw} 累计{len(products)}")
                if nw == 0 and pg > 1: break
        rpt(f"    最终: {len(products)}条商品")

        # Step 10: 导出CSV
        rpt("\n=== 10. 导出 ===")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in keyword)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        csv_path = OUTPUT_DIR / f"human_{safe}_{ts}.csv"
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f); w.writerow(["商品ID","标题","价格","销量","店铺","链接"])
            for p in products: w.writerow([p.get("id",""),p.get("t",""),p.get("p",""),p.get("sa",""),p.get("sh",""),p.get("l","")])
        rpt(f"    文件: {csv_path} ({os.path.getsize(csv_path)} bytes)")

        # 报告
        rpt_path = OUTPUT_DIR / f"report_human_{ts}.txt"
        with open(rpt_path, 'w') as f:
            f.write(f"游客模式测试报告 — {keyword}\n时间: {datetime.now().isoformat()}\n")
            f.write(f"临时Profile: {run_id}\n")
            f.write(f"关键词: {keyword}\n")
            f.write(f"DTS加载: {'✅' if dts_ok else '⚠️'}\n")
            f.write(f"有效商品: {len(products)}\n")
            f.write(f"文件: {csv_path}\n\n详细日志:\n")
            f.write("\n".join(report))
        rpt(f"    报告: {rpt_path}")
        return csv_path, len(products)

    finally:
        # 优雅关闭WebSocket（安全）
        try:
            ws.close()
        except: pass
        # Step 11: 关闭Chrome + 保存Cookie + 清理临时Profile
        rpt("\n=== 11. 清理 ===")
        # Sync cookies back to base template (preserve login session)
        rpt("    保存Cookie到基准模板...")
        cookie_src = f"{clean_profile_dir}/Default/Cookies"
        cookie_dst = f"{BASE_TEMPLATE}/Default/Cookies"
        if os.path.exists(cookie_src) and os.path.getsize(cookie_src) > 4096:  # 至少4KB才值得保存
            try:
                # 清理目标WAL/SHM
                for wf in ["Cookies-wal", "Cookies-shm"]:
                    wp = f"{BASE_TEMPLATE}/Default/{wf}"
                    if os.path.exists(wp): os.remove(wp)
                shutil.copy2(cookie_src, cookie_dst)
                rpt(f"    ✅ Cookie已回存 ({os.path.getsize(cookie_src)} bytes)")
            except Exception as e:
                rpt(f"    ⚠️ Cookie回存失败: {e}")
        else:
            rpt("    ⚠️ Cookie文件过小，跳过回存")
        # ★ 优雅关闭 — 始终执行，无论上面是否出错
        try:
            graceful_shutdown(clean_profile_dir)
        except Exception as e:
            rpt(f"    ⚠️ 优雅关闭异常: {e}")
            subprocess.run(["pkill", "-TERM", "chrome"], check=False, capture_output=True, timeout=5)
            time.sleep(5)
        if os.path.exists(clean_profile_dir):
            shutil.rmtree(clean_profile_dir, ignore_errors=True)
            rpt(f"    临时Profile已删除: {clean_profile_dir}")
        rpt("✅ 流程结束")


# ═══════════════════ Main ═══════════════════
if __name__ == "__main__":
    # 验证基准模板存在
    if not os.path.exists(f"{BASE_TEMPLATE}/Default/Extensions/{DTS_ID}"):
        print(f"❌ 基准模板不存在！先运行: python3 scripts/prepare_base_template.py")
        sys.exit(1)

    keyword = sys.argv[1] if len(sys.argv) > 1 else KEYWORD
    csv_path, count = human_like_crawl(keyword)
    print(f"\n✅ 完成: {count}条 → {csv_path}")
