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

# 获取按钮位置和viewport偏移
js = r"""
(function(){
    var btns = document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
        var txt = (btns[i].textContent || '').trim();
        if (txt === '开始分析' && btns[i].offsetHeight > 0) {
            var rect = btns[i].getBoundingClientRect();
            var fl = (window.outerWidth - window.innerWidth) / 2;
            var to = window.outerHeight - window.innerHeight - fl;
            var ox = (window.screenLeft || 0) + fl;
            var oy = (window.screenTop || 0) + to;
            return JSON.stringify({
                vx: Math.round(rect.x + rect.width/2),
                vy: Math.round(rect.y + rect.height/2),
                ox: Math.round(ox),
                oy: Math.round(oy),
                screenX: Math.round(rect.x + rect.width/2 + ox),
                screenY: Math.round(rect.y + rect.height/2 + oy)
            });
        }
    }
    return JSON.stringify({found: false});
})()
"""
r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
pos = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
print(f'按钮位置: viewport=({pos.get("vx")},{pos.get("vy")}) offset=({pos.get("ox")},{pos.get("oy")}) screen=({pos.get("screenX")},{pos.get("screenY")})')

sx = pos.get('screenX', 0)
sy = pos.get('screenY', 0)

# xdotool 物理鼠标点击
print(f'\nxdotool 点击 screen({sx}, {sy})')
env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
time.sleep(0.3)
subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
print('xdotool 点击完成')

# 等待并检查
for i in range(20):
    time.sleep(5)
    r = cdp('Runtime.evaluate', {'expression': r"""(function(){
        var body = document.body ? document.body.innerText : '';
        var hasSort = body.indexOf('综合排序') !== -1;
        var hasAutoLoad = body.indexOf('自动加载') !== -1;
        var hasLoadMore = body.indexOf('加载下一页') !== -1;
        var hasLoading = body.indexOf('加载中') !== -1 || body.indexOf('拼命加载') !== -1;
        var hasStart = body.indexOf('开始分析') !== -1;
        return JSON.stringify({hasSort:hasSort, hasAutoLoad:hasAutoLoad, hasLoadMore:hasLoadMore, hasLoading:hasLoading, hasStart:hasStart});
    })()""", 'returnByValue': True})
    info = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
    elapsed = (i+1) * 5
    print(f'{elapsed}s: start={info.get("hasStart")} sort={info.get("hasSort")} autoload={info.get("hasAutoLoad")} loadmore={info.get("hasLoadMore")} loading={info.get("hasLoading")}')
    if info.get('hasAutoLoad') or info.get('hasLoadMore') or info.get('hasSort'):
        print(f'\n✅ 分析已启动! ({elapsed}s)')
        break
    if not info.get('hasStart') and (info.get('hasLoading') or info.get('hasSort')):
        print(f'\n✅ 分析进行中! ({elapsed}s)')
        break

ws.close()
