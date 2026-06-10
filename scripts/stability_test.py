#!/usr/bin/env python3
"""连续5次稳定性测试 — 全自动运行，评估长期可靠性"""

import csv, json, logging, math, os, random, re, signal, subprocess, sys, time, traceback, urllib.parse, urllib.request
from datetime import datetime; from pathlib import Path
from Xlib import X, display as xd; from Xlib.ext import xtest as xt

# Config
CDP_PORT = 9223
OUTPUT_DIR = Path("/home/lab-admin/price-monitor/data/stability")
OX, OY = 66, 119
INTERVAL_MINUTES = 15
MAX_RETRIES = 1  # Retry once per test

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Global results
ALL_RESULTS = []
TEST_START_TIME = None


def setup_logging(test_num):
    """Setup per-test logging."""
    logger = logging.getLogger(f"test_{test_num}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(OUTPUT_DIR / f"test_{test_num}.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s [T{0}] %(levelname)s %(message)s".format(test_num)))
    logger.addHandler(sh)
    return logger


# ═══ CDP ═══
def cdp_cmd(ws, m, p=None, t=15):
    msg = {"id": int(time.time()*1000)%1000000, "method": m}
    if p: msg["params"] = p
    ws.send(json.dumps(msg)); dl = time.time() + t
    while time.time() < dl:
        r = json.loads(ws.recv())
        if r.get("id") == msg["id"]: return r
    raise TimeoutError(m)

def cdp_eval(ws, js):
    r = cdp_cmd(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))

def cdp_eval_ctx(ws, ctx, js):
    r = cdp_cmd(ws, "Runtime.evaluate", {"expression": js, "contextId": ctx, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))


# ═══ Chrome ═══
def launch_chrome(logger):
    logger.info("启动Chrome (3参数)...")
    subprocess.run(["pkill", "-TERM", "chrome"], check=False)
    time.sleep(3)
    subprocess.run(["pkill", "-KILL", "chrome"], check=False)
    time.sleep(2)

    subprocess.Popen([
        "/usr/bin/google-chrome-stable",
        "--remote-debugging-port=9223", "--remote-allow-origins=*",
        "--user-data-dir=/home/lab-admin/.config/chrome-profile-minimal",
    ], env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(8)

    import websocket
    for i in range(20):
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=3)
            targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]
            if not pages:
                urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank", timeout=5)
                time.sleep(1); continue
            ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=15, origin="")
            cdp_cmd(ws, "Page.enable"); cdp_cmd(ws, "Runtime.enable")
            logger.info(f"Chrome ready ({i+1}s)")
            return ws, targets
        except: time.sleep(1)
    return None, None

def shutdown_chrome(logger):
    logger.info("优雅关闭Chrome...")
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json")
        for t in json.loads(resp.read()):
            if t.get("type") == "page":
                try:
                    import websocket; pw = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=5, origin="")
                    pw.send(json.dumps({"id":1,"method":"Page.close"})); pw.recv(); pw.close()
                except: pass
    except: pass
    time.sleep(2)
    subprocess.run(["pkill", "-TERM", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
    time.sleep(3)
    if subprocess.run(["pgrep", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True).returncode == 0:
        subprocess.run(["pkill", "-KILL", "-f", f"remote-debugging-port={CDP_PORT}"], capture_output=True)
        logger.warning("KILL兜底")
    remaining = len(subprocess.run(["pgrep", "-c", "chrome"], capture_output=True, text=True).stdout.strip() or "0")
    logger.info(f"残留Chrome进程: {remaining}")


# ═══ Slider ═══
def wait_for_slider(ws, logger, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        ft = cdp_cmd(ws, "Page.getFrameTree")
        tree = ft.get("result",{}).get("frameTree",{})
        h5fid = [None]
        def fh(n):
            for c in n.get("childFrames",[]):
                if "h5api.m.taobao.com" in c.get("frame",{}).get("url",""): h5fid[0]=c.get("frame",{}).get("id",""); return
                fh(c)
        fh(tree)
        if not h5fid[0]: time.sleep(0.5); continue
        try:
            iso = cdp_cmd(ws, "Page.createIsolatedWorld", {"frameId": h5fid[0]})
            ctx = iso.get("result",{}).get("executionContextId")
            if not ctx: time.sleep(0.5); continue
        except: time.sleep(0.5); continue
        for _ in range(50):
            try:
                c = cdp_eval_ctx(ws, ctx, "document.querySelectorAll('#nc_1_n1z').length")
                if c not in ("0","undefined","null","") and int(c) > 0:
                    v = cdp_eval_ctx(ws, ctx, """(function(){var s=document.querySelector('#nc_1_n1z');return s&&s.offsetParent!==null&&s.getBoundingClientRect().width>0?'true':'false';})()""")
                    if v == "true":
                        cd = cdp_eval_ctx(ws, ctx, """(function(){var s=document.querySelector('#nc_1_n1z');var t=document.querySelector('#nc_1__scale_text');if(!s||!t)return JSON.stringify({found:false});var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()""")
                        sd = json.loads(cd)
                        if sd.get("found"): return ctx, sd
            except: pass
            time.sleep(0.2)
        time.sleep(0.5)
    return None, None

def drag_slider(ws, ctx, sd, logger):
    try:
        ipos = cdp_eval(ws, """(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return'{}';})()""")
        ip = json.loads(ipos)
        sx, sy = ip.get("x",397)+sd["sx"]+OX, ip.get("y",181)+sd["sy"]+OY
        dist = sd["dist"]+random.randint(-3,5)
        logger.info(f"X11拖拽:({int(sx)},{int(sy)}) dist={dist}")

        disp = xd.Display()
        def mov(x,y): xt.fake_input(disp, X.MotionNotify, x=int(x), y=int(y)); disp.sync()
        ax,ay = sx-random.randint(60,120),sy+random.randint(-10,10)
        for i in range(5): p=(i+1)/5; mov(int(ax+(sx-ax)*p),int(ay+(sy-ay)*p)); time.sleep(0.015+random.random()*0.02)
        mov(sx,sy); time.sleep(0.06+random.random()*0.05)
        xt.fake_input(disp, X.ButtonPress, detail=1); disp.sync(); time.sleep(0.025+random.random()*0.03)
        n=random.randint(320,356); dur=3.3+random.random()*0.3
        for i in range(n):
            p=i/n; e=1-(1-p)**random.uniform(1.6,2.8)
            x=int(sx+dist*e); y=sy+int(math.sin(p*math.pi*4)*random.randint(1,4))
            if p>0.85: y=sy+random.randint(-1,1); mov(x,y); time.sleep(dur/n*(0.8+random.random()*0.4))
        time.sleep(0.05+random.random()*0.04)
        xt.fake_input(disp, X.ButtonRelease, detail=1); disp.sync(); disp.close()
        time.sleep(6); return True
    except Exception as e:
        logger.error(f"X11异常: {e}"); return False


# ═══ Single Test ═══
def run_single_test(test_num, keyword, logger):
    result = {
        "test_num": test_num, "keyword": keyword, "success": False,
        "chrome_start": False, "dts_loaded": False, "login_ok": False,
        "slider_triggered": False, "slider_attempts": 0, "slider_passed": False,
        "product_count": 0, "product_ids": [], "duration": 0,
        "chrome_closed": False, "residual_procs": 0, "errors": []
    }
    start_time = time.time()

    try:
        # 1. Chrome
        logger.info(f"=== Test {test_num}: {keyword} ===")
        ws, targets = launch_chrome(logger)
        if not ws: result["errors"].append("Chrome启动失败"); return result
        result["chrome_start"] = True

        # 2. DTS check
        dts_found = any("ppgdlgnehnajbbngnohepfigdmjbdpfb" in t.get("url","") or
                        "diantoushi" in t.get("url","") for t in targets)
        result["dts_loaded"] = dts_found
        logger.info(f"DTS: {'✅' if dts_found else '⚠️ 未检测到'}")

        # 3. Warm-up + login check
        logger.info("预热淘宝首页...")
        cdp_cmd(ws, "Page.navigate", {"url": "https://www.taobao.com"})
        time.sleep(5)
        for i in range(3): cdp_eval(ws, f"window.scrollTo(0,{random.randint(200,500)})"); time.sleep(1)

        login_info = cdp_eval(ws, """(function(){
            var b=document.body?.innerText||'';
            var hasLogin=b.indexOf('请登录')===-1&&b.indexOf('我的淘宝')!==-1;
            var hasUser=!!document.querySelector('.site-nav-user .nickname');
            return JSON.stringify({ok:hasLogin||hasUser});
        })()""")
        result["login_ok"] = json.loads(login_info).get("ok", False)
        logger.info(f"登录态: {'✅' if result['login_ok'] else '❌'}")

        # 4. Search
        logger.info(f"搜索: {keyword}")
        cdp_cmd(ws, "Page.navigate", {"url": f"https://s.taobao.com/search?q={urllib.parse.quote(keyword)}"})
        time.sleep(6)

        # 5. Slider
        logger.info("滑块检测...")
        for a in range(5):
            ctx, sd = wait_for_slider(ws, logger, timeout=15)
            if not ctx:
                st = cdp_eval(ws, "JSON.stringify({t:document.title,l:(document.body?.innerText||'').length,pl:document.querySelectorAll('a[href*=\"item.taobao.com\"]').length})")
                st = json.loads(st)
                logger.info(f"无滑块: {st.get('t','')[:30]}, len={st.get('l')}, links={st.get('pl')}")
                if st.get('pl',0) > 0: break
                time.sleep(3); continue
            result["slider_triggered"] = True
            result["slider_attempts"] += 1
            logger.info(f"滑块第{result['slider_attempts']}次...")
            if drag_slider(ws, ctx, sd, logger):
                time.sleep(3)
                def ck(n):
                    for c in n.get("childFrames",[]):
                        if "h5api.m.taobao.com" in c.get("frame",{}).get("url",""):
                            v=cdp_eval(ws,"""(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1&&fs[i].getBoundingClientRect().width>0)return'true';}return'false';})()""")
                            return v=="true"
                        if ck(c): return True
                    return False
                ft=cdp_cmd(ws,"Page.getFrameTree")
                if not ck(ft.get("result",{}).get("frameTree",{})):
                    result["slider_passed"]=True; logger.info("滑块通过!"); break
            time.sleep(2)

        logger.info(f"滑块: 触发={result['slider_triggered']}, 尝试={result['slider_attempts']}, 通过={result['slider_passed']}")

        # 6. Extract
        logger.info("商品提取...")
        prods = []; seen = set()
        for pg in range(1, 6):
            if pg > 1: cdp_cmd(ws, "Page.navigate", {"url": f"https://s.taobao.com/search?page={pg}&q={urllib.parse.quote(keyword)}"}); time.sleep(4)
            for y in [500,1200,2000]: cdp_eval(ws, f"window.scrollTo(0,{y})"); time.sleep(1)
            res = cdp_eval(ws, """(function(){var p=[];var c=document.querySelectorAll('[class*="Card--doubleCardWrapper"]');if(!c.length)c=document.querySelectorAll('.doubleCardWrapper--');var w=[];if(c.length)w=c[0].querySelectorAll('[class*="Content--"]');if(!w.length)w=document.querySelectorAll('[class*="Content--"]');for(var i=0;i<w.length;i++){var e=w[i];var t=e.querySelector('[class*="Title--"]'),pr=e.querySelector('[class*="Price--"]'),sh=e.querySelector('[class*="ShopInfo--"],[class*="shopName--"]'),l=e.querySelector('a[href*="item.taobao.com"], a[href*="detail.tmall.com"]'),sa=e.querySelector('[class*="sales--"],[class*="Sales--"]');p.push({t:t?(t.textContent||'').trim():'',p:pr?(pr.textContent||'').trim():'',sh:sh?(sh.textContent||'').trim():'',sa:sa?(sa.textContent||'').trim():'',l:l?l.href:''});}return JSON.stringify({c:p.length,i:p});})()""")
            try: data = json.loads(res)
            except: continue
            nw = 0
            for p in data.get("i",[]):
                m = re.search(r'[?&]id=(\d{13})', p.get("l","")) or re.search(r'id=(\d+)', p.get("l",""))
                pid = m.group(1) if m else ""
                if pid and pid not in seen: seen.add(pid); p["id"]=pid; prods.append(p); nw+=1
            logger.info(f"  第{pg}页: {data['c']}卡片, +{nw} (累计{len(prods)})")
            if nw==0 and pg>1: break

        result["product_count"] = len(prods)
        result["product_ids"] = [p["id"] for p in prods[:3]]
        result["success"] = len(prods) > 0
        logger.info(f"商品: {len(prods)}, 样本ID: {result['product_ids']}")

        # 7. Export CSV
        if prods:
            csv_path = OUTPUT_DIR / f"test{test_num}_{keyword}_{datetime.now().strftime('%H%M%S')}.csv"
            with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f); w.writerow(["商品ID","标题","价格","销量","店铺","链接"])
                for p in prods: w.writerow([p.get("id",""),p.get("t",""),p.get("p",""),p.get("sa",""),p.get("sh",""),p.get("l","")])
            logger.info(f"导出: {csv_path}")

    except Exception as e:
        result["errors"].append(f"{type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
    finally:
        if ws: ws.close()
        shutdown_chrome(logger)
        result["chrome_closed"] = True
        result["duration"] = round(time.time() - start_time, 1)
        result["residual_procs"] = len(subprocess.run(["pgrep", "-c", "chrome"], capture_output=True, text=True).stdout.strip() or "0")
        logger.info(f"耗时: {result['duration']}s, 残留进程: {result['residual_procs']}")

    ALL_RESULTS.append(result)
    return result


# ═══ Main ═══
def main():
    global TEST_START_TIME
    TEST_START_TIME = datetime.now()

    keywords = [
        "蒙牛一米八八奶粉",
        "蒙牛一米八八营养棒",
        "蒙牛一米八八益生菌",
        "蒙牛一米八八奶粉",
        "蒙牛一米八八营养棒",
    ]

    print("="*70)
    print(f"  连续5次稳定性测试")
    print(f"  开始时间: {TEST_START_TIME.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  间隔: {INTERVAL_MINUTES}分钟")
    print("="*70)

    consecutive_failures = 0

    for i, kw in enumerate(keywords, 1):
        logger = setup_logging(i)
        logger.info(f"\n{'#'*50}\n# 第{i}/5次测试: {kw}\n{'#'*50}")

        # Run with retry
        result = None
        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                logger.warning(f"重试第{attempt}次...")
                time.sleep(30)
            result = run_single_test(i, kw, logger)
            if result["success"]: break

        # Evaluate
        if result["success"]:
            consecutive_failures = 0
            logger.info(f"✅ 测试{i}通过: {result['product_count']}商品, {result['duration']}s")
        else:
            consecutive_failures += 1
            logger.error(f"❌ 测试{i}失败: errors={result['errors']}")
            if consecutive_failures >= 2:
                logger.critical("连续2次失败，终止全部测试!")
                break

        # Wait for next test
        if i < 5:
            wait = INTERVAL_MINUTES * 60
            logger.info(f"\n等待{INTERVAL_MINUTES}分钟后开始下一次测试...")
            time.sleep(wait)

    # ═══ Final Report ═══
    print("\n" + "="*70)
    print("  稳定性测试总结报告")
    print("="*70)

    successes = [r for r in ALL_RESULTS if r["success"]]
    total = len(ALL_RESULTS)

    print(f"\n总测试次数: {total}")
    print(f"成功次数: {len(successes)}")
    print(f"成功率: {len(successes)/total*100:.1f}%" if total > 0 else "N/A")

    slider_triggered = [r for r in ALL_RESULTS if r["slider_triggered"]]
    print(f"\n平均滑块触发率: {len(slider_triggered)/total*100:.1f}%" if total > 0 else "N/A")
    slider_passes = [r for r in slider_triggered if r["slider_passed"]]
    print(f"滑块通过率: {len(slider_passes)/len(slider_triggered)*100:.1f}%" if slider_triggered else "N/A (无触发)")

    durations = [r["duration"] for r in ALL_RESULTS]
    print(f"\n平均执行时间: {sum(durations)/len(durations):.1f}s" if durations else "N/A")

    products = [r["product_count"] for r in ALL_RESULTS]
    print(f"平均商品数: {sum(products)/len(products):.1f}" if products else "N/A")

    print("\n分次明细:")
    for r in ALL_RESULTS:
        status = "✅" if r["success"] else "❌"
        print(f"  [{r['test_num']}] {status} {r['keyword']}: {r['product_count']}商品, "
              f"滑块={'触发' if r['slider_triggered'] else '无'}, "
              f"通过={'✅' if r['slider_passed'] else '❌'}, "
              f"耗时{r['duration']}s")

    errors = [r for r in ALL_RESULTS if r["errors"]]
    if errors:
        print(f"\n异常汇总:")
        for r in errors:
            for e in r["errors"]:
                print(f"  测试{r['test_num']}: {e}")

    # Stability assessment
    success_rate = len(successes)/total*100 if total > 0 else 0
    if success_rate >= 80 and len(slider_passes)/max(len(slider_triggered),1) >= 0.5:
        assessment = "✅ 达到生产环境标准"
    elif success_rate >= 60:
        assessment = "⚠️ 基本可用，需优化滑块或反爬策略"
    else:
        assessment = "❌ 未达生产标准，存在严重稳定性问题"

    print(f"\n稳定性评估: {assessment}")

    # Write report file
    report_path = OUTPUT_DIR / f"summary_{TEST_START_TIME.strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_path, 'w') as f:
        f.write(f"稳定性测试总结报告\n{'='*70}\n")
        f.write(f"开始: {TEST_START_TIME.isoformat()}\n")
        f.write(f"结束: {datetime.now().isoformat()}\n")
        f.write(f"成功率: {success_rate:.1f}%\n")
        f.write(f"评估: {assessment}\n")
        for r in ALL_RESULTS:
            f.write(f"\n测试{r['test_num']} ({r['keyword']}): {'✅' if r['success'] else '❌'}\n")
            f.write(f"  Chrome:{r['chrome_start']} DTS:{r['dts_loaded']} 登录:{r['login_ok']}\n")
            f.write(f"  滑块:触发={r['slider_triggered']} 尝试={r['slider_attempts']} 通过={r['slider_passed']}\n")
            f.write(f"  商品:{r['product_count']} 耗时:{r['duration']}s 残留:{r['residual_procs']}\n")
            f.write(f"  错误:{r['errors']}\n")

    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
