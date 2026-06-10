"""在iframe内部直接操作滑块 - 不需要外部坐标"""
import json, urllib.request, websocket, time, base64, os, subprocess

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
    for _ in range(80):
        r = json.loads(ws.recv())
        if r.get("id") == mid[0]:
            return r
    return {}

for d in ("Runtime", "Page", "DOM", "Input"):
    cmd(f"{d}.enable")

# Get FrameTree to find punish iframe ID
r = cmd("Page.getFrameTree")
ft = r.get("result", {}).get("frameTree", {})

punish_fid = None
def find_punish(node):
    global punish_fid
    f = node.get("frame", {})
    if "punish" in f.get("url", ""):
        punish_fid = f.get("id", "")
        return True
    for c in node.get("childFrames", []):
        if find_punish(c):
            return True
    return False

find_punish(ft)
print(f"[1] Punish frameId: {punish_fid}")

if not punish_fid:
    print("No punish iframe!")
    ws.close()
    exit(0)

# Create isolated world in the iframe
r = cmd("Page.createIsolatedWorld", {
    "frameId": punish_fid,
    "worldTag": "solve_in_iframe",
})
time.sleep(0.3)
print(f"[2] Isolated world created")

# Check what elements exist in the iframe
r = cmd("Runtime.evaluate", {
    "expression": """JSON.stringify((function(){
        var result = {};
        result.bodyExists = !!document.body;
        result.documentTitle = document.title || 'EMPTY';
        result.headHTML = document.head ? document.head.innerHTML.slice(0, 300) : 'NO_HEAD';
        result.bodyHTML = document.body ? document.body.innerHTML.slice(0, 800) : 'NO_BODY';
        result.doctype = document.doctype ? document.doctype.name : 'NONE';

        var nc_s = document.getElementById('nc_1_n1z');
        var nc_t = document.getElementById('nc_1__scale_text');
        var nc_w = document.getElementById('nc_1_wrapper');
        result.nc_n1z = nc_s ? 'FOUND' : 'NOT_FOUND';
        result.nc_scale = nc_t ? 'FOUND' : 'NOT_FOUND';
        result.nc_wrapper = nc_w ? 'FOUND' : 'NOT_FOUND';

        if (nc_s) {
            var r = nc_s.getBoundingClientRect();
            result.slider_rect = {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};
        }
        if (nc_t) {
            var r = nc_t.getBoundingClientRect();
            result.track_rect = {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};
        }

        var allEls = document.querySelectorAll('*');
        result.totalElements = allEls.length;

        var ids = [];
        var allWithId = document.querySelectorAll('[id]');
        for (var i=0; i<Math.min(allWithId.length, 30); i++) {
            ids.push(allWithId[i].id);
        }
        result.ids = ids;

        var divs = document.querySelectorAll('div, span');
        var divCount = 0;
        for (var i=0; i<Math.min(divs.length, 50); i++) {
            if (divs[i].offsetHeight > 0) divCount++;
        }
        result.visibleDivs = divCount;

        return result;
    })())""",
    "returnByValue": True,
})
info = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"\n[3] Iframe内部状态:")
for k, v in info.items():
    val_str = str(v)[:200]
    print(f"    {k}: {val_str}")

if info.get("nc_n1z") == "FOUND":
    # Direct JS drag within the iframe!
    slider_rect = info.get("slider_rect", {})
    track_rect = info.get("track_rect", {})
    sx = slider_rect.get("x", 0)
    sy = slider_rect.get("y", 0)
    sw = slider_rect.get("w", 0)
    sh = slider_rect.get("h", 0)
    tx = track_rect.get("x", 0)
    tw = track_rect.get("w", 0)
    distance = tx + tw - sx - sw + 3
    slider_center_x = sx + sw // 2
    slider_center_y = sy + sh // 2
    
    print(f"\n[4] 滑块坐标: ({sx},{sy}) {sw}x{sh}")
    print(f"    滑轨: ({tx},?) w={tw}")
    print(f"    拖拽距离: {distance}px")
    print(f"    滑块中心: ({slider_center_x}, {slider_center_y})")
    
    # Dispatch mouse events within the iframe using JS
    print(f"\n[5] 在iframe内直接触发鼠标事件...")
    
    drag_js = f"""
    (function() {{
        var slider = document.getElementById('nc_1_n1z');
        if (!slider) return 'NO_SLIDER';
        
        var rect = slider.getBoundingClientRect();
        var startX = rect.x + rect.width / 2;
        var startY = rect.y + rect.height / 2;
        var distance = {distance};
        var steps = 60;
        
        function dispatch(evtType, x, y, btn) {{
            var evt = new MouseEvent(evtType, {{
                bubbles: true, cancelable: true, view: window,
                clientX: x, clientY: y, button: btn || 0, buttons: btn === 0 ? 1 : 0
            }});
            slider.dispatchEvent(evt);
        }}
        
        // mousedown
        dispatch('mousedown', startX, startY, 0);
        
        // mousemove steps
        var stepX = distance / steps;
        var noiseY = 3;
        for (var i = 1; i <= steps; i++) {{
            var p = i / steps;
            var noise = Math.floor((Math.random() - 0.5) * noiseY * 2 * (1 - p * 0.8));
            var cx = startX + stepX * i + (Math.random() - 0.5) * 2;
            var cy = startY + noise;
            dispatch('mousemove', cx, cy, 0);
        }}
        
        // mouseup
        setTimeout(function() {{
            dispatch('mouseup', startX + distance, startY, 0);
        }}, 100);
        
        return 'DISPATCHED';
    }})()
    """
    
    r = cmd("Runtime.evaluate", {
        "expression": drag_js,
        "returnByValue": True,
    })
    result = r.get("result", {}).get("result", {}).get("value", "")
    print(f"    结果: {result}")
    
    time.sleep(4)
    
    # Check if captcha is gone
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var s = document.getElementById('nc_1_n1z');
            var w = document.getElementById('nc_1_wrapper');
            if (!w || w.offsetHeight === 0) return 'GONE';
            if (!s) return 'GONE_NO_SLIDER';
            return 'STILL_THERE';
        })()""",
        "returnByValue": True,
    })
    status = r.get("result", {}).get("result", {}).get("value", "")
    print(f"    验证后iframe内状态: {status}")
    
    if status == "GONE" or status == "GONE_NO_SLIDER":
        print("\n    >>> ✅✅✅ 验证通过! ✅✅✅")
    else:
        print("\n    ❌ 仍在，尝试触摸事件...")
        
        # Try touch events
        touch_js = f"""
        (function() {{
            var slider = document.getElementById('nc_1_n1z');
            if (!slider) return 'NO_SLIDER';
            
            var rect = slider.getBoundingClientRect();
            var sx = rect.x + rect.width / 2;
            var sy = rect.y + rect.height / 2;
            var dist = {distance};
            
            var touchId = Date.now();
            
            function fireTouch(type, x, y) {{
                var touch = new Touch({{
                    identifier: touchId,
                    target: slider,
                    clientX: x, clientY: y,
                    pageX: x, pageY: y,
                    radiusX: 2.5, radiusY: 2.5,
                    rotationAngle: 0,
                    force: 0.5,
                }});
                var evt = new TouchEvent(type, {{
                    bubbles: true, cancelable: true,
                    touches: type === 'touchend' ? [] : [touch],
                    targetTouches: type === 'touchend' ? [] : [touch],
                    changedTouches: [touch],
                    view: window
                }});
                slider.dispatchEvent(evt);
            }}
            
            fireTouch('touchstart', sx, sy);
            
            var steps = 40;
            var stepX = dist / steps;
            for (var i = 1; i <= steps; i++) {{
                var cx = sx + stepX * i;
                var cy = sy + Math.floor((Math.random() - 0.5) * 4);
                fireTouch('touchmove', cx, cy);
            }}
            
            setTimeout(function() {{
                fireTouch('touchend', sx + dist, sy);
            }}, 50);
            
            return 'TOUCH_DISPATCHED';
        }})()
        """
        
        r = cmd("Runtime.evaluate", {
            "expression": touch_js,
            "returnByValue": True,
        })
        print(f"    touch结果: {r.get('result',{}).get('result',{}).get('value','')}")
        time.sleep(4)
        
        r = cmd("Runtime.evaluate", {
            "expression": """(function(){
                var w = document.getElementById('nc_1_wrapper');
                if (!w || w.offsetHeight === 0) return 'GONE';
                return 'STILL_THERE';
            })()""",
            "returnByValue": True,
        })
        print(f"    touch后状态: {r.get('result',{}).get('result',{}).get('value','')}")

else:
    print(f"\n[4] 滑块元素#nc_1_n1z未找到!")
    print(f"    可见div: {info.get('visibleDivs')}, 总元素: {info.get('totalElements')}")
    print(f"    需要等iframe内容加载...")

# Back to main page - check captcha
r = cmd("Runtime.evaluate", {
    "expression": """(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i=0; i<frames.length; i++) {
            if ((frames[i].src||'').indexOf('punish') !== -1) {
                var r = frames[i].getBoundingClientRect();
                return JSON.stringify({found:true, vis:r.width>0&&r.height>0, x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
            }
        }
        return JSON.stringify({found:false});
    })()""",
    "returnByValue": True,
})
final = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
print(f"\n[最终] punish iframe: {json.dumps(final)}")

r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/iframe_drag_result.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

ws.close()
print("\n[DONE]")
