import json, urllib.request, websocket, time, math, ctypes, ctypes.util, os, random, subprocess

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
os.environ.setdefault("DISPLAY", DISPLAY)

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())

main_page = None
for t in targets:
    url = t.get('url', '')
    if t.get('type') == 'page' and 'taobao.com/search' in url:
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

# ====== Step 1: Navigate to punish iframe URL to get slider position ======
# Find the punish iframe src
js = r"""(function(){
    var iframes = document.querySelectorAll('iframe');
    var results = [];
    for (var i = 0; i < iframes.length; i++) {
        var src = iframes[i].src || '';
        var rect = iframes[i].getBoundingClientRect();
        results.push({src: src.substring(0, 120), vx: Math.round(rect.x), vy: Math.round(rect.y), vw: Math.round(rect.width), vh: Math.round(rect.height)});
    }
    return JSON.stringify(results);
})()"""
r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
iframes = json.loads(r.get('result', {}).get('result', {}).get('value', '[]'))
print(f'=== iframes ===')
for f in iframes:
    print(f'  src={f.get("src")} @ ({f.get("vx")},{f.get("vy")}) {f.get("vw")}x{f.get("vh")}')

punish_iframe = None
for f in iframes:
    if 'punish' in f.get('src', ''):
        punish_iframe = f
        break

if not punish_iframe:
    print('未找到punish iframe')
    ws.close()
    exit(1)

punish_url = next((f['src'] for f in iframes if 'punish' in f['src']), None)
print(f'\npunish URL: {punish_url}')

# Get viewport offset
js2 = r"""(function(){
    var fl = (window.outerWidth - window.innerWidth) / 2;
    return JSON.stringify({
        ox: Math.round((window.screenLeft || 0) + fl),
        oy: Math.round((window.screenTop || 0) + window.outerHeight - window.innerHeight - fl)
    });
})()"""
r2 = cdp('Runtime.evaluate', {'expression': js2, 'returnByValue': True})
off = json.loads(r2.get('result', {}).get('result', {}).get('value', '{}'))
OX, OY = off.get('ox', 66), off.get('oy', 119)
print(f'Viewport offset: ({OX}, {OY})')

# ====== Step 2: Navigate main page to punish URL to access its DOM ======
# Save current URL
cur_url = cdp('Runtime.evaluate', {'expression': 'window.location.href', 'returnByValue': True})
current_url = cur_url.get('result', {}).get('result', {}).get('value', '')
print(f'当前URL: {current_url[:100]}')

# Navigate to punish URL to get slider info
print(f'\n导航到punish页面获取滑块信息...')
cdp('Page.navigate', {'url': punish_url})
time.sleep(3)

# Get slider info
slider_js = r"""(function(){
    var s = document.querySelector('#nc_1_n1z');
    var t = document.querySelector('#nc_1__scale_text');
    if (!s || !t) {
        var e = document.querySelector('.errloading');
        if (e) return JSON.stringify({error: 'errloading', text: (e.textContent || '').trim()});
        var body = (document.body?.innerText || '').substring(0, 200);
        return JSON.stringify({found: false, body: body});
    }
    var sr = s.getBoundingClientRect(), tr = t.getBoundingClientRect();
    return JSON.stringify({
        found: true,
        x: Math.round(sr.x + sr.width/2),
        y: Math.round(sr.y + sr.height/2),
        distance: Math.round(tr.x + tr.width - sr.x - sr.width + 8)
    });
})()"""
sr = cdp('Runtime.evaluate', {'expression': slider_js, 'returnByValue': True})
slider = json.loads(sr.get('result', {}).get('result', {}).get('value', '{}'))
print(f'滑块信息: {json.dumps(slider, ensure_ascii=False)}')

if slider.get('error') == 'errloading':
    print('errloading! 点击恢复...')
    cdp('Runtime.evaluate', {'expression': r"""(function(){
        var e = document.querySelector('.errloading');
        if (e) { e.click(); return 'clicked'; }
        var nc = document.querySelector('#nc_1_n1z');
        if (nc) {
            var rect = nc.getBoundingClientRect();
            nc.click();
            return 'clicked_nc';
        }
        return 'not_found';
    })()""", 'returnByValue': True})
    time.sleep(3)
    sr = cdp('Runtime.evaluate', {'expression': slider_js, 'returnByValue': True})
    slider = json.loads(sr.get('result', {}).get('result', {}).get('value', '{}'))
    print(f'重试后: {json.dumps(slider, ensure_ascii=False)}')

if not slider.get('found'):
    print('❌ 无法定位滑块，body内容:', slider.get('body', '')[:200])
    # Navigate back
    cdp('Page.navigate', {'url': current_url})
    ws.close()
    exit(1)

# ====== Step 3: Navigate back and drag ======
print(f'\n导航回淘宝页...')
cdp('Page.navigate', {'url': current_url})
time.sleep(3)

# Verify captcha is still there
js3 = r"""(function(){
    var frames = document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
        if ((frames[i].src || '').indexOf('punish') !== -1) {
            var rect = frames[i].getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) return JSON.stringify({captcha: true, x: Math.round(rect.x), y: Math.round(rect.y)});
        }
    }
    return JSON.stringify({captcha: false});
})()"""
r3 = cdp('Runtime.evaluate', {'expression': js3, 'returnByValue': True})
cap_state = json.loads(r3.get('result', {}).get('result', {}).get('value', '{}'))
print(f'验证码状态: {json.dumps(cap_state, ensure_ascii=False)}')

if not cap_state.get('captcha'):
    print('验证码已消失!')
    ws.close()
    exit(0)

# Calculate screen coordinates
iframe_x = cap_state.get('x', punish_iframe.get('vx', 397))
iframe_y = cap_state.get('y', punish_iframe.get('vy', 181))
slider_iframe_x = slider['x']
slider_iframe_y = slider['y']
distance = slider['distance']

sx = int(slider_iframe_x + iframe_x + OX)
sy = int(slider_iframe_y + iframe_y + OY)
print(f'\n=== 拖拽坐标 ===')
print(f'iframe: ({iframe_x},{iframe_y})')
print(f'滑块在iframe内: ({slider_iframe_x},{slider_iframe_y})')
print(f'viewport offset: ({OX},{OY})')
print(f'screen: ({sx},{sy}) distance={distance}')

# ====== Step 4: X11 Drag ======
print('\n=== X11 XTest 拖拽 ===')
xlib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
xtest = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xtst"))
disp = xlib.XOpenDisplay(None)

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
print('✅ X11拖拽完成')
xlib.XCloseDisplay(disp)

# Verify
time.sleep(5)
r4 = cdp('Runtime.evaluate', {'expression': js3, 'returnByValue': True})
final = json.loads(r4.get('result', {}).get('result', {}).get('value', '{}'))
print(f'\n最终状态: {json.dumps(final, ensure_ascii=False)}')
if not final.get('captcha'):
    print('✅✅✅ 滑块验证成功！！！')
else:
    print('❌ 仍需重试')

ws.close()
