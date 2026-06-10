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

def get_viewport_offset():
    js = r"""(function(){
        var fl = (window.outerWidth - window.innerWidth) / 2;
        var to = window.outerHeight - window.innerHeight - fl;
        return JSON.stringify({
            ox: (window.screenLeft || 0) + fl,
            oy: (window.screenTop || 0) + to
        });
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    val = r.get('result', {}).get('result', {}).get('value', '{}')
    d = json.loads(val)
    return d.get('ox', 66), d.get('oy', 119)

ox, oy = get_viewport_offset()
print(f'Viewport offset: ({ox}, {oy})')

# "自动加载" 在 viewport(299, 620)，中心点大约 (299+59/2, 620+16/2) = (328, 628)
vx, vy = 328, 628
sx = vx + ox
sy = vy + oy
print(f'自动加载按钮: viewport({vx},{vy}) -> screen({sx},{sy})')

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

# 先移动鼠标让用户确认位置
print(f'移动鼠标到 ({sx},{sy})...')
subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
time.sleep(2)

# 点击
print('点击...')
subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
print('点击完成')

# 等待并检查进度
time.sleep(10)
js = r"""(function(){
    var body = document.body ? document.body.innerText : '';
    var m = body.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);
    return JSON.stringify({
        progress: m ? {loaded: parseInt(m[1]), total: parseInt(m[2])} : null,
        hasAutoLoad: body.indexOf('自动加载') !== -1,
        hasLoadMore: body.indexOf('加载下一页') !== -1
    });
})()"""
r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
state = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
print(f'10秒后状态: {state}')

ws.close()
