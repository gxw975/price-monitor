"""python-xlib + CDP 完整滑块解决方案"""
import json, urllib.request, websocket, time, random, os, subprocess

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

# === CDP connection ===
CDP = "http://127.0.0.1:9223/json"
targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())
ws = None
for t in targets:
    if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
        ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=15)
        break
ws.settimeout(8)
mid = [0]
def cmd(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    for _ in range(80):
        r = json.loads(ws.recv())
        if r.get("id") == mid[0]:
            return r
    return {}

for d in ("Runtime", "Page"):
    cmd(f"{d}.enable")

# === Window geometry ===
ox, oy = 66, 119

# === python-xlib setup ===
from Xlib import X, display as xdisplay
from Xlib.ext import xtest
disp = xdisplay.Display()

def xlib_move(x, y):
    xtest.fake_input(disp, X.MotionNotify, x=x, y=y)
    disp.sync()

def xlib_click(button=1, down=True):
    xtest.fake_input(disp, X.ButtonPress if down else X.ButtonRelease, detail=button)
    disp.sync()

def xlib_scroll(up=True):
    btn = 4 if up else 5
    xtest.fake_input(disp, X.ButtonPress, detail=btn)
    disp.sync()
    xtest.fake_input(disp, X.ButtonRelease, detail=btn)
    disp.sync()

def xlib_drag(start_x, start_y, end_x, end_y, steps=15, total_ms=650):
    """拟人化拖拽"""
    # Approach from left
    app_x = start_x - random.randint(60, 100)
    app_y = start_y + random.randint(-10, 10)
    xlib_move(app_x, app_y)
    time.sleep(0.02)
    
    for i in range(4):
        p = (i+1)/4
        ax = int(app_x + (start_x - app_x) * p)
        ay = int(app_y + (start_y - app_y) * p)
        xlib_move(ax, ay)
        time.sleep(0.02)
    
    xlib_move(start_x, start_y)
    time.sleep(0.06 + random.random() * 0.04)
    
    # Press
    xlib_click(1, True)
    time.sleep(0.03 + random.random() * 0.02)
    
    # Drag
    drag_dist = end_x - start_x
    weights = []
    for i in range(steps):
        p = (i+1)/steps
        w = 0.5 + (1-p) * 1.5
        weights.append(w)
    total_w = sum(weights)
    
    for i in range(steps):
        p = (i+1)/steps
        eased = 1 - (1-p) ** 2.2
        x = int(start_x + drag_dist * eased)
        y = start_y + random.randint(-3, 3) if p < 0.85 else start_y + random.randint(-1, 1)
        xlib_move(x, y)
        delay = total_ms * weights[i] / total_w / 1000.0
        time.sleep(max(0.005, delay))
    
    time.sleep(0.05 + random.random() * 0.03)
    xlib_click(1, False)
    time.sleep(0.5)

# === Helper functions ===
def main_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try: return json.loads(v)
        except: return v
    return v

def iframe_eval(expr, ctx):
    r = cmd("Runtime.evaluate", {"expression": expr, "contextId": ctx, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try: return json.loads(v)
        except: return v
    return v

# === Wait for page and captcha to fully load ===
print("[1] 等待页面完全加载...")
time.sleep(3)

# Scroll a bit to warm up
for _ in range(3):
    xlib_scroll(False)
    time.sleep(0.3 + random.random() * 0.2)

# Activate window
WID = subprocess.run(["xdotool", "search", "--name", "淘宝"], capture_output=True, text=True,
                    env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"}).stdout.strip().split("\n")[0]
subprocess.run(["xdotool", "windowactivate", WID, "windowfocus", WID],
              env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})

# Move mouse around naturally
for _ in range(8):
    rx = random.randint(200, 900) + int(ox)
    ry = random.randint(100, 600) + int(oy)
    xlib_move(rx, ry)
    time.sleep(random.uniform(0.03, 0.08))

print("[2] 检测captcha...")
capt = main_eval("""(function(){
    var fs = document.querySelectorAll('iframe');
    for (var i=0;i<fs.length;i++) {
        if ((fs[i].src||'').indexOf('h5api.m.taobao.com') !== -1) {
            var r = fs[i].getBoundingClientRect();
            return JSON.stringify({captcha:true, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
        }
    }
    return JSON.stringify({captcha:false});
})()""")
print(f"  captcha: {json.dumps(capt, ensure_ascii=False) if capt else 'None'}")

if not capt or not capt.get("captcha"):
    print("无验证码！截图保存。")
    r = cmd("Page.captureScreenshot", {"format": "png"})
    import base64
    with open("/home/lab-admin/price-monitor/data/no_captcha.png", "wb") as f:
        f.write(base64.b64decode(r["result"]["data"]))
    ws.close()
    disp.close()
    exit(0)

# Get punish frame
r = cmd("Page.getFrameTree")
ft = r.get("result", {}).get("frameTree", {})
punish_fid = None
def find_punish(node):
    global punish_fid
    for c in node.get("childFrames", []):
        f = c.get("frame", {})
        if "h5api.m.taobao.com" in f.get("url", "") and "punish" in f.get("url", ""):
            punish_fid = f.get("id", "")
            return True
        if find_punish(c):
            return True
    return False
if not find_punish(ft):
    print("No punish frame!")
    ws.close()
    disp.close()
    exit(0)

r = cmd("Page.createIsolatedWorld", {"frameId": punish_fid})
ctx = r.get("result", {}).get("executionContextId")
print(f"  contextId: {ctx}")

# Check captcha state
body_text = iframe_eval('document.body?.innerText?.slice(0,200) || "EMPTY"', ctx)
print(f"  iframe body: {body_text[:100] if isinstance(body_text, str) else body_text}")

# === SOLVE LOOP ===
for attempt in range(1, 5):
    print(f"\n[3] Attempt {attempt}...")
    
    # Recover errloading
    st = iframe_eval('JSON.stringify({hasErr:!!document.querySelector(".errloading")})', ctx)
    if st and st.get("hasErr"):
        print("  recover errloading...")
        err = iframe_eval('(function(){var e=document.querySelector(".errloading");if(!e)return null;var r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()', ctx)
        ex = int(capt["x"] + err["x"] + ox)
        ey = int(capt["y"] + err["y"] + oy)
        xlib_move(ex, ey)
        time.sleep(0.1)
        xlib_click(1, True)
        time.sleep(0.05)
        xlib_click(1, False)
        time.sleep(2.5)
    
    # Get slider position
    sd = iframe_eval('(function(){var s=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]");var t=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1__scale_text" + String.fromCharCode(39) + "]");if(!s||!t)return null;var sr=s.getBoundingClientRect();var tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()', ctx)
    
    if not sd:
        print("  无滑块！")
        continue
    
    ssx = int(capt["x"] + sd["sx"] + ox)
    ssy = int(capt["y"] + sd["sy"] + oy)
    dist = sd["dist"]
    esx = ssx + dist
    
    print(f"  start=({ssx},{ssy}) end=({esx},{ssy}) dist={dist}")
    
    # Do the drag with python-xlib
    xlib_drag(ssx, ssy, esx, ssy, steps=12+attempt*2, total_ms=500+attempt*80)
    
    time.sleep(2.5)
    
    # Check result
    res = main_eval("""(function(){
        var fs = document.querySelectorAll('iframe');
        for (var i=0;i<fs.length;i++) {
            if ((fs[i].src||'').indexOf('h5api.m.taobao.com') !== -1) {
                var r = fs[i].getBoundingClientRect();
                return JSON.stringify({found:true, vis:r.width>0&&r.height>0});
            }
        }
        return JSON.stringify({found:false});
    })()""")
    
    ifr = iframe_eval('JSON.stringify({hasErr:!!document.querySelector(".errloading"),hasSlider:!!document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]"),body:(document.body?.innerText||"").slice(0,100)})', ctx)
    
    print(f"  result: main={res}")
    print(f"  iframe: {ifr}")
    
    if not res.get("found") or not res.get("vis"):
        print(f"\n>>> ✅✅✅ PASS! (attempt {attempt}) ✅✅✅")
        r = cmd("Page.captureScreenshot", {"format": "png"})
        import base64
        with open("/home/lab-admin/price-monitor/data/win_xlib.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        break

r = cmd("Page.captureScreenshot", {"format": "png"})
import base64
with open("/home/lab-admin/price-monitor/data/last_xlib.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

ws.close()
disp.close()
print("\n[DONE]")
