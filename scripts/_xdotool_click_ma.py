import json, urllib.request, websocket, time, subprocess

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())

main_tab = next((t for t in tabs if t["type"] == "page" and "taobao.com" in t.get("url", "")), None)
if main_tab:
    ws = websocket.create_connection(main_tab["webSocketDebuggerUrl"], timeout=10)

    # Get market analysis button viewport position
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var el = document.querySelector('.itemToolsBox');
            if(!el) return JSON.stringify({found:false, reason:'no_box'});
            var children = el.querySelectorAll('div, span, a');
            for(var i=0;i<children.length;i++){
                if((children[i].textContent||'').trim()==='市场分析'){
                    var cr = children[i].getBoundingClientRect();
                    var fl = (window.outerWidth - window.innerWidth) / 2;
                    var to = window.outerHeight - window.innerHeight - fl;
                    return JSON.stringify({
                        found: true,
                        vpX: Math.round(cr.x + cr.width/2),
                        vpY: Math.round(cr.y + cr.height/2),
                        screenX: Math.round(cr.x + cr.width/2 + (window.screenLeft || 0) + fl),
                        screenY: Math.round(cr.y + cr.height/2 + (window.screenTop || 0) + to),
                        inView: cr.y >= 0 && cr.y < window.innerHeight
                    });
                }
            }
            return JSON.stringify({found:false});
        })()
        """,
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    pos = json.loads(r["result"]["result"]["value"])
    print(f"Market analysis position: {pos}")
    ws.close()

    if pos.get("found"):
        env = {"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"}
        
        # First make sure extension popup is open - click extension icon area
        # Actually, let's just click the market analysis
        subprocess.run(["xdotool", "mousemove", str(pos["screenX"]), str(pos["screenY"])], env=env)
        time.sleep(0.5)
        subprocess.run(["xdotool", "click", "1"], env=env)
        print(f"xdotool clicked at ({pos['screenX']}, {pos['screenY']})")
        time.sleep(5)
        
        # Check results
        resp2 = urllib.request.urlopen("http://127.0.0.1:9223/json")
        tabs2 = json.loads(resp2.read())
        pages2 = [t for t in tabs2 if t["type"] == "page"]
        print(f"\nPages after xdotool click: {len(pages2)}")
        for p in pages2:
            url = (p.get("url", "") or "")[:100]
            print(f"  {p.get('title','')[:60]} | {url}")

        # Check new targets
        for t in tabs2:
            if t["type"] not in ("page", "iframe"):
                url = (t.get("url", "") or "")[:80]
                if url:
                    print(f"  [{t['type']}] {url}")
