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

def find_button(text):
    js = f"""
    (function(){{
        var btns = document.querySelectorAll('button, [role="button"]');
        for (var i = 0; i < btns.length; i++) {{
            var txt = (btns[i].textContent || '').trim();
            if (txt.indexOf('{text}') !== -1 && btns[i].offsetHeight > 0) {{
                var rect = btns[i].getBoundingClientRect();
                var fl = (window.outerWidth - window.innerWidth) / 2;
                var to = window.outerHeight - window.innerHeight - fl;
                var ox = (window.screenLeft || 0) + fl;
                var oy = (window.screenTop || 0) + to;
                return JSON.stringify({{
                    found: true, text: txt,
                    sx: Math.round(rect.x + rect.width/2 + ox),
                    sy: Math.round(rect.y + rect.height/2 + oy)
                }});
            }}
        }}
        return JSON.stringify({{found: false}});
    }})()
    """
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

def xdotool_click(sx, sy):
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    env["XAUTHORITY"] = XAUTH_FILE
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.3)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)

def check_state():
    js = r"""(function(){
        var body = document.body ? document.body.innerText : '';
        return JSON.stringify({
            hasAutoLoad: body.indexOf('自动加载') !== -1,
            hasLoadMore: body.indexOf('加载下一页') !== -1,
            hasExport: body.indexOf('导出表格') !== -1,
            hasSort: body.indexOf('综合排序') !== -1
        });
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

# 点击自动加载按钮，等待数据加载
total_clicks = 0
for batch in range(6):
    for click in range(8):
        total_clicks += 1

        pos = find_button('自动加载')
        if not pos.get('found'):
            pos = find_button('加载下一页')

        if not pos.get('found'):
            print(f'总点击{total_clicks}次后，自动加载按钮消失，数据加载完成!')
            break

        sx, sy = pos['sx'], pos['sy']
        print(f'点击 #{total_clicks}: "{pos.get("text","")}" @ ({sx},{sy})')
        xdotool_click(sx, sy)
        time.sleep(30)

        state = check_state()
        print(f'  状态: autoload={state.get("hasAutoLoad")} loadmore={state.get("hasLoadMore")}')
    else:
        continue
    break

print(f'\n数据加载完成，总点击{total_clicks}次')

# 检查最终状态
state = check_state()
print(f'最终状态: {state}')
ws.close()
