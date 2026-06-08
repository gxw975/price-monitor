"""CDP Fetch拦截 - 伪造baxia验证成功响应"""
import json, urllib.request, websocket, time, base64, re, os

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

for d in ("Runtime", "Page", "Fetch", "Network"):
    cmd(f"{d}.enable")

# Enable fetch interception for captcha domains
print("[1] Enable Fetch interception for captcha domains...")
r = cmd("Fetch.enable", {
    "patterns": [
        {"urlPattern": "*cf.aliyun.com/nocaptcha*", "requestStage": "Request"},
        {"urlPattern": "*cf.aliyun.com/nocaptcha*", "requestStage": "Response"},
    ],
    "handleAuthRequests": False
})
print(f"Fetch.enable: ok" if "error" not in r else f"Fetch.enable err: {r.get('error')}")

# Set up event listener
import threading
intercepted = []
fetch_lock = threading.Lock()

def ws_listener():
    global intercepted
    try:
        while True:
            raw = ws.recv()
            msg = json.loads(raw)
            method = msg.get("method", "")
            if method == "Fetch.requestPaused":
                with fetch_lock:
                    intercepted.append(msg)
            elif method == "Fetch.authRequired":
                pass
    except Exception as e:
        print(f"  listener done: {e}")

listener = threading.Thread(target=ws_listener, daemon=True)
listener.start()

# frame + contextId
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
print(f"punish_fid: {punish_fid}")

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

# First, take a screenshot of current state
r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/fetch_before.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

# === Try to access NC object through iframe main world ===
print("\n[2] 尝试在iframe MainWorld中访问NoCaptcha对象...")

# Create another isolated world with universal access
r = cmd("Page.createIsolatedWorld", {
    "frameId": punish_fid,
    "grantUniveralAccess": True,
    "worldName": "nc_explorer",
})
ctx_id2 = r.get("result", {}).get("executionContextId")
print(f"  UA contextId: {ctx_id2}")

def iframe_ua_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "contextId": ctx_id2, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except:
            return v
    return v

# Try to find all global variables with grantUniveralAccess
r = iframe_ua_eval("""JSON.stringify(Object.keys(window).filter(function(k){
    return k.length <= 6 && k === k.toUpperCase() && /^[A-Z]/.test(k)
}).slice(0, 30))""")
print(f"  UA window短大写: {r}")

# Try AWSC
r = iframe_ua_eval("""(function(){
    try { return JSON.stringify({AWSC: typeof AWSC, NoCaptcha: typeof NoCaptcha, _nc: typeof _nc, _AWSC: typeof _AWSC}); }
    catch(e) { return 'err:'+e.message; }
})()""")
print(f"  UA types: {r}")

# Try to access nc tokens and session in main world of iframe
r = iframe_ua_eval("""JSON.stringify({
    sessionId: document.getElementById('nc-session-id')?.value || '',
    sig: document.getElementById('nc-sig')?.value || '',
    token: document.querySelector('[name=nc_token]')?.value || '',
    step: document.getElementById('x5step')?.value || '',
})""")
print(f"  tokens: {r}")

# === Try to trigger captcha verification by directly calling nc.js internals ===
print("\n[3] 尝试通过CommonJS module系统访问nc模块...")
r = iframe_ua_eval("""(function(){
    // Try to find the script element for nc.js and check if there's an exports/module
    var scripts = document.querySelectorAll('script');
    var ncScript = null;
    for (var i=0; i<scripts.length; i++) {
        var txt = scripts[i].textContent || '';
        // nc.js is the main captcha script
        if (txt.indexOf('nc_1_wrapper') !== -1 || txt.indexOf('NoCaptcha') !== -1) {
            ncScript = scripts[i];
            break;
        }
        // check inline
        if (scripts[i].src && scripts[i].src.indexOf('nc.js') !== -1) {
            ncScript = scripts[i];
            break;
        }
    }
    if (ncScript && ncScript.src) return JSON.stringify({type:'external', src:ncScript.src});
    if (ncScript) return JSON.stringify({type:'inline', len:ncScript.textContent.length});
    
    // Look for require/define (webpack)
    if (typeof __webpack_require__ !== 'undefined') return 'webpack_found';
    if (typeof define !== 'undefined') return 'amd_define';
    
    return 'NOT_FOUND';
})()""")
print(f"  nc模块: {r}")

import base64 as b64

# === INTERCEPT: Now attempt to do an XTest drag and intercept the verify request ===
print("\n[4] 执行X11拖拽 + 拦截验证请求...")

# First recover from errloading
state = iframe_eval('JSON.stringify({hasErr:!!document.querySelector(".errloading")})')
if state and state.get("hasErr"):
    print("  recover errloading...")
    r = cmd("Runtime.evaluate", {
        "expression": "JSON.stringify({ox:(window.screenLeft||0)+(window.outerWidth-window.innerWidth)/2, oy:(window.screenTop||0)+window.outerHeight-window.innerHeight-(window.outerWidth-window.innerWidth)/2})",
        "returnByValue": True,
    })
    off = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
    ox, oy = off["ox"], off["oy"]
    
    err = iframe_eval('(function(){var e=document.querySelector(".errloading");if(!e)return null;var r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()')
    ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')
    import ctypes
    libx11 = ctypes.CDLL("libX11.so.6")
    libxtest = ctypes.CDLL("libXtst.so.6")
    d = libx11.XOpenDisplay(None)
    ex = int(ip["x"] + err["x"] + ox)
    ey = int(ip["y"] + err["y"] + oy)
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

# Get slider coords
sd = iframe_eval('(function(){var s=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]");var t=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1__scale_text" + String.fromCharCode(39) + "]");if(!s||!t)return null;var sr=s.getBoundingClientRect();var tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()')
ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')

if sd and ip:
    # Get offset
    r = cmd("Runtime.evaluate", {
        "expression": "JSON.stringify({ox:(window.screenLeft||0)+(window.outerWidth-window.innerWidth)/2, oy:(window.screenTop||0)+window.outerHeight-window.innerHeight-(window.outerWidth-window.innerWidth)/2})",
        "returnByValue": True,
    })
    off = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
    ox, oy = off["ox"], off["oy"]
    
    sx = int(ip["x"] + sd["sx"] + ox)
    sy = int(ip["y"] + sd["sy"] + oy)
    dist = sd["dist"]
    
    print(f"  slider screen: ({sx},{sy}) dist={dist}")
    
    import ctypes, random as rnd
    libx11 = ctypes.CDLL("libX11.so.6")
    libxtest = ctypes.CDLL("libXtst.so.6")
    d = libx11.XOpenDisplay(None)
    
    # Approach
    for i in range(4):
        p = (i+1)/4
        ax = int(sx - 80 + 80*p)
        ay = sy + rnd.randint(-3, 3)
        libxtest.XTestFakeMotionEvent(d, 0, ax, ay, 0)
        libx11.XFlush(d)
        time.sleep(0.015 + rnd.random()*0.015)
    
    libxtest.XTestFakeMotionEvent(d, 0, sx, sy, 0)
    libx11.XFlush(d)
    time.sleep(0.07)
    
    # Down
    libxtest.XTestFakeButtonEvent(d, 1, True, 0)
    libx11.XFlush(d)
    time.sleep(0.03)
    
    # Drag
    for i in range(1, 16):
        p = i/15
        eased = 1 - (1-p)**2
        x = int(sx + dist * eased)
        y = sy + rnd.randint(-2, 2)
        libxtest.XTestFakeMotionEvent(d, 0, x, y, 0)
        libx11.XFlush(d)
        time.sleep(0.01 + rnd.random()*0.02)
    
    # Up
    time.sleep(0.05)
    libxtest.XTestFakeButtonEvent(d, 1, False, 0)
    libx11.XFlush(d)
    libx11.XCloseDisplay(d)
    
    time.sleep(3)

# Check intercepted requests
print(f"\n[5] 拦截的请求数量: {len(intercepted)}")
for i, msg in enumerate(intercepted):
    params = msg.get("params", {})
    req = params.get("request", {})
    rid = params.get("requestId", "")
    url = req.get("url", "")
    stage = params.get("responseStatusCode", "request")
    print(f"  [{i}] {stage} {url[:120]}")
    
    # If this is a nocaptcha response, fake the success
    if "cf.aliyun.com/nocaptcha" in url and params.get("responseStatusCode"):
        print(f"    >>> FAKING SUCCESS RESPONSE")
        # Check the original response
        fetch_id = params.get("requestId")
        
        # First get the response body
        r = cmd("Fetch.getResponseBody", {"requestId": fetch_id})
        body = r.get("result", {}).get("body", "")
        base64encoded = r.get("result", {}).get("base64Encoded", False)
        print(f"    body ({len(body)} bytes): {body[:200]}")
        
        # Fake a success response
        cmd("Fetch.fulfillRequest", {
            "requestId": fetch_id,
            "responseCode": 200,
            "responseHeaders": [
                {"name": "Content-Type", "value": "text/javascript; charset=utf-8"},
                {"name": "Access-Control-Allow-Origin", "value": "*"},
            ],
            "body": b64.b64encode(b"""{"result":0,"success":true,"data":{"sessionId":"fake_session_123","sig":"fake_sig_456","token":"fake_token_789"}}""").decode(),
        })

time.sleep(2)

# Check if captcha is gone
res = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api.m.taobao.com")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({found:true,vis:r.width>0&&r.height>0});}}return JSON.stringify({found:false});})()')
print(f"\n[最终] punish iframe: {res}")

r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/fetch_after.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

ws.close()
print("\n[DONE]")
