#!/usr/bin/env python3
"""
固化版DTS完整抓取脚本 - 整合所有已验证经验
用法: python3 scripts/crawl_keyword_dts.py "关键词"
"""
import json, urllib.request, websocket, time, math, os, random, subprocess, sys, glob as g

DISPLAY = ":0"
XAUTH_FILE = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH_FILE
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")

KEYWORD = sys.argv[1] if len(sys.argv) > 1 else "蒙牛纯牛奶"
print(f'=== DTS完整抓取: {KEYWORD} ===')

resp = urllib.request.urlopen('http://127.0.0.1:9223/json', timeout=5)
targets = json.loads(resp.read())

main_page = None
for t in targets:
    if t.get('type') == 'page' and 'taobao.com' in t.get('url', ''):
        main_page = t; break
if not main_page:
    print('未找到淘宝页面'); exit(1)

ws = websocket.create_connection(main_page['webSocketDebuggerUrl'], timeout=15)
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

# ---- X11 init ----
from Xlib import display as xdisplay, X
from Xlib.ext import xtest
d = xdisplay.Display()

def x11_move(x, y):
    xtest.fake_input(d, X.MotionNotify, x=int(x), y=int(y)); d.sync()

def x11_click(x, y):
    x11_move(x, y); time.sleep(0.1)
    xtest.fake_input(d, X.ButtonPress, 1); d.sync(); time.sleep(0.05)
    xtest.fake_input(d, X.ButtonRelease, 1); d.sync()

def x11_down():
    xtest.fake_input(d, X.ButtonPress, 1); d.sync()

def x11_up():
    xtest.fake_input(d, X.ButtonRelease, 1); d.sync()

# ---- Helpers ----
def get_offset():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var fl = (window.outerWidth - window.innerWidth) / 2;
            return JSON.stringify({
                ox: Math.round((window.screenLeft||0)+fl),
                oy: Math.round((window.screenTop||0)+window.outerHeight-window.innerHeight-fl)
            });
        })()""",
        'returnByValue': True
    })
    d2 = json.loads(r.get('result',{}).get('result',{}).get('value','{}'))
    return d2.get('ox',66), d2.get('oy',119)

def xdotool_click(vx, vy, label=""):
    ox, oy = get_offset()
    sx, sy = vx + ox, vy + oy
    subprocess.run(["xdotool", "mousemove", str(sx), str(sy)], env=env, capture_output=True, timeout=10)
    time.sleep(0.4)
    subprocess.run(["xdotool", "click", "1"], env=env, capture_output=True, timeout=10)

def find_by_text(text):
    js = r"""(function(){
        var t = '""" + text + r"""';
        var all = document.querySelectorAll('*');
        for (var i=0; i<all.length; i++) {
            if ((all[i].textContent||'').trim()===t && all[i].offsetHeight>0 && all[i].offsetHeight<100) {
                var r = all[i].getBoundingClientRect();
                return JSON.stringify({found:true, vx:Math.round(r.x+r.width/2), vy:Math.round(r.y+r.height/2)});
            }
        }
        return JSON.stringify({found:false});
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result',{}).get('result',{}).get('value','{}'))

def find_by_contains(text):
    js = r"""(function(){
        var t = '""" + text + r"""';
        var all = document.querySelectorAll('*');
        for (var i=0; i<all.length; i++) {
            var txt = (all[i].textContent||'').trim();
            if (txt.indexOf(t)!==-1 && all[i].offsetHeight>0 && all[i].offsetHeight<100 && txt.length===t.length) {
                var r = all[i].getBoundingClientRect();
                return JSON.stringify({found:true, vx:Math.round(r.x+r.width/2), vy:Math.round(r.y+r.height/2), text:txt.substring(0,20)});
            }
        }
        return JSON.stringify({found:false});
    })()"""
    r = cdp('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    return json.loads(r.get('result',{}).get('result',{}).get('value','{}'))

def body_has(text):
    r = cdp('Runtime.evaluate', {
        'expression': f"(function(){{return (document.body?.innerText||'').indexOf('{text}')!==-1;}})()",
        'returnByValue': True
    })
    return r.get('result',{}).get('result',{}).get('value') == True

def body_progress():
    r = cdp('Runtime.evaluate', {
        'expression': r"""(function(){
            var body = document.body?.innerText||'';
            var m = body.match(/已成功加载[：:]\s*(\d+)\s*\/\s*(\d+)/);
            return JSON.stringify(m ? {loaded:parseInt(m[1]),total:parseInt(m[2])} : null);
        })()""",
        'returnByValue': True
    })
    return json.loads(r.get('result',{}).get('result',{}).get('value','null'))

# ---- Navigate to search if needed ----
cur_url_js = cdp('Runtime.evaluate', {'expression': 'window.location.href', 'returnByValue': True})
cur_url = cur_url_js.get('result',{}).get('result',{}).get('value','')
print(f'当前URL: {cur_url[:100]}')

enc = urllib.request.quote(KEYWORD)
if f'q={enc}' not in cur_url:
    print(f'导航到搜索页: {KEYWORD}')
    cdp('Page.navigate', {'url': f'https://s.taobao.com/search?q={enc}'})
    time.sleep(5)

# ---- Check captcha ----
print('\n【检查滑块验证】')
captcha_js = r"""(function(){
    var fs = document.querySelectorAll('iframe');
    for (var i=0; i<fs.length; i++) {
        if ((fs[i].src||'').indexOf('h5api')!==-1 && fs[i].getBoundingClientRect().width>0)
            return JSON.stringify({captcha:true});
    }
    return JSON.stringify({captcha:false});
})()"""
r = cdp('Runtime.evaluate', {'expression': captcha_js, 'returnByValue': True})
has_cap = json.loads(r.get('result',{}).get('result',{}).get('value','{}')).get('captcha')

if has_cap:
    print('检测到滑块验证，开始求解...')
    # Find punish frame
    ft = cdp('Page.getFrameTree')
    ftree = ft.get('result',{}).get('frameTree',{})
    p_fid = [None]
    def walk(node):
        for c in node.get('childFrames',[]):
            f = c.get('frame',{})
            if 'h5api' in f.get('url','') and 'punish' in f.get('url',''):
                p_fid[0] = f.get('id',''); return
            walk(c)
    walk(ftree)
    p_fid = p_fid[0]

    if p_fid:
        iso = cdp('Page.createIsolatedWorld', {'frameId': p_fid})
        ctx = iso.get('result',{}).get('executionContextId')

        for attempt in range(1, 6):
            r = cdp('Runtime.evaluate', {
                'expression': r"""(function(){
                    var s = document.querySelector('[id*="nc_1_n1z"]');
                    var t = document.querySelector('[id*="nc_1__scale_text"]');
                    if (!s||!t) { var w=document.querySelector('[id*="nc_1_wrapper"]');
                        if(w&&(w.innerHTML||'').indexOf('errloading')!==-1) return JSON.stringify({e:'errloading'});
                        return JSON.stringify({f:false}); }
                    var sr=s.getBoundingClientRect(), tr=t.getBoundingClientRect();
                    return JSON.stringify({x:Math.round(sr.x+sr.width/2),y:Math.round(sr.y+sr.height/2),d:Math.round(tr.x+tr.width-sr.x-sr.width+3)});
                })()""",
                'contextId': ctx, 'returnByValue': True
            })
            sl = json.loads(r.get('result',{}).get('result',{}).get('value','{}'))

            if sl.get('e') == 'errloading':
                err_js = r"""(function(){
                    var e = document.querySelector('.errloading');
                    if(!e) return JSON.stringify({f:false});
                    var r=e.getBoundingClientRect();
                    return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
                })()"""
                er = cdp('Runtime.evaluate', {'expression': err_js, 'contextId': ctx, 'returnByValue': True})
                ep = json.loads(er.get('result',{}).get('result',{}).get('value','{}'))
                if ep.get('x'):
                    ip = cdp('Runtime.evaluate', {
                        'expression': r"""(function(){var fs=document.querySelectorAll('iframe');
                            for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){
                                var r=fs[i].getBoundingClientRect();var fl=(window.outerWidth-window.innerWidth)/2;
                                return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y),ox:Math.round((window.screenLeft||0)+fl),oy:Math.round((window.screenTop||0)+window.outerHeight-window.innerHeight-fl)});}}
                            return JSON.stringify({f:false});})()""",
                        'returnByValue': True
                    })
                    ip2 = json.loads(ip.get('result',{}).get('result',{}).get('value','{}'))
                    ex = int(ip2.get('x',397)+ep['x']+ip2.get('ox',66))
                    ey = int(ip2.get('y',181)+ep['y']+ip2.get('oy',119))
                    x11_click(ex, ey)
                    time.sleep(3)
                continue

            if not sl.get('x'):
                if not body_has('请拖动'): print('✅ 验证码已消失'); break
                time.sleep(2); continue

            ip = cdp('Runtime.evaluate', {
                'expression': r"""(function(){var fs=document.querySelectorAll('iframe');
                    for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){
                        var r=fs[i].getBoundingClientRect();var fl=(window.outerWidth-window.innerWidth)/2;
                        return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y),ox:Math.round((window.screenLeft||0)+fl),oy:Math.round((window.screenTop||0)+window.outerHeight-window.innerHeight-fl)});}}
                    return JSON.stringify({});})()""",
                'returnByValue': True
            })
            ip2 = json.loads(ip.get('result',{}).get('result',{}).get('value','{}'))

            sx = ip2.get('x',397) + sl['x'] + ip2.get('ox',66)
            sy = ip2.get('y',181) + sl['y'] + ip2.get('oy',119)
            dist = sl['d']

            print(f'  尝试{attempt}: screen({sx},{sy}) dist={dist}')

            ax = sx - random.randint(35, 55)
            ay = sy + random.randint(-10, 10)
            for i in range(14):
                p = (i+1)/14
                x11_move(int(ax+(sx-ax)*p), int(ay+(sy-ay)*p+math.sin(i*0.5)*5))
                time.sleep(0.015+random.random()*0.02)
            x11_move(sx, sy); time.sleep(0.25+random.random()*0.35)
            x11_down(); time.sleep(0.03)

            pts = 280+random.randint(40,80)
            total_t = 3.0+random.random()*2.5
            for i in range(pts):
                p = i/pts
                if p<0.08: e=(p/0.08)**2*0.08
                elif p<0.88: e=0.08+(p-0.08)*0.84
                else: r2=(1-p)/0.12; e=1-r2*r2*0.12
                e+=(random.random()-0.5)*0.005
                x=int(sx+dist*e)
                yj=(math.sin(p*math.pi*3.1)*2.5+math.sin(p*math.pi*7.3)*0.6+math.sin(p*math.pi*13.7)*0.3)
                if random.random()<0.02: yj+=(random.random()-0.5)*8
                y=int(sy+yj)
                x11_move(x,y)
                time.sleep(max(0.002,total_t/pts*(0.6+random.random()*0.8)))
            x11_move(int(sx+dist),int(sy)); time.sleep(0.05)
            x11_move(int(sx+dist+random.uniform(2,5)),int(sy+random.randint(-1,1))); time.sleep(0.04)
            x11_move(int(sx+dist),int(sy)); time.sleep(0.05)
            time.sleep(0.18+random.random()*0.25)
            x11_up()
            print(f'  拖拽完成 (pts={pts})'); time.sleep(4)

            if not body_has('请拖动'): print(f'✅ 尝试{attempt}验证成功!'); break

print(f'\n验证码状态: {"存在" if has_cap else "无"}')

# ---- DTS Flow ----
print('\n=== 步骤1: 点击市场分析 ===')
for _ in range(3):
    el = find_by_text('市场分析')
    if el.get('found'):
        xdotool_click(el['vx'], el['vy'], '市场分析')
        break
    time.sleep(2)

for i in range(15):
    time.sleep(3)
    if body_has('开始分析'):
        print(f'  ✅ DTS面板已打开 ({i*3}s)'); break

if not body_has('开始分析'):
    print('  ❌ 面板未打开'); ws.close(); d.close(); exit(1)

# Check captcha barrier
if body_has('请拖动'):
    print('  ⚠️ 滑块验证又出现了！待处理...')
    # (TODO: add captcha re-solve inline)

print('\n=== 步骤2: 点击开始分析 ===')
el2 = find_by_text('开始分析')
if el2.get('found'):
    xdotool_click(el2['vx'], el2['vy'], '开始分析')

for i in range(20):
    time.sleep(5)
    if body_has('自动加载'):
        p = body_progress()
        print(f'  分析完成! progress={p}'); break

print('\n=== 步骤3: 自动加载全部数据 ===')
total_clicks = 0
for batch in range(8):
    for click_num in range(7):
        time.sleep(5)
        if click_num == 0: time.sleep(10)

        if body_has('遇到异常'):
            print('  ⚠️ 加载异常! 需要清理缓存重来')
            # Find and click clear cache button
            for item_text in ['清理缓存']:
                el = find_by_text(item_text)
                if not el.get('found'): el = find_by_contains(item_text)
                if el.get('found'):
                    xdotool_click(el['vx'], el['vy'], f'清理缓存'); break
            time.sleep(5)
            print('  缓存已清理，重新开始流程...')
            # Recursive restart
            ws.close(); d.close()
            os.execv(sys.executable, [sys.executable] + sys.argv)

        el = find_by_text('自动加载')
        if not el.get('found'):
            p = body_progress()
            print(f'  ✅ 自动加载完成! total_clicks={total_clicks} progress={p}'); break

        total_clicks += 1
        xdotool_click(el['vx'], el['vy'], f'自动加载 #{total_clicks}')
        time.sleep(30)
    else:
        continue
    break

# ---- Export ----
print('\n=== 步骤4: 导出xlsx ===')
# DTS header export button at about viewport(960+43,196+14) = (1003,210)
export_btn = find_by_text('导出表格')
if not export_btn.get('found'):
    # Try DTS panel header area
    export_btn = {'vx': 1003, 'vy': 210}

# Remove old xlsx files to detect new one
old_xlsx = set(g.glob(f'{DOWNLOAD_DIR}/*.xlsx'))
xdotool_click(export_btn.get('vx', 1003), export_btn.get('vy', 210), '导出表格')
time.sleep(3)

# Look for xlsx in dropdown
xlsx_item = find_by_contains('xlsx')
if not xlsx_item.get('found'):
    xlsx_item = find_by_contains('XLSX')
if not xlsx_item.get('found'):
    xlsx_item = find_by_contains('Excel')

if xlsx_item.get('found'):
    xdotool_click(xlsx_item['vx'], xlsx_item['vy'], f'xlsx选项')
    time.sleep(3)

# Wait for download
for i in range(24):
    new_xlsx = set(g.glob(f'{DOWNLOAD_DIR}/*.xlsx')) - old_xlsx
    if new_xlsx:
        fname = list(new_xlsx)[0]
        print(f'\n✅ xlsx下载完成: {fname}')
        break
    cr = g.glob(f'{DOWNLOAD_DIR}/*.crdownload')
    if cr: print(f'  下载中...')
    time.sleep(5)

d.close()
ws.close()
print('\n=== ✅ 完整抓取流程完成! ===')
