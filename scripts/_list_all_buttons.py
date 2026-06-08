import json, urllib.request, websocket, time

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

# 列出所有可见按钮及其位置
js = r"""
(function(){
    var results = [];
    var all = document.querySelectorAll('button, [role="button"], div, span, a, li');
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var txt = (el.textContent || '').trim();
        var rect = el.getBoundingClientRect();
        if (rect.height > 0 && rect.height < 60 && txt.length > 0 && txt.length < 30 &&
            (txt.indexOf('加载') !== -1 || txt.indexOf('导出') !== -1 || txt.indexOf('全选') !== -1 ||
             txt.indexOf('复制') !== -1 || txt.indexOf('分析') !== -1 || txt.indexOf('开始') !== -1 ||
             txt.indexOf('确定') !== -1 || txt.indexOf('取消') !== -1 || txt.indexOf('表格') !== -1)) {
            results.push({
                text: txt,
                tag: el.tagName,
                vx: Math.round(rect.x),
                vy: Math.round(rect.y),
                vw: Math.round(rect.width),
                vh: Math.round(rect.height)
            });
        }
    }
    return JSON.stringify(results);
})()
"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
val = r.get('result', {}).get('result', {}).get('value', '[]')
items = json.loads(val)

print('=== 页面上与DTS相关的可见元素 ===')
for item in items:
    print(f'  [{item.get("tag")}] "{item.get("text")}" @ viewport({item.get("vx")},{item.get("vy")}) {item.get("vw")}x{item.get("vh")}')

ws.close()
