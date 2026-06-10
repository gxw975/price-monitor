import json, urllib.request, websocket, time, math, ctypes, ctypes.util, os, random

DISPLAY = ":0"
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
        var body = document.body ? document.body.innerText : '';
        if (body.indexOf('请拖动下方滑块') !== -1) return JSON.stringify({captcha: true, type: 'text'});
        return JSON.stringify({captcha: false});
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

def get_viewport_offset():
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

# Init
cap = check_captcha()
if not cap.get('captcha'):
    print('✅ 无验证码')
    ws.close()
    exit(0)

print(f'验证码iframe: {cap}')

OX, OY = get_viewport_offset()
iframe_x, iframe_y = cap.get('x', 397), cap.get('y', 181)
iframe_w, iframe_h = cap.get('w', 420), cap.get('h', 320)

print(f'viewport offset: ({OX},{OY})')

# X11 init
xlib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
xtest = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xtst"))
disp = xlib.XOpenDisplay(None)

def mov(x, y):
    xtest.XTestFakeMotionEvent(disp, 0, int(x), int(y), 0)
    xlib.XSync(disp, 0)

# Try multiple slider positions
# Standard GeeTest slider: about 12-15% from left, 88-92% from top of iframe
attempts = [
    # (slider_iframe_x_ratio, slider_iframe_y_ratio, distance_ratio)
    (0.13, 0.90, None),  # 13% from left, 90% from top
    (0.15, 0.88, None),
    (0.12, 0.92, None),
    (0.14, 0.89, None),
    (0.13, 0.90, None),
]

for attempt_idx, (sx_ratio, sy_ratio, _) in enumerate(attempts):
    print(f'\n=== 尝试 {attempt_idx+1}/{len(attempts)} ===')

    cap = check_captcha()
    if not cap.get('captcha'):
        print('✅ 验证码已消失！')
        break

    slider_x = int(iframe_w * sx_ratio)
    slider_y = int(iframe_h * sy_ratio)

    # Estimate distance: slider moves across about 75-80% of iframe width
    distance = int(iframe_w * 0.65) + random.randint(-10, 15)

    sx = slider_x + iframe_x + OX
    sy = slider_y + iframe_y + OY

    print(f'slider@iframe({slider_x},{slider_y}) screen({sx},{sy}) dist={distance}')

    # Approach
    ax = sx - random.randint(35, 55)
    ay = sy + random.randint(-10, 10)
    for i in range(14):
        p = (i + 1) / 14
        mov(int(ax + (sx - ax) * p), int(ay + (sy - ay) * p + math.sin(i * 0.5) * 5))
        time.sleep(0.015 + random.random() * 0.02)

    mov(sx, sy)
    time.sleep(0.25 + random.random() * 0.35)

    xtest.XTestFakeButtonEvent(disp, 1, 1, 0)
    xlib.XSync(disp, 0)
    time.sleep(0.03)

    pts = 300 + random.randint(40, 80)
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
        mov(x, y)
        time.sleep(max(0.002, total_t / pts * (0.6 + random.random() * 0.8)))

    mov(int(sx + distance), int(sy))
    time.sleep(0.05)
    mov(int(sx + distance + random.uniform(2, 5)), int(sy + random.randint(-1, 1)))
    time.sleep(0.04)
    mov(int(sx + distance), int(sy))
    time.sleep(0.05)

    time.sleep(0.18 + random.random() * 0.25)
    xtest.XTestFakeButtonEvent(disp, 1, 0, 0)
    xlib.XSync(disp, 0)
    print('拖拽完成，等待验证...')

    time.sleep(5)

xlib.XCloseDisplay(disp)

cap = check_captcha()
print(f'\n最终: {json.dumps(cap, ensure_ascii=False)}')
if not cap.get('captcha'):
    print('✅✅✅ 滑块验证成功！')
else:
    print('❌ 验证码仍存在')

ws.close()
