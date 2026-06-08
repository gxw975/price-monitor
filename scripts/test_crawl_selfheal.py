#!/usr/bin/env python3
"""全流程自闭环抓取测试 — 蒙牛一米八八益生菌

特性：
- DTS扩展自修复（Singleton清理 + chrome://extensions/校验）
- 固定7项Chrome参数
- 分步页面校验
- 滑块：python-xlib XTest
- 浏览器关闭：CDP批量关→TERM→KILL兜底
"""

import json, logging, os, re, shutil, signal, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────
KEYWORD = "蒙牛一米八八益生菌"
CHROME_BIN = "/usr/bin/google-chrome-stable"
CHROME_USER_DATA = "/home/lab-admin/.config/google-chrome-profile-manual"
CDP_HOST = "127.0.0.1"
CDP_PORT = 9223
DISPLAY = ":0"
XAUTH = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
DOWNLOAD_DIR = Path("/home/lab-admin/Downloads")
OUTPUT_DIR = Path("/home/lab-admin/price-monitor/data/downloads")
DTS_EXT_ID = "ppgdlgnehnajbbngnohepfigdmjbdpfb"
REPORT_FILE = Path(f"/home/lab-admin/price-monitor/data/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("test_crawl")

report_lines: list[str] = []
def report(msg: str) -> None:
    logger.info(msg)
    report_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ── Utility ──────────────────────────────────────────────────
def _cdp_cmd(ws, method, params=None, timeout=15):
    """Send CDP command."""
    msg = {"id": int(time.time()*1000)%1000000, "method": method}
    if params: msg["params"] = params
    ws.send(json.dumps(msg))
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = ws.recv()
        resp = json.loads(raw)
        if resp.get("id") == msg["id"]:
            return resp
    raise TimeoutError(f"CDP timeout: {method}")

def _cdp_connect(url_hint=""):
    """Connect to a Chrome page via CDP."""
    import websocket
    for attempt in range(10):
        try:
            resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5)
            targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]
            target = None
            if url_hint:
                for p in pages:
                    if url_hint in p.get("url", ""): target = p; break
            if not target:
                for p in pages:
                    if "about:blank" in p.get("url", ""): target = p; break
            if not target and pages: target = pages[0]
            if not target:
                time.sleep(2); continue
            ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=15, origin="")
            _cdp_cmd(ws, "Page.enable")
            _cdp_cmd(ws, "Runtime.enable")
            return ws, target
        except Exception:
            time.sleep(2)
    return None, None

def _cdp_eval(ws, js):
    r = _cdp_cmd(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))


# ── Phase 0: Cleanup & Chrome Start ──────────────────────────
def cleanup_and_start_chrome():
    """Graceful shutdown + clean start with exact 7 params."""
    report("=== Phase 0: Chrome 环境准备 ===")

    # 1. Clean shutdown
    report("Step 0.1: 优雅关闭旧Chrome...")
    try:
        ws, _ = _cdp_connect()
        if ws:
            pages = json.loads(urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json").read())
            for t in pages:
                if t.get("type") == "page":
                    try:
                        import websocket as _ws
                        pw = _ws.create_connection(t["webSocketDebuggerUrl"], timeout=5, origin="")
                        pw.send(json.dumps({"id":1,"method":"Page.close"}))
                        pw.recv(); pw.close()
                    except: pass
            ws.close()
    except: pass
    time.sleep(2)

    subprocess.run(["pkill", "-TERM", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
    time.sleep(3)
    if subprocess.run(["pgrep", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True).returncode == 0:
        report("  有残留进程，pkill -KILL 兜底")
        subprocess.run(["pkill", "-KILL", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
        time.sleep(2)

    # 2. Clean Singleton & SW cache
    report("Step 0.2: 清理Singleton锁和SW缓存...")
    ud = Path(CHROME_USER_DATA)
    for f in ud.rglob("SingletonLock*"): f.unlink(missing_ok=True)
    for f in ud.rglob("SingletonSocket*"): f.unlink(missing_ok=True)
    for f in ud.rglob("SingletonCookie*"): f.unlink(missing_ok=True)
    # Clean Service Worker caches that may prevent extension loading
    sw_dir = ud / "Default" / "Service Worker"
    if sw_dir.exists(): shutil.rmtree(sw_dir, ignore_errors=True)
    # Clean extension state cache
    for d in ud.rglob("Extension State"): shutil.rmtree(d, ignore_errors=True)

    # 3. Fix DTS extension registration in Secure Preferences
    report("Step 0.3: 修复DTS扩展注册...")
    _ensure_dts_registered(ud)

    # 4. Start Chrome with exact 7 params
    report("Step 0.4: 启动Chrome (7项固定参数)...")
    # DTS extension path (must be loaded via --load-extension to register)
    dts_ext_path = "/home/lab-admin/chrome-user-data/Default/Extensions/ppgdlgnehnajbbngnohepfigdmjbdpfb/5.0.6_0"
    cmd = [
        CHROME_BIN,
        f"--user-data-dir={CHROME_USER_DATA}",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--remote-debugging-port=9223",
        "--remote-allow-origins=*",
        "--start-maximized",
        "--ozone-platform=x11",
        f"--load-extension={dts_ext_path}",
    ]
    proc = subprocess.Popen(cmd, env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(8)

    # Verify CDP
    for i in range(20):
        try:
            urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json/version", timeout=3)
            report(f"  Chrome CDP ready (PID={proc.pid})")
            return proc
        except:
            time.sleep(1)
    report("  ❌ Chrome启动失败")
    return None


def _ensure_dts_registered(ud: Path):
    """确保DTS扩展在Chrome中注册。"""
    prefs_file = ud / "Default" / "Preferences"
    if not prefs_file.exists():
        report("  Preferences不存在，跳过DTS注册修复")
        return

    try:
        with open(prefs_file, 'r') as f:
            prefs = json.load(f)

        ext_settings = prefs.get("extensions", {}).get("settings", {})
        dts_key = None
        for k in ext_settings:
            if DTS_EXT_ID in k:
                dts_key = k
                break

        if dts_key:
            cfg = ext_settings[dts_key]
            if cfg.get("state") != 1:
                cfg["state"] = 1  # ENABLED
                with open(prefs_file, 'w') as f:
                    json.dump(prefs, f, indent=2)
                report(f"  DTS扩展已启用: state=1")
            else:
                report(f"  DTS扩展已注册且启用")
        else:
            report("  DTS扩展未在Preferences中注册，将在Chrome启动后校验")
    except Exception as e:
        report(f"  Preferences修复异常: {e}")


# ── Phase 1: DTS Extension Verification ──────────────────────
def verify_dts():
    """访问 chrome://extensions/ 校验DTS状态。"""
    report("\n=== Phase 1: DTS扩展校验 ===")
    ws, target = _cdp_connect()
    if not ws:
        report("  ❌ CDP连接失败")
        return False

    # Navigate to extensions page
    _cdp_cmd(ws, "Page.navigate", {"url": "chrome://extensions/"})
    time.sleep(4)

    # Check DTS via management API (try both get and getAll)
    result = _cdp_eval(ws, f"""
    (function() {{
        return new Promise((resolve) => {{
            chrome.management.getAll(function(exts) {{
                for (var i=0;i<exts.length;i++) {{
                    if (exts[i].id === '{DTS_EXT_ID}') {{
                        resolve(JSON.stringify({{name: exts[i].name, enabled: exts[i].enabled, type: exts[i].type}}));
                        return;
                    }}
                }}
                resolve(JSON.stringify({{error: 'not found in installed extensions (total: '+exts.length+')'}}));
            }});
        }});
    }})()
    """)
    report(f"  DTS getAll: {result[:200]}")

    try: info = json.loads(result) if result.startswith('{') else {}
    except: info = {}

    if info.get("enabled"):
        report(f"  ✅ DTS扩展已启用: {info.get('name','?')}")
    elif info.get("error"):
        report(f"  ⚠️ {info['error']}")

    # Also check Service Worker
    resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json")
    targets = json.loads(resp.read())
    sw_found = False
    for t in targets:
        if DTS_EXT_ID in t.get("url", ""):
            report(f"  ✅ DTS Service Worker: {t.get('type')} running")
            sw_found = True
            break

    if not sw_found:
        report("  ⚠️ DTS Service Worker未运行")

    # Check if DTS icon appears by looking for extension in toolbar
    # (indirect - check if any page target has DTS iframe)
    for t in targets:
        if "diantoushi.com" in t.get("url", ""):
            report("  ✅ DTS iframe detected in page targets")
            sw_found = True
            break

    ws.close()
    return sw_found or info.get("enabled", False)


# ── Phase 2-10: Full Crawl Flow ──────────────────────────────
class CrawlRunner:
    def __init__(self):
        self.ws = None
        self.step_results = {}

    def connect(self, url_hint=""):
        self.ws, _ = _cdp_connect(url_hint)
        if not self.ws:
            raise RuntimeError("CDP连接失败")
        _cdp_cmd(self.ws, "Browser.setDownloadBehavior",
                  {"behavior": "allow", "downloadPath": str(DOWNLOAD_DIR), "eventsEnabled": True})

    def disconnect(self):
        if self.ws:
            try: self.ws.close()
            except: pass
            self.ws = None

    def verify_step(self, step_name, check_js, expected):
        """页面校验：执行JS，检查是否符合预期。失败重试1次。"""
        for attempt in range(2):
            try:
                result = _cdp_eval(self.ws, check_js)
                if expected in result or result == expected:
                    self.step_results[step_name] = "✅"
                    return True
                if attempt == 0:
                    report(f"  [{step_name}] 校验失败(result={result[:80]})，重试...")
                    time.sleep(3)
            except Exception as e:
                if attempt == 0:
                    report(f"  [{step_name}] 异常({e})，重试...")
                    time.sleep(3)
        self.step_results[step_name] = "❌"
        report(f"  ❌ [{step_name}] 校验失败，终止任务")
        return False

    # ── Slider Captcha (python-xlib) ──
    def solve_captcha(self):
        """python-xlib XTest slider solve."""
        import random as rng, math
        from Xlib import X, display as xdisplay
        from Xlib.ext import xtest as xext

        report("  检测到滑块验证，python-xlib求解...")
        disp = xdisplay.Display()
        xt = xext

        # Get slider coords via CDP frameTree + isolatedWorld
        try:
            ft_resp = _cdp_cmd(self.ws, "Page.getFrameTree")
            frame_tree = ft_resp.get("result", {}).get("frameTree", {})

            punish_fid = None
            def find_punish(node):
                nonlocal punish_fid
                for c in node.get("childFrames", []):
                    f = c.get("frame", {})
                    if "h5api.m.taobao.com" in f.get("url","") and "punish" in f.get("url",""):
                        punish_fid = f.get("id",""); return
                    find_punish(c)
            find_punish(frame_tree)
            if not punish_fid: return False

            iso = _cdp_cmd(self.ws, "Page.createIsolatedWorld", {"frameId": punish_fid})
            ctx = iso.get("result",{}).get("executionContextId")
            if not ctx: return False
            time.sleep(0.2)

            r = _cdp_cmd(self.ws, "Runtime.evaluate", {
                "expression": """(function(){
                    var s=document.querySelector('[id*="nc_1_n1z"]');
                    var t=document.querySelector('[id*="nc_1__scale_text"]');
                    if(!s||!t)return JSON.stringify({found:false});
                    var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();
                    return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});
                })()""", "contextId": ctx, "returnByValue": True})
            data = json.loads(r.get("result",{}).get("result",{}).get("value","{}"))
            if not data.get("found"): return False

            # Calculate screen position
            iframe_pos = _cdp_eval(self.ws, """(function(){
                var fs=document.querySelectorAll('iframe');
                for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}
                return '{}';
            })()""")
            ip = json.loads(iframe_pos) if iframe_pos else {}
            OX, OY = 66, 119
            sx = ip.get("x",397) + data["sx"] + OX
            sy = ip.get("y",181) + data["sy"] + OY
            dist = data["dist"] + rng.randint(-3, 5)

            report(f"  拖拽: screen({sx},{sy}) dist={dist}")

            def mov(x,y): xt.fake_input(disp, X.MotionNotify, x=int(x), y=int(y)); disp.sync()

            # Approach
            ax, ay = sx - rng.randint(60,120), sy + rng.randint(-10,10)
            for i in range(rng.randint(3,6)):
                p = (i+1)/6; mov(int(ax+(sx-ax)*p), int(ay+(sy-ay)*p))
                time.sleep(0.015+rng.random()*0.025)

            mov(sx, sy); time.sleep(0.06+rng.random()*0.05)

            # Press
            xt.fake_input(disp, X.ButtonPress, detail=1); disp.sync()
            time.sleep(0.025+rng.random()*0.03)

            # Drag: 320-356点, 3.3-3.6s
            n_points = rng.randint(320, 356)
            total_s = 3.3 + rng.random() * 0.3
            for i in range(n_points):
                p = i / n_points
                eased = 1 - (1-p)**rng.uniform(1.6, 2.8)
                x = int(sx + dist * eased)
                y = sy + int(math.sin(p*math.pi*4)*rng.randint(1,4))
                if p > 0.85: y = sy + rng.randint(-1,1)
                mov(x, y)
                time.sleep(total_s/n_points * (0.8+rng.random()*0.4))

            time.sleep(0.05+rng.random()*0.04)
            xt.fake_input(disp, X.ButtonRelease, detail=1); disp.sync()
            disp.close()
            time.sleep(6)
            return True
        except Exception as e:
            report(f"  滑块求解异常: {e}")
            return False

    # ── DTS click via xdotool ──
    def xdotool_click(self, x, y):
        subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))],
                       env=os.environ, capture_output=True, timeout=10)
        time.sleep(0.15)
        subprocess.run(["xdotool", "click", "1"],
                       env=os.environ, capture_output=True, timeout=10)

    def xdotool_click_element(self, js_selector_center):
        """Find element center via CDP, then xdotool click at screen coords."""
        result = _cdp_eval(self.ws, js_selector_center)
        try:
            info = json.loads(result)
        except:
            return False
        if not info.get("found"): return False
        sx, sy = info["sx"], info["sy"]
        self.xdotool_click(sx, sy)
        return True

    # ── Main Flow ──
    def run(self):
        report("\n=== Phase 2-10: 全链路抓取 ===")

        # Step 2: Taobao homepage
        report("\n[Step 2] 打开淘宝首页...")
        self.connect()
        _cdp_cmd(self.ws, "Page.navigate", {"url": "https://www.taobao.com"})
        time.sleep(6)
        if not self.verify_step("淘宝首页", "JSON.stringify({t:document.title})", "淘宝"):
            return False

        # Check login
        login_info = _cdp_eval(self.ws, """(function(){
            var b=document.body?.innerText||'';
            var u=document.querySelector('.site-nav-user .nickname,.site-nav-login-info-nick');
            return JSON.stringify({loggedIn:!!u||b.indexOf('我的淘宝')!==-1,user:u?u.textContent.trim():''});
        })()""")
        report(f"  登录态: {login_info}")

        # Step 3: Search keyword
        report(f"\n[Step 3] 搜索关键词: {KEYWORD}...")
        # xdotool click search box
        self.xdotool_click_element("""(function(){
            var q=document.getElementById('q');if(!q)return JSON.stringify({found:false});
            var r=q.getBoundingClientRect();
            var fl=(window.outerWidth-window.innerWidth)/2;
            var to=window.outerHeight-window.innerHeight-fl;
            return JSON.stringify({found:true,sx:Math.round(r.x+r.width/2+(window.screenLeft||0)+fl),sy:Math.round(r.y+r.height/2+(window.screenTop||0)+to)});
        })()""")
        time.sleep(1)
        # xdotool type keyword
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "50", KEYWORD],
                       env=os.environ, capture_output=True, timeout=30)
        time.sleep(1)
        # Enter
        subprocess.run(["xdotool", "key", "Return"], env=os.environ, capture_output=True, timeout=10)
        time.sleep(6)

        if not self.verify_step("搜索结果页", "JSON.stringify({u:window.location.href})", "s.taobao.com"):
            # Direct navigate fallback
            report("  直接导航到搜索URL...")
            _cdp_cmd(self.ws, "Page.navigate", {"url": f"https://s.taobao.com/search?q={urllib.parse.quote(KEYWORD)}"})
            time.sleep(6)

        # Step 3.5: Captcha handling
        report("\n[Step 3.5] 滑块验证检测...")
        captcha_count = 0
        for attempt in range(5):
            has_captcha = _cdp_eval(self.ws, """(function(){
                var fs=document.querySelectorAll('iframe');
                for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('punish')!==-1&&fs[i].getBoundingClientRect().width>0)return'true';}
                return'false';
            })()""")
            if has_captcha == "false":
                report(f"  无滑块，或已通过 (attempt={attempt+1})")
                break
            captcha_count += 1
            report(f"  尝试求解 #{captcha_count}...")
            if not self.solve_captcha():
                if attempt == 4:
                    report("  ❌ 滑块求解失败")
                    return False

        report(f"  滑块执行次数: {captcha_count}, 最终状态: {'通过' if captcha_count < 5 else '失败'}")

        # Step 4: Search results verify
        report("\n[Step 4] 搜索结果渲染校验...")
        cards = _cdp_eval(self.ws, "document.querySelectorAll('[class*=\"Card--\"]').length")
        bones = _cdp_eval(self.ws, "document.querySelectorAll('[class*=\"bone\"]').length")
        report(f"  Cards: {cards}, Bones: {bones}")

        # Step 5: DTS activation
        report("\n[Step 5] 唤起DTS插件...")
        # Scroll to make DTS toolbar visible
        _cdp_eval(self.ws, "window.scrollTo(0,0)")
        time.sleep(2)
        # Trigger DTS
        _cdp_eval(self.ws, """(function(){
            var btn=document.querySelector('[class*=\"dts-float\"]');if(btn)btn.click();
            document.dispatchEvent(new CustomEvent('dts-search-trigger'));
        })()""")
        time.sleep(3)

        dts_visible = _cdp_eval(self.ws, """(function(){
            var body=document.body?.innerText||'';
            return JSON.stringify({ma:body.indexOf('市场分析')!==-1,export:body.indexOf('导出表格')!==-1});
        })()""")
        report(f"  DTS工具栏: {dts_visible}")

        if "false" in dts_visible or '-1' in dts_visible:
            report("  ❌ DTS工具栏未出现，终止")
            return False

        # Step 6: Clear cache
        report("\n[Step 6] 清理缓存...")
        self.xdotool_click_element("""(function(){
            var all=document.querySelectorAll('*');
            for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim();if(t.indexOf('清理缓存')!==-1&&all[i].offsetHeight>0){var r=all[i].getBoundingClientRect();var fl=(window.outerWidth-window.innerWidth)/2;return JSON.stringify({found:true,sx:Math.round(r.x+r.width/2+(window.screenLeft||0)+fl),sy:Math.round(r.y+r.height/2+(window.screenTop||0)+(window.outerHeight-window.innerHeight-fl))});}}
            return JSON.stringify({found:false});
        })()""")
        time.sleep(3)
        report("  缓存清理完成")

        # Step 7: Market Analysis
        report("\n[Step 7] 点击市场分析...")
        for _ in range(2):
            clicked = self.xdotool_click_element("""(function(){
                var el=document.querySelector('.itemToolsBox .item-value,.item-value');
                if(!el)return JSON.stringify({found:false});
                var r=el.getBoundingClientRect();
                var fl=(window.outerWidth-window.innerWidth)/2,to=window.outerHeight-window.innerHeight-fl;
                return JSON.stringify({found:true,sx:Math.round(r.x+r.width/2+(window.screenLeft||0)+fl),sy:Math.round(r.y+r.height/2+(window.screenTop||0)+to)});
            })()""")
            if clicked: break
            time.sleep(2)

        time.sleep(5)
        panel_state = _cdp_eval(self.ws, """(function(){
            var b=document.body?.innerText||'';
            return JSON.stringify({hasStart:b.indexOf('开始分析')!==-1,hasSort:b.indexOf('综合排序')!==-1,len:b.length});
        })()""")
        report(f"  市场分析面板: {panel_state}")

        # Step 8: Start Analysis
        report("\n[Step 8] 点击开始分析...")
        self.xdotool_click_element("""(function(){
            var btn=document.querySelector('button.el-button--primary');
            if(!btn)return JSON.stringify({found:false});
            var r=btn.getBoundingClientRect();
            var fl=(window.outerWidth-window.innerWidth)/2,to=window.outerHeight-window.innerHeight-fl;
            return JSON.stringify({found:true,sx:Math.round(r.x+r.width/2+(window.screenLeft||0)+fl),sy:Math.round(r.y+r.height/2+(window.screenTop||0)+to)});
        })()""")
        time.sleep(10)

        # Step 9: Auto-load × 8 rounds
        report("\n[Step 9] 8轮自动加载...")
        total_loaded = 0
        for round_num in range(1, 9):
            report(f"  第{round_num}/8轮...")
            # Find and click load button
            btn_found = _cdp_eval(self.ws, """(function(){
                var all=document.querySelectorAll('*');
                for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim();if((t.indexOf('加载下一页')!==-1||t.indexOf('自动加载')!==-1)&&all[i].offsetHeight>0&&!all[i].disabled){all[i].click();return'clicked';}}
                return'not_found';
            })()""")
            if btn_found == "not_found":
                report(f"  第{round_num}轮: 加载按钮已消失，提前结束")
                break
            total_loaded += 1
            time.sleep(30)

        report(f"  自动加载完成: {total_loaded}轮")

        # Step 10: Pause 315s
        report("\n[Step 10] 满载静置315秒...")
        time.sleep(315)

        # Step 11: Export
        report("\n[Step 11] 全选+导出...")
        _cdp_eval(self.ws, """(function(){
            var all=document.querySelectorAll('*');
            for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim();if(t==='全选'&&all[i].offsetHeight>0){all[i].click();return;}}
        })()""")
        time.sleep(2)

        _cdp_eval(self.ws, """(function(){
            var all=document.querySelectorAll('*');
            for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim();if(t==='导出表格'&&all[i].offsetHeight>0){all[i].click();return;}}
        })()""")
        time.sleep(3)

        # Select xlsx option
        _cdp_eval(self.ws, """(function(){
            var all=document.querySelectorAll('*');
            for(var i=0;i<all.length;i++){var t=(all[i].textContent||'').trim().toLowerCase();if(t.indexOf('xlsx')!==-1&&all[i].offsetHeight>0){all[i].click();return;}}
        })()""")

        # Wait for download
        report("\n  等待xlsx下载...")
        before = set(DOWNLOAD_DIR.glob("*.xlsx"))
        xlsx_path = None
        for i in range(120):
            time.sleep(2)
            current = set(DOWNLOAD_DIR.glob("*.xlsx"))
            new = current - before
            if not new:
                new = {f for f in current if time.time()-f.stat().st_mtime<120 and f.stat().st_size>1000}
            if new:
                newest = max(new, key=lambda f: f.stat().st_mtime)
                xlsx_path = str(newest)
                report(f"  ✅ 文件下载: {xlsx_path}")
                break
            if i % 20 == 0:
                report(f"  等待中... ({i*2}s)")

        if not xlsx_path:
            report("  ❌ 未检测到下载文件")

        # Count products in xlsx
        if xlsx_path:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(xlsx_path, read_only=True)
                count = wb.active.max_row - 1
                wb.close()
                report(f"  有效商品数: {count}")
            except:
                count = -1

        return xlsx_path, count if xlsx_path else 0


# ── Main ──────────────────────────────────────────────────────
def main():
    report("="*60)
    report(f"全流程自闭环抓取测试 — {KEYWORD}")
    report(f"开始时间: {datetime.now().isoformat()}")
    report("="*60)

    # Phase 0
    proc = cleanup_and_start_chrome()
    if not proc:
        report("❌ Chrome启动失败，终止测试")
        _write_report()
        return 1

    # Phase 1
    dts_ok = verify_dts()
    report(f"\nDTS加载状态: {'✅ 正常' if dts_ok else '❌ 异常'}")

    if not dts_ok:
        report("❌ DTS未就绪，终止测试")
        _cleanup_chrome(proc)
        _write_report()
        return 1

    # Phase 2-10
    runner = CrawlRunner()
    try:
        result = runner.run()
        if result:
            xlsx_path, count = result
            report(f"\n✅ 抓取成功! 商品数: {count}, 文件: {xlsx_path}")
        else:
            report(f"\n❌ 抓取失败")
    except Exception as e:
        report(f"\n❌ 异常: {e}")
    finally:
        runner.disconnect()

    # Cleanup
    _cleanup_chrome(proc)
    _write_report()
    return 0


def _cleanup_chrome(proc):
    report("\n=== Chrome关闭 ===")
    try:
        resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json")
        for t in json.loads(resp.read()):
            if t.get("type") == "page":
                try:
                    import websocket
                    ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=5, origin="")
                    ws.send(json.dumps({"id":1,"method":"Page.close"})); ws.recv(); ws.close()
                except: pass
    except: pass
    report("  CDP批量关闭标签完成")
    time.sleep(2)

    subprocess.run(["pkill", "-TERM", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
    time.sleep(3)
    if subprocess.run(["pgrep", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True).returncode == 0:
        report("  TERM未完全关闭，KILL兜底")
        subprocess.run(["pkill", "-KILL", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
    report("  Chrome已关闭")


def _write_report():
    report("\n" + "="*60)
    report("测试报告结束")
    with open(REPORT_FILE, 'w') as f:
        f.write("\n".join(report_lines))
    print(f"\n报告已保存: {REPORT_FILE}")


if __name__ == "__main__":
    sys.exit(main())
