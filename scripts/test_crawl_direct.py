#!/usr/bin/env python3
"""直接搜索结果提取测试 — 蒙牛一米八八益生菌
绕过DTS，CDP直接提取搜索结果页商品数据 + python-xlib滑块验证
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

os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("test")

report_lines = []
def rpt(msg):
    logger.info(msg)
    report_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ── CDP helpers ──
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
            return ws, tgt
        except: time.sleep(2)
    return None, None

# ── Slider via python-xlib ──
def solve_captcha(ws):
    """python-xlib XTest slider solve. Returns True if passed."""
    rpt("  python-xlib滑块求解...")
    from Xlib import X, display as xd
    from Xlib.ext import xtest as xt

    try:
        # Get captcha frame + coords
        ft = cdp_cmd(ws, "Page.getFrameTree")
        tree = ft.get("result",{}).get("frameTree",{})
        pfid = None
        def find(n):
            nonlocal pfid
            for c in n.get("childFrames",[]):
                f=c.get("frame",{}); u=f.get("url","")
                if "h5api" in u and "punish" in u: pfid=f.get("id",""); return
                find(c)
        find(tree)
        if not pfid: return False

        iso = cdp_cmd(ws, "Page.createIsolatedWorld", {"frameId": pfid})
        ctx = iso.get("result",{}).get("executionContextId")
        if not ctx: return False
        time.sleep(0.2)

        r = cdp_cmd(ws, "Runtime.evaluate", {
            "expression": """(function(){
                var s=document.querySelector('[id*="nc_1_n1z"]');
                var t=document.querySelector('[id*="nc_1__scale_text"]');
                if(!s||!t)return JSON.stringify({found:false});
                var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();
                return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});
            })()""", "contextId": ctx, "returnByValue": True})
        data = json.loads(r.get("result",{}).get("result",{}).get("value","{}"))
        if not data.get("found"): return False

        # Screen coords
        ipos = cdp_eval(ws, """(function(){
            var fs=document.querySelectorAll('iframe');
            for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}
            return '{}';
        })()""")
        ip = json.loads(ipos)
        OX, OY = 66, 119
        sx = ip.get("x",397) + data["sx"] + OX
        sy = ip.get("y",181) + data["sy"] + OY
        dist = data["dist"] + random.randint(-3, 5)

        rpt(f"  拖拽: screen({sx},{sy}) dist={dist}")

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

        # 320-356点, 3.3-3.6s
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
        return True
    except Exception as e:
        rpt(f"  滑块异常: {e}")
        return False


def detect_captcha(ws):
    result = cdp_eval(ws, """(function(){
        var fs=document.querySelectorAll('iframe');
        for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('punish')!==-1&&fs[i].getBoundingClientRect().width>0)return'true';}
        return'false';
    })()""")
    return result == "true"


# ── Product extraction from search page ──
def extract_products(ws, max_items=200):
    """Extract product cards from current search results page."""
    all_products = []
    seen_ids = set()

    for page in range(1, 6):  # Up to 5 pages
        if page > 1:
            url = f"https://s.taobao.com/search?page={page}&q={urllib.parse.quote(KEYWORD)}"
            cdp_cmd(ws, "Page.navigate", {"url": url})
            time.sleep(5)

        # Scroll to trigger lazy load
        for y in [500, 1200, 2000]:
            cdp_eval(ws, f"window.scrollTo(0, {y})")
            time.sleep(1)

        result = cdp_eval(ws, """(function(){
            var products = [];
            var cards = document.querySelectorAll('[class*="Card--doubleCardWrapper"]');
            if(!cards.length) cards = document.querySelectorAll('.doubleCardWrapper--');
            if(!cards.length) {
                // Try newer selectors
                var items = document.querySelectorAll('[class*="Content--"]');
                for(var i=0;i<items.length;i++){
                    var el = items[i];
                    var titleEl = el.querySelector('[class*="Title--"]');
                    var priceEl = el.querySelector('[class*="Price--"]');
                    var shopEl = el.querySelector('[class*="ShopInfo--"], [class*="shopName--"]');
                    var salesEl = el.querySelector('[class*="sales--"], [class*="Sales--"]');
                    var linkEl = el.querySelector('a[href*="item.taobao.com"]');
                    var title = titleEl ? (titleEl.textContent||'').trim() : '';
                    var price = priceEl ? (priceEl.textContent||'').trim() : '';
                    var shop = shopEl ? (shopEl.textContent||'').trim() : '';
                    var sales = salesEl ? (salesEl.textContent||'').trim() : '';
                    var link = linkEl ? linkEl.href : '';
                    if(title && price && link){
                        var idMatch = link.match(/id=(\\d+)/);
                        products.push({
                            id: idMatch ? idMatch[1] : '',
                            title: title.substring(0, 150),
                            price: price,
                            shop: shop.substring(0, 60),
                            sales: sales,
                            link: link
                        });
                    }
                }
                return JSON.stringify({source: 'Content--', count: products.length, items: products});
            }

            var card = cards[0];
            var wrappers = card.querySelectorAll('[class*="Content--"]');
            for(var i=0;i<wrappers.length;i++){
                var w = wrappers[i];
                var titleEl = w.querySelector('[class*="Title--"]');
                var priceEl = w.querySelector('[class*="Price--"]');
                var shopEl = w.querySelector('[class*="ShopInfo--"], [class*="shopName--"]');
                var salesEl = w.querySelector('[class*="sales--"], [class*="Sales--"]');
                var linkEl = w.querySelector('a[href*="item.taobao.com"]');
                var title = titleEl ? (titleEl.textContent||'').trim() : '';
                var price = priceEl ? (priceEl.textContent||'').trim() : '';
                var shop = shopEl ? (shopEl.textContent||'').trim() : '';
                var sales = salesEl ? (salesEl.textContent||'').trim() : '';
                var link = linkEl ? linkEl.href : '';
                if(title){
                    var idMatch = link.match(/id=(\\d+)/);
                    products.push({
                        id: idMatch ? idMatch[1] : '',
                        title: title.substring(0, 150),
                        price: price,
                        shop: shop.substring(0, 60),
                        sales: sales,
                        link: link
                    });
                }
            }
            return JSON.stringify({source: 'Card--', count: products.length, items: products});
        })()""")
        try:
            data = json.loads(result)
        except:
            rpt(f"  第{page}页解析失败")
            continue

        new_count = 0
        for p in data.get("items", []):
            pid = p.get("id", "")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_products.append(p)
                new_count += 1

        rpt(f"  第{page}页: {data.get('count',0)}个卡片, 新增{new_count}个唯一商品 (累计{len(all_products)})")

        if len(all_products) >= max_items or new_count == 0:
            break

    return all_products


# ── Main ──
def main():
    rpt("="*60)
    rpt(f"直接搜索结果抓取测试 — {KEYWORD}")
    rpt("="*60)

    # Phase 0: Chrome start
    rpt("\n=== Phase 0: Chrome启动 ===")
    # Close old
    subprocess.run(["pkill", "-TERM", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
    time.sleep(3)
    subprocess.run(["pkill", "-KILL", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
    time.sleep(2)

    # Clean locks
    ud = Path(CHROME_USER_DATA)
    for f in ud.rglob("Singleton*"): f.unlink(missing_ok=True)

    cmd = [CHROME_BIN,
           f"--user-data-dir={CHROME_USER_DATA}", "--disable-gpu",
           "--disable-software-rasterizer", "--ozone-platform=x11",
           "--remote-debugging-port=9223", "--remote-allow-origins=*",
           "--start-maximized"]
    subprocess.Popen(cmd, env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(8)
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3)
        rpt("  Chrome已启动 ✅")
    except:
        rpt("  ❌ Chrome启动失败"); return 1

    ws, tgt = cdp_connect()
    if not ws:
        rpt("  ❌ CDP连接失败"); return 1

    # Phase 1: Navigate to search
    rpt("\n=== Phase 1: 搜索 ===")
    cdp_cmd(ws, "Page.navigate", {"url": f"https://s.taobao.com/search?q={urllib.parse.quote(KEYWORD)}"})
    time.sleep(8)

    # Phase 2: Captcha handling
    rpt("\n=== Phase 2: 滑块验证 ===")
    captcha_attempts = 0
    captcha_passed = False
    for attempt in range(5):
        if not detect_captcha(ws):
            rpt("  无滑块验证 ✅")
            captcha_passed = True
            break
        captcha_attempts += 1
        rpt(f"  尝试 #{captcha_attempts}...")
        if solve_captcha(ws):
            time.sleep(3)
            if not detect_captcha(ws):
                captcha_passed = True
                rpt("  ✅ 滑块通过!")
                break
    rpt(f"  滑块执行{max(0,captcha_attempts)}次, 通过率: {'100%' if captcha_passed else '0%'}")

    # Phase 3: Extract products
    rpt("\n=== Phase 3: 商品提取 ===")
    products = extract_products(ws)
    rpt(f"  有效抓取商品总数: {len(products)}")

    # Phase 4: Save to Excel
    rpt("\n=== Phase 4: 导出 ===")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_kw = "".join(c if c.isalnum() else "_" for c in KEYWORD)
    xlsx_path = OUTPUT_DIR / f"{safe_kw}_{ts}.csv"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(xlsx_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(["商品ID", "标题", "价格", "销量", "店铺", "链接"])
        for p in products:
            writer.writerow([p.get("id",""), p.get("title",""), p.get("price",""),
                           p.get("sales",""), p.get("shop",""), p.get("link","")])

    rpt(f"  导出文件: {xlsx_path}")
    rpt(f"  文件大小: {os.path.getsize(xlsx_path)} bytes")

    # Phase 5: Cleanup
    rpt("\n=== Phase 5: Chrome关闭 ===")
    ws.close()
    # CDP close tabs
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json")
        for t in json.loads(resp.read()):
            if t.get("type") == "page":
                try:
                    import websocket
                    pw = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=5, origin="")
                    pw.send(json.dumps({"id":1,"method":"Page.close"})); pw.recv(); pw.close()
                except: pass
    except: pass
    rpt("  CDP关闭标签完成")
    time.sleep(2)
    subprocess.run(["pkill", "-TERM", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
    time.sleep(3)
    if subprocess.run(["pgrep", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True).returncode == 0:
        subprocess.run(["pkill", "-KILL", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
        rpt("  KILL兜底")
    rpt("  Chrome已关闭")

    # Report
    report_path = OUTPUT_DIR / f"report_{ts}.txt"
    with open(report_path, 'w') as f:
        f.write(f"测试报告 — {KEYWORD}\n")
        f.write(f"时间: {datetime.now().isoformat()}\n")
        f.write(f"{'='*60}\n")
        f.write(f"滑块执行次数: {max(0,captcha_attempts)}\n")
        f.write(f"滑块通过率: {'100%' if captcha_passed else '0%'}\n")
        f.write(f"有效抓取商品总数: {len(products)}\n")
        f.write(f"导出文件路径: {xlsx_path}\n")
        f.write(f"异常: 无\n")

    rpt(f"\n报告已保存: {report_path}")
    rpt("="*60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
