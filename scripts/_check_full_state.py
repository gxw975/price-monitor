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

# 检查完整body文本（不限长度）
js = r"""
(function(){
    var body = document.body ? document.body.innerText : '';
    var len = body.length;

    // 检查关键词
    var keywords = ['开始分析', '综合排序', '导出表格', '自动加载', '加载下一页', '加载更多', '拼命加载', '加载中', '复制表格', '取消', '确定'];
    var found = {};
    for (var i = 0; i < keywords.length; i++) {
        found[keywords[i]] = body.indexOf(keywords[i]) !== -1;
    }

    // 检查所有可见按钮文本
    var btns = [];
    var allBtns = document.querySelectorAll('button, [role="button"]');
    for (var j = 0; j < allBtns.length; j++) {
        if (allBtns[j].offsetHeight > 0) {
            btns.push((allBtns[j].textContent || '').trim().substring(0, 30));
        }
    }

    // 检查DTS面板特定元素
    var dtsPanel = document.querySelector('.marketAnalysis, .market-analysis, [class*="marketAnalysis"]');
    var dtsFloat = document.querySelector('[class*="dts-float"], [class*="dtsFloat"]');

    return JSON.stringify({
        bodyLen: len,
        keywords: found,
        buttons: btns.slice(0, 20),
        dtsPanel: !!dtsPanel,
        dtsFloat: !!dtsFloat,
        bodySnippet: body.substring(0, 300)
    });
})()
"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
val = r.get('result', {}).get('result', {}).get('value', '{}')
info = json.loads(val)

print(f'body长度: {info.get("bodyLen")}')
print(f'\n关键词检测:')
for k, v in info.get('keywords', {}).items():
    print(f'  {k}: {v}')
print(f'\n可见按钮: {info.get("buttons")}')
print(f'DTS面板: {info.get("dtsPanel")}')
print(f'DTS浮动按钮: {info.get("dtsFloat")}')
print(f'\nbody前300字: {info.get("bodySnippet")}')

ws.close()
