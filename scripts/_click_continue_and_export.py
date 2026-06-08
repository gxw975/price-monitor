import json, urllib.request, websocket, time, math, os, random, subprocess, glob as g

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH_FILE

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())
main = None
for t in targets:
    if 'taobao.com' in t.get('url','') and t.get('type')=='page':
        main = t; break

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

def get_offset():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var fl=(window.outerWidth-window.innerWidth)/2;
            return JSON.stringify({ox:Math.round((window.screenLeft||0)+fl),oy:Math.round((window.screenTop||0)+window.outerHeight-window.innerHeight-fl)});
        })()""",
        'returnByValue': True
    })
    d2 = json.loads(r.get('result',{}).get('result',{}).get('value','{}'))
    return d2.get('ox',66), d2.get('oy',119)

def find(text):
    js = f"""(function(){{
        var t='{text}'; var all=document.querySelectorAll('*');
        for(var i=0;i<all.length;i++){{
            if((all[i].textContent||'').trim()===t && all[i].offsetHeight>0 && all[i].offsetHeight<100){{
                var r=all[i].getBoundingClientRect();
                return JSON.stringify({{found:true,vx:Math.round(r.x+r.width/2),vy:Math.round(r.y+r.height/2)}});
            }}
        }}
        return JSON.stringify({{found:false}});
    }})()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result',{}).get('result',{}).get('value','{}'))

def click(vx, vy, label=""):
    ox, oy = get_offset()
    sx, sy = vx + ox, vy + oy
    print(f'  xdotool click "{label}" @ screen({sx},{sy})')
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.4)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    time.sleep(1)

def body_has(text):
    r = cdp('Runtime.evaluate', {
        'expression': f"(function(){{return(document.body?.innerText||'').indexOf('{text}')!==-1;}})()",
        'returnByValue': True
    })
    return r.get('result',{}).get('result',{}).get('value')==True

def progress():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){var b=document.body?.innerText||'';var m=b.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);return JSON.stringify(m?{loaded:parseInt(m[1]),total:parseInt(m[2])}:null);})()""",
        'returnByValue': True
    })
    return json.loads(r.get('result',{}).get('result',{}).get('value','null'))

# ---- Main ----
print('=== 当前状态 ===')
print(f'  进度: {progress()}')
print(f'  异常: {body_has("遇到异常")}')
print(f'  继续加载: {body_has("继续加载")}')
print(f'  自动加载: {body_has("自动加载")}')

# Step 1: If error, try "继续加载" first
if body_has('遇到异常') and body_has('继续加载'):
    print('\n=== 点击继续加载 ===')
    for _ in range(5):
        el = find('继续加载')
        if el.get('found'):
            click(el['vx'], el['vy'], '继续加载')
            time.sleep(15)
            if not body_has('继续加载'):
                print('  继续加载成功，等待数据...')
                break
        time.sleep(5)

# Step 2: Wait and check progress
for i in range(10):
    time.sleep(10)
    p = progress()
    has_err = body_has('遇到异常')
    has_auto = body_has('自动加载')
    has_cont = body_has('继续加载')
    print(f'  {(i+1)*10}s: progress={p} error={has_err} auto={has_auto} continue={has_cont}')
    if has_cont:
        el = find('继续加载')
        if el.get('found'):
            click(el['vx'], el['vy'], '继续加载')
    if not has_auto and not has_cont:
        break

# Step 3: Export
print(f'\n=== 导出xlsx ===')
p = progress()
print(f'最终进度: {p}')

old = set(g.glob(f'{DOWNLOAD_DIR}/*.xlsx'))

# Click 导出表格 in DTS header
el = find('导出表格')
if el.get('found'):
    click(el['vx'], el['vy'], '导出表格')
else:
    click(1003, 210, '导出表格(估计)')

time.sleep(3)

# Wait for download
for i in range(30):
    new = set(g.glob(f'{DOWNLOAD_DIR}/*.xlsx')) - old
    if new:
        fname = list(new)[0]
        print(f'\n✅ 下载完成: {fname}')
        break
    cr = g.glob(f'{DOWNLOAD_DIR}/*.crdownload')
    if cr: print(f'  下载中...')
    time.sleep(5)
    if i % 6 == 5: print(f'  等待{(i+1)*5}s...')

ws.close()
