import json, urllib.request, websocket, time, math, os, random, subprocess

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
os.environ.setdefault("DISPLAY", DISPLAY)

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())

main_page = None
for t in targets:
    if t.get('type') == 'page' and 'taobao.com/search' in t.get('url', ''):
        main_page = t
        break

if not main_page:
    print('未找到淘宝搜索页')
    exit(1)

ws = websocket.create_connection(main_page['webSocketDebuggerUrl'], timeout=15)
msg_id = 0

def cdp(method, params=None):
    global msg_id
    msg_id += 1
    msg = {'id': msg_id, 'method': method}
    if params:
        msg['params'] = params
    ws.send(json.dumps(msg))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == msg_id:
            return r

cdp('Page.enable')
cdp('Runtime.enable')

def check_captcha():
    js = r"""(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i = 0; i < frames.length; i++) {
            if ((frames[i].src || '').indexOf('punish') !== -1) {
                var rect = frames[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    return JSON.stringify({captcha: true, x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)});
                }
            }
        }
        return JSON.stringify({captcha: false});
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

def get_offset():
    js = r"""(function(){
        var fl = (window.outerWidth - window.innerWidth) / 2;
        return JSON.stringify({
            ox: Math.round((window.screenLeft || 0) + fl),
            oy: Math.round((window.screenTop || 0) + window.outerHeight - window.innerHeight - fl)
        });
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    d = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
    return d.get('ox', 66), d.get('oy', 119)

cap = check_captcha()
if not cap.get('captcha'):
    print('✅ 无验证码')
    ws.close()
    exit(0)

OX, OY = get_offset()
iframe_x, iframe_y = cap.get('x', 397), cap.get('y', 181)
iframe_w, iframe_h = cap.get('w', 420), cap.get('h', 320)

print(f'验证码iframe: viewport({iframe_x},{iframe_y}) {iframe_w}x{iframe_h}')
print(f'viewport offset: ({OX},{OY})')

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

# Use xdotool for mouse drag
# xdotool mousedown 1 -> mousemove with sleep -> mouseup 1

def xdotool_move(sx, sy):
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=5)

def xdotool_down():
    subprocess.run(["xdotool", "mousedown", "1"], env=env, capture_output=True, timeout=5)

def xdotool_up():
    subprocess.run(["xdotool", "mouseup", "1"], env=env, capture_output=True, timeout=5)

attempts = [
    (0.13, 0.90, 0.65),
    (0.14, 0.89, 0.67),
    (0.12, 0.91, 0.63),
    (0.15, 0.88, 0.66),
    (0.13, 0.90, 0.68),
]

for attempt_idx, (sx_ratio, sy_ratio, dist_ratio) in enumerate(attempts):
    print(f'\n=== 尝试 {attempt_idx+1}/{len(attempts)} ===')

    cap = check_captcha()
    if not cap.get('captcha'):
        print('✅ 验证码已消失！')
        break

    slider_x = int(iframe_w * sx_ratio)
    slider_y = int(iframe_h * sy_ratio)
    distance = int(iframe_w * dist_ratio) + random.randint(-10, 15)

    sx = slider_x + iframe_x + OX
    sy = slider_y + iframe_y + OY

    print(f'screen({sx},{sy}) dist={distance}')

    # Approach
    ax = sx - random.randint(35, 55)
    ay = sy + random.randint(-10, 10)
    for i in range(10):
        p = (i + 1) / 10
        cx = int(ax + (sx - ax) * p)
        cy = int(ay + (sy - ay) * p + math.sin(i * 0.5) * 5)
        xdotool_move(cx, cy)
        time.sleep(0.02 + random.random() * 0.03)

    # Hover
    xdotool_move(sx, sy)
    time.sleep(0.25 + random.random() * 0.35)

    # Press
    xdotool_down()
    time.sleep(0.03)

    # Drag - ~200 points via xdotool
    pts = 200 + random.randint(30, 60)
    total_t = 3.0 + random.random() * 2.5
    for i in range(pts):
        p = i / pts
        if p < 0.08:
            e = (p / 0.08) ** 2 * 0.08
        elif p < 0.88:
            e = 0.08 + (p - 0.08) * 0.84
        else:
            r = (1 - p) / 0.12
            e = 1 - r * r * 0.12
        e += (random.random() - 0.5) * 0.005
        x = int(sx + distance * e)
        yj = (math.sin(p * math.pi * 3.1) * 2.5 +
              math.sin(p * math.pi * 7.3) * 0.6 +
              math.sin(p * math.pi * 13.7) * 0.3)
        if random.random() < 0.02:
            yj += (random.random() - 0.5) * 8
        y = int(sy + yj)
        xdotool_move(x, y)
        time.sleep(max(0.005, total_t / pts * (0.6 + random.random() * 0.8)))

    # Settle
    xdotool_move(int(sx + distance), int(sy))
    time.sleep(0.05)
    xdotool_move(int(sx + distance + random.uniform(2, 5)), int(sy + random.randint(-1, 1)))
    time.sleep(0.04)
    xdotool_move(int(sx + distance), int(sy))
    time.sleep(0.05)

    # Release
    time.sleep(0.18 + random.random() * 0.25)
    xdotool_up()
    print('拖拽完成，等待验证...')

    time.sleep(5)

cap = check_captcha()
print(f'\n最终: {json.dumps(cap, ensure_ascii=False)}')
if not cap.get('captcha'):
    print('✅✅✅ 滑块验证成功！')
else:
    print('❌ 验证码仍存在')

ws.close()
