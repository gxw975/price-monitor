"""深度诊断 - 检查DOM层级 + 尝试多种绕过方法"""
import json, urllib.request, websocket, time, base64, random, os

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

CDP = "http://127.0.0.1:9223/json"
targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())

ws_url = None
for t in targets:
    if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
        ws_url = t["webSocketDebuggerUrl"]
        break

ws = websocket.create_connection(ws_url, timeout=15)
ws.settimeout(10)
mid = [0]
def cmd(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    for _ in range(60):
        r = json.loads(ws.recv())
        if r.get("id") == mid[0]:
            return r
    return {}

for d in ("Runtime", "Page", "DOM", "Input"):
    cmd(f"{d}.enable")

# 1. Check DOM structure: is punish iframe inside J_MIDDLEWARE_FRAME_WIDGET?
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i=0; i<frames.length; i++) {
            if ((frames[i].src||'').indexOf('punish') !== -1) {
                var p = frames[i].parentElement;
                var ancestors = [];
                while (p && p !== document.body && ancestors.length < 10) {
                    ancestors.push({
                        tag: p.tagName,
                        cls: (p.className||'').toString().slice(0, 80),
                        id: p.id || '',
                        z: window.getComputedStyle(p).zIndex,
                        ptr: window.getComputedStyle(p).pointerEvents
                    });
                    p = p.parentElement;
                }
                return JSON.stringify(ancestors);
            }
        }
        return '[]';
    })()""",
    "returnByValue": True,
})
ancestors = json.loads(r.get("result", {}).get("result", {}).get("value", "[]"))
print("[1] Punish iframe ancestors:")
for a in ancestors:
    print(f"    <{a['tag']}#{a['id']}> cls={a['cls'][:60]} z={a['z']} ptr={a['ptr']}")
print()

# 2. Try: temporarily set J_MIDDLEWARE_FRAME_WIDGET pointer-events to none
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var el = document.querySelector('.J_MIDDLEWARE_FRAME_WIDGET');
        if (el) {
            el.style.setProperty('pointer-events', 'none', 'important');
            return 'set_none';
        }
        return 'not_found';
    })()""",
    "returnByValue": True,
})
print(f"[2] Set J_MIDDLEWARE pointer-events=none: {r.get('result', {}).get('result', {}).get('value', '')}")

# 3. Get captcha iframe position
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i=0; i<frames.length; i++) {
            if ((frames[i].src||'').indexOf('punish') !== -1) {
                var r = frames[i].getBoundingClientRect();
                return JSON.stringify({found:true, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
            }
        }
        return JSON.stringify({found:false});
    })()""",
    "returnByValue": True,
})
capt = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"[3] Captcha iframe: {json.dumps(capt)}")

if not capt.get("found"):
    ws.close()
    exit(0)

# 4. NOW try CDP drag with overlay disabled
print("\n[4] 尝试 CDP拖拽 (overlay已禁用)...")
for px, py, dr, desc in [(0.13, 0.77, 0.86, "1"), (0.11, 0.76, 0.87, "2"), (0.14, 0.78, 0.85, "3")]:
    sx = capt["x"] + int(capt["w"] * px)
    sy = capt["y"] + int(capt["h"] * py)
    dd = int(capt["w"] * dr)
    print(f"  {desc}: ({sx},{sy}) dist={dd}")
    
    cmd("Input.dispatchMouseEvent", {"type": "mousePressed", "x": sx, "y": sy, "button": "left", "clickCount": 1})
    time.sleep(0.15)
    
    for i in range(1, 81):
        p = i / 80
        cx = sx + int(dd * i / 80)
        cy = sy + random.randint(-2, 2)
        cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy, "button": "left"})
        time.sleep(random.uniform(0.003, 0.015))
    
    cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": sx + dd, "y": sy, "button": "left"})
    time.sleep(3)
    
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var frames = document.querySelectorAll('iframe');
            for (var i=0; i<frames.length; i++) {
                if ((frames[i].src||'').indexOf('punish') !== -1) {
                    var r = frames[i].getBoundingClientRect();
                    return JSON.stringify({found:true, vis:r.width>0&&r.height>0});
                }
            }
            return JSON.stringify({found:false});
        })()""",
        "returnByValue": True,
    })
    res = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
    print(f"    -> {json.dumps(res)}")
    if not res.get("vis"):
        print(f"    >>> ✅ 成功!")
        r = cmd("Page.captureScreenshot", {"format": "png"})
        with open("/home/lab-admin/price-monitor/data/diag2_success.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        ws.close()
        exit(0)

# 5. If still failing, try xdotool with overlay disabled
print("\n[5] 尝试 xdotool (overlay已禁用)...")
import subprocess
r = cmd("Runtime.evaluate", {
    "expression": """JSON.stringify({ox: (window.screenLeft||0)+(window.outerWidth-window.innerWidth)/2, oy: (window.screenTop||0)+window.outerHeight-window.innerHeight-(window.outerWidth-window.innerWidth)/2})""",
    "returnByValue": True,
})
off = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
ox, oy = off["ox"], off["oy"]

for px, py, dr in [(0.13, 0.77, 0.86), (0.11, 0.76, 0.87)]:
    sx = capt["x"] + int(capt["w"] * px) + ox
    sy = capt["y"] + int(capt["h"] * py) + oy
    dd = int(capt["w"] * dr)
    print(f"  screen=({sx},{sy}) dist={dd}")
    
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.15)
    subprocess.run(["xdotool", "mousedown", "1"],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.15)
    for i in range(1, 81):
        cx = int(sx + dd * i / 80)
        cy = sy + random.randint(-2, 2)
        subprocess.run(["xdotool", "mousemove", str(cx), str(cy)],
                       env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
        time.sleep(random.uniform(0.003, 0.01))
    subprocess.run(["xdotool", "mouseup", "1"],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(3)
    
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var frames = document.querySelectorAll('iframe');
            for (var i=0; i<frames.length; i++) {
                if ((frames[i].src||'').indexOf('punish') !== -1) {
                    var r = frames[i].getBoundingClientRect();
                    return JSON.stringify({found:true, vis:r.width>0&&r.height>0});
                }
            }
            return JSON.stringify({found:false});
        })()""",
        "returnByValue": True,
    })
    res = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
    print(f"    -> {json.dumps(res)}")
    if not res.get("vis"):
        print(f"    >>> ✅ 成功!")
        r = cmd("Page.captureScreenshot", {"format": "png"})
        with open("/home/lab-admin/price-monitor/data/diag2_success.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        ws.close()
        exit(0)

# 6. Restore overlay
cmd("Runtime.evaluate", {
    "expression": """(function(){
        var el = document.querySelector('.J_MIDDLEWARE_FRAME_WIDGET');
        if (el) { el.style.removeProperty('pointer-events'); return 'restored'; }
        return 'not_found';
    })()""",
    "returnByValue": True,
})

r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/diag2_failed.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

ws.close()
print("\n[DONE]")
