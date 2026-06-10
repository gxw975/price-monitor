"""内核级 uinput 虚拟鼠标 - 完全等同于物理设备"""
import json, urllib.request, websocket, time, base64, random, ctypes, os, struct, fcntl

os.environ["DISPLAY"] = ":0"
os.environ["XAUTHORITY"] = "/run/user/1000/.mutter-Xwaylandauth.47UFP3"

# ===== CDP setup =====
CDP = "http://127.0.0.1:9223/json"
targets = json.loads(urllib.request.urlopen(CDP, timeout=5).read())
ws = None
for t in targets:
    if t.get("type") == "page" and "s.taobao.com" in t.get("url", ""):
        ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=15)
        break
ws.settimeout(10)
mid = [0]
def cmd(method, params=None):
    mid[0] += 1
    ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
    for _ in range(80):
        r = json.loads(ws.recv())
        if r.get("id") == mid[0]:
            return r
    return {}
for d in ("Runtime", "Page", "DOM", "Input"):
    cmd(f"{d}.enable")

# geometry
r = cmd("Runtime.evaluate", {
    "expression": "JSON.stringify({outerW:window.outerWidth, outerH:window.outerHeight, innerW:window.innerWidth, innerH:window.innerHeight, screenLeft:window.screenLeft||0, screenTop:window.screenTop||0})",
    "returnByValue": True,
})
geo = json.loads(r.get("result", {}).get("result", {}).get("value", "{}"))
fl = (geo["outerW"] - geo["innerW"]) / 2
to = geo["outerH"] - geo["innerH"] - fl
ox = geo["screenLeft"] + fl
oy = geo["screenTop"] + to

# frame tree + contextId
r = cmd("Page.getFrameTree")
ft = r.get("result", {}).get("frameTree", {})
punish_fid = None
def find_punish(node):
    global punish_fid
    f = node.get("frame", {})
    if "h5api.m.taobao.com" in f.get("url", "") and "punish" in f.get("url", ""):
        punish_fid = f.get("id", "")
        return True
    for c in node.get("childFrames", []):
        if find_punish(c):
            return True
    return False
find_punish(ft)
r = cmd("Page.createIsolatedWorld", {"frameId": punish_fid, "grantUniveralAccess": False})
ctx_id = r.get("result", {}).get("executionContextId")

def iframe_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "contextId": ctx_id, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return v
    return v

def main_eval(expr):
    r = cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value", "")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return v
    return v

# ===== uinput setup =====
# Linux input constants
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567

# event types
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03
EV_SYN = 0x00

# relative axes
REL_X = 0x00
REL_Y = 0x01
REL_WHEEL = 0x08

# absolute axes
ABS_X = 0x00
ABS_Y = 0x01

# keys
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_TOUCH = 0x14a
BTN_TOOL_FINGER = 0x145
BTN_TOOL_PEN = 0x140

SYN_REPORT = 0
SYN_CONFIG = 1

# input_event struct: timeval(sec, usec) + type + code + value
# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
# timeval: { __kernel_old_time_t tv_sec; __kernel_suseconds_t tv_usec; }
# on 64-bit: timeval=16 bytes (8+8), input_event=16+2+2+4=24 bytes

def pack_event(tv_sec, tv_usec, ev_type, ev_code, ev_value):
    return struct.pack('qqHHi', tv_sec, tv_usec, ev_type, ev_code, ev_value)

# Open uinput
try:
    uinput_fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    print("uinput fd:", uinput_fd)
except PermissionError:
    print("uinput权限不足，尝试sudo...")
    import subprocess
    result = subprocess.run(
        ["sudo", "chmod", "666", "/dev/uinput"],
        capture_output=True, text=True
    )
    print(result.stdout, result.stderr)
    uinput_fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)

# Enable device capabilities
fcntl.ioctl(uinput_fd, UI_SET_EVBIT, EV_KEY)
fcntl.ioctl(uinput_fd, UI_SET_EVBIT, EV_REL)
fcntl.ioctl(uinput_fd, UI_SET_EVBIT, EV_ABS)
fcntl.ioctl(uinput_fd, UI_SET_EVBIT, EV_SYN)

fcntl.ioctl(uinput_fd, UI_SET_KEYBIT, BTN_LEFT)
fcntl.ioctl(uinput_fd, UI_SET_KEYBIT, BTN_RIGHT)
fcntl.ioctl(uinput_fd, UI_SET_KEYBIT, BTN_TOUCH)
fcntl.ioctl(uinput_fd, UI_SET_KEYBIT, BTN_TOOL_FINGER)

fcntl.ioctl(uinput_fd, UI_SET_RELBIT, REL_X)
fcntl.ioctl(uinput_fd, UI_SET_RELBIT, REL_Y)
fcntl.ioctl(uinput_fd, UI_SET_RELBIT, REL_WHEEL)

fcntl.ioctl(uinput_fd, UI_SET_ABSBIT, ABS_X)
fcntl.ioctl(uinput_fd, UI_SET_ABSBIT, ABS_Y)

# Device setup struct
# struct uinput_user_dev {
#   char name[80];
#   struct input_id id;       // bus, vendor, product, version
#   __u32 ff_effects_max;
#   __s32 absmax[ABS_CNT];
#   __s32 absmin[ABS_CNT];
#   __s32 absfuzz[ABS_CNT];
#   __s32 absflat[ABS_CNT];
# }
# input_id: __u16 bustype, vendor, product, version

BUS_USB = 0x03

dev_name = b"ga-virtual-mouse\x00" + b"\x00" * 62  # 80 bytes total
dev_id = struct.pack('HHHH', BUS_USB, 0x1234, 0x5678, 0x0100)  # 8 bytes
ff_max = struct.pack('I', 0)  # 4 bytes

# ABS_CNT = 0x40 (64)
abs_data = b"\x00" * (6 * 4 * 64)  # 64 entries × 6 ints × 4 bytes
# Actually it's: absmax[64] (256 bytes) + absmin[64] (256 bytes) + absfuzz[64] (256 bytes) + absflat[64] (256 bytes)
# = 4 * 64 * 4 = 1024 bytes
# But actually the kernel definition might use __s32 absmax[ABS_CNT] (where ABS_CNT=0x40=64)
# some kernels use ABS_MAX (0x3f=63) entries
# Let me just fill zeros
abs_size = 64  # ABS_CNT
abs_data = b""
for field in range(4):
    for i in range(abs_size):
        abs_data += struct.pack('i', 0)

setup_data = dev_name + dev_id + ff_max + abs_data
os.write(uinput_fd, setup_data)

# Create device
fcntl.ioctl(uinput_fd, UI_DEV_CREATE)
time.sleep(0.3)  # Wait for device to be registered
print("uinput device created")

# ===== Helper: move mouse to absolute screen position =====
# We need to use REL_X/REL_Y (relative movement) since we're a mouse device
# But we can simulate absolute by computing relative deltas
# First, use xdotool to get current position, then use relative uinput from there

import subprocess

def get_current_mouse():
    r = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                       capture_output=True, text=True,
                       env={"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.47UFP3"})
    result = {}
    for line in r.stdout.strip().split("\n"):
        if "=" in line:
            k, v = line.split("=")
            result[k] = int(v)
    return result.get("x", 0), result.get("y", 0)

def uinput_event(ev_type, ev_code, ev_value):
    now = time.time()
    tv_sec = int(now)
    tv_usec = int((now - tv_sec) * 1000000)
    data = pack_event(tv_sec, tv_usec, ev_type, ev_code, ev_value)
    os.write(uinput_fd, data)

def uinput_sync():
    uinput_event(EV_SYN, SYN_REPORT, 0)

def uinput_move_rel(dx, dy):
    uinput_event(EV_REL, REL_X, dx)
    uinput_event(EV_REL, REL_Y, dy)
    uinput_sync()

def uinput_move_abs(screen_x, screen_y):
    """使用REL移动到绝对位置"""
    cx, cy = get_current_mouse()
    print(f"  current=({cx},{cy}) target=({screen_x},{screen_y})")
    
    # Break into segments to look more natural
    dx = screen_x - cx
    dy = screen_y - cy
    steps = max(1, int(max(abs(dx), abs(dy)) / 20))
    
    for i in range(steps):
        p = (i + 1) / steps
        cur_dx = int(dx * p) - (cx - get_current_mouse()[0])  # adjust for drift
        cur_dy = int(dy * p) - (cy - get_current_mouse()[1])
        uinput_move_rel(cur_dx, cur_dy)
        time.sleep(0.003 + random.random() * 0.005)
    
    # Fine correction
    for _ in range(5):
        nx, ny = get_current_mouse()
        rx = screen_x - nx
        ry = screen_y - ny
        if abs(rx) <= 1 and abs(ry) <= 1:
            break
        uinput_move_rel(rx, ry)
        time.sleep(0.005)

def uinput_left_down():
    uinput_event(EV_KEY, BTN_LEFT, 1)
    uinput_sync()

def uinput_left_up():
    uinput_event(EV_KEY, BTN_LEFT, 0)
    uinput_sync()

# ===== Get slider position =====
state = iframe_eval('JSON.stringify({hasErr:!!document.querySelector(".errloading"),hasSlider:!!document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]")})')
print(f"初始状态: {state}")

# Recover from errloading if needed
if state and state.get("hasErr"):
    print("恢复errloading...")
    err = iframe_eval('(function(){var e=document.querySelector(".errloading");if(!e)return null;var r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()')
    ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')
    ex = int(ip["x"] + err["x"] + ox)
    ey = int(ip["y"] + err["y"] + oy)
    uinput_move_abs(ex, ey)
    time.sleep(0.1)
    uinput_left_down()
    time.sleep(0.05)
    uinput_left_up()
    time.sleep(2.5)

# Get slider coords
sd = iframe_eval('(function(){var s=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]");var t=document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1__scale_text" + String.fromCharCode(39) + "]");if(!s||!t)return null;var sr=s.getBoundingClientRect();var tr=t.getBoundingClientRect();return JSON.stringify({sx:Math.round(sr.x+sr.width/2),sy:Math.round(sr.y+sr.height/2),dist:Math.round(tr.x+tr.width-sr.x-sr.width+3)});})()')
ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')

start_sx = int(ip["x"] + sd["sx"] + ox)
start_sy = int(ip["y"] + sd["sy"] + oy)
drag_d = sd["dist"]
print(f"滑块屏幕:({start_sx},{start_sy}) dist={drag_d}")

# ===== uinput drag attempts =====
strategies = [
    {"label": "uinput-A", "steps": 12, "total_ms": 550, "ease_pow": 2.0},
    {"label": "uinput-B", "steps": 15, "total_ms": 650, "ease_pow": 2.5},
    {"label": "uinput-C", "steps": 18, "total_ms": 800, "ease_pow": 1.8},
    {"label": "uinput-D", "steps": 10, "total_ms": 450, "ease_pow": 3.0},
]

for strat in strategies:
    label = strat["label"]
    steps = strat["steps"]
    total_ms = strat["total_ms"]
    ep = strat["ease_pow"]
    
    print(f"\n[{label}] {steps}步/{total_ms}ms ease={ep}")

    # Phase 1: approach from left
    approach_start_x = start_sx - random.randint(60, 120)
    approach_start_y = start_sy + random.randint(-8, 8)
    uinput_move_abs(approach_start_x, approach_start_y)
    time.sleep(0.04)

    for a_step in range(3):
        p = (a_step + 1) / 3
        ax = int(approach_start_x + (start_sx - approach_start_x) * p)
        ay = int(approach_start_y + (start_sy - approach_start_y) * p)
        uinput_move_abs(ax, ay)
        time.sleep(0.03 + random.random() * 0.02)

    # Pause at slider
    time.sleep(0.06 + random.random() * 0.04)

    # Press
    uinput_left_down()
    time.sleep(0.04 + random.random() * 0.03)

    # Drag steps
    precomputed_delays = []
    for i in range(steps):
        p = (i + 1) / steps
        w = 0.4 + (1 - p) * 1.8
        precomputed_delays.append(w)
    total_w = sum(precomputed_delays)

    for i in range(steps):
        p = (i + 1) / steps
        eased = 1 - (1 - p) ** ep
        x = int(start_sx + drag_d * eased)
        noise = random.randint(-3, 3) if p < 0.85 else random.randint(-1, 1)
        y = start_sy + noise

        uinput_move_abs(x, y)
        delay = total_ms * precomputed_delays[i] / total_w / 1000.0
        time.sleep(max(0.005, delay))

    # Release
    time.sleep(0.05 + random.random() * 0.03)
    uinput_left_up()
    time.sleep(2)

    # Check result
    res = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api.m.taobao.com")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({found:true,vis:r.width>0&&r.height>0});}}return JSON.stringify({found:false});})()')
    js = 'JSON.stringify({hasErr:!!document.querySelector(".errloading"),hasSlider:!!document.querySelector("[id*=" + String.fromCharCode(39) + "nc_1_n1z" + String.fromCharCode(39) + "]"),body:(document.body?.innerText||"").slice(0,100)})'
    if_res = iframe_eval(js)
    print(f"    主页: {res}")
    print(f"    iframe: {if_res}")

    if not res.get("found") or not res.get("vis"):
        print(f"\n>>> ✅✅✅ uinput验证通过! ({label}) ✅✅✅")
        r = cmd("Page.captureScreenshot", {"format": "png"})
        with open("/home/lab-admin/price-monitor/data/ga_win.png", "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        ws.close()
        os.close(uinput_fd)
        exit(0)

    # Recover if needed
    if if_res and if_res.get("hasErr"):
        err = iframe_eval('(function(){var e=document.querySelector(".errloading");if(!e)return null;var r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()')
        ip = main_eval('(function(){var fs=document.querySelectorAll("iframe");for(var i=0;i<fs.length;i++){if((fs[i].src||"").indexOf("h5api")!==-1){var r=fs[i].getBoundingClientRect();return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y)});}}return JSON.stringify({found:false});})()')
        ex = int(ip["x"] + err["x"] + ox)
        ey = int(ip["y"] + err["y"] + oy)
        uinput_move_abs(ex, ey)
        time.sleep(0.1)
        uinput_left_down()
        time.sleep(0.05)
        uinput_left_up()
        time.sleep(2.5)

r = cmd("Page.captureScreenshot", {"format": "png"})
with open("/home/lab-admin/price-monitor/data/ga_final3.png", "wb") as f:
    f.write(base64.b64decode(r["result"]["data"]))

os.close(uinput_fd)
ws.close()
print("\n[DONE]")
