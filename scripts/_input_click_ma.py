import json, urllib.request, websocket, time

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())

# Check all iframes
main_page = next((t for t in tabs if t["type"] == "page" and "taobao.com" in t.get("url", "")), None)

if main_page:
    ws = websocket.create_connection(main_page["webSocketDebuggerUrl"], timeout=10)
    
    # Get iframe details
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var iframes = document.querySelectorAll('iframe');
            var result = [];
            for(var i=0;i<iframes.length;i++){
                var cr = iframes[i].getBoundingClientRect();
                result.push({
                    index: i,
                    src: (iframes[i].src||'').substring(0,80),
                    x: Math.round(cr.x), y: Math.round(cr.y),
                    w: Math.round(cr.width), h: Math.round(cr.height),
                    visible: cr.height > 0 && cr.width > 0
                });
            }
            return JSON.stringify(result);
        })()
        """,
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    print(f"Iframes: {r['result']['result']['value']}")
    
    # Try clicking the item-value directly with xdotool via the element's screen coords
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var el = document.querySelector('.itemToolsBox .item-value');
            if(!el) return JSON.stringify({found:false});
            var cr = el.getBoundingClientRect();
            var fl = (window.outerWidth - window.innerWidth) / 2;
            var to = window.outerHeight - window.innerHeight - fl;
            return JSON.stringify({
                found: true,
                tag: el.tagName,
                text: el.textContent.trim(),
                vpX: Math.round(cr.x + cr.width/2),
                vpY: Math.round(cr.y + cr.height/2),
                screenX: Math.round(cr.x + cr.width/2 + (window.screenLeft || 0) + fl),
                screenY: Math.round(cr.y + cr.height/2 + (window.screenTop || 0) + to),
                w: Math.round(cr.width), h: Math.round(cr.height)
            });
        })()
        """,
        "returnByValue": True
    }}))
    r2 = json.loads(ws.recv())
    print(f"\nItem-value: {r2['result']['result']['value']}")
    
    # Try Chrome devtools protocol Input.dispatchMouseEvent to do a proper click
    coords = json.loads(r2['result']['result']['value'])
    if coords.get('found'):
        print(f"\nUsing Input.dispatchMouseEvent at ({coords['vpX']}, {coords['vpY']})")
        
        # Mouse pressed
        ws.send(json.dumps({"id": 10, "method": "Input.dispatchMouseEvent", "params": {
            "type": "mousePressed",
            "x": coords['vpX'],
            "y": coords['vpY'],
            "button": "left",
            "clickCount": 1
        }}))
        ws.recv()
        time.sleep(0.2)
        
        # Mouse released
        ws.send(json.dumps({"id": 11, "method": "Input.dispatchMouseEvent", "params": {
            "type": "mouseReleased",
            "x": coords['vpX'],
            "y": coords['vpY'],
            "button": "left",
            "clickCount": 1
        }}))
        ws.recv()
        
        time.sleep(3)
        
        # Check if anything changed
        resp2 = urllib.request.urlopen("http://127.0.0.1:9223/json")
        tabs2 = json.loads(resp2.read())
        pages2 = [t for t in tabs2 if t["type"] == "page"]
        print(f"\nPages after Input click: {len(pages2)}")
        for p in pages2:
            print(f"  {p.get('title','')[:60]}")
        
        # Check iframes
        iframes = [t for t in tabs2 if t["type"] == "iframe"]
        print(f"Iframes after: {len(iframes)}")
        for f in iframes:
            print(f"  {(f.get('url','') or '')[:100]}")
        
        # Check body changes
        ws.send(json.dumps({"id": 20, "method": "Runtime.evaluate", "params": {
            "expression": "JSON.stringify({bodyLen:(document.body?document.body.innerText.length:0), hasSort:(document.body?document.body.innerText:'').indexOf('综合排序')})",
            "returnByValue": True
        }}))
        r3 = json.loads(ws.recv())
        print(f"Body after: {r3['result']['result']['value']}")
    
    ws.close()
