#!/usr/bin/env python3
"""Chrome Profile 一键环境初始化 — DTS扩展 + 淘宝登录 + 会话预热"""

import json, logging, math, os, pickle, random, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime; from pathlib import Path
from Xlib import X, display as xd; from Xlib.ext import xtest as xt

CDP_PORT = 9223
PROFILE = Path("/home/lab-admin/.config/google-chrome-profile-manual")
SYSTEM_PROFILE = Path("/home/lab-admin/.config/google-chrome")
DTS_EXT_ID = "ppgdlgnehnajbbngnohepfigdmjbdpfb"
DISPLAY = ":0"
XAUTH = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"
OX, OY = 66, 119

TAOBAO_USER = "tb334522221422"
TAOBAO_PASS = "qxd@2026"

os.environ["DISPLAY"] = DISPLAY
os.environ["XAUTHORITY"] = XAUTH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("init")

def rpt(msg): logger.info(msg)

# ═══ CDP ═══
def cdp_cmd(ws, m, p=None, t=15):
    msg = {"id": int(time.time()*1000)%1000000, "method": m}
    if p: msg["params"] = p
    ws.send(json.dumps(msg)); dl = time.time() + t
    while time.time() < dl:
        r = json.loads(ws.recv())
        if r.get("id") == msg["id"]: return r
    raise TimeoutError(m)

def cdp_eval(ws, js):
    r = cdp_cmd(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))

def cdp_eval_ctx(ws, ctx, js):
    r = cdp_cmd(ws, "Runtime.evaluate", {"expression": js, "contextId": ctx, "returnByValue": True, "awaitPromise": True})
    return str(r.get("result",{}).get("result",{}).get("value",""))


# ═══ Chrome Lifecycle ═══
def kill_chrome():
    rpt("杀死所有Chrome进程...")
    subprocess.run(["pkill", "-TERM", "chrome"], check=False); time.sleep(3)
    subprocess.run(["pkill", "-KILL", "chrome"], check=False); time.sleep(1)

def launch_chrome():
    rpt("启动Chrome (3参数)...")
    # Clean locks
    for f in PROFILE.rglob("Singleton*"): f.unlink(missing_ok=True)
    subprocess.Popen([
        "/usr/bin/google-chrome-stable",
        "--remote-debugging-port=9223", "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}",
    ], env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(8)

    import websocket
    for i in range(20):
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=3)
            targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]
            if not pages:
                urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank", timeout=5)
                time.sleep(1); continue
            ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=15, origin="")
            cdp_cmd(ws, "Page.enable"); cdp_cmd(ws, "Runtime.enable")
            rpt(f"Chrome ready ({i+1}s)")
            return ws
        except: time.sleep(1)
    return None


# ═══ Phase 1: Profile Setup ═══
def setup_profile():
    rpt("\n" + "="*60)
    rpt("Phase 1: 环境清理与Profile准备")
    rpt("="*60)

    # 1. Kill Chrome
    kill_chrome()

    # 2. Backup empty profile
    if PROFILE.exists():
        backup = Path(f"{PROFILE}-empty")
        if backup.exists(): shutil.rmtree(backup)
        shutil.move(str(PROFILE), str(backup))
        rpt(f"空Profile已备份: {backup}")

    # 3. Copy DTS extension from system Chrome
    PROFILE.mkdir(parents=True, exist_ok=True)
    ext_dst = PROFILE / "Default" / "Extensions"
    ext_dst.mkdir(parents=True, exist_ok=True)

    ext_src = SYSTEM_PROFILE / "Default" / "Extensions"
    if ext_src.exists():
        for item in ext_src.iterdir():
            dst = ext_dst / item.name
            if not dst.exists():
                shutil.copytree(str(item), str(dst))
                rpt(f"复制扩展: {item.name}")
    else:
        rpt("⚠️ 系统Chrome无Extensions目录，尝试UnpackedExtensions...")
        unpacked = SYSTEM_PROFILE / "Default" / "UnpackedExtensions"
        if unpacked.exists():
            udst = PROFILE / "Default" / "UnpackedExtensions"
            udst.mkdir(parents=True, exist_ok=True)
            for item in unpacked.iterdir():
                shutil.copytree(str(item), str(udst / item.name))
                rpt(f"复制Unpacked: {item.name}")

    # Also copy from old chrome-user-data
    old_ext = Path("/home/lab-admin/chrome-user-data/Default/Extensions")
    if old_ext.exists():
        rpt("从旧chrome-user-data补充扩展...")
        for item in old_ext.iterdir():
            dst = ext_dst / item.name
            if not dst.exists():
                shutil.copytree(str(item), str(dst))
                rpt(f"补充: {item.name}")

    # 4. Set permissions
    rpt("设置权限...")
    subprocess.run(["sudo", "chown", "-R", "lab-admin:lab-admin", str(PROFILE)],
                   capture_output=True)
    subprocess.run(["chmod", "-R", "700", str(PROFILE)], capture_output=True)

    # List installed extensions
    extensions = list(ext_dst.iterdir()) if ext_dst.exists() else []
    rpt(f"已安装扩展: {len(extensions)} 个")
    for e in extensions:
        rpt(f"  - {e.name}")


# ═══ Phase 2: Enable DTS ═══
def enable_dts(ws):
    rpt("\n" + "="*60)
    rpt("Phase 2: 启用DTS扩展")
    rpt("="*60)

    # Navigate to extensions page
    cdp_cmd(ws, "Page.navigate", {"url": "chrome://extensions/"})
    time.sleep(3)

    # Check if developer mode is on; if not, click the toggle
    dev_mode = cdp_eval(ws, """(function(){
        var toggle = document.querySelector('cr-toggle#devMode');
        if(!toggle) return 'no_toggle';
        return toggle.getAttribute('aria-pressed') === 'true' ? 'on' : 'off';
    })()""")
    rpt(f"开发者模式: {dev_mode}")

    if dev_mode == "off":
        rpt("开启开发者模式...")
        cdp_eval(ws, """(function(){
            var toggle = document.querySelector('cr-toggle#devMode');
            if(toggle) toggle.click();
            return 'clicked';
        })()""")
        time.sleep(2)

    # Refresh to load extensions
    rpt("刷新扩展列表...")
    cdp_cmd(ws, "Page.reload")
    time.sleep(5)

    # Check DTS status
    dts_status = cdp_eval(ws, """(function(){
        return new Promise((resolve) => {
            chrome.management.getAll(function(exts){
                for(var i=0;i<exts.length;i++){
                    if(exts[i].id.indexOf('ppgdlg')!==-1){
                        resolve(JSON.stringify({name:exts[i].name, enabled:exts[i].enabled, id:exts[i].id}));
                        return;
                    }
                }
                resolve(JSON.stringify({found:false, total:exts.length}));
            });
        });
    })()""")
    rpt(f"DTS状态: {dts_status}")

    try:
        info = json.loads(dts_status)
    except:
        info = {"found": False}

    if info.get("enabled"):
        rpt("✅ DTS已启用")
        return True
    elif info.get("found") == False:
        rpt(f"⚠️ DTS未在已安装列表中 (共{info.get('total',0)}个扩展)")
        # Try to load from filesystem
        rpt("尝试加载DTS扩展...")
        # Register via management API
        dts_path = str(PROFILE / "Default" / "Extensions" / DTS_EXT_ID)
        if Path(dts_path).exists():
            for ver in Path(dts_path).iterdir():
                if ver.is_dir():
                    rpt(f"找到DTS版本: {ver.name}")
        return False
    else:
        rpt("⚠️ DTS存在但未启用，尝试启用...")
        cdp_eval(ws, f"""chrome.management.setEnabled('{info.get("id",DTS_EXT_ID)}', true)""")
        time.sleep(2)
        return True


# ═══ Phase 3: Taobao Login ═══
def login_taobao(ws):
    rpt("\n" + "="*60)
    rpt("Phase 3: 淘宝登录")
    rpt("="*60)

    # Navigate to taobao
    cdp_cmd(ws, "Page.navigate", {"url": "https://www.taobao.com"})
    time.sleep(5)

    # Check if already logged in
    login_state = cdp_eval(ws, """(function(){
        var body = document.body?.innerText || '';
        var hasUser = !!document.querySelector('.site-nav-user .nickname');
        var hasLoginBtn = body.indexOf('请登录') !== -1;
        return JSON.stringify({loggedIn:!hasLoginBtn||hasUser, hasLoginBtn:hasLoginBtn});
    })()""")
    state = json.loads(login_state)
    rpt(f"当前登录态: {state}")

    if state.get("loggedIn"):
        rpt("✅ 已登录，跳过")
        return True

    # Click login button
    rpt("点击'请登录'...")
    clicked = cdp_eval(ws, """(function(){
        var all = document.querySelectorAll('a, button, span, div');
        for(var i=0;i<all.length;i++){
            var t = (all[i].textContent||'').trim();
            if(t==='请登录' && all[i].offsetHeight>0){all[i].click();return'clicked';}
        }
        // Try site-nav login
        var nav = document.querySelector('.site-nav-login-info-nick, #J_SiteNavLogin');
        if(nav){nav.click();return'nav_clicked';}
        return'not_found';
    })()""")
    rpt(f"  点击结果: {clicked}")
    time.sleep(3)

    # Check if login form appeared
    current_url = cdp_eval(ws, "window.location.href")
    rpt(f"  当前URL: {current_url[:100]}")

    # If on login page, fill credentials
    if "login.taobao.com" in current_url:
        rpt("  在登录页面，填写账号密码...")
        # Switch to password login (might default to QR)
        cdp_eval(ws, """(function(){
            var tabs = document.querySelectorAll('.login-tab, .password-login-tab, [data-spm="password"]');
            for(var i=0;i<tabs.length;i++){tabs[i].click();}
            var links = document.querySelectorAll('a');
            for(var i=0;i<links.length;i++){
                if((links[i].textContent||'').indexOf('密码登录')!==-1){links[i].click();return;}
            }
        })()""")
        time.sleep(2)

        # Fill username - use native setter
        cdp_eval(ws, f"""(function(){{
            var u = document.querySelector('#fm-login-id, input[name="loginfno"], input[type="text"]');
            if(!u) return 'no_user_input';
            var ns = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            ns.call(u, '{TAOBAO_USER}');
            u.dispatchEvent(new Event('input',{{bubbles:true}}));
            u.dispatchEvent(new Event('change',{{bubbles:true}}));
            return 'filled_user';
        }})()""")
        time.sleep(1)

        # Fill password
        cdp_eval(ws, f"""(function(){{
            var p = document.querySelector('#fm-login-password, input[type="password"]');
            if(!p) return 'no_pass_input';
            var ns = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            ns.call(p, '{TAOBAO_PASS}');
            p.dispatchEvent(new Event('input',{{bubbles:true}}));
            p.dispatchEvent(new Event('change',{{bubbles:true}}));
            return 'filled_pass';
        }})()""")
        time.sleep(1)

        # Click login button
        rpt("  点击登录按钮...")
        cdp_eval(ws, """(function(){
            var btn = document.querySelector('.fm-button button, .fm-btn, button[type="submit"], .login-btn');
            if(btn){btn.click();return'clicked';}
            var all = document.querySelectorAll('button');
            for(var i=0;i<all.length;i++){if((all[i].textContent||'').indexOf('登录')!==-1){all[i].click();return'clicked_alt';}}
            return'not_found';
        })()""")
        time.sleep(5)

        # Handle slider if needed
        if _handle_slider_if_present(ws):
            rpt("  滑块已通过")

    # Verify login
    time.sleep(3)
    cdp_cmd(ws, "Page.navigate", {"url": "https://www.taobao.com"})
    time.sleep(4)

    logged_in = cdp_eval(ws, """(function(){
        var body = document.body?.innerText || '';
        return JSON.stringify({ok: body.indexOf('请登录')===-1 || body.indexOf('我的淘宝')!==-1});
    })()""")
    ok = json.loads(logged_in).get("ok", False)
    rpt(f"登录验证: {'✅ 成功' if ok else '❌ 失败'}")
    return ok


def _handle_slider_if_present(ws):
    """Handle slider captcha if present."""
    for a in range(5):
        ft = cdp_cmd(ws, "Page.getFrameTree")
        tree = ft.get("result",{}).get("frameTree",{})
        h5fid = [None]
        def fh(n):
            for c in n.get("childFrames",[]):
                if "h5api.m.taobao.com" in c.get("frame",{}).get("url",""): h5fid[0]=c.get("frame",{}).get("id",""); return
                fh(c)
        fh(tree)
        if not h5fid[0]:
            rpt("  无滑块")
            return False
        try:
            iso = cdp_cmd(ws, "Page.createIsolatedWorld", {"frameId": h5fid[0]})
            ctx = iso.get("result",{}).get("executionContextId")
            if not ctx: continue
        except: continue
        for _ in range(30):
            c = cdp_eval_ctx(ws, ctx, "document.querySelectorAll('#nc_1_n1z').length")
            if c not in ("0","undefined","null","") and int(c)>0:
                v = cdp_eval_ctx(ws, ctx, """(function(){var s=document.querySelector('#nc_1_n1z');return s&&s.offsetParent!==null&&s.getBoundingClientRect().width>0;})()""")
                if v == "true":
                    cd = cdp_eval_ctx(ws, ctx, """(function(){var s=document.querySelector('#nc_1_n1z');var t=document.querySelector('#nc_1__scale_text');if(!s||!t)return JSON.stringify({found:false});var sr=s.getBoundingClientRect(),tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()""")
                    sd = json.loads(cd)
                    if sd.get("found"):
                        rpt(f"  滑块就绪, 拖拽...")
                        if _drag_slider(ws, sd):
                            time.sleep(4); return True
            time.sleep(0.2)
    return False


def _drag_slider(ws, sd):
    try:
        ipos = cdp_eval(ws, """(function(){var fs=document.querySelectorAll('iframe');for(var i=0;i<fs.length;i++){if((fs[i].src||'').indexOf('h5api')!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return'{}';})()""")
        ip = json.loads(ipos)
        sx, sy = ip.get("x",397)+sd["sx"]+OX, ip.get("y",181)+sd["sy"]+OY
        dist = sd["dist"]+random.randint(-3,5)
        disp = xd.Display()
        def mov(x,y): xt.fake_input(disp, X.MotionNotify, x=int(x), y=int(y)); disp.sync()
        ax,ay=sx-random.randint(60,120),sy+random.randint(-10,10)
        for i in range(5): p=(i+1)/5; mov(int(ax+(sx-ax)*p),int(ay+(sy-ay)*p)); time.sleep(0.015+random.random()*0.02)
        mov(sx,sy); time.sleep(0.06); xt.fake_input(disp, X.ButtonPress, detail=1); disp.sync()
        n=random.randint(320,356); dur=3.3+random.random()*0.3
        for i in range(n):
            p=i/n; e=1-(1-p)**random.uniform(1.6,2.8); x=int(sx+dist*e)
            y=sy+int(math.sin(p*math.pi*4)*random.randint(1,4))
            if p>0.85: y=sy+random.randint(-1,1); mov(x,y); time.sleep(dur/n*(0.8+random.random()*0.4))
        xt.fake_input(disp, X.ButtonRelease, detail=1); disp.sync(); disp.close()
        return True
    except: return False


# ═══ Phase 4: Warm-up & Save Cookies ═══
def warmup_and_save(ws):
    rpt("\n" + "="*60)
    rpt("Phase 4: 会话预热 + Cookies保存")
    rpt("="*60)

    # Ensure on taobao.com
    cdp_cmd(ws, "Page.navigate", {"url": "https://www.taobao.com"})
    time.sleep(4)

    # Scroll
    rpt("预热: 滚动页面...")
    for i in range(3):
        cdp_eval(ws, f"window.scrollTo(0, {random.randint(200, 500)})")
        time.sleep(random.uniform(1, 2))

    # Click product
    rpt("预热: 点击商品...")
    try:
        cdp_eval(ws, """(function(){
            var ps = document.querySelectorAll('a[href*="item.taobao.com"]');
            if(ps.length){ps[Math.floor(Math.random()*Math.min(ps.length,5))].click();return'ok';}
            return'no';
        })()""")
        time.sleep(3)
        cdp_eval(ws, "window.history.back()")
        time.sleep(2)
    except: pass

    # Random mouse
    rpt("预热: 随机鼠标移动...")
    disp = xd.Display()
    for i in range(5):
        disp.warp_pointer(random.randint(100, 800), random.randint(100, 600)); disp.sync()
        time.sleep(0.2)
    disp.close()

    # Save cookies via CDP Network.getCookies
    rpt("保存Cookies...")
    cookies_resp = cdp_cmd(ws, "Network.getCookies", {
        "urls": ["https://www.taobao.com", "https://s.taobao.com", "https://i.taobao.com",
                  "https://login.taobao.com", "https://h5api.m.taobao.com"]
    })
    cookies = cookies_resp.get("result", {}).get("cookies", [])
    rpt(f"  获取到 {len(cookies)} 个cookies")

    cookie_path = Path("/home/lab-admin/price-monitor/data/taobao_cookies.pkl")
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cookie_path, 'wb') as f:
        pickle.dump(cookies, f)
    rpt(f"  Cookies已保存: {cookie_path}")

    return cookies


# ═══ Phase 5: Verify ═══
def verify_all(ws):
    rpt("\n" + "="*60)
    rpt("Phase 5: 验证初始化结果")
    rpt("="*60)

    # 1. DTS
    rpt("验证1: DTS扩展...")
    dts_ok = cdp_eval(ws, """(function(){
        return new Promise(r=>{chrome.management.getAll(function(e){
            for(var i=0;i<e.length;i++){if(e[i].id.indexOf('ppgdlg')!==-1){r(JSON.stringify({ok:true,n:e[i].name}));return;}}
            r(JSON.stringify({ok:false,total:e.length}));
        });});
    })()""")
    dts_info = json.loads(dts_ok)
    rpt(f"  DTS: {'✅ ' + dts_info.get('n','') if dts_info.get('ok') else '❌ 未安装 (共'+str(dts_info.get('total',0))+'个扩展)'}")

    # 2. Taobao login
    rpt("验证2: 淘宝登录...")
    cdp_cmd(ws, "Page.navigate", {"url": "https://www.taobao.com"})
    time.sleep(4)
    login_ok = cdp_eval(ws, """(function(){
        var b=document.body?.innerText||'';
        return JSON.stringify({ok:b.indexOf('请登录')===-1||b.indexOf('我的淘宝')!==-1});
    })()""")
    rpt(f"  登录: {'✅' if json.loads(login_ok).get('ok') else '❌'}")

    # 3. Cookies
    cookie_path = Path("/home/lab-admin/price-monitor/data/taobao_cookies.pkl")
    rpt(f"验证3: Cookies: {'✅ 已保存' if cookie_path.exists() else '❌ 未找到'}")
    if cookie_path.exists():
        with open(cookie_path, 'rb') as f:
            c = pickle.load(f)
        rpt(f"  包含 {len(c)} 个cookies")

    # 4. Search test
    rpt("验证4: 搜索测试...")
    cdp_cmd(ws, "Page.navigate", {"url": "https://s.taobao.com/search?q=%E8%92%99%E7%89%9B%E4%B8%80%E7%B1%B3%E5%85%AB%E5%85%AB%E5%A5%B6%E7%B2%89"})
    time.sleep(5)
    st = cdp_eval(ws, """JSON.stringify({t:document.title,l:(document.body?.innerText||'').length,links:document.querySelectorAll('a[href*="item.taobao.com"]').length,bones:document.querySelectorAll('[class*="bone"]').length})""")
    st = json.loads(st)
    rpt(f"  搜索页: {st.get('t','')[:40]}, len={st.get('l')}, links={st.get('pl','?')}, bones={st.get('b')}")
    search_ok = st.get('l',0) > 500 and st.get('b',0) < 10
    rpt(f"  搜索: {'✅ 正常' if search_ok else '❌ 骨架/空'}")

    return dts_info.get("ok", False), json.loads(login_ok).get("ok", False), search_ok


# ═══ Main ═══
def main():
    rpt("="*60)
    rpt("Chrome Profile 一键环境初始化")
    rpt(f"开始: {datetime.now().isoformat()}")
    rpt("="*60)

    # Phase 1
    setup_profile()

    # Phase 2
    ws = launch_chrome()
    if not ws:
        rpt("❌ Chrome启动失败"); return 1
    dts_enabled = enable_dts(ws)

    # Phase 3
    login_ok = login_taobao(ws)

    # Phase 4
    cookies = warmup_and_save(ws)

    # Phase 5
    dts_v, login_v, search_v = verify_all(ws)

    # Final report
    rpt("\n" + "="*60)
    rpt("初始化结果报告")
    rpt("="*60)
    rpt(f"DTS扩展: {'✅' if dts_v else '❌'}")
    rpt(f"淘宝登录: {'✅' if login_v else '❌'}")
    rpt(f"搜索测试: {'✅' if search_v else '❌'}")
    rpt(f"Cookies: {'✅' if cookies else '❌'} ({len(cookies) if cookies else 0}个)")
    rpt(f"\n总评: {'✅ 环境就绪' if (dts_v and login_v and search_v) else '❌ 存在异常'}")

    ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
