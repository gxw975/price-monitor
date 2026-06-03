import json, urllib.request, websocket, time, math, os, random, subprocess, tempfile

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
os.environ.setdefault("DISPLAY", DISPLAY)
os.environ.setdefault("XAUTHORITY", XAUTH_FILE)

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
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var e = document.querySelector('.errloading');
            if (e) { e.click(); return 'errloading_clicked'; }
            var nc = document.querySelector('[id*="nc_1_n1z"]');
            if (nc && nc.getBoundingClientRect().width > 0) { nc.click(); return 'nc_clicked'; }
            var w = document.querySelector('[id*="nc_1_wrapper"]');
            if (w) { w.click(); return 'wrapper_clicked'; }
            return 'not_found';
        })()""",
        'contextId': ctx_id, 'returnByValue': True
    })
    return r.get('result', {}).get('result', {}).get('value', '')

# ===== xdotool-based smooth drag with mousemove_relative =====
env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

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

    # Phase 1: Approach - move to slider start position
    ax = sx - random.randint(35, 55)
    ay = sy + random.randint(-10, 10)
    subprocess.run(["xdotool", "mousemove", str(ax), str(ay)], env=env, capture_output=True, timeout=5)
    time.sleep(0.05)

    # Approach smoothly with incremental relative moves
    dx_total = sx - ax
    dy_total = sy - ay
    approach_pts = 15
    for i in range(approach_pts):
        p = (i + 1) / approach_pts
        cur_x = ax + int(dx_total * p)
        cur_y = ay + int(dy_total * p + math.sin(i * 0.5) * 5)
        subprocess.run(["xdotool", "mousemove", str(cur_x), str(cur_y)], env=env, capture_output=True, timeout=5)
        time.sleep(0.02 + random.random() * 0.02)

    # Hover
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=5)
    time.sleep(0.25 + random.random() * 0.35)

    # Mouse down
    subprocess.run(["xdotool", "mousedown", "1"], env=env, capture_output=True, timeout=5)
    time.sleep(0.05)

    # ===== Drag with mousemove_relative for smooth movement =====
    # Precompute trajectory points
    pts = 120 + random.randint(20, 40)
    total_t = 3.0 + random.random() * 2.0
    trajectory = []
    prev_x, prev_y = sx, sy

    for i in range(pts):
        p = i / pts
        if p < 0.08: e = (p / 0.08) ** 2 * 0.08
        elif p < 0.88: e = 0.08 + (p - 0.08) * 0.84
        else: r = (1 - p) / 0.12; e = 1 - r * r * 0.12
        e += (random.random() - 0.5) * 0.003

        target_x = int(sx + dist * e)
        yj = (math.sin(p * math.pi * 2.7) * 1.8 +
              math.sin(p * math.pi * 6.5) * 0.5 +
              math.sin(p * math.pi * 12.3) * 0.2)
        if random.random() < 0.015: yj += (random.random() - 0.5) * 6
        target_y = int(sy + yj)

        dx = target_x - prev_x
        dy = target_y - prev_y
        trajectory.append((dx, dy))
        prev_x, prev_y = target_x, target_y

    # Execute trajectory with mousemove_relative + sleep
    # Use xdotool mousemove_relative --sync for precise per-pixel movement
    for i, (dx, dy) in enumerate(trajectory):
        p = (i + 1) / len(trajectory)
        # Less time during mid-drag (faster), more at start/end (slower)
        speed = 0.3 if p < 0.1 else (0.8 if p < 0.85 else 0.4)
        delay = total_t / len(trajectory) * speed * (0.8 + random.random() * 0.4)

        if abs(dx) <= 3 and abs(dy) <= 3:
            # Small move: use absolute positioning to avoid accumulated error
            subprocess.run(["xdotool", "mousemove", str(sx + int(dist * p)), str(prev_y)],
                          env=env, capture_output=True, timeout=5)
        else:
            subprocess.run(["xdotool", "mousemove_relative", "--", str(dx), str(dy)],
                          env=env, capture_output=True, timeout=5)
        time.sleep(max(0.005, delay))

    # Settle
    subprocess.run(["xdotool", "mousemove", str(int(sx + dist)), str(sy)], env=env, capture_output=True, timeout=5)
    time.sleep(0.06)
    subprocess.run(["xdotool", "mousemove", str(int(sx + dist + random.uniform(1, 4))),
                   str(sy + random.randint(-1, 1))], env=env, capture_output=True, timeout=5)
    time.sleep(0.04)
    subprocess.run(["xdotool", "mousemove", str(int(sx + dist)), str(sy)], env=env, capture_output=True, timeout=5)
    time.sleep(0.20)
    subprocess.run(["xdotool", "mouseup", "1"], env=env, capture_output=True, timeout=5)

    print(f'拖拽完成 (pts={pts}, t={total_t:.1f}s)')
    time.sleep(4)

    if check_gone():
        print(f'✅✅✅ 尝试{attempt} 验证成功！！！'); break

    slider2 = get_slider()
    print(f'  验证后: {json.dumps(slider2, ensure_ascii=False)}')

ws.close()
