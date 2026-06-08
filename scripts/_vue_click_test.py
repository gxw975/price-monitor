import json, urllib.request, websocket, time, subprocess

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())

main_page = next((t for t in tabs if t["type"] == "page" and "taobao.com" in t.get("url","")), None)

if main_page:
    ws = websocket.create_connection(main_page["webSocketDebuggerUrl"], timeout=10)
    
    # First: make sure extension popup is open by clicking the extension icon
    # Use xdotool to click the extension icon area
    
    # Get extension icon position (near Chrome toolbar)
    # Then click itemToolsBox .item-value
    
    # Get position
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            // Try to find and click via the Vue instance
            var el = document.querySelector('.itemToolsBox');
            if(!el || !el.__vue__) return JSON.stringify({found:false, reason:'no_vue'});
            
            // Get the Vue component instance
            var vm = el.__vue__;
            // Try to find the click method
            var methods = [];
            if(vm.$options && vm.$options.methods) {
                methods = Object.keys(vm.$options.methods);
            }
            // Check $vnode
            var props = vm.$options && vm.$options.propsData ? Object.keys(vm.$options.propsData) : [];
            
            return JSON.stringify({
                found: true,
                hasVue: true,
                methods: methods.slice(0, 30),
                props: props.slice(0, 10),
                componentName: (vm.$options.name || 'unnamed'),
                elTag: vm.$el.tagName
            });
        })()
        """,
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    print(f"Vue info: {r['result']['result']['value']}")
    
    # Try dispatching a proper click sequence on the item-value
    # with mousedown + mouseup (more realistic than single click)
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var el = document.querySelector('.itemToolsBox .item-value');
            if(!el) return 'no_el';
            var cr = el.getBoundingClientRect();
            var cx = cr.x + cr.width/2;
            var cy = cr.y + cr.height/2;
            return JSON.stringify({x:Math.round(cx), y:Math.round(cy)});
        })()
        """,
        "returnByValue": True
    }}))
    r2 = json.loads(ws.recv())
    coords = json.loads(r2['result']['result']['value'])
    print(f"Coords: {coords}")
    
    # Use Input.dispatchMouseEvent with proper sequence
    # Move first
    ws.send(json.dumps({"id": 10, "method": "Input.dispatchMouseEvent", "params": {
        "type": "mouseMoved", "x": coords['x'], "y": coords['y']
    }}))
    r3 = json.loads(ws.recv())
    
    time.sleep(0.3)
    
    # mousePressed
    ws.send(json.dumps({"id": 11, "method": "Input.dispatchMouseEvent", "params": {
        "type": "mousePressed", "x": coords['x'], "y": coords['y'],
        "button": "left", "clickCount": 1
    }}))
    r4 = json.loads(ws.recv())
    time.sleep(0.1)
    
    # mouseReleased  
    ws.send(json.dumps({"id": 12, "method": "Input.dispatchMouseEvent", "params": {
        "type": "mouseReleased", "x": coords['x'], "y": coords['y'],
        "button": "left", "clickCount": 1
    }}))
    r5 = json.loads(ws.recv())
    
    time.sleep(4)
    
    # Check results
    resp2 = urllib.request.urlopen("http://127.0.0.1:9223/json")
    tabs2 = json.loads(resp2.read())
    pages2 = [t for t in tabs2 if t["type"] == "page"]
    print(f"\nPages after: {len(pages2)}")
    for p in pages2:
        print(f"  {p.get('title','')[:60]}")
    
    # Check body
    ws.send(json.dumps({"id": 20, "method": "Runtime.evaluate", "params": {
        "expression": "JSON.stringify({bodyLen:(document.body?document.body.innerText.length:0), hasSort:(document.body?document.body.innerText||'').indexOf('综合排序'), hasExport:(document.body?document.body.innerText||'').indexOf('导出表格')})",
        "returnByValue": True
    }}))
    r6 = json.loads(ws.recv())
    print(f"Body: {r6['result']['result']['value']}")
    
    ws.close()
