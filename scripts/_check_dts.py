import json, urllib.request, websocket, time

resp = urllib.request.urlopen("http://127.0.0.1:9223/json")
tabs = json.loads(resp.read())
pages = [t for t in tabs if t["type"] == "page"]
print(f"Pages: {len(pages)}")

dts_items = [t for t in tabs if "ppgdlg" in (t.get("url", "") or "")]
print(f"DTS SW: {len(dts_items)}")
for item in dts_items:
    print(f"  type={item['type']} url={(item.get('url','') or '')[:80]}")

if pages:
    ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=10)
    ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": "https://www.taobao.com/"}}))
    ws.recv()
    time.sleep(10)

    # Check login
    ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var nick = document.querySelector(".site-nav-login-info-nick");
            return nick ? ("logged_in:" + nick.textContent.trim()) : "no_nick";
        })()
        """,
        "returnByValue": True
    }}))
    r = json.loads(ws.recv())
    print(f"Login: {r['result']['result']['value']}")

    # Check "确定" dialog
    ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {
        "expression": """
        (function(){
            var all = document.querySelectorAll("*");
            var found = [];
            for (var i = 0; i < all.length; i++) {
                if ((all[i].textContent || "").trim() === "确定" && all[i].offsetHeight > 0) {
                    found.push({tag: all[i].tagName, cls: (all[i].className || "").substring(0, 30)});
                }
                if (found.length > 5) break;
            }
            return JSON.stringify({count: found.length, items: found});
        })()
        """,
        "returnByValue": True
    }}))
    r2 = json.loads(ws.recv())
    print(f"确定 dialogs: {r2['result']['result']['value']}")

    ws.close()
