import json, urllib.request, websocket, time

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())

main_tab = next((t for t in tabs if t["type"] == "page" and "taobao.com" in t.get("url", "")), None)
if main_tab:
    ws = websocket.create_connection(main_tab["webSocketDebuggerUrl"], timeout=10)

    # Click the market analysis button via JS dispatchEvent (simulate real click)
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var el = document.querySelector('.itemToolsBox');
            if(!el) return 'no_itemToolsBox';
            var children = el.querySelectorAll('div, span, a');
            for(var i=0;i<children.length;i++){
                if((children[i].textContent||'').trim()==='市场分析'){
                    var evt = new MouseEvent('click', {bubbles:true, cancelable:true});
                    children[i].dispatchEvent(evt);
                    return 'dispatched click on: '+children[i].tagName;
                }
            }
            return 'not found';
        })()
        """,
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    print(f"Click result: {r['result']['result']['value']}")
    
    time.sleep(5)

    # Check for new tabs/pages
    resp2 = urllib.request.urlopen("http://127.0.0.1:9223/json")
    tabs2 = json.loads(resp2.read())
    pages2 = [t for t in tabs2 if t["type"] == "page"]
    print(f"\nPages after click: {len(pages2)}")
    for p in pages2:
        print(f"  [{p['type']}] {p.get('title','')[:50]} | {(p.get('url','') or '')[:80]}")
    
    iframes2 = [t for t in tabs2 if t["type"] == "iframe"]
    print(f"\nIframes after click: {len(iframes2)}")
    for f in iframes2:
        print(f"  {(f.get('url','') or '')[:100]}")
    
    # Check body length after
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify({bodyLen:(document.body?document.body.innerText.length:0), bodyStart: (document.body?document.body.innerText||'':'').substring(0,200)})",
        "returnByValue": True
    }}))
    r2 = json.loads(ws.recv())
    print(f"\nBody after: {r2['result']['result']['value'][:300]}")
    
    ws.close()
