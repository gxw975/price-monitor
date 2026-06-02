"""快速：焦点窗口 + 精确坐标 + X11拖拽"""
import json, urllib.request, websocket, time, random, ctypes, os, subprocess

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

# Ensure focus
WID = subprocess.run(["xdotool", "search", "--name", "淘宝"], capture_output=True, text=True,
                    env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"}).stdout.strip().split("\n")[0]
subprocess.run(["xdotool", "windowactivate", WID, "windowfocus", WID],
              env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
time.sleep(1)

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

# Check focus and captcha
print("[1] 检查状态...")
r = cmd("Runtime.evaluate", {"expression": "document.hasFocus()", "returnByValue": True})
print(f"    hasFocus: {r.get('result',{}).get('result',{}).get('value')}")

r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var fs = document.querySelectorAll('iframe');
        for (var i=0;i<fs.length;i++) {
            if ((fs[i].src||'').indexOf('punish') !== -1) {
                var r = fs[i].getBoundingClientRect();
                return JSON.stringify({captcha:true, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
            }
        }
        return JSON.stringify({captcha:false});
    })()""",
    "returnByValue": True,
})
capt = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"    captcha: {json.dumps(capt)}")

if not capt.get("captcha"):
    print("无验证码！等待5秒再检查...")
    time.sleep(5)
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var fs = document.querySelectorAll('iframe');
            for (var i=0;i<fs.length;i++) {
                if ((fs[i].src||'').indexOf('punish') !== -1) {
                    var r = fs[i].getBoundingClientRect();
                    return JSON.stringify({captcha:true, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
                }
            }
            return JSON.stringify({captcha:false});
        })()""",
        "returnByValue": True,
    })
    capt = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
    print(f"    captcha(retry): {json.dumps(capt)}")

if not capt.get("captcha"):
    print("仍然无验证码，页面可能不需要验证")
    r = cmd("Page.captureScreenshot", {"format": "png"})
    import base64
    with open("/home/lab-admin/price-monitor/data/final_state.png", "wb") as f:
        f.write(base64.b64decode(r["result"]["data"]))
    ws.close()
    exit(0)

# Find punish frame
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
has_fid = find_punish(ft)

if has_fid:
    r = cmd("Page.createIsolatedWorld", {"frameId": punish_fid})
    ctx_id = r.get("result", {}).get("executionContextId")
    
    def iframe_eval(expr):
        r = cmd("Runtime.evaluate", {"expression": expr, "contextId": ctx_id, "returnByValue": True})
        v = r.get("result", {}).get("result", {}).get("value", "")
        if isinstance(v, str):
            try: return json.loads(v)
            except: return v
        return v
    
    # Get slider
    sd = iframe_eval('(function(){var s=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]");var t=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1__scale_text" + String.fromCharCode(39) + "]");if(!s||!t)return null;var sr=s.getBoundingClientRect();var tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()')
    print(f"\n[2] 滑块iframe内: {json.dumps(sd)}")
    
    # Recover errloading
    st = iframe_eval('JSON.stringify({hasErr:!!document.querySelector(".errloading")})')
    if st and st.get("hasErr"):
        print("[recover] errloading...")
        err = iframe_eval('(function(){var e=document.querySelector(".errloading");if(!e)return null;var r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()')
        
        libx11 = ctypes.CDLL("libX11.so.6")
        libxtest = ctypes.CDLL("libXtst.so.6")
        d = libx11.XOpenDisplay(None)
        
        ex = int(capt["x"] + err["x"] + 66)
        ey = int(capt["y"] + err["y"] + 119)
        libxtest.XTestFakeMotionEvent(d, 0, ex, ey, 0)
        libx11.XFlush(d)
        time.sleep(0.1)
        libxtest.XTestFakeButtonEvent(d, 1, True, 0)
        libx11.XFlush(d)
        time.sleep(0.05)
        libxtest.XTestFakeButtonEvent(d, 1, False, 0)
        libx11.XFlush(d)
        time.sleep(2.5)
        libx11.XCloseDisplay(d)
    
    # Get slider coords after recovery
    sd = iframe_eval('(function(){var s=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]");var t=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1__scale_text" + String.fromCharCode(39) + "]");if(!s||!t)return null;var sr=s.getBoundingClientRect();var tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()')
    
    if sd:
        sx = int(capt["x"] + sd["sx"] + 66)
        sy = int(capt["y"] + sd["sy"] + 119)
        dist = sd["dist"]
        print(f"\n[3] 屏幕坐标: ({sx},{sy}) dist={dist}")
        
        # Try multiple approaches
        attempts = 0
        failed = False
        
        while attempts < 4 and not failed:
            attempts += 1
            
            # Re-activate window before each attempt
            subprocess.run(["xdotool", "windowactivate", WID, "windowfocus", WID],
                          env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
            time.sleep(0.3)
            
            libx11 = ctypes.CDLL("libX11.so.6")
            libxtest = ctypes.CDLL("libXtst.so.6")
            d = libx11.XOpenDisplay(None)
            
            # Approach
            for i in range(4):
                p = (i+1)/4
                ax = int(sx - 90 + 90*p)
                ay = sy + random.randint(-4, 4)
                libxtest.XTestFakeMotionEvent(d, 0, ax, ay, 0)
                libx11.XFlush(d)
                time.sleep(0.018)
            
            libxtest.XTestFakeMotionEvent(d, 0, sx, sy, 0)
            libx11.XFlush(d)
            time.sleep(0.06)
            
            # Down
            libxtest.XTestFakeButtonEvent(d, 1, True, 0)
            libx11.XFlush(d)
            time.sleep(0.025)
            
            # Drag
            steps = 12 + attempts * 2
            for i in range(1, steps + 1):
                p = i/steps
                eased = 1 - (1-p)**(2 + attempts*0.3)
                x = int(sx + dist * eased)
                y = sy + random.randint(-2, 2)
                libxtest.XTestFakeMotionEvent(d, 0, x, y, 0)
                libx11.XFlush(d)
                delay = (0.01 + random.random() * 0.015) if p < 0.5 else (0.015 + random.random() * 0.025)
                time.sleep(delay)
            
            time.sleep(0.06)
            libxtest.XTestFakeButtonEvent(d, 1, False, 0)
            libx11.XFlush(d)
            libx11.XCloseDisplay(d)
            
            time.sleep(2.5)
            
            # Check result
            r = cmd("Runtime.evaluate", {
                "expression": """(function(){
                    var fs = document.querySelectorAll('iframe');
                    for (var i=0;i<fs.length;i++) {
                        if ((fs[i].src||'').indexOf('h5api.m.taobao.com') !== -1) {
                            var r = fs[i].getBoundingClientRect();
                            return JSON.stringify({found:true, vis:r.width>0&&r.height>0});
                        }
                    }
                    return JSON.stringify({found:false});
                })()""",
                "returnByValue": True,
            })
            result = json.loads(r.get("result",{}).get("result",{}).get("value","{}"))
            
            if iframe_eval:
                ifr = iframe_eval('JSON.stringify({hasErr:!!document.querySelector(".errloading"),body:(document.body?.innerText||"").slice(0,80)})')
                print(f"  Attempt {attempts}: main={result} iframe={ifr}")
            else:
                print(f"  Attempt {attempts}: main={result}")
            
            if not result.get("found") or not result.get("vis"):
                print(f"\n>>> ✅✅✅ PASS! (attempt {attempts}) ✅✅✅")
                r = cmd("Page.captureScreenshot", {"format": "png"})
                import base64
                with open("/home/lab-admin/price-monitor/data/win.png", "wb") as f:
                    f.write(base64.b64decode(r["result"]["data"]))
                ws.close()
                exit(0)

r = cmd("Page.captureScreenshot", {"format": "png"})
import base64
with open("/home/lab-admin/price-monitor/data/last.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

ws.close()
print("\n[DONE]")
