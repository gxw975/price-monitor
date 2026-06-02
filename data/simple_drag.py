"""最简X11 XTest拖拽 — 去掉所有花里胡哨"""
import json, urllib.request, websocket, time, base64, random, ctypes, os, math

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

CDP = "http://127.0.0.1:9223/json"
targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())
ws = None
for t in targets:
    if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
        ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=15)
        break
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

r = cmd("Runtime.evaluate", {
    "expression": "JSON.stringify({ow:window.outerWidth, oh:window.outerHeight, iw:window.innerWidth, ih:window.innerHeight, sl:window.screenLeft||0, st:window.screenTop||0})",
    "returnByValue": True,
})
g = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
ox = g["sl"] + (g["ow"] - g["iw"]) / 2
oy = g["st"] + g["oh"] - g["ih"] - (g["ow"] - g["iw"]) / 2

# frame + contextId
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

def iframe_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "contextId": ctx_id, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except:
            return v
    return v

def main_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except:
            return v
    return v

libx11 = ctypes.CDLL("libX11.so.6")
libxtest = ctypes.CDLL("libXtst.so.6")

def xmove(d, x, y):
    libxtest.XTestFakeMotionEvent(d, 0, int(x), int(y), 0)

def xflush(d):
    libx11.XFlush(d)

def xclick(d, down):
    libxtest.XTestFakeButtonEvent(d, 1, down, 0)

# ============ Main loop ============
def get_slider_screen():
    sd = iframe_eval('(function(){var s=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]");var t=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1__scale_text" + String.fromCharCode(39) + "]");if(!s||!t)return null;var sr=s.getBoundingClientRect();var tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()')
    ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')
    if not sd or not ip or sd is True:
        return None, None, None
    sx = int(ip["x"] + sd["sx"] + ox)
    sy = int(ip["y"] + sd["sy"] + oy)
    return sx, sy, sd["dist"]

def check_result():
    res = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api.m.taobao.com")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({found:true,vis:r.width>0&&r.height>0});}}return JSON.stringify({found:false});})()')
    return not (res.get("found") and res.get("vis"))

def recover_err():
    js = 'JSON.stringify({hasErr:!!document.querySelector(".errloading")})' 
    st = iframe_eval(js)
    if st and st.get("hasErr"):
        print("  recover errloading...")
        err = iframe_eval('(function(){var e=document.querySelector(".errloading");if(!e)return null;var r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()')
        ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')
        ex = int(ip["x"] + err["x"] + ox)
        ey = int(ip["y"] + err["y"] + oy)
        d = libx11.XOpenDisplay(None)
        xmove(d, ex, ey)
        xflush(d)
        time.sleep(0.1)
        xclick(d, True)
        xflush(d)
        time.sleep(0.05)
        xclick(d, False)
        xflush(d)
        time.sleep(2.5)
        libx11.XCloseDisplay(d)

# Recover from any errloading
recover_err()

sx, sy, dist = get_slider_screen()
if sx is None:
    print("No slider found!")
    ws.close()
    exit(0)

print(f"滑块屏幕: ({sx},{sy}) dist={dist}")

# ======= Try different drag strategies =======
attempts = []

# Strategy 1: Simple sine wave
def build_strat1():
    steps = 20
    moves = []
    for i in range(steps):
        p = (i + 1) / steps
        eased = 1 - (1 - p) ** 2
        x = int(sx + dist * eased)
        y_off = int(4 * math.sin(p * math.pi * 3) * (1 - p))
        y = sy + y_off
        moves.append((x, y))
    return moves, 0.6

# Strategy 2: Two-phase (slow start, fast finish)  
def build_strat2():
    steps = 15
    moves = []
    for i in range(steps):
        p = (i + 1) / steps
        if p < 0.3:
            eased = p * 0.3 / 0.3 * 0.2
        else:
            eased = 0.2 + 0.8 * ((p - 0.3) / 0.7)
        x = int(sx + dist * eased)
        y = sy + random.randint(-2, 2)
        moves.append((x, y))
    return moves, 0.5

# Strategy 3: Jerky with pauses
def build_strat3():
    segments = [(0.0, 0.0), (0.15, 0.08), (0.16, 0.08), (0.35, 0.28), (0.36, 0.28),
                 (0.6, 0.52), (0.61, 0.52), (0.85, 0.82), (0.86, 0.82), (1.0, 1.0)]
    moves = []
    for pp, ep in segments:
        x = int(sx + dist * ep)
        y = sy + random.randint(-3, 3)
        moves.append((x, y))
    return moves, 0.8

# Strategy 4: Very simple, moderate speed
def build_strat4():
    steps = 12
    moves = []
    for i in range(steps):
        p = (i + 1) / steps
        eased = p ** 0.7
        x = int(sx + dist * eased)
        y = sy + random.randint(-1, 1)
        moves.append((x, y))
    return moves, 0.45

# Strategy 5: Very fast, few steps
def build_strat5():
    steps = 8
    moves = []
    for i in range(steps):
        p = (i + 1) / steps
        eased = 1 - (1 - p) ** 1.5
        x = int(sx + dist * eased)
        y = sy + random.randint(-1, 1)
        moves.append((x, y))
    return moves, 0.25

attempts = [
    ("S1-sine", build_strat1),
    ("S2-2phase", build_strat2),
    ("S3-jerky", build_strat3),
    ("S4-simple", build_strat4),
    ("S5-fast", build_strat5),
]

for label, builder in attempts:
    print(f"\n[{label}]")
    
    moves, total_time = builder()
    
    d = libx11.XOpenDisplay(None)
    
    # Approach from random position
    app_x = sx - random.randint(60, 140)
    app_y = sy + random.randint(-15, 15)
    xmove(d, app_x, app_y)
    xflush(d)
    time.sleep(0.02)
    
    # Smooth approach to slider
    for i in range(3):
        p = (i + 1) / 3
        ax = int(app_x + (sx - app_x) * p)
        ay = int(app_y + (sy - app_y) * p)
        xmove(d, ax, ay)
        xflush(d)
        time.sleep(0.025)
    
    xmove(d, sx, sy)
    xflush(d)
    time.sleep(0.05 + random.random() * 0.05)
    
    # Press
    xclick(d, True)
    xflush(d)
    time.sleep(0.02)
    
    # Drag: send all moves with calculated timing
    num_moves = len(moves)
    for i, (mx, my) in enumerate(moves):
        xmove(d, mx, my)
        xflush(d)
        # Variable delay
        p = (i + 1) / num_moves
        if p < 0.2:
            delay = 0.015 + random.random() * 0.01
        elif p < 0.6:
            delay = 0.01 + random.random() * 0.01
        else:
            delay = 0.015 + random.random() * 0.015
        time.sleep(delay)
    
    # Final position hold
    time.sleep(0.05)
    xclick(d, False)
    xflush(d)
    time.sleep(0.5)
    
    libx11.XCloseDisplay(d)
    
    # Wait and check
    time.sleep(2)
    
    res = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api.m.taobao.com")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({found:true,vis:r.width>0&&r.height>0});}}return JSON.stringify({found:false});})()')
    if_res = iframe_eval('JSON.stringify({hasErr:!!document.querySelector(".errloading"),hasSlider:!!document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]"),body:(document.body?.innerText||"").slice(0,100)})')
    print(f"  res={res} iframe={if_res}")
    
    if check_result():
        print(f"\n>>> ✅✅✅ PASS! {label} ✅✅✅")
        r = cmd("Page.captureScreenshot", {"format": "png"})
        with open("/home/lab-admin/price-monitor/data/ga_win.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        ws.close()
        exit(0)
    
    recover_err()
    time.sleep(1)

r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/ga_final4.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

ws.close()
print("\n[DONE]")
