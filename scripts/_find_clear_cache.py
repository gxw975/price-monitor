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

js = r"""
(function(){
    var results = [];
    var all = document.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var txt = (el.textContent || '').trim();
        if (txt.length > 0 && txt.length < 30 && el.offsetHeight > 0 && el.offsetHeight < 50 &&
            (txt.indexOf('清理') !== -1 || txt.indexOf('缓存') !== -1 || txt.indexOf('清除') !== -1 ||
             txt.indexOf('刷新') !== -1 || txt.indexOf('重试') !== -1 || txt.indexOf('继续加载') !== -1 ||
             txt.indexOf('重新加载') !== -1 || txt.indexOf('异常') !== -1 || txt.indexOf('关闭') !== -1)) {
            var rect = el.getBoundingClientRect();
            results.push({
                text: txt.substring(0, 30),
                tag: el.tagName,
                cls: String(el.className || '').substring(0, 50),
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

print('=== DTS弹窗中相关元素 ===')
for item in items:
    print(f'  [{item.get("tag")}] "{item.get("text")}" cls="{item.get("cls")}" @ viewport({item.get("vx")},{item.get("vy")}) {item.get("vw")}x{item.get("vh")}')

ws.close()
