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

# 检查数据加载进度
js = r"""
(function(){
    var body = document.body ? document.body.innerText : '';

    // 查找数据加载进度
    var progressMatch = body.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);
    var progress = progressMatch ? {loaded: parseInt(progressMatch[1]), total: parseInt(progressMatch[2])} : null;

    // 查找导出按钮
    var hasExport = body.indexOf('导出表格') !== -1;
    var hasAutoLoad = body.indexOf('自动加载') !== -1;

    // 检查数据行数
    var rows = document.querySelectorAll('table tr, [class*="data-row"], [class*="DataItem"]');

    return JSON.stringify({
        progress: progress,
        hasExport: hasExport,
        hasAutoLoad: hasAutoLoad,
        dataRows: rows.length,
        bodyLen: body.length
    });
})()
"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
val = r.get('result', {}).get('result', {}).get('value', '{}')
info = json.loads(val)

print(f'数据加载进度: {info.get("progress")}')
print(f'导出表格: {info.get("hasExport")}')
print(f'自动加载: {info.get("hasAutoLoad")}')
print(f'数据行数: {info.get("dataRows")}')
print(f'body长度: {info.get("bodyLen")}')

# 现在尝试点击导出表格
print('\n=== 尝试导出 ===')

# 先滚动到导出按钮位置
js_scroll = r"""
(function(){
    var btns = document.querySelectorAll('button, [role="button"], div, span');
    for (var i = 0; i < btns.length; i++) {
        var txt = (btns[i].textContent || '').trim();
        if (txt === '导出表格' && btns[i].offsetHeight > 0) {
            btns[i].scrollIntoView({behavior: 'instant', block: 'center'});
            var rect = btns[i].getBoundingClientRect();
            var fl = (window.outerWidth - window.innerWidth) / 2;
            var to = window.outerHeight - window.innerHeight - fl;
            var ox = (window.screenLeft || 0) + fl;
            var oy = (window.screenTop || 0) + to;
            return JSON.stringify({
                found: true,
                sx: Math.round(rect.x + rect.width/2 + ox),
                sy: Math.round(rect.y + rect.height/2 + oy)
            });
        }
    }
    return JSON.stringify({found: false});
})()
"""

r = cdp('Runtime.evaluate', {'expression': js_scroll, 'returnByValue': True})
pos = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
print(f'导出表格按钮: {pos}')

if pos.get('found'):
    sx, sy = pos['sx'], pos['sy']
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["XAUTHORITY"] = XAUTH_FILE

    # xdotool点击导出表格
    print(f'xdotool点击导出表格 @ ({sx},{sy})')
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.3)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    time.sleep(3)

    # 检查弹出的菜单
    js_menu = r"""
    (function(){
        var all = document.querySelectorAll('*');
        var items = [];
        for (var i = 0; i < all.length; i++) {
            var txt = (all[i].textContent || '').trim();
            var cls = String(all[i].className || '');
            if ((txt.indexOf('xlsx') !== -1 || txt.indexOf('Excel') !== -1 || txt.indexOf('表格') !== -1 ||
                 txt.indexOf('csv') !== -1 || txt.indexOf('全部导出') !== -1) &&
                all[i].offsetHeight > 0 && all[i].offsetHeight < 100) {
                var rect = all[i].getBoundingClientRect();
                items.push({
                    text: txt.substring(0, 40),
                    tag: all[i].tagName,
                    cls: cls.substring(0, 40),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                });
            }
        }
        return JSON.stringify(items.slice(0, 10));
    })()
    """
    r = cdp('Runtime.evaluate', {'expression': js_menu, 'returnByValue': True})
    val = r.get('result', {}).get('result', {}).get('value', '[]')
    menu_items = json.loads(val)
    print(f'\n菜单项: {json.dumps(menu_items, ensure_ascii=False, indent=2)}')

    # 点击xlsx选项
    for item in menu_items:
        txt = item.get('text', '')
        if 'xlsx' in txt.lower() or 'excel' in txt.lower():
            rect = item.get('rect', {})
            if rect.get('w', 0) > 0 and rect.get('h', 0) > 0:
                js_pos = f"""
                (function(){{
                    var all = document.querySelectorAll('*');
                    for (var i = 0; i < all.length; i++) {{
                        var t = (all[i].textContent || '').trim();
                        var r = all[i].getBoundingClientRect();
                        if (t === '{txt}' && Math.abs(r.x - {rect['x']}) < 5 && all[i].offsetHeight > 0) {{
                            var fl = (window.outerWidth - window.innerWidth) / 2;
                            var to = window.outerHeight - window.innerHeight - fl;
                            var ox = (window.screenLeft || 0) + fl;
                            var oy = (window.screenTop || 0) + to;
                            return JSON.stringify({{
                                sx: Math.round(r.x + r.width/2 + ox),
                                sy: Math.round(r.y + r.height/2 + oy)
                            }});
                        }}
                    }}
                    return JSON.stringify({{found: false}});
                }})()
                """
                r2 = cdp('Runtime.evaluate', {'expression': js_pos, 'returnByValue': True})
                p = json.loads(r2.get('result', {}).get('result', {}).get('value', '{}'))
                if p.get('sx'):
                    print(f'点击xlsx选项 "{txt}" @ ({p["sx"]},{p["sy"]})')
                    subprocess.run(["xdotool", "mousemove", str(p['sx']), str(p['sy'])], env=env, capture_output=True, timeout=10)
                    time.sleep(0.3)
                    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
                    print('xlsx选项点击完成')
                    break

ws.close()
