#!/usr/bin/env python3
"""
第二次完整抓取测试 - 严格按10步流程
关键词: 蒙牛一米八八营养棒
"""
import json, urllib.request, websocket, time, math, os, random, subprocess, glob as g

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
KEYWORD = "蒙牛一米八八营养棒"

os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH_FILE

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

# ---- Init X11 ----
from Xlib import display as xdisplay, X
from Xlib.ext import xtest
xd = xdisplay.Display()

def x11_click(sx, sy):
    xtest.fake_input(xd, X.MotionNotify, x=int(sx), y=int(sy)); xd.sync(); time.sleep(0.08)
    xtest.fake_input(xd, X.ButtonPress, 1); xd.sync(); time.sleep(0.05)
    xtest.fake_input(xd, X.ButtonRelease, 1); xd.sync()

def x11_move(x, y):
    xtest.fake_input(xd, X.MotionNotify, x=int(x), y=int(y)); xd.sync()

def x11_down():
    xtest.fake_input(xd, X.ButtonPress, 1); xd.sync()

def x11_up():
    xtest.fake_input(xd, X.ButtonRelease, 1); xd.sync()

# ---- CDP Helpers ----
def get_main_ws():
    resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
    targets = json.loads(resp.read())
    for t in targets:
        if t.get('type') == 'page' and 'taobao' in t.get('url', ''):
            return websocket.create_connection(t['webSocketDebuggerUrl'], timeout=15)
    raise Exception("No taobao page found")

ws = get_main_ws()
mid = [0]
def cdp(method, params=None):
    mid[0] += 1
    msg = {'id': mid[0], 'method': method}
    if params: msg['params'] = params
    ws.send(json.dumps(msg))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid[0]: return r

cdp('Page.enable')
cdp('Runtime.enable')

def reconnect_ws():
    global ws
    try: ws.close()
    except: pass
    time.sleep(1)
    ws = get_main_ws()
    cdp('Page.enable')
    cdp('Runtime.enable')

def get_offset():
    r = cdp('Runtime.evaluate', {
        'expression': """(function(){var fl=(window.outerWidth-window.innerWidth)/2;return JSON.stringify({ox:Math.round((window.screenLeft||0)+fl),oy:Math.round((window.screenTop||0)+window.outerHeight-window.innerHeight-fl)});})()""",
        'returnByValue': True
    })
    d = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
    return d.get('ox', 66), d.get('oy', 119)

def body_has(text):
    r = cdp('Runtime.evaluate', {
        'expression': f"(function(){{return (document.body?.innerText||'').indexOf('{text}')!==-1;}})()",
        'returnByValue': True
    })
    return r.get('result', {}).get('result', {}).get('value') == True

def body_progress():
    r = cdp('Runtime.evaluate', {
        'expression': """(function(){var b=document.body?.innerText||'';var m=b.match(/已成功加载[：:]?\s*(\\d+)\s*\/\s*(\\d+)/);return JSON.stringify(m?{loaded:parseInt(m[1]),total:parseInt(m[2])}:null);})()""",
        'returnByValue': True
    })
    return json.loads(r.get('result', {}).get('result', {}).get('value', 'null'))

def find_text_exact(text):
    js = f"""(function(){{var t='{text}';var all=document.querySelectorAll('*');for(var i=0;i<all.length;i++){{if((all[i].textContent||'').trim()===t&&all[i].offsetHeight>0&&all[i].offsetHeight<100){{var r=all[i].getBoundingClientRect();return JSON.stringify({{found:true,vx:Math.round(r.x+r.width/2),vy:Math.round(r.y+r.height/2)}});}}}}return JSON.stringify({{found:false}});}})()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

def has_captcha_iframe():
    r = cdp('Runtime.evaluate', {
        'expression': """(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1&&fs[i].getBoundingClientRect().width>0)return true;}return false;})()""",
        'returnByValue': True
    })
    return r.get('result', {}).get('result', {}).get('value') == True

# ---- Captcha solver ----
def solve_captcha():
    print("\n  ⚠️ 检测到滑块验证码，开始求解...")
    ft = cdp('Page.getFrameTree')
    ftree = ft.get('result', {}).get('frameTree', {})
    pfid = [None]
    def walk(node):
        for c in node.get('childFrames', []):
            f = c.get('frame', {})
            if 'h5api' in f.get('url', '') and 'punish' in f.get('url', ''):
                pfid[0] = f.get('id', ''); return
            walk(c)
    walk(ftree)
    pfid = pfid[0]
    if not pfid:
        print("  ❌ 未找到punish frame"); return False

    iso = cdp('Page.createIsolatedWorld', {'frameId': pfid})
    ctx = iso.get('result', {}).get('executionContextId')

    ox, oy = get_offset()

    for attempt in range(1, 7):
        r = cdp('Runtime.evaluate', {
            'expression': """(function(){var s=document.querySelector('[id*="nc_1_n1z"]');var t=document.querySelector('[id*="nc_1__scale_text"]');if(!s||!t){var w=document.querySelector('[id*="nc_1_wrapper"]');if(w&&(w.innerHTML||'').indexOf('errloading')!==-1)return JSON.stringify({e:'errloading'});return JSON.stringify({f:false});}var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();return JSON.stringify({x:Math.round(sr.x+sr.width/2),y:Math.round(sr.y+sr.height/2),d:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()""",
            'contextId': ctx, 'returnByValue': True
        })
        sl = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

        if sl.get('e') == 'errloading':
            # Get errloading position in iframe
            er = cdp('Runtime.evaluate', {
                'expression': """(function(){var e=document.querySelector('.errloading');if(!e)return JSON.stringify({f:false});var r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()""",
                'contextId': ctx, 'returnByValue': True
            })
            ep = json.loads(er.get('result', {}).get('result', {}).get('value', '{}'))
            if ep.get('x'):
                # Get iframe screen position
                ip = cdp('Runtime.evaluate', {
                    'expression': """(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({f:false});})()""",
                    'returnByValue': True
                })
                ip2 = json.loads(ip.get('result', {}).get('result', {}).get('value', '{}'))
                ex = int(ip2.get('x', 397) + ep['x'] + ox)
                ey = int(ip2.get('y', 181) + ep['y'] + oy)
                x11_click(ex, ey)
                print(f"  errloading恢复 clk=({ex},{ey})")
                time.sleep(3)
            continue

        if not sl.get('x'):
            if not body_has('请拖动') and not has_captcha_iframe():
                print("  ✅ 验证码已消失!"); return True
            time.sleep(2); continue

        # Get iframe screen position
        ip = cdp('Runtime.evaluate', {
            'expression': """(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({});})()""",
            'returnByValue': True
        })
        ip2 = json.loads(ip.get('result', {}).get('result', {}).get('value', '{}'))

        sx = ip2.get('x', 397) + sl['x'] + ox
        sy = ip2.get('y', 181) + sl['y'] + oy
        dist = sl['d']

        print(f"  尝试{attempt}: screen({sx},{sy}) dist={dist}")

        # Approach
        ax = sx - random.randint(35, 55)
        ay = sy + random.randint(-10, 10)
        for i in range(14):
            p = (i + 1) / 14
            x11_move(int(ax + (sx - ax) * p), int(ay + (sy - ay) * p + math.sin(i * 0.5) * 5))
            time.sleep(0.015 + random.random() * 0.02)
        x11_move(sx, sy); time.sleep(0.25 + random.random() * 0.35)
        x11_down(); time.sleep(0.03)

        pts = 300 + random.randint(40, 70)
        total_t = 3.2 + random.random() * 2.3
        for i in range(pts):
            p = i / pts
            if p < 0.08: e = (p / 0.08) ** 2 * 0.08
            elif p < 0.88: e = 0.08 + (p - 0.08) * 0.84
            else: r2 = (1 - p) / 0.12; e = 1 - r2 * r2 * 0.12
            e += (random.random() - 0.5) * 0.005
            x = int(sx + dist * e)
            yj = math.sin(p * math.pi * 3.1) * 2.5 + math.sin(p * math.pi * 7.3) * 0.6 + math.sin(p * math.pi * 13.7) * 0.3
            if random.random() < 0.02: yj += (random.random() - 0.5) * 8
            y = int(sy + yj)
            x11_move(x, y)
            time.sleep(max(0.002, total_t / pts * (0.6 + random.random() * 0.8)))
        x11_move(int(sx + dist), int(sy)); time.sleep(0.05)
        x11_move(int(sx + dist + random.uniform(1, 4)), int(sy + random.randint(-1, 1))); time.sleep(0.04)
        x11_move(int(sx + dist), int(sy)); time.sleep(0.05)
        time.sleep(0.18 + random.random() * 0.25)
        x11_up()
        print(f"  拖拽完成 (pts={pts}, t={total_t:.1f}s)")
        time.sleep(4)

        if not body_has('请拖动') and not has_captcha_iframe():
            print(f"  ✅ 尝试{attempt}验证成功!"); return True

    return False

# ---- DTS click helper ----
def dts_click(vx, vy, label=""):
    ox, oy = get_offset()
    sx, sy = vx + ox, vy + oy
    print(f"  xdotool click '{label}' @ screen({sx},{sy})")
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.4)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    time.sleep(1)

# ====================
# 10-STEP TEST FLOW
# ====================

# Step 1+2: Environment is clean, Chrome is running

# Step 3: Verify on taobao.com
print("=== 步骤3: 验证淘宝首页 ===")
r = cdp('Runtime.evaluate', {'expression': 'window.location.href', 'returnByValue': True})
url = r.get('result', {}).get('result', {}).get('value', '')
print(f"  当前URL: {url[:80]}")

# Step 4: Search for keyword
print(f"\n=== 步骤4: 搜索关键词 '{KEYWORD}' ===")
enc = urllib.request.quote(KEYWORD)
cdp('Page.navigate', {'url': f'https://s.taobao.com/search?q={enc}'})
time.sleep(8)

# Check for captcha after navigation
for i in range(6):
    time.sleep(5)
    if has_captcha_iframe():
        print(f"  ({(i+1)*5+8}s) 检测到验证码!")
        solve_captcha()
        time.sleep(5)
        continue
    if body_has('市场分析'):
        print(f"  ✅ 搜索结果已加载")
        break
    print(f"  等待中...({(i+1)*5+8}s)")

# Step 5: DTS 市场分析 → 开始分析
print("\n=== 步骤5: 店透视市场分析 → 开始分析 ===")

# Check captcha before DTS
if has_captcha_iframe():
    print("  检测到验证码!")
    solve_captcha()
    time.sleep(5)

el = find_text_exact('市场分析')
if not el.get('found'):
    # Try center of itemToolsBox area
    r = cdp('Runtime.evaluate', {
        'expression': """(function(){var el=document.querySelector('.itemToolsBox');if(!el)return JSON.stringify({f:false});el.scrollIntoView({behavior:'instant',block:'center'});var rect=el.getBoundingClientRect();return JSON.stringify({vx:Math.round(rect.x+rect.width/2),vy:Math.round(rect.y+rect.height/2)});})()""",
        'returnByValue': True
    })
    tools = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
    if tools.get('vx'):
        el = tools
    else:
        # Default: "市场分析" at viewport(~747,302) with size 64x24 => center (779,314)
        el = {'vx': 779, 'vy': 314}
    print(f"  使用位置估计: ({el['vx']},{el['vy']})")

dts_click(el['vx'], el['vy'], '市场分析')

# Wait for DTS panel
for i in range(12):
    time.sleep(3)
    if body_has('开始分析'):
        print(f"  ✅ DTS面板已打开 ({(i+1)*3}s)")
        break
else:
    print("  ❌ DTS面板未打开")
    ws.close(); xd.close(); exit(1)

# Click 开始分析
el2 = find_text_exact('开始分析')
if not el2.get('found'):
    el2 = {'vx': 356, 'vy': 484}  # Default DTS 开始分析 center
dts_click(el2['vx'], el2['vy'], '开始分析')

# Wait for analysis to complete
for i in range(20):
    time.sleep(5)
    p = body_progress()
    if p:
        print(f"  ✅ 分析完成! progress={p}")
        break

# Step 6: 8轮自动加载，每轮30秒
print("\n=== 步骤6: 8轮自动加载 ===")
total_clicks = 0
for round_num in range(1, 9):
    print(f"\n  --- 第{round_num}轮 ---")
    for click_in_round in range(7):
        time.sleep(5)
        if click_in_round == 0:
            time.sleep(10)

        # Check for error
        if body_has('遇到异常') or body_has('继续加载'):
            cbtn = find_text_exact('继续加载')
            if cbtn.get('found'):
                dts_click(cbtn['vx'], cbtn['vy'], '继续加载')
                time.sleep(10)
                continue

        el = find_text_exact('自动加载')
        if not el.get('found'):
            el = find_text_exact('加载下一页')
        if not el.get('found'):
            p = body_progress()
            print(f"  加载按钮消失，完成! progress={p}")
            break

        total_clicks += 1
        dts_click(el['vx'], el['vy'], f'自动加载 R{round_num}C{click_in_round}')
        time.sleep(25)  # 等待数据加载
    else:
        continue
    break

p = body_progress()
print(f"\n  自动加载完成: {total_clicks}次点击, progress={p}")

# Step 7: 等待315秒
print("\n=== 步骤7: 等待315秒 ===")
for i in range(21):
    time.sleep(15)
    print(f"  等待{(i+1)*15}s...")
time.sleep(0)  # final check

# Step 8: 导出表格xlsx+图片链接
print("\n=== 步骤8: 导出表格 ===")
p = body_progress()
print(f"  当前数据: {p}")

old_files = set(g.glob(f'{DOWNLOAD_DIR}/*.xlsx'))

# Click 导出表格 header button in DTS panel
export_el = find_text_exact('导出表格')
if export_el.get('found'):
    dts_click(export_el['vx'], export_el['vy'], '导出表格(header)')
else:
    dts_click(1003, 210, '导出表格(估计)')

time.sleep(3)

# Wait for xlsx download
downloaded = None
for i in range(30):
    new_files = set(g.glob(f'{DOWNLOAD_DIR}/*.xlsx')) - old_files
    if new_files:
        downloaded = list(new_files)[0]
        print(f"\n  ✅ xlsx下载完成: {downloaded}")
        break
    cr = g.glob(f'{DOWNLOAD_DIR}/*.crdownload')
    if cr: print(f"  下载中...")
    time.sleep(5)

# Step 9: 验证数据完整性
print("\n=== 步骤9: 验证数据完整性 ===")
if downloaded:
    import openpyxl
    wb = openpyxl.load_workbook(downloaded)
    for name in wb.sheetnames:
        ws2 = wb[name]
        print(f"  Sheet: {name} rows={ws2.max_row} cols={ws2.max_column}")
        header = [str(c.value)[:30] if c.value else '' for c in next(ws2.iter_rows(min_row=1, max_row=1))]
        print(f"  Header: {header}")
    product_count = ws2.max_row - 1  # minus header

# Step 10: 环境清理 - just disconnect
print("\n=== 步骤10: 环境清理 ===")
ws.close()
xd.close()
print("  CDP和X11已关闭")

print(f"\n{'='*50}")
print(f"第二次测试完成")
print(f"关键词：{KEYWORD}")
print(f"导出文件：{os.path.basename(downloaded) if downloaded else 'N/A'}")
print(f"商品数量：{product_count if downloaded else 0}条")
print(f"是否有异常：{'否' if downloaded else '是，xlsx未下载'}")
print(f"{'='*50}")
