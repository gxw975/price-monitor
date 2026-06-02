"""GA探索验证 v4 - 简化版，先定位再拖拽"""
import json, urllib.request, websocket, time, base64, ctypes, random, os, subprocess

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

CDP = "http://127.0.0.1:9223/json"

def get_ws():
    targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())
    for t in targets:
        if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
            return t["webSocketDebuggerUrl"], t.get("title", "")
    return None, None

def connect():
    url, title = get_ws()
    if not url: raise RuntimeError("No page")
    ws = websocket.create_connection(url, timeout=15)
    ws.settimeout(10)
    mid = [0]
    def cmd(method, params=None):
        mid[0] += 1
        msg = json.dumps({"id": mid[0], "method": method, "params": params or {}})
        ws.send(msg)
        for _ in range(60):
            raw = ws.recv()
            r = json.loads(raw)
            if r.get("id") == mid[0]:
                return r
        return {"error": "timeout"}
    return ws, cmd

def enable_domains(ws, cmd):
    for d in ("Runtime", "Page", "DOM"):
        cmd(f"{d}.enable")

def screen(ws, cmd, path):
    r = cmd("Page.captureScreenshot", {"format": "png"})
    data = r.get("result", {}).get("data", "")
    if data:
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"    截图: {path} ({len(base64.b64decode(data))} bytes)")
        return True
    print(f"    截图失败: {str(r)[:100]}")
    return False

def check_captcha(ws, cmd):
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var frames = document.querySelectorAll('iframe');
            for (var i=0; i<frames.length; i++) {
                if ((frames[i].src||'').indexOf('punish') !== -1) {
                    var r = frames[i].getBoundingClientRect();
                    return JSON.stringify({
                        found: true, visible: r.width>0 && r.height>0,
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height)
                    });
                }
            }
            return JSON.stringify({found: false});
        })()""",
        "returnByValue": True,
    })
    return json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))

def get_offset(ws, cmd):
    r = cmd("Runtime.evaluate", {
        "expression": """(function(){
            var fl = (window.outerWidth - window.innerWidth) / 2;
            var to = window.outerHeight - window.innerHeight - fl;
            var ox = (window.screenLeft || 0) + fl;
            var oy = (window.screenTop || 0) + to;
            return JSON.stringify({
                ox: Math.round(ox), oy: Math.round(oy),
                outerW: window.outerWidth, outerH: window.outerHeight,
                innerW: window.innerWidth, innerH: window.innerHeight,
                screenLeft: window.screenLeft || 0,
                screenTop: window.screenTop || 0
            });
        })()""",
        "returnByValue": True,
    })
    return json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))

def get_body_text(ws, cmd):
    r = cmd("Runtime.evaluate", {
        "expression": "document.body ? document.body.innerText.slice(0, 2000) : 'NO_BODY'",
        "returnByValue": True,
    })
    return r.get("result", {}).get("result", {}).get("value", "")

# ============================================================
print("[1] 连接并截图...")
ws, cmd = connect()
enable_domains(ws, cmd)

screen(ws, cmd, "/home/lab-admin/price-monitor/data/v4_before.png")

captcha = check_captcha(ws, cmd)
print(f"    验证弹窗: {json.dumps(captcha)}")

if not captcha.get("visible"):
    print("    → 弹窗不存在或不可见!")
    ws.close()
    exit(0)

offset = get_offset(ws, cmd)
print(f"    偏移: ox={offset['ox']} oy={offset['oy']}")
print(f"    尺寸: outer={offset['outerW']}x{offset['outerH']} inner={offset['innerW']}x{offset['innerH']}")
print(f"    screenLeft={offset['screenLeft']} screenTop={offset['screenTop']}")

# 读主页文字确认能看到什么
body = get_body_text(ws, cmd)
print(f"    body文字长度: {len(body)}")
print(f"    body前200字: {body[:200]}")

ws.close()

# ============================================================
# 计算屏幕坐标
iframe_x = captcha["x"]
iframe_y = captcha["y"]  
iframe_w = captcha["w"]
iframe_h = captcha["h"]
ox = offset["ox"]
oy = offset["oy"]

print(f"\n[2] iframe: viewport=({iframe_x},{iframe_y}) {iframe_w}x{iframe_h}")
print(f"    iframe屏幕区域: ({iframe_x+ox},{iframe_y+oy}) - ({iframe_x+ox+iframe_w},{iframe_y+oy+iframe_h})")

# 尝试不同估算
estimates = [
    ("14/78/85", 0.14, 0.78, 0.85),
    ("12/76/87", 0.12, 0.76, 0.87),
    ("10/75/88", 0.10, 0.75, 0.88),
    ("16/80/83", 0.16, 0.80, 0.83),
    ("18/78/82", 0.18, 0.78, 0.82),
]

for desc, sx_r, sy_r, dist_r in estimates:
    screen_x = iframe_x + int(iframe_w * sx_r) + ox
    screen_y = iframe_y + int(iframe_h * sy_r) + oy
    drag_dist = int(iframe_w * dist_r)
    end_x = screen_x + drag_dist
    
    print(f"\n[3] 尝试 xdotool {desc}: ({screen_x},{screen_y}) -> ({end_x},{screen_y}) dist={drag_dist}")
    
    subprocess.run(["xdotool", "mousemove", str(screen_x), str(screen_y)],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.15)
    subprocess.run(["xdotool", "mousedown", "1"],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.15)
    
    steps = 80
    step_size = drag_dist / steps
    for i in range(1, steps + 1):
        p = i / steps
        noise = random.randint(-3, 3)
        cx = int(screen_x + step_size * i)
        cy = screen_y + noise
        subprocess.run(["xdotool", "mousemove", str(cx), str(cy)],
                       env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
        time.sleep(random.uniform(0.005, 0.02))
    
    subprocess.run(["xdotool", "mousemove", str(end_x), str(screen_y)],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.2)
    subprocess.run(["xdotool", "mouseup", "1"],
                   env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    time.sleep(0.3)
    
    time.sleep(3)
    
    ws2, cmd2 = connect()
    enable_domains(ws2, cmd2)
    result = check_captcha(ws2, cmd2)
    print(f"    → found={result.get('found')} visible={result.get('visible')}")
    
    if not result.get("visible"):
        print(f"\n    ✅✅✅ 验证通过! ({desc}) ✅✅✅")
        screen(ws2, cmd2, "/home/lab-admin/price-monitor/data/v4_success.png")
        
        # 读页面确认
        body2 = get_body_text(ws2, cmd2)
        print(f"    通过后body文字长度: {len(body2)}")
        print(f"    通过后body前200字: {body2[:200]}")
        
        ws2.close()
        exit(0)
    
    ws2.close()
    time.sleep(1)

# ============================================================
print("\n[4] xdotool全失败，尝试直接点击iframe中心...")
ws3, cmd3 = connect()
enable_domains(ws3, cmd3)

# 也许需要先点一下iframe激活它
cx = iframe_x + ox + iframe_w // 2
cy = iframe_y + oy + iframe_h // 2
print(f"    点击iframe中心: ({cx},{cy})")
subprocess.run(["xdotool", "mousemove", str(cx), str(cy)],
               env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
time.sleep(0.2)
subprocess.run(["xdotool", "click", "1"],
               env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
time.sleep(2)

result3 = check_captcha(ws3, cmd3)
print(f"    点击后: found={result3.get('found')} visible={result3.get('visible')}")

# 截图最终状态
screen(ws3, cmd3, "/home/lab-admin/price-monitor/data/v4_final.png")
ws3.close()

print("\n[DONE] 探索完成，截图已保存到 data/v4_*.png")
