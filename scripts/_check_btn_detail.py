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
    var btns = document.querySelectorAll('button');
    var results = [];
    for (var i = 0; i < btns.length; i++) {
        var txt = (btns[i].textContent || '').trim();
        if (txt === '开始分析' || txt === '取消') {
            var rect = btns[i].getBoundingClientRect();
            var parent = btns[i].parentElement;
            var grandparent = parent ? parent.parentElement : null;
            results.push({
                text: txt,
                tag: btns[i].tagName,
                rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                parentClass: parent ? String(parent.className || '').substring(0, 80) : '',
                grandparentClass: grandparent ? String(grandparent.className || '').substring(0, 80) : '',
                disabled: btns[i].disabled,
                onclick: !!btns[i].onclick
            });
        }
    }

    var iframes = document.querySelectorAll('iframe');
    var iframeInfo = [];
    for (var j = 0; j < iframes.length; j++) {
        iframeInfo.push({
            src: (iframes[j].src || '').substring(0, 100),
            cls: String(iframes[j].className || '').substring(0, 60),
            visible: iframes[j].offsetHeight > 0
        });
    }

    return JSON.stringify({buttons: results, iframes: iframeInfo});
})()
"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
val = r.get('result', {}).get('result', {}).get('value', '{}')
info = json.loads(val)

print('=== 开始分析/取消按钮 ===')
for b in info.get('buttons', []):
    print(f'  text={b.get("text")} rect={b.get("rect")} disabled={b.get("disabled")} onclick={b.get("onclick")}')
    print(f'    parentClass: {b.get("parentClass")}')
    print(f'    grandparentClass: {b.get("grandparentClass")}')

print('\n=== iframe ===')
for f in info.get('iframes', []):
    print(f'  src={f.get("src")} cls={f.get("cls")} visible={f.get("visible")}')

ws.close()
