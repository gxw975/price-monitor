"""验证后的页面状态快照 - 建立pass判据"""
import json, urllib.request, websocket, time, base64

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

for d in ("Runtime", "Page", "Network", "DOM"):
    cmd(f"{d}.enable")

print("=== 验证通过后页面状态快照 ===")

# 1. Captcha iframe check (should be gone)
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var fs = document.querySelectorAll('iframe');
        var result = {total: fs.length, punishFound: false, punishVisible: false};
        for (var i=0; i<fs.length; i++) {
            var src = (fs[i].src||'');
            var rect = fs[i].getBoundingClientRect();
            if (src.indexOf('h5api.m.taobao.com') !== -1) {
                result.punishFound = true;
                result.punishVisible = rect.width > 0 && rect.height > 0;
                result.punishRect = {x:Math.round(rect.x), y:Math.round(rect.y), w:Math.round(rect.width), h:Math.round(rect.height)};
            }
        }
        return JSON.stringify(result);
    })()""",
    "returnByValue": True,
})
captcha_state = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"1. Captcha iframe: {json.dumps(captcha_state)}")

# 2. URL check
r = cmd("Runtime.evaluate", {
    "expression": "JSON.stringify({url: location.href, title: document.title})",
    "returnByValue": True,
})
page_info = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"2. Page: {json.dumps(page_info)}")

# 3. Check if search results are visible
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var hasResults = !!document.querySelector('.item, .item-box, [class*=item], [class*=Item], .grid, .m-itemlist');
        var hasDtool = !!document.querySelector('[class*=dtool], [class*=diantoushi]');
        var bodyLen = document.body ? document.body.innerText.length : 0;
        var first200 = document.body ? document.body.innerText.slice(0, 200) : '';
        return JSON.stringify({hasResults:hasResults, hasDtool:hasDtool, bodyLen:bodyLen, first200:first200});
    })()""",
    "returnByValue": True,
})
body_info = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"3. Body: hasResults={body_info.get('hasResults')}, hasDtool={body_info.get('hasDtool')}, len={body_info.get('bodyLen')}")
print(f"   text: {body_info.get('first200', '')[:150]}")

# 4. Check for J_MIDDLEWARE_FRAME_WIDGET overlay
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var el = document.querySelector('.J_MIDDLEWARE_FRAME_WIDGET');
        if (!el) return JSON.stringify({found: false});
        var r = el.getBoundingClientRect();
        return JSON.stringify({found: true, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height), display:window.getComputedStyle(el).display});
    })()""",
    "returnByValue": True,
})
overlay = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"4. J_MIDDLEWARE: {json.dumps(overlay)}")

# 5. Check cookies
r = cmd("Network.getCookies", {"urls": ["https://s.taobao.com", "https://h5api.m.taobao.com"]})
cookies = r.get("result", {}).get("cookies", [])
print(f"5. Cookies: {len(cookies)} total")
for c in cookies:
    if any(k in (c.get('name','')+c.get('value','')).lower() for k in ['nc', 'token', 'sig', 'session', 'x5', 'punish']):
        print(f"   {c['domain']} {c['name']}={c['value'][:60]}")

# 6. Screenshot
r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/pass_snapshot.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))
print("6. Screenshot: pass_snapshot.png")

# 7. All iframes currently on page
r = cmd("Runtime.evaluate", {
    "expression": """JSON.stringify(Array.from(document.querySelectorAll('iframe')).map(function(f,i){
        var r = f.getBoundingClientRect();
        return {
            i:i,
            src: (f.src||'').slice(0, 120),
            visible: r.width>0 && r.height>0,
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height)
        };
    }))""",
    "returnByValue": True,
})
iframes = json.loads(r.get("result", {}).get("result", {}).get("value", "[]"))
print(f"7. All iframes ({len(iframes)}):")
for f in iframes:
    print(f"   [{f['i']}] vis={f['visible']} ({f['x']},{f['y']}) {f['w']}x{f['h']} src={f['src'][:100]}")

ws.close()
print("\n=== 判据总结 ===")
print("验证通过 = punish iframe不存在 OR punish iframe不visible")
print("验证通过 = J_MIDDLEWARE_FRAME_WIDGET不存在 OR display:none")
