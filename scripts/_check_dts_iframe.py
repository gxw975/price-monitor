import json, urllib.request, websocket, time

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())

print(f"All targets: {len(tabs)}")
for t in tabs:
    url = (t.get("url", "") or "")[:100]
    ttype = t.get("type", "")
    if "diantoushi" in url.lower() or ttype == "iframe" or "page" in ttype:
        print(f"  [{ttype}] {url}")

# Find the main page tab
main_tab = next((t for t in tabs if t["type"] == "page" and "taobao.com" in t.get("url", "")), None)
if main_tab:
    ws = websocket.create_connection(main_tab["webSocketDebuggerUrl"], timeout=10)
    
    # Check the DTS iframe content
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var iframes = document.querySelectorAll('iframe');
            for(var i=0;i<iframes.length;i++){
                var src = iframes[i].src || '';
                if(src.indexOf('diantoushi') !== -1){
                    var cr = iframes[i].getBoundingClientRect();
                    return JSON.stringify({
                        found: true,
                        index: i,
                        src: src.substring(0,80),
                        x: Math.round(cr.x), y: Math.round(cr.y),
                        w: Math.round(cr.width), h: Math.round(cr.height),
                        visible: cr.height > 0
                    });
                }
            }
            return JSON.stringify({found: false});
        })()
        """,
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    iframe_info = json.loads(r["result"]["result"]["value"])
    print(f"\nDTS iframe: {iframe_info}")
    
    # Find the iframe's CDP target
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var iframes = document.querySelectorAll('iframe');
            for(var i=0;i<iframes.length;i++){
                var src = iframes[i].src || '';
                if(src.indexOf('diantoushi') !== -1){
                    return JSON.stringify({
                        hasContent: !!iframes[i].contentDocument,
                        contentLen: iframes[i].contentDocument ? iframes[i].contentDocument.body.innerText.length : 0,
                        contentSrc: src.substring(0,80)
                    });
                }
            }
            return JSON.stringify({found: false});
        })()
        """,
        "returnByValue": True
    }}))
    r2 = json.loads(ws.recv())
    print(f"DTS iframe content: {r2['result']['result']['value']}")
    
    ws.close()
