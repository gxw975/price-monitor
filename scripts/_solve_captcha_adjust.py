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
    if params: msg['params'] = params
    ws.send(json.dumps(msg))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == msg_id: return r

cdp('Page.enable')
cdp('Runtime.enable')

# Find punish frameId
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

iso = cdp('Page.createIsolatedWorld', {'frameId': punish_fid})
ctx_id = iso.get('result', {}).get('executionContextId')
time.sleep(0.2)

# Get slider + iframe positions
def get_slider():
    r = cdp('Runtime.evaluate', {
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
        'contextId': ctx_id, 'returnByValue': True
    })
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

def get_iframe():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var fs = document.querySelectorAll('iframe');
            for (var i=0; i<fs.length; i++) {
                if ((fs[i].src||'').indexOf('h5api') !== -1) {
                    var r = fs[i].getBoundingClientRect();
                    var fl = (window.outerWidth - window.innerWidth) / 2;
                    var to = window.outerHeight - window.innerHeight - fl;
                    return JSON.stringify({
                        x:Math.round(r.x), y:Math.round(r.y),
                        w:Math.round(r.width), h:Math.round(r.height),
                        ox:Math.round((window.screenLeft||0)+fl),
                        oy:Math.round((window.screenTop||0)+to)
                    });
                }
            }
            return JSON.stringify({found:false});
        })()""",
        'returnByValue': True
    })
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

slider = get_slider()
iframe = get_iframe()

if slider.get('error') == 'errloading':
    cdp('Runtime.evaluate', {
        'expression': r"""(function(){var e=document.querySelector('.errloading');if(e){e.click();return'clicked';}return'not_found';})()""",
        'contextId': ctx_id, 'returnByValue': True
    })
    time.sleep(3)
    slider = get_slider()

print(f'滑块iframe内: {json.dumps(slider, ensure_ascii=False)}')
print(f'iframe: {json.dumps(iframe, ensure_ascii=False)}')

OX = iframe.get('ox', 66)
OY = iframe.get('oy', 119)

# ---- Also use xdotool to get actual Chrome window position ----
env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

r = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "淘宝"],
                   env=env, capture_output=True, text=True, timeout=10)
print(f'\nxdotool Chrome窗口: {r.stdout.strip()}')
for wid in r.stdout.strip().split('\n'):
    if wid:
        geom = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid],
                             env=env, capture_output=True, text=True, timeout=10)
        print(f'  {wid}: {geom.stdout.replace(chr(10)," ")}')

# Calculate screen coordinates with xdotool window offset
# xdotool uses absolute screen coords. Chrome window at (66,32) size 1214x768
# The viewport starts at (66+0, 32+87) = (66, 119) where 87 = 768-681 (titlebar+decorations)
# But maybe xdotool coordinate system differs...

# Let's try moving mouse to where we think the slider is and wait
sx_theory = iframe['x'] + slider['slider_iframe_x'] + OX
sy_theory = iframe['y'] + slider['slider_iframe_y'] + OY

print(f'\n理论屏幕坐标: ({sx_theory}, {sy_theory}) dist={slider["distance"]}')
print(f'  = iframe({iframe["x"]},{iframe["y"]}) + slider({slider["slider_iframe_x"]},{slider["slider_iframe_y"]}) + offset({OX},{OY})')

# First, just move mouse there for visual verification
print(f'\n移动鼠标到理论位置({sx_theory},{sy_theory})...用户请确认是否在滑块上')
subprocess.run(["xdotool", "mousemove", str(sx_theory), str(sy_theory)],
              env=env, capture_output=True, timeout=5)
print('5秒后开始拖拽...')
time.sleep(5)

# Try with y_adjustments 
y_adjustments = [0, -10, -20, -30, -40]
for y_adj in y_adjustments:
    sx = sx_theory
    sy = sy_theory + y_adj
    dist = slider['distance']

    print(f'\n尝试 y_adj={y_adj}: screen({sx},{sy}) dist={dist}')

    def xd_move(x, y):
        subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))],
                      env=env, capture_output=True, timeout=5)

    def xd_down():
        subprocess.run(["xdotool", "mousedown", "1"], env=env, capture_output=True, timeout=5)

    def xd_up():
        subprocess.run(["xdotool", "mouseup", "1"], env=env, capture_output=True, timeout=5)

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
        x = int(sx + dist * e)
        yj = (math.sin(p * math.pi * 3.1) * 2.5 + math.sin(p * math.pi * 7.3) * 0.6 + math.sin(p * math.pi * 13.7) * 0.3)
        if random.random() < 0.02: yj += (random.random() - 0.5) * 8
        y = int(sy + yj)
        xd_move(x, y)
        time.sleep(max(0.005, total_t / pts * (0.6 + random.random() * 0.8)))

    xd_move(int(sx + dist), int(sy))
    time.sleep(0.05)
    xd_move(int(sx + dist + random.uniform(2, 5)), int(sy + random.randint(-1, 1)))
    time.sleep(0.04)
    xd_move(int(sx + dist), int(sy))
    time.sleep(0.05)
    time.sleep(0.18 + random.random() * 0.25)
    xd_up()
    print(f'拖拽完成 y_adj={y_adj}')

    time.sleep(4)

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
        })()""", 'returnByValue': True
    })
    final = json.loads(check.get('result', {}).get('result', {}).get('value', '{}'))
    print(f'验证码: {json.dumps(final, ensure_ascii=False)}')
    if not final.get('captcha'):
        print(f'✅✅✅ y_adj={y_adj} 验证成功！')
        break

ws.close()
