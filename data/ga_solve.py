"""按照GA经验文档精确破解滑块验证"""
import json, urllib.request, websocket, time, base64, random, ctypes, os

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

CDP = "http://127.0.0.1:9223/json"
targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())

# Find target page and get browser-level WS (for window maximize)
browser_ws = None
page_ws = None
for t in targets:
    if "webSocketDebuggerUrl" in t and "browser" in t.get("url", ""):
        browser_ws = t["webSocketDebuggerUrl"]
    if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
        page_ws = t["webSocketDebuggerUrl"]
        page_id = t.get("id", "")

print(f"Page ID: {page_id}")

ws = websocket.create_connection(page_ws, timeout=15)
ws.settimeout(10)
mid = [0]
def cmd(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    for _ in range(80):
        r = json.loads(ws.recv())
        if r.get("id") == mid[0]:
            return r
    return {}

for d in ("Runtime", "Page", "DOM", "Input"):
    cmd(f"{d}.enable")

# === STEP 0: 最大化窗口（经验文档铁律）===
print("[0] 最大化窗口...")
r = cmd("Browser.getWindowForTarget", {"targetId": page_id})
win_id = r.get("result", {}).get("windowId")
print(f"    windowId: {win_id}")

r = cmd("Browser.setWindowBounds", {
    "windowId": win_id,
    "bounds": {"windowState": "maximized"}
})
print(f"    maximize: ok")
time.sleep(1)

# Verify geometry
r = cmd("Runtime.evaluate", {
    "expression": "JSON.stringify({outerW:window.outerWidth, outerH:window.outerHeight, innerW:window.innerWidth, innerH:window.innerHeight, screenW:window.screen.width, screenH:window.screen.height, screenLeft:window.screenLeft||0, screenTop:window.screenTop||0})",
    "returnByValue": True,
})
geo = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"    窗口: outer={geo['outerW']}x{geo['outerH']} inner={geo['innerW']}x{geo['innerH']}")
print(f"    屏幕: {geo['screenW']}x{geo['screenH']}")
print(f"    screenLeft={geo['screenLeft']} screenTop={geo['screenTop']}")

# === STEP 1: CDP getFrameTree 找到 punish iframe ===
print("\n[1] FrameTree查找punish iframe...")
r = cmd("Page.getFrameTree")
ft = r.get("result", {}).get("frameTree", {})

punish_fid = None
def find_punish(node):
    global punish_fid
    f = node.get("frame", {})
    if "h5api.m.taobao.com" in f.get("url", "") and "punish" in f.get("url", ""):
        punish_fid = f.get("id", "")
        return True
    for c in node.get("childFrames", []):
        if find_punish(c):
            return True
    return False

found = find_punish(ft)
print(f"    found: {found}, frameId: {punish_fid}")

if not punish_fid:
    print("NO PUNISH FRAME!")
    ws.close()
    exit(0)

# === STEP 2: createIsolatedWorld → 获取 executionContextId ===
print("\n[2] 创建isolated world...")
r = cmd("Page.createIsolatedWorld", {
    "frameId": punish_fid,
    "grantUniveralAccess": False,
})
ctx_id = r.get("result", {}).get("executionContextId")
print(f"    executionContextId: {ctx_id}")

if not ctx_id:
    print("NO CONTEXT ID!")
    ws.close()
    exit(0)

# === STEP 3: 在iframe内执行JS获取滑块坐标 ===
print("\n[3] 读取滑块精确坐标...")
r = cmd("Runtime.evaluate", {
    "expression": """JSON.stringify((function(){
        var s = document.querySelector("[id*='nc_1_n1z']") || document.getElementById('nc_1_n1z');
        var t = document.querySelector("[id*='nc_1__scale_text']") || document.getElementById('nc_1__scale_text');
        
        var result = {};
        if (s) {
            var sr = s.getBoundingClientRect();
            result.slider = {x:Math.round(sr.x), y:Math.round(sr.y), w:Math.round(sr.width), h:Math.round(sr.height)};
            result.slider_center_x = Math.round(sr.x + sr.width/2);
            result.slider_center_y = Math.round(sr.y + sr.height/2);
        }
        if (t) {
            var tr = t.getBoundingClientRect();
            result.track = {x:Math.round(tr.x), y:Math.round(tr.y), w:Math.round(tr.width), h:Math.round(tr.height)};
        }
        if (s && t) {
            var sr2 = s.getBoundingClientRect(), tr2 = t.getBoundingClientRect();
            result.distance = Math.round(tr2.x + tr2.width - sr2.x - sr2.width + 3);
        }
        result.allIds = Array.from(document.querySelectorAll('[id]')).map(function(e){return e.id}).slice(0, 20);
        result.bodyText = document.body ? document.body.innerText.slice(0, 200) : 'NO_BODY';
        return result;
    })())""",
    "contextId": ctx_id,
    "returnByValue": True,
})
info = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"    slider: {info.get('slider')}")
print(f"    track: {info.get('track')}")
print(f"    distance: {info.get('distance')}")
print(f"    bodyText: {info.get('bodyText', '')[:100]}")
print(f"    ids: {info.get('allIds')}")

if not info.get("slider") or not info.get("track"):
    print("滑块/滑轨未找到！iframe内容可能是主页")
    print(f"    完整info: {json.dumps(info, ensure_ascii=False)[:500]}")
    
    # Check if we got main page content
    body_text = info.get("bodyText", "")
    if "淘宝" in body_text or "搜索" in body_text or len(info.get("allIds", [])) > 50:
        print("    >>> 确认读到的是主页内容，contextId可能无效!")
        print("    >>> 尝试Runtime.discardExecutionContext + 重新enable")
    
    ws.close()
    exit(0)

# === STEP 4: 获取iframe在主页面中的视口位置 ===
print("\n[4] 获取iframe在主页面中的位置...")
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i=0; i<frames.length; i++) {
            if ((frames[i].src||'').indexOf('h5api') !== -1) {
                var r = frames[i].getBoundingClientRect();
                return JSON.stringify({x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
            }
        }
        return JSON.stringify({found:false});
    })()""",
    "returnByValue": True,
})
iframe_pos = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"    iframe视口: {json.dumps(iframe_pos)}")

# === STEP 5: 计算屏幕坐标 ===
print("\n[5] 计算屏幕坐标...")
# 视口→屏幕偏移
fl = (geo["outerW"] - geo["innerW"]) / 2
to = geo["outerH"] - geo["innerH"] - fl
ox = geo["screenLeft"] + fl
oy = geo["screenTop"] + to
print(f"    offset: ox={ox}, oy={oy} (fl={fl}, to={to}, screenLeft={geo['screenLeft']}, screenTop={geo['screenTop']})")

# 滑块在iframe内部的视口坐标
slider_iframe_x = info["slider_center_x"]
slider_iframe_y = info["slider_center_y"]

# 滑块在主页面视口中的坐标 = iframe视口位置 + 滑块在iframe内位置
slider_vp_x = iframe_pos["x"] + slider_iframe_x
slider_vp_y = iframe_pos["y"] + slider_iframe_y

# 屏幕坐标 = 视口坐标 + 偏移
slider_screen_x = int(slider_vp_x + ox)
slider_screen_y = int(slider_vp_y + oy)
drag_dist = info["distance"]
end_screen_x = slider_screen_x + drag_dist

print(f"    滑块iframe内: ({slider_iframe_x}, {slider_iframe_y})")
print(f"    滑块视口: ({slider_vp_x}, {slider_vp_y})")
print(f"    滑块屏幕: ({slider_screen_x}, {slider_screen_y})")
print(f"    拖拽距离: {drag_dist}px → 终点: ({end_screen_x}, {slider_screen_y})")

# === STEP 6: X11 XTest拟人化拖拽 ===
print("\n[6] X11 XTest拟人化拖拽...")

libx11 = ctypes.CDLL("libX11.so.6")
libxtest = ctypes.CDLL("libXtst.so.6")
d = libx11.XOpenDisplay(None)
assert d, "Cannot open display"

# 移到起点
libxtest.XTestFakeMotionEvent(d, 0, slider_screen_x, slider_screen_y, 0)
libx11.XFlush(d)
time.sleep(0.05 + random.random() * 0.05)  # 50-100ms起步停顿

# 按下
libxtest.XTestFakeButtonEvent(d, 1, True, 0)
libx11.XFlush(d)
time.sleep(0.03 + random.random() * 0.02)

# 12步拟人化拖拽（经验文档推荐）
steps = 12
for i in range(1, steps + 1):
    progress = i / steps
    # ease-out: 二次缓出 — 先快后慢
    eased = 1 - (1 - progress) ** 2
    x = int(slider_screen_x + drag_dist * eased)
    y = slider_screen_y + random.randint(-3, 3)  # Y轴微抖
    
    libxtest.XTestFakeMotionEvent(d, 0, x, y, 0)
    libx11.XFlush(d)
    
    # 变速延迟
    if i < steps // 2:
        delay = 0.02 + random.random() * 0.03  # 前段: 20-50ms
    else:
        delay = 0.04 + random.random() * 0.04  # 后段: 40-80ms
    time.sleep(delay)

# 终点停顿再松手
time.sleep(0.05 + random.random() * 0.03)
libxtest.XTestFakeButtonEvent(d, 1, False, 0)
libx11.XFlush(d)
time.sleep(0.5)

libx11.XCloseDisplay(d)
print(f"    拖拽完成: ({slider_screen_x},{slider_screen_y}) -> ({end_screen_x},{slider_screen_y})")

# === STEP 7: 等2秒后验证 ===
print("\n[7] 等待2秒验证结果...")
time.sleep(2)

r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i=0; i<frames.length; i++) {
            if ((frames[i].src||'').indexOf('h5api.m.taobao.com') !== -1) {
                var r = frames[i].getBoundingClientRect();
                return JSON.stringify({found:true, vis:r.width>0&&r.height>0, x:Math.round(r.x), y:Math.round(r.y)});
            }
        }
        return JSON.stringify({found:false});
    })()""",
    "returnByValue": True,
})
result = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"    punish iframe: {json.dumps(result)}")

if not result.get("found") or not result.get("vis"):
    print("\n>>> ✅✅✅ 验证通过!!! ✅✅✅")
    r = cmd("Page.captureScreenshot", {"format": "png"})
    with open("/home/lab-admin/price-monitor/data/ga_success.png", "wb") as f:
        f.write(base64.b64decode(r["result"]["data"]))
else:
    print("\n>>> ❌ 验证未通过")
    
    # 检查 errloading
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var s = document.querySelector("[id*='nc_1_n1z']");
            var w = document.querySelector("[id*='nc_1_wrapper']");
            return JSON.stringify({
                hasSlider: !!s,
                wrapperHTML: w ? (w.innerHTML||'').slice(0, 300) : 'NOT_FOUND',
                bodyText: document.body?document.body.innerText.slice(0,300):'NO_BODY'
            });
        })()""",
        "contextId": ctx_id,
        "returnByValue": True,
    })
    post = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
    print(f"    拖拽后iframe状态: {json.dumps(post, ensure_ascii=False)[:500]}")
    
    r = cmd("Page.captureScreenshot", {"format": "png"})
    with open("/home/lab-admin/price-monitor/data/ga_failed.png", "wb") as f:
        f.write(base64.b64decode(r["result"]["data"]))

ws.close()
print("\n[DONE]")
