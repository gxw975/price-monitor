import json, urllib.request, websocket, time

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())

# Find DTS iframe target
dts_iframe = next((t for t in tabs if t["type"] == "iframe" and "diantoushi" in (t.get("url","") or "").lower()), None)
main_page = next((t for t in tabs if t["type"] == "page" and "taobao.com" in t.get("url","")), None)

print(f"DTS iframe: {dts_iframe.get('url','?') if dts_iframe else 'NOT FOUND'}")

if dts_iframe:
    ws = websocket.create_connection(dts_iframe["webSocketDebuggerUrl"], timeout=10)
    
    # Enable Runtime for iframe
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    ws.recv()
    time.sleep(0.5)
    
    # Check iframe content
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify({url:window.location.href, bodyHTML:(document.body?document.body.innerHTML:'')})",
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    result = r.get("result", {}).get("result", {}).get("value", "no_result")
    if result and len(str(result)) > 500:
        result = str(result)[:500] + "..."
    print(f"Iframe content: {result}")
    
    # Also check document state
    ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify({readyState:document.readyState, bodyLen:(document.body?document.body.outerHTML.length:0), scripts:document.querySelectorAll('script').length})",
        "returnByValue": True
    }}))
    r2 = json.loads(ws.recv())
    print(f"Iframe state: {r2.get('result',{}).get('result',{}).get('value','?')}")
    
    ws.close()

# Also check if main page itemToolsBox has event listeners
if main_page:
    ws2 = websocket.create_connection(main_page["webSocketDebuggerUrl"], timeout=10)
    
    # Get event listeners on item-value
    ws2.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var el = document.querySelector('.itemToolsBox .item-value');
            if(!el) return 'no_el';
            // Check for __vue__ instance
            var vue = el.__vue__;
            var vueParent = el.__vue_parent__;
            var hasClick = false;
            // Check onclick attribute
            if(el.onclick) hasClick = true;
            return JSON.stringify({
                hasVue: !!vue || !!vueParent,
                hasOnClick: hasClick,
                dataset: JSON.stringify(el.dataset || {}),
                attributes: Array.from(el.attributes).map(a=>a.name).join(','),
                parentAttrs: Array.from(el.parentElement.attributes).map(a=>a.name).join(',')
            });
        })()
        """,
        "returnByValue": True
    }}))
    r3 = json.loads(ws2.recv())
    print(f"\nitem-value event info: {r3['result']['result']['value']}")
    
    # Check parent (itemToolsBox) for Vue
    ws2.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var el = document.querySelector('.itemToolsBox');
            if(!el) return 'no_el';
            var keys = Object.keys(el).filter(k=>k.startsWith('__vue') || k.startsWith('_vue'));
            return JSON.stringify({keys:keys, hasVue:keys.length>0});
        })()
        """,
        "returnByValue": True
    }}))
    r4 = json.loads(ws2.recv())
    print(f"itemToolsBox Vue: {r4['result']['result']['value']}")
    
    ws2.close()
