"""探索baxia captcha内部JS对象，尝试直接触发通过回调"""
import json, urllib.request, websocket, time, base64, os

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

CDP = "http://127.0.0.1:9223/json"
targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())
ws = None
for t in targets:
    if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
        ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=15)
        break
ws.settimeout(10)
mid = [0]
def cmd(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    for _ in range(80):
        r = json.loads(ws.recv())
        if r.get("id") == mid[0]:
            return r
    return {}
for d in ("Runtime", "Page", "DOM"):
    cmd(f"{d}.enable")

# Get punish iframe contextId
r = cmd("Page.getFrameTree")
ft = r.get("result", {}).get("frameTree", {})
punish_fid = None
def find_punish(node):
    global punish_fid
    f = node.get("frame", {})
    if "h5api.m.taobao.com" in f.get("url", "") and "punish" in f.get("url", ""):
        punish_fid = f.get("id", "")
        return True
    for c in node.get("childFrames", []):
        if find_punish(c):
            return True
    return False
find_punish(ft)
r = cmd("Page.createIsolatedWorld", {"frameId": punish_fid, "grantUniveralAccess": False})
ctx_id = r.get("result", {}).get("executionContextId")
print(f"ctx_id: {ctx_id}")

def iframe_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "contextId": ctx_id, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except:
            return v
    return v

def main_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except:
            return v
    return v

# === 1. Explore global objects in the iframe ===
print("\n=== [1] iframe全局对象 ===")

# Check window properties
r = iframe_eval("""JSON.stringify(Object.keys(window).filter(function(k){
    return k.indexOf('nc')!==-1 || k.indexOf('captcha')!==-1 || k.indexOf('alibaba')!==-1 || k.indexOf('baxia')!==-1 || 
           k.indexOf('NoCaptcha')!==-1 || k.indexOf('verify')!==-1 || k.indexOf('AWSC')!==-1 || k.indexOf('_nc')!==-1
}))""")
print(f"nc相关window属性: {r}")

# Check document scripts
r = iframe_eval("""JSON.stringify(Array.from(document.querySelectorAll('script')).map(function(s){
    return (s.src||s.textContent||'').slice(0, 120)
}).filter(function(t){return t}))""")
print(f"scripts: {json.dumps(r, ensure_ascii=False)[:500]}")

# Check inline script content that might have NC initialization
r = iframe_eval("""(function(){
    var scripts = document.querySelectorAll('script');
    var ncInit = '';
    for (var i=0; i<scripts.length; i++) {
        var txt = scripts[i].textContent || '';
        if (txt.indexOf('nc_') !== -1 && txt.indexOf('new') !== -1) {
            ncInit = txt.slice(0, 600);
            break;
        }
    }
    return ncInit || 'NOT_FOUND';
})()""")
print(f"\nnc初始化脚本: {r[:500] if isinstance(r, str) else r}")

# Check data attributes on #nc_1_wrapper
r = iframe_eval("""(function(){
    var w = document.getElementById('nc_1_wrapper');
    if (!w) return 'NO_WRAPPER';
    var attrs = {};
    for (var i=0; i<w.attributes.length; i++) {
        attrs[w.attributes[i].name] = w.attributes[i].value;
    }
    return JSON.stringify(attrs);
})()""")
print(f"\nnc_1_wrapper attrs: {r}")

# Check for hidden inputs with tokens
r = iframe_eval("""(function(){
    var inputs = document.querySelectorAll('input[type=hidden]');
    var vals = [];
    for (var i=0; i<inputs.length; i++) {
        vals.push({id: inputs[i].id, name: inputs[i].name, value: (inputs[i].value||'').slice(0, 200)});
    }
    return JSON.stringify(vals);
})()""")
print(f"\nhidden inputs: {r}")

# Check sessionId
r = iframe_eval("""(function(){
    var si = document.getElementById('nc-session-id');
    var sig = document.getElementById('nc-sig');
    var sess = si ? si.value : 'NONE';
    var sign = sig ? sig.value : 'NONE';
    return JSON.stringify({sessionId: sess, sig: sign});
})()""")
print(f"\nsession: {r}")

# === 2. Try to call AWSC (Alibaba Web Security) ===
print("\n=== [2] AWSC对象 ===")
r = iframe_eval("""JSON.stringify(typeof AWSC)""")
print(f"typeof AWSC: {r}")

r = iframe_eval("""(function(){
    try {
        if (typeof AWSC !== 'undefined' && AWSC) {
            var keys = Object.keys(AWSC);
            return JSON.stringify({type: typeof AWSC, keys: keys.slice(0, 30), isFunc: typeof AWSC === 'function'});
        }
        return 'UNDEFINED';
    } catch(e) {
        return 'ERROR: ' + e.message;
    }
})()""")
print(f"AWSC detail: {r}")

# === 3. Try to use NoCaptcha directly ===
print("\n=== [3] NoCaptcha对象 ===")
r = iframe_eval("""(function(){
    try {
        var NC = window.NoCaptcha || window._NoCaptcha || window.__nc || window._nc;
        return JSON.stringify({found: !!NC, type: typeof NC});
    } catch(e) {
        return 'ERROR: ' + e.message;
    }
})()""")
print(f"NoCaptcha: {r}")

# === 4. Check if nc object has get_instance method ===
r = iframe_eval("""(function(){
    try {
        // Try to find the NC instance
        if (typeof nc !== 'undefined') {
            return 'nc exists: ' + Object.keys(nc).slice(0, 20).join(',');
        }
        // Check nocaptcha global
        if (typeof NoCaptcha !== 'undefined') {
            if (NoCaptcha.getInstances) {
                var instances = NoCaptcha.getInstances();
                return JSON.stringify({instances: instances ? instances.length : 0});
            }
            return JSON.stringify(Object.keys(NoCaptcha).slice(0, 20));
        }
        return 'NOT_FOUND';
    } catch(e) {
        return 'ERROR: ' + e.message;
    }
})()""")
print(f"nc instance: {r}")

# === 5. Main page: check if we can inject callback to parent ===
print("\n=== [5] 检查主页面的验证状态 ===")
# On the main page, look for the captcha iframe's parent container
r = main_eval("""(function(){
    var fs = document.querySelectorAll('iframe');
    var result = 'NO_PUNISH';
    for (var i=0; i<fs.length; i++) {
        if ((fs[i].src||'').indexOf('punish') !== -1) {
            result = 'punish at index ' + i;
            var p = fs[i].parentElement;
            result += ', parent: ' + (p?p.tagName+'.'+p.className:'none');
            result += ', parentId: ' + (p?p.id:'none');
        }
    }
    return result;
})()""")
print(f"主页面: {r}")

# === 6. Get all cookies ===
print("\n=== [6] Cookies ===")
r = cmd("Page.getCookies")
cookies = r.get("result", {}).get("cookies", [])
nc_cookies = [c for c in cookies if "nc" in c.get("name", "").lower() or "sig" in c.get("name", "").lower() or "token" in c.get("name", "").lower() or "session" in c.get("name", "").lower()]
for c in nc_cookies:
    print(f"  {c['domain']} {c['name']}={c['value'][:60]}")

# === 7. Try to observe network requests for the captcha verification ===
print("\n=== [7] Network monitoring ===")
r = cmd("Network.enable", {"maxTotalBufferSize": 10000000})

ws.close()
print("\n[DONE]")
