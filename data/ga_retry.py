"""errloading恢复 + 多种拟人化拖拽策略重试"""
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

# === 获取 window geometry ===
r = cmd("Runtime.evaluate", {
    "expression": "JSON.stringify({outerW:window.outerWidth, outerH:window.outerHeight, innerW:window.innerWidth, innerH:window.innerHeight, screenLeft:window.screenLeft||0, screenTop:window.screenTop||0})",
    "returnByValue": True,
})
geo = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
fl = (geo["outerW"] - geo["innerW"]) / 2
to = geo["outerH"] - geo["innerH"] - fl
ox = geo["screenLeft"] + fl
oy = geo["screenTop"] + to
print(f"window: outer={geo['outerW']}x{geo['outerH']} inner={geo['innerW']}x{geo['innerH']}")
print(f"offset: ox={ox} oy={oy}")

# === 获取 punish frame 和 context ===
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
r = cmd("Page.createIsolatedWorld", {
    "frameId": punish_fid,
    "grantUniveralAccess": False,
})
ctx_id = r.get("result", {}).get("executionContextId")
print(f"contextId: {ctx_id}")

# Helper: JS in iframe
def iframe_eval(expr):
    r = cmd("Runtime.evaluate", {
        "expression": expr,
        "contextId": ctx_id,
        "returnByValue": True,
    })
    v = r.get("result", {}).get("result", {}).get("value", "")
    try:
        return json.loads(v) if v.startswith("{") or v.startswith("[") else v
    except json.JSONDecodeError:
        return v

# Helper: JS in main page
def main_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    try:
        return json.loads(v) if v.startswith("{") or v.startswith("[") else v
    except json.JSONDecodeError:
        return v

# === STEP A: 点击 errloading 恢复 ===
print("\n[A] 检查errloading状态...")
state = iframe_eval("""JSON.stringify({
    hasErrloading: !!document.getElementById('nc_1_refresh1'),
    hasSlider: !!document.querySelector("[id*='nc_1_n1z']").closest('#nc_1_nocaptcha') ? false : !!document.querySelector("[id*='nc_1_n1z']"),
    wrapperHTML: (document.querySelector("[id*='nc_1_wrapper']")?.innerHTML||'').slice(0,200)
})""")
print(f"    {json.dumps(state, ensure_ascii=False)}")

if state and state.get("hasErrloading"):
    print("\n[B] 物理点击errloading恢复...")
    err_info = iframe_eval("""(function(){
        var e = document.getElementById('nc_1_refresh1') || document.querySelector('.errloading');
        if (!e) return null;
        var r = e.getBoundingClientRect();
        return JSON.stringify({x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)});
    })()""")
    
    err_info = json.loads(err_info) if isinstance(err_info, str) else err_info
    print(f"    errloading iframe内: {err_info}")
    
    iframe_pos = main_eval("""(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i=0; i<frames.length; i++) {
            if ((frames[i].src||'').indexOf('h5api') !== -1) {
                var r = frames[i].getBoundingClientRect();
                return JSON.stringify({x:Math.round(r.x), y:Math.round(r.y)});
            }
        }
        return JSON.stringify({found:false});
    })()""")
    
    err_screen_x = int(iframe_pos["x"] + err_info["x"] + ox)
    err_screen_y = int(iframe_pos["y"] + err_info["y"] + oy)
    print(f"    errloading屏幕: ({err_screen_x}, {err_screen_y})")
    
    libx11 = ctypes.CDLL("libX11.so.6")
    libxtest = ctypes.CDLL("libXtst.so.6")
    d = libx11.XOpenDisplay(None)
    
    libxtest.XTestFakeMotionEvent(d, 0, err_screen_x, err_screen_y, 0)
    libx11.XFlush(d)
    time.sleep(0.1)
    libxtest.XTestFakeButtonEvent(d, 1, True, 0)
    libx11.XFlush(d)
    time.sleep(0.05)
    libxtest.XTestFakeButtonEvent(d, 1, False, 0)
    libx11.XFlush(d)
    time.sleep(2.5)  # 等待iframe刷新
    
    libx11.XCloseDisplay(d)
    print(f"    已点击errloading，等待刷新...")
    
    # Check if slider is back
    new_state = iframe_eval("""JSON.stringify({
        hasSlider: !!document.querySelector("[id*='nc_1_n1z']"),
        bodyText: (document.body?.innerText||'').slice(0, 150)
    })""")
    print(f"    刷新后: {json.dumps(new_state, ensure_ascii=False)}")

# === STEP C: 多种拟人化拖拽策略 ===
print("\n[C] 开始拟人化拖拽尝试...")

# Get current slider position (may have changed after errloading restart)
slider_data = iframe_eval("""(function(){
    var s = document.querySelector("[id*='nc_1_n1z']");
    var t = document.querySelector("[id*='nc_1__scale_text']");
    if (!s || !t) return null;
    var sr = s.getBoundingClientRect();
    var tr = t.getBoundingClientRect();
    return JSON.stringify({
        sx: Math.round(sr.x + sr.width/2),
        sy: Math.round(sr.y + sr.height/2),
        dist: Math.round(tr.x + tr.width - sr.x - sr.width + 3),
        trackW: Math.round(tr.width)
    });
})()""")

if not slider_data:
    print("滑块未恢复!")
    ws.close()
    exit(0)

sd = json.loads(slider_data) if isinstance(slider_data, str) else slider_data
print(f"    滑块中心: iframe内({sd['sx']}, {sd['sy']}) 拖拽{sd['dist']}px")

iframe_pos = main_eval("""(function(){
    var frames = document.querySelectorAll('iframe');
    for (var i=0; i<frames.length; i++) {
        if ((frames[i].src||'').indexOf('h5api') !== -1) {
            var r = frames[i].getBoundingClientRect();
            return JSON.stringify({x:Math.round(r.x), y:Math.round(r.y)});
        }
    }
    return JSON.stringify({found:false});
})()"")

start_sx = int(iframe_pos["x"] + sd["sx"] + ox)
start_sy = int(iframe_pos["y"] + sd["sy"] + oy)
drag_d = sd["dist"]
end_sx = start_sx + drag_d

print(f"    屏幕坐标: ({start_sx},{start_sy}) -> ({end_sx},{start_sy})")

strategies = [
    {
        "name": "自然-慢速长程",
        "steps": 20,
        "easing": "ease_out_quad",
        "total_ms": 900,
        "noise_y": 4,
        "start_pause_ms": 80,
    },
    {
        "name": "自然-微颤",
        "steps": 15,
        "easing": "ease_out_cubic",
        "total_ms": 700,
        "noise_y": 5,
        "start_pause_ms": 60,
    },
    {
        "name": "模拟-紧张手抖",
        "steps": 25,
        "easing": "ease_out_quad",
        "total_ms": 1100,
        "noise_y": 6,
        "start_pause_ms": 100,
    },
]

for si, strat in enumerate(strategies):
    print(f"\n  策略{si+1}: {strat['name']} ({strat['steps']}步/{strat['total_ms']}ms)")

    libx11 = ctypes.CDLL("libX11.so.6")
    libxtest = ctypes.CDLL("libXtst.so.6")
    d = libx11.XOpenDisplay(None)

    # 移到起点
    libxtest.XTestFakeMotionEvent(d, 0, start_sx, start_sy, 0)
    libx11.XFlush(d)
    sp = strat["start_pause_ms"] / 1000.0
    time.sleep(sp * (0.8 + random.random() * 0.4))

    # 按下
    libxtest.XTestFakeButtonEvent(d, 1, True, 0)
    libx11.XFlush(d)
    time.sleep(0.03 + random.random() * 0.03)

    steps = strat["steps"]
    total_ms = strat["total_ms"]
    noise_y = strat["noise_y"]

    # 预计算每步的目标位置和延迟
    delays = []
    targets_x = []
    # 生成变速延迟分布
    raw_delays = []
    for i in range(steps):
        progress = i / (steps - 1) if steps > 1 else 1
        if strat["easing"] == "ease_out_quad":
            eased = 1 - (1 - progress) ** 2
        elif strat["easing"] == "ease_out_cubic":
            eased = 1 - (1 - progress) ** 3
        else:
            eased = progress
        raw_delays.append(0.5 + eased * 2.0)  # 前慢后快权重
    total_weight = sum(raw_delays)
    for i in range(steps):
        progress = i / (steps - 1) if steps > 1 else 1
        if strat["easing"] == "ease_out_quad":
            eased = 1 - (1 - progress) ** 2
        elif strat["easing"] == "ease_out_cubic":
            eased = 1 - (1 - progress) ** 3
        else:
            eased = progress
        targets_x.append(int(start_sx + drag_d * eased))
        delays.append(total_ms * raw_delays[i] / total_weight / 1000.0)

    # 执行拖拽
    for i in range(steps):
        x = targets_x[i]
        y = start_sy + random.randint(-noise_y, noise_y)
        libxtest.XTestFakeMotionEvent(d, 0, x, y, 0)
        libx11.XFlush(d)
        time.sleep(delays[i])

    # 终点微停留再松手
    time.sleep(0.05 + random.random() * 0.05)
    libxtest.XTestFakeButtonEvent(d, 1, False, 0)
    libx11.XFlush(d)
    time.sleep(0.5)
    libx11.XCloseDisplay(d)

    # 等2秒
    time.sleep(2)

    # 验证
    result = main_eval("""(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i=0; i<frames.length; i++) {
            if ((frames[i].src||'').indexOf('h5api.m.taobao.com') !== -1) {
                var r = frames[i].getBoundingClientRect();
                return JSON.stringify({found:true, vis:r.width>0&&r.height>0});
            }
        }
        return JSON.stringify({found:false});
    })()""")

    iframe_state = iframe_eval("""JSON.stringify({
        hasSlider: !!document.querySelector("[id*='nc_1_n1z']"),
        hasErrloading: !!document.querySelector('.errloading'),
        bodyText: (document.body?.innerText||'').slice(0, 200)
    })""")

    print(f"    主页面punish iframe: {json.dumps(result)}")
    print(f"    iframe内状态: {json.dumps(iframe_state, ensure_ascii=False)}")

    if not result.get("found") or not result.get("vis"):
        print(f"\n    >>> ✅✅✅ 验证通过! 策略: {strat['name']} ✅✅✅")
        r = cmd("Page.captureScreenshot", {"format": "png"})
        with open("/home/lab-admin/price-monitor/data/ga_win.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        ws.close()
        exit(0)

    # If errloading, click to reset
    if iframe_state and iframe_state.get("hasErrloading"):
        print(f"    → errloading恢复...")
        err_info = iframe_eval("""(function(){
            var e = document.querySelector('.errloading');
            if (!e) return null;
            var r = e.getBoundingClientRect();
            return JSON.stringify({x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)});
        })()""")
        if err_info and err_info != "null":
            ei = json.loads(err_info) if isinstance(err_info, str) else err_info
            err_sx = int(iframe_pos["x"] + ei["x"] + ox)
            err_sy = int(iframe_pos["y"] + ei["y"] + oy)

            libx11 = ctypes.CDLL("libX11.so.6")
            libxtest = ctypes.CDLL("libXtst.so.6")
            d = libx11.XOpenDisplay(None)
            libxtest.XTestFakeMotionEvent(d, 0, err_sx, err_sy, 0)
            libx11.XFlush(d)
            time.sleep(0.1)
            libxtest.XTestFakeButtonEvent(d, 1, True, 0)
            libx11.XFlush(d)
            time.sleep(0.05)
            libxtest.XTestFakeButtonEvent(d, 1, False, 0)
            libx11.XFlush(d)
            time.sleep(2.5)
            libx11.XCloseDisplay(d)

r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/ga_final.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

ws.close()
print("\n[DONE] 所有策略已尝试")
