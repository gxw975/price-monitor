import json
import time
import websocket

CDP_URL = "http://127.0.0.1:9222"

import urllib.request
tabs = json.loads(urllib.request.urlopen(f"{CDP_URL}/json").read())
ws_url = None
for tab in tabs:
    if "taobao.com" in tab.get("url", ""):
        ws_url = tab.get("webSocketDebuggerUrl")
        break

if not ws_url:
    print("no taobao tab found")
    exit(1)

ws = websocket.create_connection(ws_url)
msg_id = 1

def send_cdp(method, params=None):
    global msg_id
    msg = {"id": msg_id, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    msg_id += 1
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id - 1:
            return resp

send_cdp("Runtime.enable")
send_cdp("Page.enable")

eval_resp = send_cdp("Runtime.evaluate", {
    "expression": """
    (function(){
        var iframe = document.querySelector('iframe[name=baxia-dialog-content]');
        if(!iframe) return JSON.stringify({error:'no iframe'});
        var rect = iframe.getBoundingClientRect();
        return JSON.stringify({iframe:{x:rect.x,y:rect.y,w:rect.width,h:rect.height}});
    })()
""",
    "returnByValue": True
})
iframe_info = json.loads(eval_resp.get("result", {}).get("result", {}).get("value", "{}"))
print(f"iframe info: {iframe_info}")

eval_resp2 = send_cdp("Runtime.evaluate", {
    "expression": """
    (function(){
        var iframe = document.querySelector('iframe[name=baxia-dialog-content]');
        if(!iframe) return 'no iframe';
        var doc = iframe.contentDocument;
        if(!doc) return 'cross-origin';
        return 'accessible';
    })()
""",
    "returnByValue": True
})
access = eval_resp2.get("result", {}).get("result", {}).get("value", "")
print(f"iframe access: {access}")

slider_x = 83
slider_y = 217
end_x = slider_x + 240

print(f"Dragging from ({slider_x}, {slider_y}) to ({end_x}, {slider_y})")

send_cdp("Input.dispatchMouseEvent", {
    "type": "mousePressed",
    "x": slider_x,
    "y": slider_y,
    "button": "left",
    "clickCount": 1
})

steps = [0.03, 0.06, 0.1, 0.15, 0.2, 0.27, 0.35, 0.42, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
import random
for ratio in steps:
    cx = slider_x + 240 * ratio
    cy = slider_y + random.uniform(-1, 1)
    send_cdp("Input.dispatchMouseEvent", {
        "type": "mouseMoved",
        "x": cx,
        "y": cy
    })
    time.sleep(random.uniform(0.02, 0.08))

send_cdp("Input.dispatchMouseEvent", {
    "type": "mouseReleased",
    "x": end_x,
    "y": slider_y,
    "button": "left",
    "clickCount": 1
})

print("CDP drag completed")

time.sleep(2)

eval_resp3 = send_cdp("Runtime.evaluate", {
    "expression": """
    (function(){
        var frames = document.querySelectorAll('iframe');
        var baxia = null;
        for(var i=0;i<frames.length;i++){
            if(frames[i].name==='baxia-dialog-content'){
                baxia = frames[i];
                break;
            }
        }
        if(!baxia) return JSON.stringify({status:'passed',msg:'iframe disappeared'});
        if(baxia.style.display==='none') return JSON.stringify({status:'passed',msg:'iframe hidden'});
        return JSON.stringify({status:'still_showing',msg:'iframe still visible'});
    })()
""",
    "returnByValue": True
})
status = eval_resp3.get("result", {}).get("result", {}).get("value", "")
print(f"Verification status: {status}")

ws.close()
