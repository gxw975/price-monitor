"""errloading恢复 + 自然化鼠标轨迹"""
import json, urllib.request, websocket, time, base64, random, ctypes, os

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

CDP = "http://127.0.0.1:9223/json"
targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())

page_ws = None
for t in targets:
    if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
        page_ws = t["webSocketDebuggerUrl"]
        break

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

# geometry
r = cmd("Runtime.evaluate", {
    "expression": "JSON.stringify({outerW:window.outerWidth, outerH:window.outerHeight, innerW:window.innerWidth, innerH:window.innerHeight, screenLeft:window.screenLeft||0, screenTop:window.screenTop||0})",
    "returnByValue": True,
})
geo = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
fl = (geo["outerW"] - geo["innerW"]) / 2
to = geo["outerH"] - geo["innerH"] - fl
ox = geo["screenLeft"] + fl
oy = geo["screenTop"] + to
print(f"offset: ox={ox} oy={oy}")

# frame tree + contextId
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

find_punish(ft)
r = cmd("Page.createIsolatedWorld", {"frameId": punish_fid, "grantUniveralAccess": False})
ctx_id = r.get("result", {}).get("executionContextId")
print(f"contextId: {ctx_id}")

def iframe_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "contextId": ctx_id, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return v
    return v

def main_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return v
    return v

# ============ errloading recovery ============
state = iframe_eval('JSON.stringify({hasErr:!!document.querySelector(".errloading"),hasSlider:!!document.querySelector("[id*=\'nc_1_n1z\']")})')
print(f"初始状态: {state}")

def click_errloading():
    err = iframe_eval('(function(){var e=document.querySelector(".errloading");if(!e)return null;var r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()')
    if not err:
        print("无errloading")
        return False
    ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')
    sx = int(ip["x"] + err["x"] + ox)
    sy = int(ip["y"] + err["y"] + oy)
    print(f"点击errloading屏幕:({sx},{sy})")
    libx11 = ctypes.CDLL("libX11.so.6")
    libxtest = ctypes.CDLL("libXtst.so.6")
    d = libx11.XOpenDisplay(None)
    libxtest.XTestFakeMotionEvent(d, 0, sx, sy, 0)
    libx11.XFlush(d)
    time.sleep(0.1)
    libxtest.XTestFakeButtonEvent(d, 1, True, 0)
    libx11.XFlush(d)
    time.sleep(0.08)
    libxtest.XTestFakeButtonEvent(d, 1, False, 0)
    libx11.XFlush(d)
    time.sleep(2.5)
    libx11.XCloseDisplay(d)
    return True

if state and state.get("hasErr"):
    click_errloading()

state2 = iframe_eval('JSON.stringify({hasSlider:!!document.querySelector("[id*=\'nc_1_n1z\']"),body:(document.body?.innerText||"").slice(0,80)})')
print(f"恢复后: {state2}")

# ============ get slider coords ============
sd = iframe_eval('(function(){var s=document.querySelector("[id*=\'nc_1_n1z\']");var t=document.querySelector("[id*=\'nc_1__scale_text\']");if(!s||!t)return null;var sr=s.getBoundingClientRect();var tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()')
ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')

start_sx = int(ip["x"] + sd["sx"] + ox)
start_sy = int(ip["y"] + sd["sy"] + oy)
drag_d = sd["dist"]
end_sx = start_sx + drag_d
print(f"滑块屏幕:({start_sx},{start_sy}) dist={drag_d}")

# ============ 自然化拖拽策略 ============
# 关键：鼠标必须从附近逐步移动过来，不能直接出现在滑块上
# X11 XTest 产生的是 "受信任事件"

def natural_drag(label, steps, total_ms, easing_power, noise_range, approach_from_left):
    print(f"\n[{label}] {steps}步/{total_ms}ms, approach={approach_from_left}px")

    libx11 = ctypes.CDLL("libX11.so.6")
    libxtest = ctypes.CDLL("libXtst.so.6")
    d = libx11.XOpenDisplay(None)

    # Phase 1: 从左边缓缓接近滑块（模拟人类找到滑块）
    approach_steps = 4
    approach_start_x = start_sx - approach_from_left
    approach_start_y = start_sy + random.randint(-8, 8)
    for i in range(approach_steps):
        p = (i + 1) / approach_steps
        ax = int(approach_start_x + (start_sx - approach_start_x) * p)
        ay = int(approach_start_y + (start_sy - approach_start_y) * p)
        libxtest.XTestFakeMotionEvent(d, 0, ax, ay, 0)
        libx11.XFlush(d)
        time.sleep(0.04 + random.random() * 0.03)

    # Phase 2: 停在滑块上短暂停顿
    libxtest.XTestFakeMotionEvent(d, 0, start_sx, start_sy, 0)
    libx11.XFlush(d)
    time.sleep(0.08 + random.random() * 0.06)

    # Phase 3: 按下
    libxtest.XTestFakeButtonEvent(d, 1, True, 0)
    libx11.XFlush(d)
    time.sleep(0.04 + random.random() * 0.04)

    # Phase 4: 分步拖拽，含微停顿和Y轴噪声
    delta_ms = []
    for i in range(steps):
        p = i / (steps - 1) if steps > 1 else 1
        w = 0.5 + (1 - p) * 1.5  # 前快后慢的权重
        delta_ms.append(w)
    total_w = sum(delta_ms)

    last_x = start_sx
    for i in range(steps):
        p = (i + 1) / steps
        eased = 1 - (1 - p) ** easing_power
        x = int(start_sx + drag_d * eased)
        noise = 0
        if p < 0.3:
            noise = random.randint(-1, 1)
        elif p < 0.7:
            noise = random.randint(-noise_range, noise_range)
        else:
            noise = random.randint(-noise_range//2, noise_range//2)
        y = start_sy + noise

        # 偶发微停顿
        if random.random() < 0.2:
            time.sleep(0.01)

        libxtest.XTestFakeMotionEvent(d, 0, x, y, 0)
        libx11.XFlush(d)

        delay = total_ms * delta_ms[i] / total_w / 1000.0
        # 添加随机抖动
        delay += random.uniform(-0.005, 0.005)
        time.sleep(max(0.003, delay))

    # Phase 5: 停留再松手
    time.sleep(0.06 + random.random() * 0.04)
    libxtest.XTestFakeButtonEvent(d, 1, False, 0)
    libx11.XFlush(d)
    time.sleep(0.5)
    libx11.XCloseDisplay(d)

    # 等结果
    time.sleep(2)

    res = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api.m.taobao.com")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({found:true,vis:r.width>0&&r.height>0});}}return JSON.stringify({found:false});})()')
    js_expr = 'JSON.stringify({hasErr:!!document.querySelector(".errloading"),hasSlider:!!document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]"),body:(document.body?.innerText||"").slice(0,100)})'
    if_res = iframe_eval(js_expr)
    print(f"    主页: {res}")
    print(f"    iframe: {if_res}")

    if not res.get("found") or not res.get("vis"):
        return True  # success

    if if_res and if_res.get("hasErr"):
        click_errloading()
    return False

# 尝试多种参数
attempts = [
    ("自然A", 15, 650, 2.0, 5, 80),
    ("自然B", 12, 700, 2.5, 4, 100),
    ("自然C", 20, 900, 1.8, 6, 60),
    ("自然D", 10, 600, 3.0, 3, 120),
]

for args in attempts:
    result = natural_drag(*args)
    if result:
        print("\n>>> ✅✅✅ 验证通过! ✅✅✅")
        r = cmd("Page.captureScreenshot", {"format": "png"})
        with open("/home/lab-admin/price-monitor/data/ga_win.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        ws.close()
        exit(0)
    time.sleep(1)

r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/ga_final2.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

ws.close()
print("\n[DONE]")
