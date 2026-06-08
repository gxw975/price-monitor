import json, urllib.request, websocket, time, subprocess, os

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())
pages = [t for t in targets if t.get('type') == 'page']
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

# 1. 先滚动到自动加载按钮，获取精确坐标
js = r"""
(function(){
    var btns = document.querySelectorAll('button, [role="button"], div, span');
    for (var i = 0; i < btns.length; i++) {
        var txt = (btns[i].textContent || '').trim();
        if (txt === '自动加载' && btns[i].offsetHeight > 0) {
            btns[i].scrollIntoView({behavior: 'instant', block: 'center'});
            time.sleep(500);
            var rect = btns[i].getBoundingClientRect();
            var fl = (window.outerWidth - window.innerWidth) / 2;
            var to = window.outerHeight - window.innerHeight - fl;
            var ox = (window.screenLeft || 0) + fl;
            var oy = (window.screenTop || 0) + to;
            return JSON.stringify({
                found: true, text: txt,
                vx: Math.round(rect.x), vy: Math.round(rect.y),
                vw: Math.round(rect.width), vh: Math.round(rect.height),
                sx: Math.round(rect.x + rect.width/2 + ox),
                sy: Math.round(rect.y + rect.height/2 + oy),
                ox: Math.round(ox), oy: Math.round(oy),
                screenLeft: window.screenLeft || 0,
                screenTop: window.screenTop || 0,
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                outerWidth: window.outerWidth,
                outerHeight: window.outerHeight
            });
        }
    }
    return JSON.stringify({found: false});
})()
"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
pos = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
print(f'=== 自动加载按钮位置 ===')
print(json.dumps(pos, indent=2, ensure_ascii=False))

if pos.get('found'):
    sx, sy = pos['sx'], pos['sy']
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["XAUTHORITY"] = XAUTH_FILE

    # 2. 用xdotool移动鼠标到该位置，但不点击，让用户确认位置
    print(f'\nxdotool移动到 ({sx}, {sy})')
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)

    # 3. 点击
    time.sleep(1)
    print(f'xdotool点击 ({sx}, {sy})')
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    print('点击完成')

    # 4. 等待5秒后检查状态
    time.sleep(5)
    js2 = r"""(function(){
        var body = document.body ? document.body.innerText : '';
        var progressMatch = body.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);
        return JSON.stringify({
            progress: progressMatch ? {loaded: parseInt(progressMatch[1]), total: parseInt(progressMatch[2])} : null,
            hasAutoLoad: body.indexOf('自动加载') !== -1
        });
    })()"""
    r2 = cdp('Runtime.evaluate', {'expression': js2, 'returnByValue': True})
    state = json.loads(r2.get('result', {}).get('result', {}).get('value', '{}'))
    print(f'\n点击后状态: {state}')

ws.close()
