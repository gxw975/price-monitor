import json, urllib.request, websocket, time, subprocess, os

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

# 查找Chrome窗口
result = subprocess.run(
    ["xdotool", "search", "--onlyvisible", "--name", "淘宝"],
    env=env, capture_output=True, text=True, timeout=10
)
print(f'Chrome窗口ID: {result.stdout.strip()}')

# 获取窗口几何信息
for wid in result.stdout.strip().split('\n'):
    if wid:
        geom = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", wid],
            env=env, capture_output=True, text=True, timeout=10
        )
        print(f'窗口 {wid}:')
        print(geom.stdout)

# 获取窗口焦点
focus = subprocess.run(
    ["xdotool", "getactivewindow"],
    env=env, capture_output=True, text=True, timeout=10
)
print(f'当前焦点窗口: {focus.stdout.strip()}')

# 检查Chrome viewport信息
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

# 获取详细的窗口和viewport信息
js = r"""(function(){
    return JSON.stringify({
        screenLeft: window.screenLeft,
        screenTop: window.screenTop,
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        outerWidth: window.outerWidth,
        outerHeight: window.outerHeight,
        scrollY: window.scrollY,
        scrollX: window.scrollX,
        devicePixelRatio: window.devicePixelRatio
    });
})()"""
r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
info = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
print(f'\nChrome窗口信息:')
print(json.dumps(info, indent=2))

# 计算正确的viewport offset
fl = (info['outerWidth'] - info['innerWidth']) / 2
to = info['outerHeight'] - info['innerHeight'] - fl
ox = info['screenLeft'] + fl
oy = info['screenTop'] + to
print(f'\n计算的viewport offset: ({ox}, {oy})')

# 重新获取自动加载按钮位置
js2 = r"""(function(){
    var all = document.querySelectorAll('div, span, button, a');
    for (var i = 0; i < all.length; i++) {
        var txt = (all[i].textContent || '').trim();
        if (txt === '自动加载' && all[i].offsetHeight > 0) {
            var rect = all[i].getBoundingClientRect();
            return JSON.stringify({
                found: true, text: txt, tag: all[i].tagName,
                vx: Math.round(rect.x), vy: Math.round(rect.y),
                vw: Math.round(rect.width), vh: Math.round(rect.height),
                centerX: Math.round(rect.x + rect.width/2),
                centerY: Math.round(rect.y + rect.height/2)
            });
        }
    }
    return '{"found": false}';
})()"""
r2 = cdp('Runtime.evaluate', {'expression': js2, 'returnByValue': True})
pos = json.loads(r2.get('result', {}).get('result', {}).get('value', '{}'))
print(f'\n自动加载按钮: {json.dumps(pos, indent=2)}')

if pos.get('found'):
    cx = pos['centerX']
    cy = pos['centerY']
    sx = int(cx + ox)
    sy = int(cy + oy)
    print(f'\n正确屏幕坐标: viewport({cx},{cy}) -> screen({sx},{sy})')

ws.close()
