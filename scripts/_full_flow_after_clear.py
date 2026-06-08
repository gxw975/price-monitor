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

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

def get_offset():
    js = r"""(function(){
        var fl = (window.outerWidth - window.innerWidth) / 2;
        return JSON.stringify({
            ox: (window.screenLeft || 0) + fl,
            oy: (window.screenTop || 0) + window.outerHeight - window.innerHeight - fl
        });
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    d = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
    return d.get('ox', 66), d.get('oy', 119)

def find_element(text_exact=False, text_contains=None):
    """查找元素viewport坐标，返回 {found, vx, vy, vw, vh} 或 {found: False}"""
    if text_exact:
        js = f"""(function(){{
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {{
                var txt = (all[i].textContent || '').trim();
                if (txt === '{text_exact}' && all[i].offsetHeight > 0 && all[i].offsetHeight < 100) {{
                    var rect = all[i].getBoundingClientRect();
                    return JSON.stringify({{found: true, text: txt,
                        vx: Math.round(rect.x + rect.width/2),
                        vy: Math.round(rect.y + rect.height/2)}});
                }}
            }}
            return JSON.stringify({{found: false}});
        }})()"""
    else:
        js = f"""(function(){{
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {{
                var txt = (all[i].textContent || '').trim();
                if (txt.indexOf('{text_contains}') !== -1 && all[i].offsetHeight > 0 && all[i].offsetHeight < 100) {{
                    var rect = all[i].getBoundingClientRect();
                    return JSON.stringify({{found: true, text: txt.substring(0,20),
                        vx: Math.round(rect.x + rect.width/2),
                        vy: Math.round(rect.y + rect.height/2)}});
                }}
            }}
            return JSON.stringify({{found: false}});
        }})()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

def xdotool_click(vx, vy, label=""):
    ox, oy = get_offset()
    sx = vx + ox
    sy = vy + oy
    print(f'  xdotool点击 "{label}" @ screen({sx},{sy})')
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.4)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    time.sleep(0.5)

def check_body_text():
    js = r"""(function(){
        var body = document.body ? document.body.innerText : '';
        var m = body.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);
        return JSON.stringify({
            hasMarketAnalysis: body.indexOf('市场分析') !== -1,
            hasStartAnalysis: body.indexOf('开始分析') !== -1,
            hasAutoLoad: body.indexOf('自动加载') !== -1,
            hasExport: body.indexOf('导出表格') !== -1,
            hasError: body.indexOf('遇到异常') !== -1,
            hasContinue: body.indexOf('继续加载') !== -1,
            hasClearCache: body.indexOf('清理缓存') !== -1,
            progress: m ? {loaded: parseInt(m[1]), total: parseInt(m[2])} : null
        });
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))

# ========== 步骤1: 确认在淘宝搜索结果页 ==========
print("=== 步骤1: 确认当前页面 ===")
state = check_body_text()
print(f'  状态: {json.dumps(state, ensure_ascii=False)}')

if not state.get('hasMarketAnalysis'):
    print('  错误: 不在淘宝搜索结果页')
    ws.close()
    exit(1)

# ========== 步骤2: 点击市场分析 ==========
print("\n=== 步骤2: 点击'市场分析' ===")
el = find_element(text_exact="市场分析")
if el.get('found'):
    xdotool_click(el['vx'], el['vy'], '市场分析')
else:
    el = find_element(text_contains="市场分析")
    if el.get('found'):
        xdotool_click(el['vx'], el['vy'], '市场分析(contains)')

# 等待DTS面板打开
print('  等待DTS面板打开...')
for i in range(15):
    time.sleep(3)
    state = check_body_text()
    elapsed = (i+1) * 3
    print(f'  {elapsed}s: startAnalysis={state.get("hasStartAnalysis")} export={state.get("hasExport")}')
    if state.get('hasStartAnalysis'):
        print('  ✅ DTS面板已打开，开始分析按钮出现')
        break

if not state.get('hasStartAnalysis'):
    print('  ❌ 等待超时，开始分析按钮未出现')
    ws.close()
    exit(1)

# ========== 步骤3: 点击开始分析 ==========
print("\n=== 步骤3: 点击'开始分析' ===")
time.sleep(2)
el = find_element(text_exact="开始分析")
if el.get('found'):
    xdotool_click(el['vx'], el['vy'], '开始分析')

# 等待分析完成
print('  等待分析完成...')
for i in range(20):
    time.sleep(5)
    state = check_body_text()
    elapsed = (i+1) * 5
    print(f'  {elapsed}s: autoLoad={state.get("hasAutoLoad")} export={state.get("hasExport")} error={state.get("hasError")} progress={state.get("progress")}')
    if state.get('hasAutoLoad') or state.get('hasExport'):
        print('  ✅ 分析完成！')
        break

# ========== 步骤4: 自动加载全部数据 ==========
print("\n=== 步骤4: 自动加载全部数据 ===")
total_clicks = 0

for batch in range(6):
    for click in range(7):
        time.sleep(5)

        if not click:  # batch first click, longer wait
            time.sleep(10)

        state = check_body_text()
        if state.get('hasError'):
            print(f'  ⚠️ 遇到加载异常！需要清理缓存重新开始')
            ws.close()
            exit(2)

        if not state.get('hasAutoLoad'):
            print(f'  ✅ 自动加载完成！总点击={total_clicks}次 progress={state.get("progress")}')
            break

        el = find_element(text_exact="自动加载")
        if not el.get('found'):
            print(f'  ✅ 自动加载按钮消失，完成！总点击={total_clicks}次')
            break

        total_clicks += 1
        xdotool_click(el['vx'], el['vy'], f'自动加载 #{total_clicks}')
        time.sleep(25)

    else:
        continue
    break

# ========== 最终状态 ==========
state = check_body_text()
print(f'\n=== 最终状态 ===')
print(f'  progress: {state.get("progress")}')
print(f'  hasExport: {state.get("hasExport")}')
print(f'  hasError: {state.get("hasError")}')

ws.close()
