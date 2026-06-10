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

ox, oy = get_offset()

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

def xdotool_click(vx, vy, label=""):
    sx = vx + ox
    sy = vy + oy
    print(f'点击 "{label}" viewport({vx},{vy}) -> screen({sx},{sy})')
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.5)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    time.sleep(1)

def check_page_state():
    js = r"""(function(){
        var body = document.body ? document.body.innerText : '';
        var m = body.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);
        return JSON.stringify({
            hasMarketAnalysis: body.indexOf('市场分析') !== -1,
            hasStartAnalysis: body.indexOf('开始分析') !== -1,
            hasAutoLoad: body.indexOf('自动加载') !== -1,
            hasLoadMore: body.indexOf('加载下一页') !== -1,
            hasExport: body.indexOf('导出表格') !== -1,
            hasError: body.indexOf('遇到异常') !== -1,
            hasClearCache: body.indexOf('清理缓存') !== -1,
            progress: m ? {loaded: parseInt(m[1]), total: parseInt(m[2])} : null
        });
    })()"""
    try:
        r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
        val = r.get('result', {}).get('result', {}).get('value', '{}')
        return json.loads(val)
    except Exception:
        return {}

# 步骤1: 点击清理缓存
print("=== 步骤1: 点击清理缓存 ===")
xdotool_click(967, 37, "清理缓存(顶部右侧)")

# 等待弹窗关闭
time.sleep(5)

# 检查页面状态
state = check_page_state()
print(f'清理缓存后状态: {json.dumps(state, ensure_ascii=False)}')

ws.close()
