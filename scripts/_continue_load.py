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

# 获取viewport offset
js = r"""(function(){
    var fl = (window.outerWidth - window.innerWidth) / 2;
    return JSON.stringify({
        ox: (window.screenLeft || 0) + fl,
        oy: (window.screenTop || 0) + window.outerHeight - window.innerHeight - fl
    });
})()"""
r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
offset = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
ox, oy = offset.get('ox', 66), offset.get('oy', 119)

# "继续加载" @ viewport(620,614) size 75x28 -> center (657, 628)
vx, vy = 657, 628
sx = vx + ox
sy = vy + oy
print(f'继续加载按钮: viewport({vx},{vy}) -> screen({sx},{sy})')

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

# 点击继续加载
print(f'点击继续加载 @ ({sx},{sy})')
subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
time.sleep(0.5)
subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
print('点击完成')

# 监控进度
for i in range(20):
    time.sleep(15)
    js2 = r"""(function(){
        var body = document.body ? document.body.innerText : '';
        var m = body.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);
        var hasContinue = body.indexOf('继续加载') !== -1;
        var hasAutoLoad = body.indexOf('自动加载') !== -1;
        var hasLoadMore = body.indexOf('加载下一页') !== -1;
        var hasError = body.indexOf('遇到异常') !== -1;
        return JSON.stringify({
            progress: m ? {loaded: parseInt(m[1]), total: parseInt(m[2])} : null,
            hasContinue: hasContinue, hasAutoLoad: hasAutoLoad,
            hasLoadMore: hasLoadMore, hasError: hasError
        });
    })()"""
    r2 = cdp('Runtime.evaluate', {'expression': js2, 'returnByValue': True})
    state = json.loads(r2.get('result', {}).get('result', {}).get('value', '{}'))
    elapsed = (i+1) * 15
    p = state.get('progress', {})
    print(f'{elapsed}s: loaded={p.get("loaded")}/{p.get("total")} continue={state.get("hasContinue")} autoload={state.get("hasAutoLoad")} error={state.get("hasError")}')

    if state.get('hasError'):
        print('再次遇到异常，需要再次点击继续加载')
        # 再次点击继续加载
        subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
        time.sleep(0.5)
        subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
        print('再次点击继续加载')

    if p.get('loaded') and p.get('loaded') >= p.get('total', 999):
        print(f'\n✅ 数据全部加载完成! {p.get("loaded")}/{p.get("total")}')
        break

    if state.get('hasAutoLoad') and not state.get('hasContinue') and not state.get('hasError'):
        print(f'\n自动加载按钮重新出现，需要继续点击')
        break

ws.close()
