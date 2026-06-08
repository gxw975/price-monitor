import json, urllib.request, websocket, time, math, ctypes, ctypes.util, os, random

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
os.environ.setdefault("DISPLAY", DISPLAY)

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())

# Find all pages
for t in targets:
    print(f'Page: {t.get("title","")[:60]} url={t.get("url","")[:60]}')

pages = [t for t in targets if t.get('type') == 'page']

# Check for captcha on main page
ws = websocket.create_connection(pages[0]['webSocketDebuggerUrl'], timeout=15)
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

# Detect captcha
print('\n=== 检测滑块验证 ===')
js = r"""(function(){
    var frames = document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
        if ((frames[i].src || '').indexOf('punish') !== -1) {
            var rect = frames[i].getBoundingClientRect();
            return JSON.stringify({
                captcha: true,
                type: 'iframe',
                visible: rect.width > 0 && rect.height > 0,
                iframeX: Math.round(rect.x),
                iframeY: Math.round(rect.y),
                iframeW: Math.round(rect.width),
                iframeH: Math.round(rect.height)
            });
        }
    }
    var body = document.body ? document.body.innerText : '';
    if (body.indexOf('请拖动下方滑块') !== -1) return JSON.stringify({captcha: true, type: 'text'});
    if (body.indexOf('验证码') !== -1) return JSON.stringify({captcha: true, type: 'text_captcha'});
    return JSON.stringify({captcha: false});
})()"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
cap = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
print(f'主页面检测: {json.dumps(cap, ensure_ascii=False)}')

if not cap.get('captcha'):
    print('未检测到验证码')
    ws.close()
    exit(0)

print('\n=== 验证码已检测到，开始求解 ===')

# Get the punish iframe
frame_tree = cdp('Page.getFrameTree')
ft = frame_tree.get('result', {}).get('frameTree', {})

def find_punish_frame(tree):
    fid = tree.get('frame', {}).get('id', '')
    url = tree.get('frame', {}).get('url', '')
    if 'punish' in url:
        return fid
    for child in tree.get('childFrames', []):
        result = find_punish_frame({'frame': child})
        if result:
            return result
    return None

punish_fid = find_punish_frame(ft)
print(f'punish frameId: {punish_fid}')

if not punish_fid:
    print('未找到punish frame，尝试直接用text检测求解...')
    ws.close()
    exit(1)

# Get execution context for punish frame
iso = cdp('Page.createIsolatedWorld', {'frameId': punish_fid, 'worldName': 'captcha_world'})
ctx_id = iso.get('result', {}).get('executionContextId')
print(f'executionContextId: {ctx_id}')

# Get slider position inside punish iframe
slider_js = r"""(function(){
    var s = document.querySelector('#nc_1_n1z');
    var t = document.querySelector('#nc_1__scale_text');
    if (!s || !t) return JSON.stringify({found: false});
    var sr = s.getBoundingClientRect(), tr = t.getBoundingClientRect();
    return JSON.stringify({
        found: true,
        x: Math.round(sr.x + sr.width/2),
        y: Math.round(sr.y + sr.height/2),
        w: Math.round(sr.width),
        h: Math.round(sr.height),
        distance: Math.round(tr.x + tr.width - sr.x - sr.width + 5)
    });
})()"""

slider_r = cdp('Runtime.evaluate', {
    'expression': slider_js,
    'returnByValue': True,
    'contextId': ctx_id
})
slider = json.loads(slider_r.get('result', {}).get('result', {}).get('value', '{}'))
print(f'滑块在iframe内位置: {json.dumps(slider, ensure_ascii=False)}')

if not slider.get('found'):
    # Try with errloading detection
    err_js = r"""(function(){
        var e = document.querySelector('.errloading');
        if (e) return JSON.stringify({error: 'errloading', text: e.textContent || ''});
        return JSON.stringify({found: false});
    })()"""
    err_r = cdp('Runtime.evaluate', {
        'expression': err_js,
        'returnByValue': True,
        'contextId': ctx_id
    })
    err = json.loads(err_r.get('result', {}).get('result', {}).get('value', '{}'))
    print(f'errloading: {err}')
    if err.get('error'):
        # Click errloading
        click_js = r"""(function(){
            var e = document.querySelector('.errloading');
            if (e) { e.click(); return 'clicked'; }
            return 'not_found';
        })()"""
        cdp('Runtime.evaluate', {'expression': click_js, 'returnByValue': True, 'contextId': ctx_id})
        time.sleep(3)
        # Re-detect
        slider_r2 = cdp('Runtime.evaluate', {
            'expression': slider_js,
            'returnByValue': True,
            'contextId': ctx_id
        })
        slider = json.loads(slider_r2.get('result', {}).get('result', {}).get('value', '{}'))

if not slider.get('found'):
    print('无法定位滑块')
    ws.close()
    exit(1)

# Get viewport offset
offset_js = r"""(function(){
    var fl = (window.outerWidth - window.innerWidth) / 2;
    return JSON.stringify({
        ox: (window.screenLeft || 0) + fl,
        oy: (window.screenTop || 0) + window.outerHeight - window.innerHeight - fl
    });
})()"""
offset_r = cdp('Runtime.evaluate', {'expression': offset_js, 'returnByValue': True})
off = json.loads(offset_r.get('result', {}).get('result', {}).get('value', '{}'))
OX, OY = off.get('ox', 66), off.get('oy', 119)

# Calculate screen coordinates
iframe_l = cap.get('iframeX', 0)
iframe_t = cap.get('iframeY', 0)
sx = int(slider['x'] + iframe_l + OX)
sy = int(slider['y'] + iframe_t + OY)
dist = slider['distance']

print(f'\n=== 坐标计算 ===')
print(f'iframe左上: ({iframe_l},{iframe_t})')
print(f'滑块在iframe内: ({slider["x"]},{slider["y"]})')
print(f'viewport offset: ({OX},{OY})')
print(f'屏幕坐标: ({sx},{sy}) distance={dist}')

# ========== X11 XTest drag ==========
print('\n=== X11 XTest 拖拽 ===')
import ctypes.util

xlib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
xtest = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xtst"))
disp = xlib.XOpenDisplay(None)

if not disp:
    print('❌ 无法打开X11 display')
    ws.close()
    exit(1)

def mov(x, y):
    xtest.XTestFakeMotionEvent(disp, 0, int(x), int(y), 0)
    xlib.XSync(disp, 0)

# Approach
ax = sx - random.randint(35, 55)
ay = sy + random.randint(-10, 10)
for i in range(14):
    p = (i + 1) / 14
    mov(int(ax + (sx - ax) * p), int(ay + (sy - ay) * p + math.sin(i * 0.5) * 5))
    time.sleep(0.015 + random.random() * 0.02)

# Hover
mov(sx, sy)
time.sleep(0.25 + random.random() * 0.35)

# Press
xtest.XTestFakeButtonEvent(disp, 1, 1, 0)
xlib.XSync(disp, 0)
time.sleep(0.03)

# Drag - 300 points
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

    x = int(sx + dist * e)
    yj = (math.sin(p * math.pi * 3.1) * 2.5 +
          math.sin(p * math.pi * 7.3) * 0.6 +
          math.sin(p * math.pi * 13.7) * 0.3)
    if random.random() < 0.02:
        yj += (random.random() - 0.5) * 8
    y = int(sy + yj)
    mov(x, y)
    time.sleep(max(0.002, total_t / pts * (0.6 + random.random() * 0.8)))

# Settle
mov(int(sx + dist), int(sy))
time.sleep(0.05)
mov(int(sx + dist + random.uniform(2, 5)), int(sy + random.randint(-1, 1)))
time.sleep(0.04)
mov(int(sx + dist), int(sy))
time.sleep(0.05)

# Release
time.sleep(0.18 + random.random() * 0.25)
xtest.XTestFakeButtonEvent(disp, 1, 0, 0)
xlib.XSync(disp, 0)
print('✅ X11拖拽完成')

xlib.XCloseDisplay(disp)

# Wait and verify
time.sleep(4)
r2 = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
cap2 = json.loads(r2.get('result', {}).get('result', {}).get('value', '{}'))
print(f'验证后检测: {json.dumps(cap2, ensure_ascii=False)}')

if not cap2.get('captcha'):
    print('\n✅✅✅ 滑块验证成功！！！')
else:
    print('\n❌ 滑块验证仍存在，需要重试')

ws.close()
