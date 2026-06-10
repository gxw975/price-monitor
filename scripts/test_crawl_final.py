#!/usr/bin/env python3
"""最终版全流程自闭环抓取 — 蒙牛一米八八益生菌
修复：punish iframe URL truncated导致FrameTree匹配失败
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
OX, OY = 66, 119  # viewport→screen offset

os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("test")

report = []
def rpt(msg):
    logger.info(msg); report.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ── CDP ──
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

def cdp_connect(hint=""):
    import websocket
    for _ in range(10):
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=5)
            pages = [t for t in json.loads(resp.read()) if t.get("type") == "page"]
            tgt = None
            if hint:
                for p in pages:
                    if hint in p.get("url",""): tgt = p; break
            if not tgt:
                for p in pages:
                    if "about:blank" in p.get("url",""): tgt = p; break
            if not tgt and pages: tgt = pages[0]
            if not tgt: time.sleep(2); continue
            ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=15, origin="")
            cdp_cmd(ws, "Page.enable"); cdp_cmd(ws, "Runtime.enable")
            return ws
        except: time.sleep(2)
    return None


# ── Slider ──
def solve_captcha(ws):
    """python-xlib XTest slider. Fixed: find ANY h5api frame, not just /punish."""
    from Xlib import X, display as xd
    from Xlib.ext import xtest as xt

    try:
        ft = cdp_cmd(ws, "Page.getFrameTree")
        tree = ft.get("result",{}).get("frameTree",{})

        # Find ANY h5api frame (URL may contain /punish or /_____tmd_____/)
        h5fid = None
        def find(node):
            nonlocal h5fid
            for c in node.get("childFrames",[]):
                f=c.get("frame",{}); u=f.get("url","")
                if "h5api.m.taobao.com" in u:
                    h5fid = f.get("id",""); return
                find(c)
        find(tree)
        if not h5fid:
            rpt("  ❌ 未找到h5api验证iframe"); return False

        # Wait for iframe content to fully load
        time.sleep(1.5)
        iso = cdp_cmd(ws, "Page.createIsolatedWorld", {"frameId": h5fid})
        ctx = iso.get("result",{}).get("executionContextId")
        if not ctx:
            rpt("  ❌ 无法获取iframe上下文"); return False
        time.sleep(0.5)

        r = cdp_cmd(ws, "Runtime.evaluate", {
            "expression": """(function(){
                var s=document.querySelector('[id*="nc_1_n1z"]');
                var t=document.querySelector('[id*="nc_1__scale_text"]');
                if(!s||!t)return JSON.stringify({found:false});
                var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();
                return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});
            })()""", "contextId": ctx, "returnByValue": True})
        data = json.loads(r.get("result",{}).get("result",{}).get("value","{}"))
        if not data.get("found"):
            # Retry once after waiting (iframe might still be initializing)
            rpt("  ⚠️ iframe内无滑块, 等待重试...")
            time.sleep(3)
            iso2 = cdp_cmd(ws, "Page.createIsolatedWorld", {"frameId": h5fid})
            ctx2 = iso2.get("result",{}).get("executionContextId")
            if ctx2:
                r2 = cdp_cmd(ws, "Runtime.evaluate", {
                    "expression": """(function(){var s=document.querySelector('[id*="nc_1_n1z"]');var t=document.querySelector('[id*="nc_1__scale_text"]');if(!s||!t)return JSON.stringify({found:false});var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()""",
                    "contextId": ctx2, "returnByValue": True})
                data = json.loads(r2.get("result",{}).get("result",{}).get("value","{}"))
            if not data.get("found"):
                rpt("  ❌ 重试后仍无滑块"); return False

        # Get iframe viewport position
        ipos = cdp_eval(ws, """(function(){
            var fs=document.querySelectorAll('iframe');
            for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}
            return '{}';
        })()""")
        ip = json.loads(ipos)
        sx = ip.get("x",397) + data["sx"] + OX
        sy = ip.get("y",181) + data["sy"] + OY
        dist = data["dist"] + random.randint(-3, 5)

        rpt(f"  screen({sx},{sy}) dist={dist}")

        disp = xd.Display()
        def mov(x,y): xt.fake_input(disp, X.MotionNotify, x=int(x), y=int(y)); disp.sync()

        # Approach
        ax,ay=sx-random.randint(60,120),sy+random.randint(-10,10)
        for i in range(5):
            p=(i+1)/5; mov(int(ax+(sx-ax)*p),int(ay+(sy-ay)*p))
            time.sleep(0.015+random.random()*0.02)

        mov(sx,sy); time.sleep(0.06+random.random()*0.05)
        xt.fake_input(disp, X.ButtonPress, detail=1); disp.sync()
        time.sleep(0.025+random.random()*0.03)

        n_points = random.randint(320, 356)
        total_s = 3.3 + random.random() * 0.3
        for i in range(n_points):
            p = i/n_points
            eased = 1 - (1-p)**random.uniform(1.6,2.8)
            x = int(sx + dist * eased)
            y = sy + int(math.sin(p*math.pi*4)*random.randint(1,4))
            if p > 0.85: y = sy + random.randint(-1,1)
            mov(x, y)
            time.sleep(total_s/n_points*(0.8+random.random()*0.4))

        time.sleep(0.05+random.random()*0.04)
        xt.fake_input(disp, X.ButtonRelease, detail=1); disp.sync()
        disp.close()
        time.sleep(6)

        # Verify: captcha iframe gone?
        ft2 = cdp_cmd(ws, "Page.getFrameTree")
        tree2 = ft2.get("result",{}).get("frameTree",{})
        still_there = False
        def check(node):
            nonlocal still_there
            for c in node.get("childFrames",[]):
                if "h5api.m.taobao.com" in c.get("frame",{}).get("url",""): still_there = True
                check(c)
        check(tree2)
        return not still_there

    except Exception as e:
        rpt(f"  滑块异常: {e}")
        return False


# ── Product extraction ──
def extract_products(ws, max_items=500):
    products = []; seen = set()
    for page in range(1, 8):
        if page > 1:
            cdp_cmd(ws, "Page.navigate", {"url": f"https://s.taobao.com/search?page={page}&q={urllib.parse.quote(KEYWORD)}"})
            time.sleep(5)
        for y in [500, 1200, 2000]:
            cdp_eval(ws, f"window.scrollTo(0, {y})"); time.sleep(1)

        result = cdp_eval(ws, """(function(){
            var products=[];
            var cards=document.querySelectorAll('[class*="Card--doubleCardWrapper"]');
            if(!cards.length) cards=document.querySelectorAll('.doubleCardWrapper--');
            var wrappers=[];
            if(cards.length) wrappers=cards[0].querySelectorAll('[class*="Content--"]');
            if(!wrappers.length) wrappers=document.querySelectorAll('[class*="Content--"]');
            for(var i=0;i<wrappers.length;i++){
                var w=wrappers[i];
                var tEl=w.querySelector('[class*="Title--"]');
                var pEl=w.querySelector('[class*="Price--"]');
                var sEl=w.querySelector('[class*="ShopInfo--"],[class*="shopName--"]');
                var lEl=w.querySelector('a[href*="item.taobao.com"]');
                var saEl=w.querySelector('[class*="sales--"],[class*="Sales--"]');
                var t=tEl?(tEl.textContent||'').trim():'',p=pEl?(pEl.textContent||'').trim():'';
                var sh=sEl?(sEl.textContent||'').trim():'',sa=saEl?(saEl.textContent||'').trim():'';
                var l=lEl?lEl.href:''; if(t||p) products.push({t:t,p:p,sh:sh,sa:sa,l:l});
            }
            return JSON.stringify({c:products.length,i:products})
        })()""")
        try: data = json.loads(result)
        except: continue
        new = 0
        for p in data.get("i",[]):
            pid_match = p.get("l","").split("id=")[-1].split("&")[0] if p.get("l") else ""
            if pid_match and pid_match not in seen:
                seen.add(pid_match); products.append(p); new += 1
        rpt(f"  第{page}页: {data['c']}卡片, +{new}唯一 (累计{len(products)})")
        if new == 0 and page > 1: break
        if len(products) >= max_items: break
    return products


# ── Main ──
def main():
    rpt("="*60)
    rpt(f"全流程自闭环抓取 — {KEYWORD}")
    rpt("="*60)

    # 0. Chrome start
    rpt("\n=== Phase 0: Chrome ===")
    # Clean close
    try:
        resp=urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json")
        for t in json.loads(resp.read()):
            if t.get("type")=="page":
                try:
                    import websocket; pw=websocket.create_connection(t["webSocketDebuggerUrl"],timeout=5,origin="")
                    pw.send(json.dumps({"id":1,"method":"Page.close"})); pw.recv(); pw.close()
                except: pass
    except: pass
    time.sleep(2)
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

    ws=cdp_connect()
    if not ws: rpt("  ❌ CDP failed"); return 1

    # 1. Search
    rpt("\n=== Phase 1: 搜索 ===")
    cdp_cmd(ws,"Page.navigate",{"url":f"https://s.taobao.com/search?q={urllib.parse.quote(KEYWORD)}"})
    time.sleep(10)  # Wait longer for captcha iframe to fully initialize

    # 2. Captcha
    rpt("\n=== Phase 2: 滑块 ===")
    captcha_attempts=0; captcha_passed=False
    for attempt in range(5):
        has = cdp_eval(ws,"""(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){var s=fs[i].src||'';if(s.indexOf('h5api')!==-1&&fs[i].getBoundingClientRect().width>0)return'true';}return'false';})()""")
        if has!="true": rpt("  无滑块 ✅"); captcha_passed=True; break
        captcha_attempts+=1; rpt(f"  第{captcha_attempts}次...")
        if solve_captcha(ws):
            time.sleep(3)
            has2=cdp_eval(ws,"""(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){var s=fs[i].src||'';if(s.indexOf('h5api')!==-1&&fs[i].getBoundingClientRect().width>0)return'true';}return'false';})()""")
            if has2!="true": captcha_passed=True; rpt("  ✅ 通过!"); break
    rpt(f"  结果: {captcha_attempts}次, {'通过' if captcha_passed else '失败'}")

    # 3. Extract
    rpt("\n=== Phase 3: 提取 ===")
    products=extract_products(ws)
    rpt(f"  总数: {len(products)} 个商品")

    # 4. Export
    rpt("\n=== Phase 4: 导出 ===")
    ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    safe="".join(c if c.isalnum() else"_" for c in KEYWORD)
    csv_path=OUTPUT_DIR/f"{safe}_{ts}.csv"
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    with open(csv_path,'w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(["商品ID","标题","价格","销量","店铺","链接"])
        for p in products:
            pid=p.get("l","").split("id=")[-1].split("&")[0] if p.get("l") else ""
            w.writerow([pid,p.get("t",""),p.get("p",""),p.get("sa",""),p.get("sh",""),p.get("l","")])
    rpt(f"  文件: {csv_path} ({os.path.getsize(csv_path)} bytes)")

    # 5. Cleanup
    rpt("\n=== Phase 5: 关闭 ===")
    ws.close()
    try:
        resp=urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json")
        for t in json.loads(resp.read()):
            if t.get("type")=="page":
                try:
                    import websocket; pw=websocket.create_connection(t["webSocketDebuggerUrl"],timeout=5,origin="")
                    pw.send(json.dumps({"id":1,"method":"Page.close"})); pw.recv(); pw.close()
                except: pass
    except: pass
    rpt("  CDP标签关闭"); time.sleep(2)
    subprocess.run(["pkill","-TERM","-f",f"remote-debugging-port={CDP_PORT}"],capture_output=True)
    time.sleep(3)
    if subprocess.run(["pgrep","-f",f"remote-debugging-port={CDP_PORT}"],capture_output=True).returncode==0:
        subprocess.run(["pkill","-KILL","-f",f"remote-debugging-port={CDP_PORT}"],capture_output=True)
        rpt("  KILL兜底")
    rpt("  Chrome已关闭")

    # Report
    rpt_path=OUTPUT_DIR/f"report_{ts}.txt"
    with open(rpt_path,'w') as f:
        f.write(f"测试报告 — {KEYWORD}\n")
        f.write(f"时间: {datetime.now().isoformat()}\n")
        f.write(f"滑块: {captcha_attempts}次, {'通过' if captcha_passed else '失败'}\n")
        f.write(f"商品数: {len(products)}\n")
        f.write(f"文件: {csv_path}\n")
        f.write("\n".join(report))
    rpt(f"\n✅ 报告: {rpt_path}")
    return 0

if __name__=="__main__": sys.exit(main())
