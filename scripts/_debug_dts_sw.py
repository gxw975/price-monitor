import json, urllib.request, websocket, time

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())

# Find DTS service worker
dts_sw = next((t for t in tabs if "ppgdlg" in (t.get("url", "") or "") and t["type"] == "service_worker"), None)
main_page = next((t for t in tabs if t["type"] == "page" and "taobao.com" in t.get("url", "")), None)

if dts_sw:
    print(f"DTS SW URL: {dts_sw.get('url','')[:80]}")
    print(f"DTS SW WS: {dts_sw.get('webSocketDebuggerUrl','')[:60]}")
    
    sw_ws = websocket.create_connection(dts_sw["webSocketDebuggerUrl"], timeout=10)
    
    # Enable Runtime
    sw_ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    sw_ws.recv()
    
    # Check what the DTS extension knows
    sw_ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": "self.location.href",
        "returnByValue": True
    }}))
    r = json.loads(sw_ws.recv())
    print(f"SW location: {r.get('result',{}).get('result',{}).get('value','error')}")
    
    # Check global variables
    sw_ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify(Object.keys(self).filter(k => !k.startsWith('_')).slice(0,20))",
        "returnByValue": True
    }}))
    r2 = json.loads(sw_ws.recv())
    print(f"SW globals: {r2.get('result',{}).get('result',{}).get('value','error')}")
    
    sw_ws.close()

# Check main page for DTS panel 
if main_page:
    page_ws = websocket.create_connection(main_page["webSocketDebuggerUrl"], timeout=10)
    
    # Check body for DTS content
    page_ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var body = document.body ? document.body.innerText : '';
            var idx1 = body.indexOf('开始分析');
            var idx2 = body.indexOf('综合排序');
            var idx3 = body.indexOf('导出表格');
            var idx4 = body.indexOf('市场分析');
            return JSON.stringify({
                startAnal: idx1, sort: idx2, export: idx3, market: idx4,
                bodyLen: body.length,
                dtsIframe: document.querySelectorAll('iframe').length,
                itemToolsBox: !!document.querySelector('.itemToolsBox')
            });
        })()
        """,
        "returnByValue": True
    }}))
    r3 = json.loads(page_ws.recv())
    print(f"\nPage state: {r3['result']['result']['value']}")
    
    # Check itemToolsBox HTML  
    page_ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var el = document.querySelector('.itemToolsBox');
            if(!el) return 'no_itemToolsBox';
            return el.outerHTML.substring(0, 500);
        })()
        """,
        "returnByValue": True
    }}))
    r4 = json.loads(page_ws.recv())
    print(f"\nitemToolsBox HTML: {r4['result']['result']['value'][:300]}")
    
    page_ws.close()
