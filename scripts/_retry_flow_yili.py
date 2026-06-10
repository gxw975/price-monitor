import json, urllib.request, websocket, time, math, os, random, subprocess, glob as g

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH_FILE
KEYWORD = "伊利纯牛奶"

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())
main = None
for t in targets:
    if 'taobao.com' in t.get('url','') and t.get('type')=='page':
        main = t; break
if not main: print('未找到淘宝页面'); exit(1)

ws = websocket.create_connection(main['webSocketDebuggerUrl'], timeout=15)
msg_id = 0
def cdp(method, params=None):
    global msg_id; msg_id += 1
    msg = {'id': msg_id, 'method': method}
    if params: msg['params'] = params
    ws.send(json.dumps(msg))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == msg_id: return r

cdp('Page.enable'); cdp('Runtime.enable')
env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

def get_off():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){var fl=(window.outerWidth-window.innerWidth)/2;return JSON.stringify({ox:Math.round((window.screenLeft||0)+fl),oy:Math.round((window.screenTop||0)+window.outerHeight-window.innerHeight-fl)});})()""",
        'returnByValue': True
    })
    d2 = json.loads(r.get('result',{}).get('result',{}).get('value','{}'))
    return d2.get('ox',66), d2.get('oy',119)

def xd_click(vx, vy, label=""):
    ox, oy = get_off()
    sx, sy = vx+ox, vy+oy
    print(f'  xdotool "{label}" @ screen({sx},{sy})')
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.4)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    time.sleep(1)

def find(text):
    js = f"""(function(){{var t='{text}';var all=document.querySelectorAll('*');for(var i=0;i<all.length;i++){{if((all[i].textContent||'').trim()===t&&all[i].offsetHeight>0&&all[i].offsetHeight<100){{var r=all[i].getBoundingClientRect();return JSON.stringify({{found:true,vx:Math.round(r.x+r.width/2),vy:Math.round(r.y+r.height/2)}});}}}}return JSON.stringify({{found:false}});}})()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result',{}).get('result',{}).get('value','{}'))

def has(text):
    r = cdp('Runtime.evaluate', {'expression': f"(function(){{return(document.body?.innerText||'').indexOf('{text}')!==-1;}})()", 'returnByValue': True})
    return r.get('result',{}).get('result',{}).get('value')==True

def prog():
    r = cdp('Runtime.evaluate', {'expression': r"""(function(){var b=document.body?.innerText||'';var m=b.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);return JSON.stringify(m?{loaded:parseInt(m[1]),total:parseInt(m[2])}:null);})()""", 'returnByValue': True})
    return json.loads(r.get('result',{}).get('result',{}).get('value','null'))

# ---- Cleanup remover ----
print('=== 步骤A: 清理缓存 ===')
el = find('清理缓存')
if el.get('found'):
    xd_click(el['vx'], el['vy'], '清理缓存')
    time.sleep(5)
    print('缓存已清理，DTS弹窗应已关闭')

# Verify back on taobao search page
print(f'关闭后: market={has("市场分析")} start={has("开始分析")}')

# ---- Restart flow ----
print('\n=== 步骤B: 点击市场分析 ===')
for _ in range(3):
    el = find('市场分析')
    if el.get('found'):
        xd_click(el['vx'], el['vy'], '市场分析')
        break
    time.sleep(2)

for i in range(12):
    time.sleep(3)
    if has('开始分析'):
        print(f'  DTS面板打开 ({(i+1)*3}s)')
        break

if not has('开始分析'):
    print('  面板未打开!'); ws.close(); exit(1)

print('\n=== 步骤C: 点击开始分析 ===')
el2 = find('开始分析')
if el2.get('found'):
    xd_click(el2['vx'], el2['vy'], '开始分析')

for i in range(20):
    time.sleep(5)
    if has('自动加载') or has('加载下一页'):
        print(f'  分析完成! progress={prog()}')
        break

# ---- Auto load ----
print('\n=== 步骤D: 自动加载 ===')
tc = 0
for batch in range(10):
    for click_num in range(7):
        time.sleep(5)
        if click_num == 0: time.sleep(10)

        if has('遇到异常') and has('清理缓存'):
            print('  需要清理缓存，正在处理...')
            el = find('清理缓存')
            if el.get('found'):
                xd_click(el['vx'], el['vy'], '清理缓存')
                time.sleep(5)
                # Restart from step B
                for _ in range(3):
                    el = find('市场分析')
                    if el.get('found'):
                        xd_click(el['vx'], el['vy'], '市场分析')
                        break
                    time.sleep(2)
                for i in range(12):
                    time.sleep(3)
                    if has('开始分析'): break
                el2 = find('开始分析')
                if el2.get('found'):
                    xd_click(el2['vx'], el2['vy'], '开始分析')
                for i in range(20):
                    time.sleep(5)
                    if has('自动加载') or has('加载下一页'): break
                continue

        el = find('自动加载')
        if not el.get('found'):
            el = find('加载下一页')
        if not el.get('found'):
            p = prog()
            print(f'  加载完成! clicks={tc} progress={p}')
            break
        tc += 1
        xd_click(el['vx'], el['vy'], f'加载 #{tc}')
        time.sleep(30)
    else:
        continue
    break

# ---- Export ----
print(f'\n=== 步骤E: 导出 ===')
p = prog()
print(f'最终: {p}')

old = set(g.glob(f'{DOWNLOAD_DIR}/*.xlsx'))
el = find('导出表格')
if el.get('found'):
    xd_click(el['vx'], el['vy'], '导出表格')
else:
    xd_click(1003, 210, '导出表格(估计)')
time.sleep(3)

for i in range(30):
    new = set(g.glob(f'{DOWNLOAD_DIR}/*.xlsx')) - old
    if new:
        print(f'\n✅ 下载: {list(new)[0]}')
        break
    if g.glob(f'{DOWNLOAD_DIR}/*.crdownload'):
        print('  下载中...')
    time.sleep(5)

ws.close()
print('\n✅ 完成!')
