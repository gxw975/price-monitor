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

# 先滚动到 itemToolsBox
cdp('Runtime.evaluate', {'expression': r"""(function(){
    var el = document.querySelector('.itemToolsBox');
    if (el) el.scrollIntoView({behavior: 'instant', block: 'center'});
    return !!el;
})()""", 'returnByValue': True})

time.sleep(2)

# 找到 itemToolsBox 中所有市场分析相关元素
js = r"""
(function(){
    var results = [];
    var box = document.querySelector('.itemToolsBox');
    var all = document.querySelectorAll('.itemToolsBox *, [class*="market"], [class*="Market"]');
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var txt = (el.textContent || '').trim();
        var rect = el.getBoundingClientRect();
        if (txt === '市场分析' && rect.height > 0) {
            results.push({
                text: txt,
                tag: el.tagName,
                cls: String(el.className || '').substring(0, 50),
                vx: Math.round(rect.x), vy: Math.round(rect.y),
                vw: Math.round(rect.width), vh: Math.round(rect.height),
                parentCls: el.parentElement ? String(el.parentElement.className || '').substring(0, 50) : ''
            });
        }
    }
    return JSON.stringify(results);
})()
"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
val = r.get('result', {}).get('result', {}).get('value', '[]')
items = json.loads(val)

print('=== itemToolsBox 内市场分析元素 ===')
for item in items:
    print(f'  [{item.get("tag")}] cls="{item.get("cls")}" parent="{item.get("parentCls")}" @ viewport({item.get("vx")},{item.get("vy")}) {item.get("vw")}x{item.get("vh")}')

# 获取viewport offset
js2 = r"""(function(){
    var fl = (window.outerWidth - window.innerWidth) / 2;
    return JSON.stringify({
        ox: (window.screenLeft || 0) + fl,
        oy: (window.screenTop || 0) + window.outerHeight - window.innerHeight - fl
    });
})()"""
r2 = cdp('Runtime.evaluate', {'expression': js2, 'returnByValue': True})
offset = json.loads(r2.get('result', {}).get('result', {}).get('value', '{}'))
ox, oy = offset.get('ox', 66), offset.get('oy', 119)

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

# 点击每个市场分析元素
if items:
    target = items[0]
    vx = target['vx'] + target['vw'] // 2
    vy = target['vy'] + target['vh'] // 2
    sx, sy = vx + ox, vy + oy
    print(f'\n点击 "市场分析" [{target.get("tag")}] @ viewport({vx},{vy}) -> screen({sx},{sy})')
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.5)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    print('点击完成')

    # 等待并检查DTS面板
    for i in range(10):
        time.sleep(3)
        js3 = r"""(function(){
            var body = document.body ? document.body.innerText : '';
            return JSON.stringify({
                hasStartAnalysis: body.indexOf('开始分析') !== -1,
                hasMarketAnalysis: body.indexOf('市场分析') !== -1
            });
        })()"""
        r3 = cdp('Runtime.evaluate', {'expression': js3, 'returnByValue': True})
        s = json.loads(r3.get('result', {}).get('result', {}).get('value', '{}'))
        elapsed = (i+1) * 3
        has_start = s.get("hasStartAnalysis")
        has_market = s.get("hasMarketAnalysis")
        print(f'  {elapsed}s: start={has_start} market={has_market}')
        if has_start:
            print('  ✅ DTS面板已打开！')
            break
else:
    print('未找到市场分析元素')

ws.close()
