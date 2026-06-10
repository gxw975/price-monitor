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

# Get the punish iframe URL
js = r"""(function(){
    var frames = document.querySelectorAll('iframe');
    for (var i = 0; i < frames.length; i++) {
        var src = frames[i].src || '';
        if (src.indexOf('punish') !== -1) return src;
    }
    return '';
})()"""
r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
punish_url = r.get('result', {}).get('result', {}).get('value', '')
print(f'punish URL: {punish_url}')

if not punish_url:
    print('未找到punish iframe')
    ws.close()
    exit(1)

# Save taobao search URL
tb_url = cdp('Runtime.evaluate', {'expression': 'window.location.href', 'returnByValue': True})
taobao_url = tb_url.get('result', {}).get('result', {}).get('value', '')
print(f'淘宝URL: {taobao_url[:100]}')

# ===== Navigate to punish page to solve =====
print(f'\n导航到punish页面...')
cdp('Page.navigate', {'url': punish_url})
time.sleep(3)

def solve_slider():
    """Solve slider on current page using xdotool"""
    slider_js = r"""(function(){
        var s = document.querySelector('#nc_1_n1z');
        var t = document.querySelector('#nc_1__scale_text');
        if (!s || !t) {
            var e = document.querySelector('.errloading');
            if (e) return JSON.stringify({error: 'errloading'});
            return JSON.stringify({found: false});
        }
        var sr = s.getBoundingClientRect(), tr = t.getBoundingClientRect();
        var fl = (window.outerWidth - window.innerWidth) / 2;
        return JSON.stringify({
            found: true,
            sx: Math.round(sr.x + sr.width/2 + (window.screenLeft || 0) + fl),
            sy: Math.round(sr.y + sr.height/2 + (window.screenTop || 0) + window.outerHeight - window.innerHeight - fl),
            distance: Math.round(tr.x + tr.width - sr.x - sr.width + 8)
        });
    })()"""

    for attempt in range(3):
        sr = cdp('Runtime.evaluate', {'expression': slider_js, 'returnByValue': True})
        slider = json.loads(sr.get('result', {}).get('result', {}).get('value', '{}'))
        print(f'  尝试{attempt+1}: {json.dumps(slider, ensure_ascii=False)}')

        if slider.get('error') == 'errloading':
            cdp('Runtime.evaluate', {
                'expression': r"""(function(){
                    var e = document.querySelector('.errloading');
                    if (e) { e.click(); return 'clicked'; }
                    var nc = document.querySelector('#nc_1_n1z');
                    if (nc && nc.offsetHeight > 0) {
                        var rect = nc.getBoundingClientRect();
                        nc.click(); return 'clicked_nc';
                    }
                    return 'not_found';
                })()""",
                'returnByValue': True
            })
            time.sleep(3)
            continue

        if not slider.get('found'):
            print('  ❌ 滑块未找到')
            return False

        sx, sy, dist = slider['sx'], slider['sy'], slider['distance']
        print(f'  拖拽: ({sx},{sy}) dist={dist}')

        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        env["XAUTHORITY"] = XAUTH_FILE

        def xd_move(x, y):
            subprocess.run(["xdotool", "mousemove", str(x), str(y)], env=env, capture_output=True, timeout=5)

        def xd_down():
            subprocess.run(["xdotool", "mousedown", "1"], env=env, capture_output=True, timeout=5)

        def xd_up():
            subprocess.run(["xdotool", "mouseup", "1"], env=env, capture_output=True, timeout=5)

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
        print('  拖拽完成')

        time.sleep(4)

        # Check if still on punish page
        cur = cdp('Runtime.evaluate', {'expression': 'window.location.href', 'returnByValue': True})
        cur_url = cur.get('result', {}).get('result', {}).get('value', '')
        if 'punish' not in cur_url:
            print('  ✅ 已跳转离开punish页面，验证通过！')
            return True

        # Check if still has slider
        sr2 = cdp('Runtime.evaluate', {'expression': slider_js, 'returnByValue': True})
        s2 = json.loads(sr2.get('result', {}).get('result', {}).get('value', '{}'))
        if not s2.get('found'):
            body_text = cdp('Runtime.evaluate', {'expression': '(document.body?.innerText || "").substring(0, 100)', 'returnByValue': True})
            print(f'  无滑块，body: {body_text.get("result",{}).get("result",{}).get("value","")}')
            # Check if captcha iframe is gone from parent
            check = cdp('Runtime.evaluate', {'expression': r"""(function(){
                var frames = document.querySelectorAll('iframe');
                for (var i = 0; i < frames.length; i++) {
                    if ((frames[i].src || '').indexOf('punish') !== -1) return 'captcha';
                }
                return 'none';
            })()""", 'returnByValue': True})
            if check.get('result', {}).get('result', {}).get('value', '') == 'none':
                print('  ✅ 验证码已清除！')
                return True

    return False

# Solve captcha on punish page
print('\n=== 在punish页面求解滑块 ===')
solved = solve_slider()

if solved:
    print('\n✅ 滑块求解成功！导航回淘宝...')
    time.sleep(3)

    # Navigate back to taobao
    cdp('Page.navigate', {'url': taobao_url})
    time.sleep(5)

    # Check if captcha is gone
    check_js = r"""(function(){
        var frames = document.querySelectorAll('iframe');
        for (var i = 0; i < frames.length; i++) {
            if ((frames[i].src || '').indexOf('punish') !== -1) {
                var rect = frames[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) return JSON.stringify({captcha: true});
            }
        }
        return JSON.stringify({captcha: false});
    })()"""
    r = cdp('Runtime.evaluate', {'expression': check_js, 'returnByValue': True})
    final = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
    print(f'最终验证码状态: {json.dumps(final, ensure_ascii=False)}')
    if not final.get('captcha'):
        print('✅✅✅ 淘宝搜索结果页验证码已清除！！！')
    else:
        print('❌ 验证码仍在')
else:
    print('\n❌ 滑块求解失败')

ws.close()
