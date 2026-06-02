"""使用正确的 executionContext 进入punish iframe"""
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

# Method 1: Use Runtime.enable to discover execution contexts
r = cmd("Runtime.enable")
print(f"[1] Runtime.enable: {str(r.get('result', {}))[:100]}")

# Method 2: List all targets to find the punish iframe target directly
print(f"\n[2] 搜索punish iframe的独立target...")
targets2 = json.loads(urllib.request.urlopen(CDP, timeout=5).read())
for t in targets2:
    url = t.get("url", "")
    ttype = t.get("type", "")
    if "punish" in url:
        print(f"    type={ttype}")
        print(f"    url={url[:120]}")
        print(f"    ws={t.get('webSocketDebuggerUrl', '')[:80]}")
        if "webSocketDebuggerUrl" in t:
            # Connect directly to the iframe!
            ws2 = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=15)
            ws2.settimeout(8)
            mid2 = [0]
            def cmd2(m, p=None):
                mid2[0] += 1
                ws2.send(json.dumps({"id": mid2[0], "method": m, "params": p or {}}))
                for _ in range(50):
                    r = json.loads(ws2.recv())
                    if r.get("id") == mid2[0]:
                        return r
                return {}
            
            for d in ("Runtime", "Page", "DOM"):
                cmd2(f"{d}.enable")
            
            # Check inside
            r = cmd2("Runtime.evaluate", {
                "expression": """JSON.stringify((function(){
                    var result = {};
                    result.docTitle = document.title || 'EMPTY';
                    result.bodyLen = document.body ? document.body.innerHTML.length : 0;
                    result.bodyText = document.body ? document.body.innerText.slice(0, 500) : 'NO_BODY';
                    
                    var s = document.getElementById('nc_1_n1z');
                    var t = document.getElementById('nc_1__scale_text');
                    result.hasSlider = !!s;
                    result.hasTrack = !!t;
                    
                    if (s) {
                        var r = s.getBoundingClientRect();
                        result.slider = {x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)};
                    }
                    if (t) {
                        var r = t.getBoundingClientRect();
                        result.track = {x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)};
                    }
                    if (s && t) {
                        var sr = s.getBoundingClientRect();
                        var tr = t.getBoundingClientRect();
                        result.distance = Math.round(tr.x + tr.width - sr.x - sr.width + 3);
                    }
                    
                    return result;
                })())""",
                "returnByValue": True,
            })
            info = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
            print(f"\n[3] 直接连接iframe内部:")
            for k, v in info.items():
                print(f"    {k}: {str(v)[:200]}")
            
            if info.get("hasSlider") and info.get("hasTrack"):
                sx = info["slider"]["x"] + info["slider"]["w"] // 2
                sy = info["slider"]["y"] + info["slider"]["h"] // 2
                dist = info["distance"]
                print(f"\n[4] 滑块中心: ({sx},{sy}) 拖拽: {dist}px")
                
                # Mouse events INSIDE the iframe
                cmd2("Runtime.evaluate", {
                    "expression": """(function(){
                        var s = document.getElementById('nc_1_n1z');
                        if (!s) return 'NO_SLIDER';
                        var r = s.getBoundingClientRect();
                        var sx = r.x + r.width/2;
                        var sy = r.y + r.height/2;
                        var dist = """ + str(dist) + """;
                        
                        s.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, clientX:sx, clientY:sy, button:0, buttons:1}));
                        
                        var steps = 60, stepX = dist / steps;
                        for (var i=1; i<=steps; i++) {
                            var p = i/steps;
                            var noise = Math.floor((Math.random()-0.5)*4*(1-p*0.85));
                            var cx = sx + stepX*i + (Math.random()-0.5)*2;
                            var cy = sy + noise;
                            s.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, cancelable:true, clientX:cx, clientY:cy, button:0, buttons:1}));
                        }
                        
                        setTimeout(function(){
                            s.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, clientX:sx+dist, clientY:sy, button:0, buttons:0}));
                        }, 50);
                        
                        return 'DISPATCHED';
                    })()""",
                    "returnByValue": True,
                })
                
                time.sleep(4)
                
                r = cmd2("Runtime.evaluate", {
                    "expression": """(function(){
                        var w = document.getElementById('nc_1_wrapper');
                        if (!w || w.offsetHeight === 0) return 'GONE';
                        var s = document.getElementById('nc_1_n1z');
                        if (!s) return 'NO_SLIDER';
                        return 'STILL_THERE';
                    })()""",
                    "returnByValue": True,
                })
                status = r.get("result", {}).get("result", {}).get("value", "")
                print(f"[5] 结果: {status}")
                
                if status == "GONE":
                    print(">>> ✅✅✅ 验证通过! ✅✅✅")
                    ws2.close()
                    ws.close()
                    exit(0)
                
                # Try touch events
                print("\n[6] 尝试Touch事件...")
                cmd2("Runtime.evaluate", {
                    "expression": """(function(){
                        var s = document.getElementById('nc_1_n1z');
                        if (!s) return 'NO_SLIDER';
                        var r = s.getBoundingClientRect();
                        var sx = r.x + r.width/2;
                        var sy = r.y + r.height/2;
                        var dist = """ + str(dist) + """;
                        var tid = Date.now();
                        
                        function makeTouch(x, y) {
                            return new Touch({identifier:tid, target:s, clientX:x, clientY:y, pageX:x, pageY:y, radiusX:2.5, radiusY:2.5, rotationAngle:0, force:0.5});
                        }
                        
                        var t1 = makeTouch(sx, sy);
                        s.dispatchEvent(new TouchEvent('touchstart', {bubbles:true, cancelable:true, touches:[t1], targetTouches:[t1], changedTouches:[t1]}));
                        
                        var steps=40, stepX=dist/steps;
                        for (var i=1; i<=steps; i++) {
                            var cx = sx + stepX*i;
                            var cy = sy + Math.floor((Math.random()-0.5)*4);
                            var ti = makeTouch(cx, cy);
                            s.dispatchEvent(new TouchEvent('touchmove', {bubbles:true, cancelable:true, touches:[ti], targetTouches:[ti], changedTouches:[ti]}));
                        }
                        
                        setTimeout(function(){
                            var te = makeTouch(sx+dist, sy);
                            s.dispatchEvent(new TouchEvent('touchend', {bubbles:true, cancelable:true, touches:[], targetTouches:[], changedTouches:[te]}));
                        }, 50);
                        
                        return 'TOUCH_DISPATCHED';
                    })()""",
                    "returnByValue": True,
                })
                time.sleep(4)
                
                r = cmd2("Runtime.evaluate", {
                    "expression": """(function(){
                        var w = document.getElementById('nc_1_wrapper');
                        if (!w || w.offsetHeight === 0) return 'GONE';
                        return 'STILL_THERE';
                    })()""",
                    "returnByValue": True,
                })
                status2 = r.get("result", {}).get("result", {}).get("value", "")
                print(f"[7] Touch结果: {status2}")
                
                if status2 == "GONE":
                    print(">>> ✅✅✅ Touch验证通过! ✅✅✅")
                else:
                    # Direct JS manipulation - set slider position
                    print("\n[8] 直接JS操控滑块位置...")
                    cmd2("Runtime.evaluate", {
                        "expression": """(function(){
                            var s = document.getElementById('nc_1_n1z');
                            var t = document.getElementById('nc_1_wrapper');
                            if (!s || !t) return 'NO_ELEMENTS';
                            
                            var sr = s.getBoundingClientRect();
                            var tr = t.getBoundingClientRect();
                            var maxDist = tr.width - sr.width - 10;
                            var dist = """ + str(dist) + """;
                            if (dist > maxDist) dist = maxDist;
                            
                            // Set transform
                            s.style.transform = 'translateX(' + dist + 'px)';
                            s.style.transition = 'none';
                            
                            // Trigger change event
                            s.dispatchEvent(new Event('change', {bubbles: true}));
                            
                            // Try to set data attributes
                            s.setAttribute('data-dragged', 'true');
                            
                            return 'MANIPULATED x=' + dist;
                        })()""",
                        "returnByValue": True,
                    })
                    time.sleep(2)
                    
                    r = cmd2("Runtime.evaluate", {
                        "expression": """(function(){
                            var w = document.getElementById('nc_1_wrapper');
                            if (!w || w.offsetHeight === 0) return 'GONE';
                            return 'STILL_THERE';
                        })()""",
                        "returnByValue": True,
                    })
                    print(f"[9] JS操控后: {r.get('result',{}).get('result',{}).get('value','')}")
            
            ws2.close()
        break

ws.close()
print("\n[DONE]")
