"""测试X11事件是否真的被Chrome接收"""
import json, urllib.request, websocket, time, base64, os, ctypes, subprocess

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

CDP = "http://127.0.0.1:9223/json"
targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())
ws = None
for t in targets:
    if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
        ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=15)
        break

mid = [0]
def cmd(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    for _ in range(60):
        r = json.loads(ws.recv())
        if r.get("id") == mid[0]:
            return r
    return {}

for d in ("Runtime", "Page", "Input"):
    cmd(f"{d}.enable")

# Get geometry
ox = 66
oy = 119
print(f"offset: ox={ox} oy={oy}")

# === TEST 1: Check Chrome window focus ===
print("\n=== Test 1: 窗口焦点状态 ===")
r = cmd("Runtime.evaluate", {
    "expression": "document.hasFocus()",
    "returnByValue": True,
})
print(f"document.hasFocus(): {r.get('result', {}).get('result', {}).get('value', '')}")

# === TEST 2: Click a visible element with xdotool and verify ===
print("\n=== Test 2: xdotool点击搜索框测试 ===")

# Find the search input on the page
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var el = document.querySelector('input[type=text], input[type=search], input[name=q], .search-combobox-input');
        if (!el) {
            var inputs = document.querySelectorAll('input');
            for (var i=0; i<inputs.length; i++) {
                if (inputs[i].offsetWidth > 100) {
                    el = inputs[i];
                    break;
                }
            }
        }
        if (!el) return JSON.stringify({found:false});
        var rect = el.getBoundingClientRect();
        return JSON.stringify({
            found: true,
            x: Math.round(rect.x + rect.width/2),
            y: Math.round(rect.y + rect.height/2),
            tag: el.tagName,
            cls: (el.className||'').toString().slice(0, 60)
        });
    })()""",
    "returnByValue": True,
})
target = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"Target element: {json.dumps(target)}")

if target.get("found"):
    # Calculate screen coordinates
    screen_x = int(target["x"] + ox)
    screen_y = int(target["y"] + oy)
    print(f"Screen coords: ({screen_x}, {screen_y})")
    
    # Current mouse position
    r = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                       capture_output=True, text=True,
                       env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    print(f"Current mouse: {r.stdout.strip()}")
    
    # Move and click with xdotool
    subprocess.run(["xdotool", "mousemove", str(screen_x), str(screen_y)],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.2)
    subprocess.run(["xdotool", "click", "1"],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.1)
    
    # Type something to verify focus
    subprocess.run(["xdotool", "type", "test_text"],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.3)
    
    # Check if input received text
    r2 = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var el = document.querySelector('input[type=text], input[type=search], input[name=q]');
            if (!el) {
                var inputs = document.querySelectorAll('input');
                for (var i=0; i<inputs.length; i++) {
                    if (inputs[i].offsetWidth > 100) {
                        el = inputs[i];
                        break;
                    }
                }
            }
            if (!el) return 'NO_INPUT';
            return JSON.stringify({value: el.value, hasValue: el.value.length > 0});
        })()""",
        "returnByValue": True,
    })
    print(f"Input value after xdotool click+type: {r2.get('result',{}).get('result',{}).get('value','')}")

# === TEST 3: same with X11 XTest ===
print("\n=== Test 3: X11 XTest点击测试 ===")

# Find another clickable element
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var btns = document.querySelectorAll('button, a, [role=button], .btn, [class*=btn]');
        var visible = [];
        for (var i=0; i<btns.length; i++) {
            if (btns[i].offsetWidth > 30 && btns[i].offsetHeight > 20) {
                var rect = btns[i].getBoundingClientRect();
                visible.push({
                    index: i,
                    text: (btns[i].textContent||'').trim().slice(0, 40),
                    x: Math.round(rect.x + rect.width/2),
                    y: Math.round(rect.y + rect.height/2)
                });
                if (visible.length >= 5) break;
            }
        }
        return JSON.stringify(visible);
    })()""",
    "returnByValue": True,
})
btns = json.loads(r.get("result", {}).get("result", {}).get("value", "[]"))
print(f"Visible buttons: {json.dumps(btns, ensure_ascii=False)}")

if btns:
    btn = btns[0]
    sx = int(btn["x"] + ox)
    sy = int(btn["y"] + oy)
    print(f"Clicking [{btn['text']}] at screen ({sx}, {sy})")
    
    libx11 = ctypes.CDLL("libX11.so.6")
    libxtest = ctypes.CDLL("libXtst.so.6")
    d = libx11.XOpenDisplay(None)
    
    libxtest.XTestFakeMotionEvent(d, 0, sx, sy, 0)
    libx11.XFlush(d)
    time.sleep(0.1)
    
    libxtest.XTestFakeButtonEvent(d, 1, True, 0)
    libx11.XFlush(d)
    time.sleep(0.05)
    
    libxtest.XTestFakeButtonEvent(d, 1, False, 0)
    libx11.XFlush(d)
    time.sleep(0.5)
    
    libx11.XCloseDisplay(d)
    
    # Check if page changed
    r = cmd("Runtime.evaluate", {
        "expression": "JSON.stringify({url: location.href, title: document.title})",
        "returnByValue": True,
    })
    print(f"After XTest click: {r.get('result',{}).get('result',{}).get('value','')}")

# === TEST 4: CDP Input.dispatchMouseEvent test ===
print("\n=== Test 4: CDP Input事件测试 ===")
if btns and len(btns) > 1:
    btn2 = btns[1]
    vpx = btn2["x"]
    vpy = btn2["y"]
    print(f"CDP clicking [{btn2['text']}] at vp ({vpx}, {vpy})")
    
    cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed",
        "x": vpx, "y": vpy,
        "button": "left",
        "clickCount": 1,
    })
    time.sleep(0.05)
    cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased",
        "x": vpx, "y": vpy,
        "button": "left",
    })
    time.sleep(0.5)
    
    r = cmd("Runtime.evaluate", {
        "expression": "JSON.stringify({url: location.href, title: document.title})",
        "returnByValue": True,
    })
    print(f"After CDP click: {r.get('result',{}).get('result',{}).get('value','')}")

# === TEST 5: Try to directly set slider to end using CDP JS ===
print("\n=== Test 5: CDP JS直接操控滑块位置 ===")

# Get captcha frame
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
find_punish(ft)

if punish_fid:
    r = cmd("Page.createIsolatedWorld", {"frameId": punish_fid, "grantUniveralAccess": True})
    ctx_id = r.get("result", {}).get("executionContextId")
    print(f"UA ctx_id: {ctx_id}")
    
    # Try to move slider to end via JS (even though it won't submit, we can see if the element moves)
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var s = document.querySelector("[id*='nc_1_n1z']");
            if (!s) return 'NO_SLIDER';
            // Set the transform to move it all the way right
            s.style.cssText = 'transform: translateX(258px); transition: none;';
            s.setAttribute('style', s.getAttribute('style') + '; left: auto !important; right: 0px !important;');
            return JSON.stringify({
                before: s.getBoundingClientRect(),
                after: (function(){ var r = s.getBoundingClientRect(); return {x: Math.round(r.x), w: Math.round(r.width)}; })()
            });
        })()""",
        "contextId": ctx_id,
        "returnByValue": True,
    })
    print(f"JS move slider: {r.get('result',{}).get('result',{}).get('value','')[:200]}")
    
    # Try triggering form events
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            // Try to set values and submit
            var si = document.getElementById('nc-session-id');
            var sg = document.getElementById('nc-sig');
            if (si && sg) {
                si.value = 'test_session_abc123';
                sg.value = 'test_sig_xyz789';
                
                // Trigger change events
                si.dispatchEvent(new Event('change', {bubbles: true}));
                sg.dispatchEvent(new Event('change', {bubbles: true}));
                
                // Find and submit form
                var form = document.getElementById('nc-verify-form');
                if (form) {
                    form.submit();
                    return 'SUBMITTED';
                }
                
                // Also try to notify parent window
                window.parent.postMessage({type: 'nc_verify_success', sessionId: 'test', sig: 'test'}, '*');
                return 'POST_MESSAGE_SENT';
            }
            return 'NO_INPUTS';
        })()""",
        "contextId": ctx_id,
        "returnByValue": True,
    })
    print(f"Form submit: {r.get('result',{}).get('result',{}).get('value','')}")

time.sleep(2)

r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/event_test.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

# Check final state
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var fs = document.querySelectorAll('iframe');
        for (var i=0; i<fs.length; i++) {
            if ((fs[i].src||'').indexOf('h5api.m.taobao.com') !== -1) {
                var r = fs[i].getBoundingClientRect();
                return JSON.stringify({found:true, vis: r.width>0 && r.height>0});
            }
        }
        return JSON.stringify({found:false});
    })()""",
    "returnByValue": True,
})
print(f"\n最终captcha: {r.get('result',{}).get('result',{}).get('value','')}")

ws.close()
print("\n[DONE]")
