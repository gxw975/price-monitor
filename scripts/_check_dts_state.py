import json, urllib.request, websocket, time

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())
pages = [t for t in targets if t.get('type') == 'page']
print(f'Pages: {len(pages)}')
for p in pages:
    print(f'  {p.get("url","")[:100]}')

if not pages:
    exit(1)

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
time.sleep(1)

js = """
(function(){
    var body = document.body ? document.body.innerText.substring(0, 1000) : '';
    var hasStart = body.indexOf('开始分析') !== -1;
    var hasSort = body.indexOf('综合排序') !== -1;
    var hasExport = body.indexOf('导出表格') !== -1;
    var hasAutoLoad = body.indexOf('自动加载') !== -1;
    var hasLoadMore = body.indexOf('加载下一页') !== -1;

    var dtsClasses = [];
    var all = document.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
        var cls = String(all[i].className || '');
        if ((cls.indexOf('dts') !== -1 || cls.indexOf('diantoushi') !== -1) && all[i].offsetHeight > 0) {
            dtsClasses.push(cls.substring(0, 60));
            if (dtsClasses.length >= 15) break;
        }
    }

    var buttons = [];
    var btns = document.querySelectorAll('button, [role="button"]');
    for (var j = 0; j < btns.length; j++) {
        if (btns[j].offsetHeight > 0) {
            var txt = (btns[j].textContent || '').trim().substring(0, 30);
            if (txt.length > 0 && txt.length < 30) {
                buttons.push({txt: txt, tag: btns[j].tagName, visible: true});
            }
        }
        if (buttons.length >= 15) break;
    }

    return JSON.stringify({
        url: window.location.href.substring(0, 100),
        hasStart: hasStart, hasSort: hasSort, hasExport: hasExport,
        hasAutoLoad: hasAutoLoad, hasLoadMore: hasLoadMore,
        dtsClasses: dtsClasses,
        buttons: buttons,
        bodyLen: body.length
    });
})()
"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
val = r.get('result', {}).get('result', {}).get('value', '{}')
info = json.loads(val)

print(f'\n=== 页面状态 ===')
print(f'URL: {info.get("url")}')
print(f'body长度: {info.get("bodyLen")}')
print(f'开始分析: {info.get("hasStart")}')
print(f'综合排序: {info.get("hasSort")}')
print(f'导出表格: {info.get("hasExport")}')
print(f'自动加载: {info.get("hasAutoLoad")}')
print(f'加载下一页: {info.get("hasLoadMore")}')
print(f'\n=== DTS相关class ===')
for c in info.get('dtsClasses', []):
    print(f'  {c}')
print(f'\n=== 可见按钮 ===')
for b in info.get('buttons', []):
    print(f'  [{b.get("tag")}] {b.get("txt")}')

ws.close()
