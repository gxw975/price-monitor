import json, urllib.request, websocket, time

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())
pages = [t for t in tabs if t["type"] == "page"]

print(f"Pages: {len(pages)}")
for p in pages:
    print(f"  {p.get('title','')[:60]}")

if pages:
    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=10)
    
    # Get page title, URL, body size
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify({url:window.location.href.substring(0,60), title:document.title, bodyLen:(document.body?document.body.innerText:'')})",
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    print(f"\nPage info: {r['result']['result']['value']}")
    
    # Check for DTS elements
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var items = [];
            // Check DTS panel container
            var panel = document.querySelector('[class*="dts-panel"], [class*="DtsPanel"], #dts-app, [class*="market-analysis"]');
            if(panel) items.push('DTS panel found: ' + panel.className.substring(0,40));
            
            // Check itemToolsBox children
            var box = document.querySelector('.itemToolsBox');
            if(box) {
                var children = box.querySelectorAll('div,span,a');
                var texts = [];
                for(var i=0;i<Math.min(children.length,20);i++){
                    var t=(children[i].textContent||'').trim();
                    if(t) texts.push(t.substring(0,20));
                }
                items.push('itemToolsBox children: ' + JSON.stringify(texts));
            }
            
            // Check iframes
            var iframes = document.querySelectorAll('iframe');
            var iframeUrls = [];
            for(var i=0;i<iframes.length;i++){
                iframeUrls.push((iframes[i].src||'').substring(0,40));
            }
            items.push('Iframes: ' + JSON.stringify(iframeUrls));
            
            return JSON.stringify(items);
        })()
        """,
        "returnByValue": True
    }}))
    r2 = json.loads(ws.recv())
    print(f"\nDTS elements:")
    for item in json.loads(r2['result']['result']['value']):
        print(f"  {item}")
    
    ws.close()
