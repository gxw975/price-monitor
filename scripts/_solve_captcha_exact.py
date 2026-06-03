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

# ---- Step 1: Find punish frameId (aligned with tagui_crawler.py) ----
ft_resp = cdp('Page.getFrameTree')
frame_tree = ft_resp.get('result', {}).get('frameTree', {})
punish_fid = None

def find_punish(node):
    global punish_fid
    for c in node.get('childFrames', []):
        f = c.get('frame', {})
        url = f.get('url', '')
        if 'h5api.m.taobao.com' in url and 'punish' in url:
            punish_fid = f.get('id', '')
            return
        find_punish(c)

find_punish(frame_tree)
print(f'punish frameId: {punish_fid}')

if not punish_fid:
    print('❌ 未找到punish frame')
    ws.close()
    exit(1)

# ---- Step 2: Create isolated world, get slider position ----
iso = cdp('Page.createIsolatedWorld', {'frameId': punish_fid})
ctx_id = iso.get('result', {}).get('executionContextId')
print(f'ctx_id: {ctx_id}')

time.sleep(0.2)

slider_resp = cdp('Runtime.evaluate', {
    'expression': r"""(function(){
        var s = document.querySelector('[id*="nc_1_n1z"]');
        var t = document.querySelector('[id*="nc_1__scale_text"]');
        if (!s || !t) {
            var w = document.querySelector('[id*="nc_1_wrapper"]');
            if (w && (w.innerHTML||'').indexOf('errloading') !== -1)
                return JSON.stringify({found:true, error:'errloading'});
            return JSON.stringify({found:false});
        }
        var sr = s.getBoundingClientRect();
        var tr = t.getBoundingClientRect();
        return JSON.stringify({
            found: true,
            slider_iframe_x: Math.round(sr.x + sr.width/2),
            slider_iframe_y: Math.round(sr.y + sr.height/2),
            distance: Math.round(tr.x + tr.width - sr.x - sr.width + 3)
        });
    })()""",
    'contextId': ctx_id,
    'returnByValue': True
})

slider_raw = slider_resp.get('result', {}).get('result', {}).get('value', '{}')
data = json.loads(slider_raw)
print(f'滑块iframe内: {json.dumps(data, ensure_ascii=False)}')

if data.get('error') == 'errloading':
    print('errloading! 点击恢复...')
    cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var e = document.querySelector('.errloading');
            if (e) { e.click(); return 'clicked'; }
            return 'not_found';
        })()""",
        'contextId': ctx_id,
        'returnByValue': True
    })
    time.sleep(3)
    slider_resp = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var s = document.querySelector('[id*="nc_1_n1z"]');
            var t = document.querySelector('[id*="nc_1__scale_text"]');
            if (!s || !t) return JSON.stringify({found:false});
            var sr = s.getBoundingClientRect();
            var tr = t.getBoundingClientRect();
            return JSON.stringify({
                found: true,
                slider_iframe_x: Math.round(sr.x + sr.width/2),
                slider_iframe_y: Math.round(sr.y + sr.height/2),
                distance: Math.round(tr.x + tr.width - sr.x - sr.width + 3)
            });
        })()""",
        'contextId': ctx_id,
        'returnByValue': True
    })
    slider_raw = slider_resp.get('result', {}).get('result', {}).get('value', '{}')
    data = json.loads(slider_raw)
    print(f'重试后: {json.dumps(data, ensure_ascii=False)}')

if not data.get('found'):
    print('❌ 未找到滑块')
    ws.close()
    exit(1)

# ---- Step 3: Calculate screen coordinates ----
iframe_pos = cdp('Runtime.evaluate', {
    'expression': r"""(function(){
        var fs = document.querySelectorAll('iframe');
        for (var i=0; i<fs.length; i++) {
            if ((fs[i].src||'').indexOf('h5api') !== -1) {
                var r = fs[i].getBoundingClientRect();
                var fl = (window.outerWidth - window.innerWidth) / 2;
                var to = window.outerHeight - window.innerHeight - fl;
                var ox = (window.screenLeft || 0) + fl;
                var oy = (window.screenTop || 0) + to;
                return JSON.stringify({
                    x:Math.round(r.x), y:Math.round(r.y),
                    ox:Math.round(ox), oy:Math.round(oy)
                });
            }
        }
        return JSON.stringify({found:false});
    })()""",
    'returnByValue': True
})
iframe_raw = iframe_pos.get('result', {}).get('result', {}).get('value', '{}')
ip = json.loads(iframe_raw)
print(f'iframe位置: {json.dumps(ip, ensure_ascii=False)}')

OX = ip.get('ox', 66)
OY = ip.get('oy', 119)
screen_x = int(ip.get('x', 397) + data['slider_iframe_x'] + OX)
screen_y = int(ip.get('y', 181) + data['slider_iframe_y'] + OY)
distance = data['distance']

print(f'\n=== 精确坐标 ===')
print(f'iframe视口: ({ip.get("x")},{ip.get("y")})')
print(f'滑块在iframe内: ({data["slider_iframe_x"]},{data["slider_iframe_y"]})')
print(f'viewport→screen偏移: ({OX},{OY})')
print(f'屏幕坐标: ({screen_x},{screen_y}) distance={distance}')

# ---- Step 4: xdotool drag ----
print(f'\n=== xdotool拖拽 ===')

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

def xd_move(x, y):
    subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))],
                   env=env, capture_output=True, timeout=5)

def xd_down():
    subprocess.run(["xdotool", "mousedown", "1"], env=env, capture_output=True, timeout=5)

def xd_up():
    subprocess.run(["xdotool", "mouseup", "1"], env=env, capture_output=True, timeout=5)

MAX_RETRIES = 5
for attempt in range(1, MAX_RETRIES + 1):
    print(f'\n尝试 {attempt}/{MAX_RETRIES}')

    # Refresh coordinates each attempt (errloading may shift things)
    if attempt > 1:
        time.sleep(2)
        sr = cdp('Runtime.evaluate', {
            'expression': r"""(function(){
                var s = document.querySelector('[id*="nc_1_n1z"]');
                var t = document.querySelector('[id*="nc_1__scale_text"]');
                if (!s || !t) return JSON.stringify({found:false});
                var sr = s.getBoundingClientRect();
                var tr = t.getBoundingClientRect();
                return JSON.stringify({
                    found: true,
                    slider_iframe_x: Math.round(sr.x + sr.width/2),
                    slider_iframe_y: Math.round(sr.y + sr.height/2),
                    distance: Math.round(tr.x + tr.width - sr.x - sr.width + 3)
                });
            })()""",
            'contextId': ctx_id,
            'returnByValue': True
        })
        d2 = json.loads(sr.get('result', {}).get('result', {}).get('value', '{}'))
        if d2.get('found'):
            screen_x = int(ip.get('x', 397) + d2['slider_iframe_x'] + OX)
            screen_y = int(ip.get('y', 181) + d2['slider_iframe_y'] + OY)
            distance = d2['distance']
            print(f'刷新坐标: ({screen_x},{screen_y}) dist={distance}')

    sx, sy = screen_x, screen_y

    # Approach
    ax = sx - random.randint(35, 55)
    ay = sy + random.randint(-10, 10)
    for i in range(10):
        p = (i + 1) / 10
        xd_move(int(ax + (sx - ax) * p), int(ay + (sy - ay) * p + math.sin(i * 0.5) * 5))
        time.sleep(0.02 + random.random() * 0.03)

    xd_move(sx, sy)
    time.sleep(0.25 + random.random() * 0.35)
    xd_down()
    time.sleep(0.03)

    pts = 200 + random.randint(30, 60)
    total_t = 3.0 + random.random() * 2.5
    for i in range(pts):
        p = i / pts
        if p < 0.08: e = (p / 0.08) ** 2 * 0.08
        elif p < 0.88: e = 0.08 + (p - 0.08) * 0.84
        else: r = (1 - p) / 0.12; e = 1 - r * r * 0.12
        e += (random.random() - 0.5) * 0.005
        x = int(sx + distance * e)
        yj = (math.sin(p * math.pi * 3.1) * 2.5 +
              math.sin(p * math.pi * 7.3) * 0.6 +
              math.sin(p * math.pi * 13.7) * 0.3)
        if random.random() < 0.02: yj += (random.random() - 0.5) * 8
        y = int(sy + yj)
        xd_move(x, y)
        time.sleep(max(0.005, total_t / pts * (0.6 + random.random() * 0.8)))

    xd_move(int(sx + distance), int(sy))
    time.sleep(0.05)
    xd_move(int(sx + distance + random.uniform(2, 5)), int(sy + random.randint(-1, 1)))
    time.sleep(0.04)
    xd_move(int(sx + distance), int(sy))
    time.sleep(0.05)
    time.sleep(0.18 + random.random() * 0.25)
    xd_up()
    print(f'拖拽完成')

    time.sleep(4)

    # Check if captcha is gone
    check = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var fs = document.querySelectorAll('iframe');
            for (var i=0; i<fs.length; i++) {
                if ((fs[i].src||'').indexOf('h5api') !== -1) {
                    var rect = fs[i].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0)
                        return JSON.stringify({captcha:true});
                }
            }
            return JSON.stringify({captcha:false});
        })()""",
        'returnByValue': True
    })
    final = json.loads(check.get('result', {}).get('result', {}).get('value', '{}'))
    print(f'验证码: {json.dumps(final, ensure_ascii=False)}')
    if not final.get('captcha'):
        print(f'✅✅✅ 尝试{attempt} 滑块验证成功！！！')
        break

ws.close()
