import json, urllib.request, websocket, time, math, os, random

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH_FILE

from Xlib import display, X
from Xlib.ext import xtest
import Xlib.display

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())

main_page = None
for t in targets:
    if t.get('type') == 'page' and 'taobao.com/search' in t.get('url', ''):
        main_page = t; break
if not main_page:
    print('未找到淘宝搜索页'); exit(1)

ws = websocket.create_connection(main_page['webSocketDebuggerUrl'], timeout=15)
msg_id = 0
def cdp(method, params=None):
    global msg_id; msg_id += 1
    msg = {'id': msg_id, 'method': method}
    if params: msg['params'] = params
    ws.send(json.dumps(msg))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == msg_id: return r

cdp('Page.enable'); cdp('Runtime.enable')

# Find punish frame
ft_resp = cdp('Page.getFrameTree')
frame_tree = ft_resp.get('result', {}).get('frameTree', {})
punish_fid = None
def find_punish(node):
    global punish_fid
    for c in node.get('childFrames', []):
        f = c.get('frame', {})
        if 'h5api.m.taobao.com' in f.get('url','') and 'punish' in f.get('url',''):
            punish_fid = f.get('id',''); return
        find_punish(c)
find_punish(frame_tree)
if not punish_fid:
    print('未找到punish frame'); ws.close(); exit(1)

iso = cdp('Page.createIsolatedWorld', {'frameId': punish_fid})
ctx_id = iso.get('result', {}).get('executionContextId')
print(f'ctx_id: {ctx_id}')

# Init python-xlib
d = Xlib.display.Display()
print(f'Xlib display opened')

def x11_move(x, y):
    xtest.fake_input(d, X.MotionNotify, x=int(x), y=int(y))
    d.sync()

def x11_down():
    xtest.fake_input(d, X.ButtonPress, 1)
    d.sync()

def x11_up():
    xtest.fake_input(d, X.ButtonRelease, 1)
    d.sync()

def get_slider():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var s = document.querySelector('[id*="nc_1_n1z"]');
            var t = document.querySelector('[id*="nc_1__scale_text"]');
            if (!s || !t) {
                var w = document.querySelector('[id*="nc_1_wrapper"]');
                if (w && (w.innerHTML||'').indexOf('errloading') !== -1)
                    return JSON.stringify({error:'errloading'});
                return JSON.stringify({found:false});
            }
            var sr = s.getBoundingClientRect();
            var tr = t.getBoundingClientRect();
            return JSON.stringify({
                x: Math.round(sr.x + sr.width/2),
                y: Math.round(sr.y + sr.height/2),
                dist: Math.round(tr.x + tr.width - sr.x - sr.width + 3)
            });
        })()""",
        'contextId': ctx_id, 'returnByValue': True
    })
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

def get_iframe_pos():
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

def check_gone():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var fs = document.querySelectorAll('iframe');
            for (var i=0; i<fs.length; i++) {
                if ((fs[i].src||'').indexOf('h5api') !== -1) {
                    if (fs[i].getBoundingClientRect().width > 0) return 'captcha';
                }
            }
            return 'none';
        })()""", 'returnByValue': True
    })
    return r.get('result', {}).get('result', {}).get('value', '') == 'none'

def click_retry():
    cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var e = document.querySelector('.errloading');
            if (e) { e.click(); return 'errloading'; }
            var nc = document.querySelector('[id*="nc_1_n1z"]');
            if (nc && nc.getBoundingClientRect().width > 0) { nc.click(); return 'nc'; }
            return 'none';
        })()""",
        'contextId': ctx_id, 'returnByValue': True
    })

# ===== Main loop =====
for attempt in range(1, 8):
    print(f'\n===== 尝试 {attempt} =====')

    slider = get_slider()
    iframe = get_iframe_pos()

    if slider.get('error') == 'errloading':
        print('errloading，点击重试...')
        click_retry()
        time.sleep(3)
        slider = get_slider()
        iframe = get_iframe_pos()

    if not slider.get('x'):
        if check_gone():
            print('✅ 验证码已消失！'); break
        print('滑块未找到'); time.sleep(3); continue

    sx = iframe['x'] + slider['x'] + iframe['ox']
    sy = iframe['y'] + slider['y'] + iframe['oy']
    dist = slider['dist']

    print(f'screen({sx},{sy}) dist={dist}')

    # Approach
    ax = sx - random.randint(35, 55)
    ay = sy + random.randint(-10, 10)
    for i in range(14):
        p = (i + 1) / 14
        x11_move(int(ax + (sx - ax) * p), int(ay + (sy - ay) * p + math.sin(i * 0.5) * 5))
        time.sleep(0.015 + random.random() * 0.02)

    # Hover
    x11_move(sx, sy)
    time.sleep(0.25 + random.random() * 0.35)

    # Press
    x11_down()
    time.sleep(0.03)

    # Drag - 280+ points, 3-5.5s, sine wave
    pts = 280 + random.randint(40, 80)
    total_t = 3.0 + random.random() * 2.5
    for i in range(pts):
        p = i / pts
        if p < 0.08: e = (p / 0.08) ** 2 * 0.08
        elif p < 0.88: e = 0.08 + (p - 0.08) * 0.84
        else: r = (1 - p) / 0.12; e = 1 - r * r * 0.12
        e += (random.random() - 0.5) * 0.005

        x = int(sx + dist * e)
        yj = (math.sin(p * math.pi * 3.1) * 2.5 +
              math.sin(p * math.pi * 7.3) * 0.6 +
              math.sin(p * math.pi * 13.7) * 0.3)
        if random.random() < 0.02: yj += (random.random() - 0.5) * 8
        y = int(sy + yj)
        x11_move(x, y)
        time.sleep(max(0.002, total_t / pts * (0.6 + random.random() * 0.8)))

    # Settle
    x11_move(int(sx + dist), int(sy)); time.sleep(0.05)
    x11_move(int(sx + dist + random.uniform(2, 5)), int(sy + random.randint(-1, 1))); time.sleep(0.04)
    x11_move(int(sx + dist), int(sy)); time.sleep(0.05)
    time.sleep(0.18 + random.random() * 0.25)
    x11_up()

    print(f'python-xlib拖拽完成 (pts={pts}, t={total_t:.1f}s)')
    time.sleep(4)

    if check_gone():
        print(f'✅✅✅ 尝试{attempt} 验证成功！！！'); break

    slider2 = get_slider()
    print(f'  验证后: {json.dumps(slider2, ensure_ascii=False)}')

d.close()
ws.close()
