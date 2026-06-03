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

for i in range(12):
    time.sleep(10)
    js = r"""(function(){
        var body = document.body ? document.body.innerText : '';
        var m = body.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);
        return JSON.stringify({
            progress: m ? {loaded: parseInt(m[1]), total: parseInt(m[2])} : null,
            hasAutoLoad: body.indexOf('自动加载') !== -1,
            hasLoadMore: body.indexOf('加载下一页') !== -1,
            hasLoading: body.indexOf('加载中') !== -1 || body.indexOf('拼命加载') !== -1
        });
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    state = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
    elapsed = (i+1) * 10
    p = state.get('progress', {})
    print(f'{elapsed}s: loaded={p.get("loaded")}/{p.get("total")} autoload={state.get("hasAutoLoad")} loadmore={state.get("hasLoadMore")} loading={state.get("hasLoading")}')

    if state.get('hasAutoLoad') or state.get('hasLoadMore'):
        print(f'\n按钮重新出现，数据加载中...')
        break

    if p.get('loaded') and p.get('loaded') >= p.get('total', 999):
        print(f'\n数据加载完成!')
        break

ws.close()
