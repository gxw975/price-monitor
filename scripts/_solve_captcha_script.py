import json, urllib.request, websocket, time, math, os, random, subprocess, tempfile

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
if not punish_fid:
    print('❌ 未找到punish frame')
    ws.close()
    exit(1)

iso = cdp('Page.createIsolatedWorld', {'frameId': punish_fid})
ctx_id = iso.get('result', {}).get('executionContextId')
time.sleep(0.2)

def get_captcha_data():
    slider_r = cdp('Runtime.evaluate', {
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
    slider = json.loads(slider_r.get('result', {}).get('result', {}).get('value', '{}'))

    iframe_r = cdp('Runtime.evaluate', {
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
            return JSON.stringify({});
        })()""",
        'returnByValue': True
    })
    iframe = json.loads(iframe_r.get('result', {}).get('result', {}).get('value', '{}'))
    return slider, iframe

def check_captcha_gone():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var fs = document.querySelectorAll('iframe');
            for (var i=0; i<fs.length; i++) {
                if ((fs[i].src||'').indexOf('h5api') !== -1) {
                    if (fs[i].getBoundingClientRect().width > 0) return 'captcha';
                }
            }
            return 'none';
        })()""",
        'returnByValue': True
    })
    return r.get('result', {}).get('result', {}).get('value', '') == 'none'

# ===== Main drag logic =====
for attempt in range(1, 6):
    slider, iframe_pos = get_captcha_data()

    if slider.get('error') == 'errloading':
        cdp('Runtime.evaluate', {
            'expression': r"""document.querySelector('.errloading')?.click();""",
            'contextId': ctx_id, 'returnByValue': True
        })
        time.sleep(2.5)
        slider, iframe_pos = get_captcha_data()

    if not slider.get('x'):
        print(f'尝试{attempt}: 滑块未找到')
        if check_captcha_gone():
            print('✅ 验证码已消失！')
            break
        continue

    sx = iframe_pos['x'] + slider['x'] + iframe_pos['ox']
    sy = iframe_pos['y'] + slider['y'] + iframe_pos['oy']
    dist = slider['dist']

    print(f'\n尝试{attempt}: screen({sx},{sy}) dist={dist}')

    # Build a single xdotool shell command for smooth drag
    # This avoids subprocess overhead per-point
    ax = sx - random.randint(35, 55)
    ay = sy + random.randint(-10, 10)

    commands = []

    # Approach: smooth moves to slider
    for i in range(15):
        p = (i + 1) / 15
        x = int(ax + (sx - ax) * p)
        y = int(ay + (sy - ay) * p + math.sin(i * 0.4) * 4)
        commands.append(f"xdotool mousemove --sync {x} {y}")
        if i < 14:
            commands.append(f"sleep 0.02")

    # Hover
    commands.append(f"xdotool mousemove --sync {sx} {sy}")
    commands.append("sleep 0.30")

    # Mouse down
    commands.append("xdotool mousedown 1")
    commands.append("sleep 0.05")

    # Drag with precise timing
    pts = 150 + random.randint(30, 50)
    total_t = 2.5 + random.random() * 2.0
    for i in range(pts):
        p = i / pts
        if p < 0.08: e = (p / 0.08) ** 2 * 0.08
        elif p < 0.88: e = 0.08 + (p - 0.08) * 0.84
        else: r = (1 - p) / 0.12; e = 1 - r * r * 0.12
        e += (random.random() - 0.5) * 0.003

        x = int(sx + dist * e)
        yj = (math.sin(p * math.pi * 2.7) * 1.8 +
              math.sin(p * math.pi * 6.5) * 0.5 +
              math.sin(p * math.pi * 12.3) * 0.2)
        if random.random() < 0.015: yj += (random.random() - 0.5) * 6
        y = int(sy + yj)

        commands.append(f"xdotool mousemove --sync {x} {y}")
        interval = total_t / pts * (0.5 + random.random() * 0.5)
        commands.append(f"sleep {interval:.4f}")

    # Settle
    commands.append(f"xdotool mousemove --sync {int(sx + dist)} {sy}")
    commands.append("sleep 0.06")
    commands.append(f"xdotool mousemove --sync {int(sx + dist + random.uniform(1, 4))} {sy + random.randint(-1, 1)}")
    commands.append("sleep 0.04")
    commands.append(f"xdotool mousemove --sync {int(sx + dist)} {sy}")
    commands.append("sleep 0.20")

    # Release
    commands.append("xdotool mouseup 1")

    # Write to temp file and execute
    script = "#!/bin/bash\n" + "\n".join(commands)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(script)
        script_path = f.name

    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["XAUTHORITY"] = XAUTH_FILE

    print(f'  执行拖拽脚本 ({pts}+点)...')
    result = subprocess.run(
        ["bash", script_path],
        env=env, capture_output=True, text=True, timeout=30
    )
    os.unlink(script_path)

    if result.returncode != 0:
        print(f'  脚本错误: {result.stderr[:200]}')

    time.sleep(4)

    if check_captcha_gone():
        print(f'✅✅✅ 尝试{attempt} 验证成功！！！')
        break
    else:
        print(f'  尝试{attempt} 失败')

ws.close()
