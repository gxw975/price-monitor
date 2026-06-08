import json, urllib.request, websocket, time, subprocess, os

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())
main = None
for t in targets:
    if 'taobao.com/search' in t.get('url','') and t.get('type')=='page':
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

def get_offset():
    js = r"""(function(){
        var fl = (window.outerWidth - window.innerWidth) / 2;
        return JSON.stringify({
            ox: Math.round((window.screenLeft || 0) + fl),
            oy: Math.round((window.screenTop || 0) + window.outerHeight - window.innerHeight - fl)
        });
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    d = json.loads(r.get('result', {}).get('result', {}).get('value', '{}'))
    return d.get('ox', 66), d.get('oy', 119)

ox, oy = get_offset()

env = os.environ.copy()
env["DISPLAY"] = DISPLAY
env["XAUTHORITY"] = XAUTH_FILE

def xdotool_click(vx, vy, label):
    sx, sy = vx + ox, vy + oy
    print(f'xdotool点击 "{label}" @ screen({sx},{sy})')
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.4)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)
    time.sleep(1)

# Step 1: Click "导出表格" in DTS panel header
# DTS panel header "导出表格" button is at viewport(960,196) with size 87x28
# Center: (960+87/2, 196+28/2) = (1003, 210)
print('=== 步骤1: 点击DTS面板"导出表格" ===')
xdotool_click(1003, 210, '导出表格(DTS面板)')

# Wait for dropdown menu
time.sleep(3)

# Check what appeared
js = r"""(function(){
    var results = [];
    var all = document.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
        var txt = (all[i].textContent || '').trim();
        var rect = all[i].getBoundingClientRect();
        if ((txt.indexOf('xlsx') !== -1 || txt.indexOf('Excel') !== -1 || txt.indexOf('XLSX') !== -1 ||
             txt.indexOf('csv') !== -1 || txt.indexOf('CSV') !== -1) &&
            rect.height > 0 && rect.height < 60 && rect.width > 0) {
            results.push({
                text: txt.substring(0, 30),
                tag: all[i].tagName,
                cls: String(all[i].className || '').substring(0, 30),
                vx: Math.round(rect.x),
                vy: Math.round(rect.y),
                vw: Math.round(rect.width),
                vh: Math.round(rect.height)
            });
        }
    }
    if (results.length === 0) {
        // Fallback: show all dropdown/popup items
        var all2 = document.querySelectorAll('.el-dropdown-menu__item, .el-menu-item, [class*="dropdown"], [class*="popup"], [class*="menu"]');
        for (var j = 0; j < all2.length; j++) {
            var t2 = (all2[j].textContent || '').trim();
            var r2 = all2[j].getBoundingClientRect();
            if (t2.length > 0 && t2.length < 30 && r2.height > 0 && r2.width > 0) {
                results.push({
                    text: t2.substring(0, 30),
                    tag: all2[j].tagName,
                    cls: String(all2[j].className || '').substring(0, 30),
                    vx: Math.round(r2.x),
                    vy: Math.round(r2.y),
                    vw: Math.round(r2.width),
                    vh: Math.round(r2.height)
                });
            }
        }
    }
    return JSON.stringify(results.slice(0, 15));
})()"""

r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
items = json.loads(r.get('result', {}).get('result', {}).get('value', '[]'))
print(f'\n导出菜单项:')
for item in items:
    print(f'  [{item.get("tag")}] "{item.get("text")}" cls="{item.get("cls")}" @ ({item.get("vx")},{item.get("vy")}) {item.get("vw")}x{item.get("vh")}')

# If xlsx found, click it
for item in items:
    txt = item.get('text', '').lower()
    if 'xlsx' in txt or 'excel' in txt:
        cx = item.get('vx', 0) + item.get('vw', 0) // 2
        cy = item.get('vy', 0) + item.get('vh', 0) // 2
        print(f'\n=== 点击xlsx选项: "{item.get("text")}" @ viewport({cx},{cy}) ===')
        xdotool_click(cx, cy, f'xlsx: {item.get("text")}')
        time.sleep(3)
        break

# Check if download started
print('\n=== 等待下载 ===')
download_dir = '/home/lab-admin/Downloads'
for i in range(30):
    import glob as g
    xlsx_files = g.glob(f'{download_dir}/*.xlsx')
    crdownload_files = g.glob(f'{download_dir}/*.crdownload')
    if xlsx_files:
        print(f'✅ 下载完成: {xlsx_files}')
        break
    if crdownload_files:
        print(f'  下载中: {crdownload_files}')
    time.sleep(5)
    if (i+1) % 6 == 0:
        print(f'  已等待{(i+1)*5}s...')

ws.close()
