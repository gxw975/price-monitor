#!/usr/bin/env python3
"""v2 全流程自闭环 — 事件驱动滑块等待 + python-xlib 拖拽

核心改进：三层递进轮询等待滑块DOM完全挂载，替换固定time.sleep()
"""

import csv, json, logging, math, os, random, signal, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path

KEYWORD = "蒙牛一米八八益生菌"
CHROME_BIN = "/usr/bin/google-chrome-stable"
CHROME_USER_DATA = "/home/lab-admin/.config/google-chrome-profile-manual"
CDP_PORT = 9223
DISPLAY = ":0"
XAUTH = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
OUTPUT_DIR = Path("/home/lab-admin/price-monitor/data/downloads")
OX, OY = 66, 119

os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("test")

report = []
def rpt(msg):
    logger.info(msg); report.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ═══════════════════════════════════════════════════════════════
# CDP helpers
# ═══════════════════════════════════════════════════════════════

def cdp_cmd(ws, method, params=None, t=15):
    msg = {"id": int(time.time()*1000)%1000000, "method": method}
    if params: msg["params"] = params
    ws.send(json.dumps(msg))
    dl = time.time() + t
    while time.time() < dl:
        raw = ws.recv(); resp = json.loads(raw)
        if resp.get("id") == msg["id"]: return resp
    raise TimeoutError(method)

def cdp_eval(ws, js):
    r = cdp_cmd(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))

def cdp_eval_ctx(ws, ctx_id, js):
    """Evaluate in a specific execution context (isolated world)."""
    r = cdp_cmd(ws, "Runtime.evaluate", {"expression": js, "contextId": ctx_id, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))

def cdp_connect():
    import websocket
    for _ in range(10):
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=5)
            pages = [t for t in json.loads(resp.read()) if t.get("type") == "page"]
            for p in pages:
                if "about:blank" in p.get("url",""):
                    ws = websocket.create_connection(p["webSocketDebuggerUrl"], timeout=15, origin="")
                    cdp_cmd(ws, "Page.enable"); cdp_cmd(ws, "Runtime.enable")
                    return ws
            if pages:
                ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=15, origin="")
                cdp_cmd(ws, "Page.enable"); cdp_cmd(ws, "Runtime.enable")
                return ws
        except: time.sleep(2)
    return None


# ═══════════════════════════════════════════════════════════════
# 三层递进事件驱动滑块等待 (CDP版)
# ═══════════════════════════════════════════════════════════════

def wait_for_slider_ready(ws, timeout=30) -> tuple:
    """三层递进轮询等待滑块DOM完全挂载。

    层1: 检测h5api iframe是否存在
    层2: 获取iframe执行上下文
    层3: 循环检测滑块元素真正挂载（可见+可点击）

    Returns:
        (ctx_id, slider_data) 或 (None, None)
    """
    start_time = time.time()
    last_log = 0

    while time.time() - start_time < timeout:
        # ── 层1: 检测h5api iframe ──
        ft = cdp_cmd(ws, "Page.getFrameTree")
        tree = ft.get("result",{}).get("frameTree",{})

        h5fid = None
        def find_h5(node):
            nonlocal h5fid
            for c in node.get("childFrames",[]):
                u = c.get("frame",{}).get("url","")
                if "h5api.m.taobao.com" in u:
                    h5fid = c.get("frame",{}).get("id",""); return
                find_h5(c)
        find_h5(tree)

        # Periodic logging
        elapsed = int(time.time() - start_time)
        if elapsed - last_log >= 5:
            rpt(f"  层1轮询: {elapsed}s, h5api frame={'found' if h5fid else 'NOT found'}")
            last_log = elapsed

        if not h5fid:
            time.sleep(0.5)
            continue

        # ── 层2: 获取iframe执行上下文 ──
        try:
            iso = cdp_cmd(ws, "Page.createIsolatedWorld", {"frameId": h5fid})
            ctx = iso.get("result",{}).get("executionContextId")
            if not ctx:
                time.sleep(0.5)
                continue
        except Exception:
            time.sleep(0.5)
            continue

        # ── 层3: 循环检测滑块元素真正挂载（最多50次=10秒）──
        for _ in range(50):
            try:
                # 非抛异常方式：用 querySelectorAll 返回数组
                result = cdp_eval_ctx(ctx, """
                (function(){
                    var sliders = document.querySelectorAll('#nc_1_n1z');
                    return sliders.length;
                })()
                """)

                if result not in ("0", "undefined", "null", ""):
                    count = int(result)
                    if count > 0:
                        # 额外验证：滑块可见且可点击
                        is_visible = cdp_eval_ctx(ctx, """
                        (function(){
                            var slider = document.querySelector('#nc_1_n1z');
                            if (!slider) return 'false';
                            var visible = slider.offsetParent !== null && slider.getBoundingClientRect().width > 0;
                            return visible ? 'true' : 'false';
                        })()
                        """)

                        if is_visible == "true":
                            # 滑块已就绪，读取坐标
                            coords = cdp_eval_ctx(ctx, """(function(){
                                var s = document.querySelector('#nc_1_n1z');
                                var t = document.querySelector('#nc_1__scale_text');
                                if(!s||!t)return JSON.stringify({found:false});
                                var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();
                                return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});
                            })()""")
                            try:
                                data = json.loads(coords)
                                if data.get("found"):
                                    rpt("  ✅ 滑块就绪 (3层递进通过)")
                                    return ctx, data
                            except: pass
            except Exception:
                pass

            time.sleep(0.2)

        # 当前iframe没就绪，等0.5s重新获取
        time.sleep(0.5)

    rpt("  ⚠️ 滑块等待超时")
    return None, None


# ═══════════════════════════════════════════════════════════════
# python-xlib 滑块拖拽
# ═══════════════════════════════════════════════════════════════

def drag_slider_xlib(ws, ctx, slider_data):
    """使用python-xlib XTest执行滑块拖拽。"""
    from Xlib import X, display as xd
    from Xlib.ext import xtest as xt

    try:
        # 获取iframe在主页面中的视口位置
        ipos = cdp_eval(ws, """(function(){
            var fs=document.querySelectorAll('iframe');
            for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}
            return '{}';
        })()""")
        ip = json.loads(ipos)
        sx = ip.get("x",397) + slider_data["sx"] + OX
        sy = ip.get("y",181) + slider_data["sy"] + OY
        dist = slider_data["dist"] + random.randint(-3, 5)

        rpt(f"  X11拖拽: screen({sx},{sy}) dist={dist}")

        disp = xd.Display()
        def mov(x,y): xt.fake_input(disp, X.MotionNotify, x=int(x), y=int(y)); disp.sync()

        # Approach
        ax,ay = sx-random.randint(60,120), sy+random.randint(-10,10)
        for i in range(5):
            p=(i+1)/5; mov(int(ax+(sx-ax)*p), int(ay+(sy-ay)*p))
            time.sleep(0.015+random.random()*0.02)

        mov(sx,sy); time.sleep(0.06+random.random()*0.05)
        xt.fake_input(disp, X.ButtonPress, detail=1); disp.sync()
        time.sleep(0.025+random.random()*0.03)

        # 320-356点, 3.3-3.6s正弦曲线
        n = random.randint(320, 356)
        dur = 3.3 + random.random() * 0.3
        for i in range(n):
            p = i/n
            e = 1 - (1-p)**random.uniform(1.6,2.8)
            x = int(sx + dist * e)
            y = sy + int(math.sin(p*math.pi*4)*random.randint(1,4))
            if p > 0.85: y = sy + random.randint(-1,1)
            mov(x, y)
            time.sleep(dur/n * (0.8+random.random()*0.4))

        time.sleep(0.05+random.random()*0.04)
        xt.fake_input(disp, X.ButtonRelease, detail=1); disp.sync()
        disp.close()

        # 等待验证结果
        time.sleep(6)
        return True
    except Exception as e:
        rpt(f"  ❌ X11拖拽异常: {e}")
        return False


def captcha_still_present(ws):
    """检查滑块是否还在。"""
    try:
        ft = cdp_cmd(ws, "Page.getFrameTree")
        tree = ft.get("result",{}).get("frameTree",{})
        def check(node):
            for c in node.get("childFrames",[]):
                u = c.get("frame",{}).get("url","")
                if "h5api.m.taobao.com" in u:
                    # 还需检查iframe是否可见
                    visible = cdp_eval(ws, """(function(){
                        var fs=document.querySelectorAll('iframe');
                        for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1&&fs[i].getBoundingClientRect().width>0)return'true';}
                        return'false';
                    })()""")
                    return visible == "true"
                if check(c): return True
            return False
        return check(tree)
    except:
        return True  # 不确定时保守返回True



# ═══════════════════════════════════════════════════════════════
# 商品提取
# ═══════════════════════════════════════════════════════════════

def extract_products(ws, max_items=500):
    """提取商品卡片，使用新版正则 [?&]id=(\\d{13}) 匹配13位商品ID。"""
    products = []; seen = set()
    for page in range(1, 8):
        if page > 1:
            cdp_cmd(ws, "Page.navigate", {"url": f"https://s.taobao.com/search?page={page}&q={urllib.parse.quote(KEYWORD)}"})
            time.sleep(5)
        for y in [500, 1200, 2000]:
            cdp_eval(ws, f"window.scrollTo(0, {y})"); time.sleep(1)

        # JS提取（保持已验证可用的选择器，仅扩充链接选择器覆盖天猫）
        result = cdp_eval(ws, """(function(){
            var p=[];var cards=document.querySelectorAll('[class*="Card--doubleCardWrapper"]');
            if(!cards.length)cards=document.querySelectorAll('.doubleCardWrapper--');
            var wrappers=[];if(cards.length)wrappers=cards[0].querySelectorAll('[class*="Content--"]');
            if(!wrappers.length)wrappers=document.querySelectorAll('[class*="Content--"]');
            for(var i=0;i<wrappers.length;i++){var w=wrappers[i];
                var t=w.querySelector('[class*="Title--"]'),pr=w.querySelector('[class*="Price--"]');
                var sh=w.querySelector('[class*="ShopInfo--"],[class*="shopName--"]');
                var l=w.querySelector('a[href*="item.taobao.com"], a[href*="detail.tmall.com"]');
                var sa=w.querySelector('[class*="sales--"],[class*="Sales--"]');
                p.push({t:t?(t.textContent||'').trim():'',p:pr?(pr.textContent||'').trim():'',
                    sh:sh?(sh.textContent||'').trim():'',sa:sa?(sa.textContent||'').trim():'',l:l?l.href:''});
            }return JSON.stringify({c:p.length,i:p});
        })()""")
        try: data = json.loads(result)
        except: continue

        new = 0
        for p in data.get("i",[]):
            url = p.get("url","")
            # 新版正则: [?&]id=(\d{13})
            import re
            m = re.search(r'[?&]id=(\d{13})', url)
            if m:
                pid = m.group(1)
            else:
                # 兜底: 旧版格式 item.htm?id= 或直接提取13位数字
                m = re.search(r'id=(\d+)', url)
                pid = m.group(1) if m else ""

            if pid and pid not in seen:
                seen.add(pid)
                p["id"] = pid
                products.append(p)
                new += 1

        rpt(f"  第{page}页: {data['c']}卡片, +{new}唯一 (累计{len(products)})")
        if new == 0 and page > 1: break
        if len(products) >= max_items: break
    return products


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    rpt("="*60)
    rpt(f"v2 事件驱动抓取 — {KEYWORD}")
    rpt("="*60)

    # 0. Chrome start
    rpt("\n=== Phase 0: Chrome ===")
    subprocess.run(["pkill","-TERM","-f",f"remote-debugging-port={CDP_PORT}"],capture_output=True)
    time.sleep(3)
    subprocess.run(["pkill","-KILL","-f",f"remote-debugging-port={CDP_PORT}"],capture_output=True)
    time.sleep(2)
    ud=Path(CHROME_USER_DATA)
    for f in ud.rglob("Singleton*"): f.unlink(missing_ok=True)
    subprocess.Popen([CHROME_BIN,f"--user-data-dir={CHROME_USER_DATA}","--disable-gpu",
        "--disable-software-rasterizer","--ozone-platform=x11",
        "--remote-debugging-port=9223","--remote-allow-origins=*","--start-maximized"],
        env=os.environ,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    time.sleep(8)
    try: urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version",timeout=3); rpt("  Chrome ✅")
    except: rpt("  ❌ Chrome failed"); return 1

    ws = cdp_connect()
    if not ws: rpt("  ❌ CDP failed"); return 1

    # 1. Navigate to search
    rpt("\n=== Phase 1: 搜索 ===")
    cdp_cmd(ws, "Page.navigate", {"url": f"https://s.taobao.com/search?q={urllib.parse.quote(KEYWORD)}"})

    # 2. Event-driven slider wait + solve
    rpt("\n=== Phase 2: 滑块 (事件驱动) ===")
    captcha_attempts = 0; captcha_passed = False

    for attempt in range(5):
        # 三层递进等待滑块挂载
        ctx, slider_data = wait_for_slider_ready(ws, timeout=30)

        if not ctx:
            rpt(f"  第{attempt+1}次: 未检测到滑块或已通过")
            if not captcha_still_present(ws):
                captcha_passed = True
                rpt("  ✅ 无滑块，继续")
            break

        captcha_attempts += 1
        rpt(f"  第{captcha_attempts}次拖拽...")

        if drag_slider_xlib(ws, ctx, slider_data):
            if not captcha_still_present(ws):
                captcha_passed = True
                rpt("  ✅ 滑块通过!")
                break

        rpt("  ⚠️ 未通过，重试...")

    rpt(f"  结果: {captcha_attempts}次拖拽, {'✅ 通过' if captcha_passed else '❌ 失败'}")

    # 3. Extract
    rpt("\n=== Phase 3: 提取 ===")
    products = extract_products(ws)
    rpt(f"  总数: {len(products)} 个商品")

    # 4. Export CSV
    rpt("\n=== Phase 4: 导出 ===")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() else "_" for c in KEYWORD)
    csv_path = OUTPUT_DIR / f"{safe}_{ts}.csv"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(["商品ID","标题","价格","销量","店铺","链接"])
        for p in products:
            w.writerow([p.get("id",""), p.get("t",""), p.get("p",""), p.get("sa",""), p.get("sh",""), p.get("url","")])
    rpt(f"  文件: {csv_path} ({os.path.getsize(csv_path)} bytes)")

    # 5. Cleanup
    rpt("\n=== Phase 5: 关闭 ===")
    ws.close()
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json")
        for t in json.loads(resp.read()):
            if t.get("type") == "page":
                try:
                    import websocket; pw = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=5, origin="")
                    pw.send(json.dumps({"id":1,"method":"Page.close"})); pw.recv(); pw.close()
                except: pass
    except: pass
    rpt("  CDP标签关闭"); time.sleep(2)
    subprocess.run(["pkill","-TERM","-f",f"remote-debugging-port={CDP_PORT}"], capture_output=True)
    time.sleep(3)
    if subprocess.run(["pgrep","-f",f"remote-debugging-port={CDP_PORT}"], capture_output=True).returncode == 0:
        subprocess.run(["pkill","-KILL","-f",f"remote-debugging-port={CDP_PORT}"], capture_output=True)
        rpt("  KILL兜底")
    rpt("  Chrome已关闭")

    # Report
    rpt_path = OUTPUT_DIR / f"report_{ts}.txt"
    with open(rpt_path, 'w') as f:
        f.write(f"v2 事件驱动测试报告 — {KEYWORD}\n")
        f.write(f"时间: {datetime.now().isoformat()}\n")
        f.write(f"滑块: {captcha_attempts}次, {'通过' if captcha_passed else '失败'}\n")
        f.write(f"商品: {len(products)}\n")
        f.write(f"文件: {csv_path}\n")
        f.write("\n".join(report))
    rpt(f"\n✅ 报告: {rpt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
