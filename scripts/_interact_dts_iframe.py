import json, urllib.request, websocket, time

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())

# Find DTS iframe target
dts_iframe = next((t for t in tabs if t["type"] == "iframe" and "diantoushi" in (t.get("url", "") or "").lower()), None)
print(f"DTS iframe target: {dts_iframe.get('url','')[:80] if dts_iframe else 'NOT FOUND'}")

if dts_iframe:
    ws = websocket.create_connection(dts_iframe["webSocketDebuggerUrl"], timeout=10)
    
    # Check current state
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify({url: window.location.href.substring(0,100), bodyLen: (document.body?document.body.innerText.length:0), title: document.title.substring(0,60)})",
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    print(f"1. Iframe state: {r['result']['result']['value']}")
    
    # Try to enumerate Runtime contexts
    ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
    ws.recv()
    time.sleep(1)
    
    # Navigate the iframe to market analysis
    ws.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {
        "url": "https://assets.diantoushi.com/page/market-analysis.html"
    }}))
    r3 = json.loads(ws.recv())
    print(f"2. Navigate: {r3}")
    time.sleep(5)
    
    # Check state after navigation
    ws.send(json.dumps({"id": 4, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify({url: window.location.href.substring(0,100), bodyLen: (document.body?document.body.innerText.length:0)})",
        "returnByValue": True
    }}))
    r4 = json.loads(ws.recv())
    print(f"3. After nav: {r4['result']['result']['value']}")
    
    ws.close()
