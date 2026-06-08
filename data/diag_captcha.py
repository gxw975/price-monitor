"""深度诊断 - 列出所有iframe和弹窗元素"""
import json, urllib.request, websocket, base64, os

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

for d in ("Runtime", "Page", "DOM"):
    cmd(f"{d}.enable")

# 1. All iframes
r = cmd("Runtime.evaluate", {
    "expression": """JSON.stringify(Array.from(document.querySelectorAll('iframe')).map(function(f,i){
        var r = f.getBoundingClientRect();
        var cs = window.getComputedStyle(f);
        return {
            i:i, 
            src: (f.src||'').slice(0, 180),
            name: f.name || '',
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
            zIndex: cs.zIndex,
            display: cs.display,
            visibility: cs.visibility,
            opacity: cs.opacity,
            position: cs.position,
            pointerEvents: cs.pointerEvents
        };
    }))""",
    "returnByValue": True,
})
iframes = json.loads(r.get("result", {}).get("result", {}).get("value", "[]"))
print("=== ALL IFRAMES ===")
for f in iframes:
    print(f"  [{f['i']}] z={f['zIndex']} pos=({f['x']},{f['y']}) {f['w']}x{f['h']} disp={f['display']} vis={f['visibility']} opacity={f['opacity']} ptr={f['pointerEvents']}")
    print(f"       name=\"{f['name']}\"")
    print(f"       src={f['src'][:150]}")
    print()

# 2. All fixed/absolute elements with high z-index
r = cmd("Runtime.evaluate", {
    "expression": """JSON.stringify(Array.from(document.querySelectorAll('div,section,span')).filter(function(el){
        var cs = window.getComputedStyle(el);
        return (cs.position === 'fixed' || cs.position === 'absolute') && 
               parseInt(cs.zIndex) > 100 && 
               el.offsetWidth > 200 && el.offsetHeight > 100;
    }).slice(0, 10).map(function(el){
        var r = el.getBoundingClientRect();
        var cs = window.getComputedStyle(el);
        return {
            tag: el.tagName, 
            cls: (el.className||'').toString().slice(0, 80),
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height),
            z: cs.zIndex,
            id: el.id || ''
        };
    }))""",
    "returnByValue": True,
})
modals = json.loads(r.get("result", {}).get("result", {}).get("value", "[]"))
print("\n=== HIGH-Z MODALS ===")
for m in modals:
    print(f"  <{m['tag']}> id={m['id']} z={m['z']} ({m['x']},{m['y']}) {m['w']}x{m['h']} cls={m['cls'][:60]}")
print()

# 3. Check all text containing "滑块" or "验证"
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var body = document.body;
        var txt = body ? body.innerText : '';
        var rs = [];
        var lines = txt.split('\\n');
        for (var i=0; i<lines.length; i++) {
            var l = lines[i].trim();
            if (l && (l.indexOf('滑块')!==-1 || l.indexOf('验证')!==-1 || l.indexOf('拖动')!==-1)) {
                rs.push(l);
            }
        }
        return JSON.stringify(rs);
    })()""",
    "returnByValue": True,
})
capt_lines = json.loads(r.get("result", {}).get("result", {}).get("value", "[]"))
print(f"=== 滑块/验证文字 ({len(capt_lines)} lines) ===")
for l in capt_lines:
    print(f"  {l}")

# 4. Window geometry
r = cmd("Runtime.evaluate", {
    "expression": """JSON.stringify({
        outerW: window.outerWidth, outerH: window.outerHeight,
        innerW: window.innerWidth, innerH: window.innerHeight,
        screenW: window.screen.width, screenH: window.screen.height,
        screenX: window.screenX, screenY: window.screenY,
        screenLeft: window.screenLeft || 0, screenTop: window.screenTop || 0,
        devicePixelRatio: window.devicePixelRatio,
        scrollX: window.scrollX, scrollY: window.scrollY
    })""",
    "returnByValue": True,
})
geo = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"\n=== WINDOW GEOMETRY ===")
print(json.dumps(geo, indent=2))

# 5. Try using xdotool getmouselocation to see where clicks actually land
import subprocess
r = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True,
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
print(f"\n=== CURRENT MOUSE POSITION (xdotool) ===")
print(f"  {r.stdout.strip()}")

# 6. Screenshot
r2 = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/v4_diag.png", "wb") as f:
    f.write(base64.b64decode(r2["result"]["data"]))
print(f"\n截图: v4_diag.png ({len(base64.b64decode(r2['result']['data']))} bytes)")

ws.close()
