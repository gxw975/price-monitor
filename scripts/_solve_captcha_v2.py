import json, urllib.request, websocket, time, math, ctypes, ctypes.util, os, random, subprocess

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
os.environ.setdefault("DISPLAY", DISPLAY)

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())

# Find main page
main_page = None
for t in targets:
    if t.get('type') == 'page' and 'taobao.com/search' in t.get('url', ''):
        main_page = t
        break

if not main_page:
    print('未找到淘宝搜索页')
    exit(1)

print(f'主页面: {main_page["url"][:100]}')

# Connect to main page
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

# Get frame tree and find punish frame
ft = cdp('Page.getFrameTree')
ftree = ft.get('result', {}).get('frameTree', {})

def dump_frames(tree, depth=0):
    f = tree.get('frame', {})
    fid = f.get('id', '')[:20]
    url = f.get('url', '')[:80]
    print(f'  {"  "*depth}[{fid}] {url}')
    for child in tree.get('childFrames', []):
        dump_frames({'frame': child}, depth+1)

print('\n=== Frame Tree ===')
dump_frames(ftree)

def find_punish(tree):
    f = tree.get('frame', {})
    url = f.get('url', '')
    fid = f.get('id', '')
    if 'punish' in url:
        return fid, url
    for child in tree.get('childFrames', []):
        result = find_punish({'frame': child})
        if result:
            return result
    return None, None

punish_fid, punish_url = find_punish(ftree)
print(f'\npunish frame: id={punish_fid} url={punish_url}')

# Get captcha iframe position from main page
js = r"""(function(){
    var frames = document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
        var src = (frames[i].src || '');
        if (src.indexOf('punish') !== -1) {
            var rect = frames[i].getBoundingClientRect();
            var fl = (window.outerWidth - window.innerWidth) / 2;
            return JSON.stringify({
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                w: Math.round(rect.width),
                h: Math.round(rect.height),
                ox: Math.round((window.screenLeft || 0) + fl),
                oy: Math.round((window.screenTop || 0) + window.outerHeight - window.innerHeight - fl)
            });
        }
    }
    return JSON.stringify({found: false});
})()"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
iframe_info = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
print(f'\n=== iframe信息 ===')
print(json.dumps(iframe_info, indent=2, ensure_ascii=False))

OX = iframe_info.get('ox', 66)
OY = iframe_info.get('oy', 119)
iframe_x = iframe_info.get('x', 0)
iframe_y = iframe_info.get('y', 0)

# Find slider inside punish iframe using CDP
if punish_fid:
    iso = cdp('Page.createIsolatedWorld', {'frameId': punish_fid, 'worldName': 'cap'})
    ctx_id = iso.get('result', {}).get('executionContextId')
    print(f'\npunish executionContextId: {ctx_id}')

    slider_js = r"""(function(){
        var s = document.querySelector('#nc_1_n1z');
        var t = document.querySelector('#nc_1__scale_text');
        if (!s || !t) {
            var e = document.querySelector('.errloading');
            if (e) return JSON.stringify({error: 'errloading'});
            return JSON.stringify({found: false, body: (document.body?.innerText || '').substring(0, 200)});
        }
        var sr = s.getBoundingClientRect(), tr = t.getBoundingClientRect();
        return JSON.stringify({
            found: true,
            x: Math.round(sr.x + sr.width/2),
            y: Math.round(sr.y + sr.height/2),
            distance: Math.round(tr.x + tr.width - sr.x - sr.width + 8)
        });
    })()"""

    slider_r = cdp('Runtime.evaluate', {
        'expression': slider_js,
        'returnByValue': True,
        'contextId': ctx_id
    })
    slider = json.loads(slider_r.get('result', {}).get('result', {}).get('value', '{}'))
    print(f'\n滑块信息: {json.dumps(slider, ensure_ascii=False)}')

    if slider.get('error') == 'errloading':
        print('检测到errloading，点击恢复...')
        cdp('Runtime.evaluate', {
            'expression': r"""(function(){
                var e = document.querySelector('.errloading');
                if (e) { e.click(); return 'clicked'; }
                return 'not_found';
            })()""",
            'returnByValue': True,
            'contextId': ctx_id
        })
        time.sleep(2.5)
        slider_r = cdp('Runtime.evaluate', {
            'expression': slider_js,
            'returnByValue': True,
            'contextId': ctx_id
        })
        slider = json.loads(slider_r.get('result', {}).get('result', {}).get('value', '{}'))
        print(f'重试后滑块: {json.dumps(slider, ensure_ascii=False)}')

    if not slider.get('found'):
        print('❌ 无法定位滑块')
        ws.close()
        exit(1)

    # Calculate screen coordinates
    sx = int(slider['x'] + iframe_x + OX)
    sy = int(slider['y'] + iframe_y + OY)
    dist = slider['distance']
    print(f'\n屏幕坐标: ({sx},{sy}) distance={dist}')

    # ===== X11 Drag =====
    print('\n=== X11 XTest 拖拽 ===')
    xlib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
    xtest = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xtst"))
    disp = xlib.XOpenDisplay(None)

    def mov(x, y):
        xtest.XTestFakeMotionEvent(disp, 0, int(x), int(y), 0)
        xlib.XSync(disp, 0)

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
        x = int(sx + dist * e)
        yj = (math.sin(p * math.pi * 3.1) * 2.5 +
              math.sin(p * math.pi * 7.3) * 0.6 +
              math.sin(p * math.pi * 13.7) * 0.3)
        if random.random() < 0.02:
            yj += (random.random() - 0.5) * 8
        y = int(sy + yj)
        mov(x, y)
        time.sleep(max(0.002, total_t / pts * (0.6 + random.random() * 0.8)))

    mov(int(sx + dist), int(sy))
    time.sleep(0.05)
    mov(int(sx + dist + random.uniform(2, 5)), int(sy + random.randint(-1, 1)))
    time.sleep(0.04)
    mov(int(sx + dist), int(sy))
    time.sleep(0.05)

    time.sleep(0.18 + random.random() * 0.25)
    xtest.XTestFakeButtonEvent(disp, 1, 0, 0)
    xlib.XSync(disp, 0)
    print('✅ X11拖拽完成')
    xlib.XCloseDisplay(disp)

    # Verify
    time.sleep(4)
    check = r"""(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i = 0; i < frames.length; i++) {
            if ((frames[i].src || '').indexOf('punish') !== -1) {
                var rect = frames[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) return JSON.stringify({captcha: true});
            }
        }
        return JSON.stringify({captcha: false});
    })()"""
    r2 = cdp('Runtime.evaluate', {'expression': check, 'returnByValue': True})
    result = json.loads(r2.get('result', {}).get('result', {}).get('value', '{}'))
    print(f'\n验证后: {json.dumps(result, ensure_ascii=False)}')
    if not result.get('captcha'):
        print('✅✅✅ 滑块验证成功！')
    else:
        print('❌ 仍需重试')

else:
    print('❌ 未找到punish frame')
    # Try without frameId - check if captcha is gone
    check = r"""(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i = 0; i < frames.length; i++) {
            if ((frames[i].src || '').indexOf('punish') !== -1) {
                var rect = frames[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) return 'captcha_visible';
            }
        }
        return 'none';
    })()"""
    r3 = cdp('Runtime.evaluate', {'expression': check, 'returnByValue': True})
    val3 = r3.get('result', {}).get('result', {}).get('value', '')
    print(f'兜底检测: {val3}')

ws.close()
