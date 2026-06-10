#!/usr/bin/env python3
"""一次性创建 chrome_base_template 基准目录 — 纯DTS扩展 + 无Cookie/无登录"""
import json, os, shutil, subprocess

BASE = "/home/lab-admin/.config/chrome_base_template"
SRC_EXT = "/home/lab-admin/chrome-user-desktop/Default/Extensions/ppgdlgnehnajbbngnohepfigdmjbdpfb/5.0.6_0"
DTS_ID = "ppgdlgnehnajbbngnohepfigdmjbdpfb"

print(f"=== 创建基准模板: {BASE} ===")

# 1. 清理旧模板
if os.path.exists(BASE):
    shutil.rmtree(BASE)
    print("  已清理旧模板")

# 2. 创建目录结构
os.makedirs(f"{BASE}/Default/Extensions/{DTS_ID}/5.0.6_0", exist_ok=True)
os.makedirs(f"{BASE}/Default/Local Extension Settings/{DTS_ID}", exist_ok=True)
print("  目录结构已创建")

# 3. 复制DTS扩展文件
shutil.copytree(SRC_EXT, f"{BASE}/Default/Extensions/{DTS_ID}/5.0.6_0", dirs_exist_ok=True)
print(f"  DTS扩展已复制 版本={json.load(open(f'{SRC_EXT}/manifest.json')).get('version','?')}")

# 4. 读取DTS manifest
with open(f"{SRC_EXT}/manifest.json") as f:
    dts_manifest = json.load(f)

# 5. 创建 Secure Preferences（注册DTS扩展 + 设置state=ENABLED）
secure_prefs = {
    "extensions": {
        "alerts": {"initialized": True},
        "settings": {
            DTS_ID: {
                "active_permissions": {
                    "api": ["activeTab", "alarms", "cookies", "declarativeNetRequest",
                            "declarativeNetRequestFeedback", "scripting", "storage",
                            "unlimitedStorage", "webNavigation", "webRequest",
                            "webRequestBlocking"],
                    "manifest_permissions": [],
                    "explicit_host": ["*://*.taobao.com/*", "*://*.tmall.com/*",
                                      "*://*.1688.com/*", "*://*.alicdn.com/*",
                                      "*://*.diantoushi.com/*", "*://*.taobao.net/*"],
                    "scriptable_host": ["*://*.taobao.com/*", "*://*.tmall.com/*"]
                },
                "commands": {},
                "content_settings": {},
                "creation_flags": 1,
                "from_webstore": False,
                "granted_permissions": {
                    "api": ["activeTab", "alarms", "cookies", "declarativeNetRequest",
                            "declarativeNetRequestFeedback", "scripting", "storage",
                            "unlimitedStorage", "webNavigation", "webRequest",
                            "webRequestBlocking"],
                    "manifest_permissions": [],
                    "explicit_host": ["*://*.taobao.com/*", "*://*.tmall.com/*",
                                      "*://*.1688.com/*", "*://*.alicdn.com/*",
                                      "*://*.diantoushi.com/*", "*://*.taobao.net/*"],
                    "scriptable_host": ["*://*.taobao.com/*", "*://*.tmall.com/*"]
                },
                "id": DTS_ID,
                "incognito_content_settings": [],
                "incognito_preferences": {},
                "install_time": "13345596000000000",
                "location": 1,
                "manifest": dts_manifest,
                "path": f"{BASE}/Default/Extensions/{DTS_ID}/5.0.6_0",
                "preferences": {},
                "regular_only_preferences": {},
                "state": 1,
                "was_installed_by_default": False,
                "was_installed_by_oem": False,
            }
        }
    }
}
with open(f"{BASE}/Default/Secure Preferences", 'w') as f:
    json.dump(secure_prefs, f, indent=2)
print("  Secure Preferences 已创建（DTS已注册 + state=ENABLED）")

# 6. 创建最小 Preferences（无cookies/无session/无账号）
preferences = {
    "autologin": {"local": False},
    "browser": {
        "has_seen_welcome_page": True,
        "window_placement": {"bottom": 1080, "left": 0, "right": 1920, "top": 0, "maximized": True, "work_area_bottom": 1080, "work_area_left": 0, "work_area_right": 1920, "work_area_top": 0}
    },
    "credentials_enable_service": False,
    "profile": {
        "content_settings": {"exceptions": {}},
        "password_manager_enabled": False,
    },
    "savefile": {"default_directory": "/home/lab-admin/Downloads"},
    "signin": {"allowed": False},
}
with open(f"{BASE}/Default/Preferences", 'w') as f:
    json.dump(preferences, f, indent=2)
print("  Preferences 已创建（无Cookie/无Session/无登录态）")

# 7. 创建空目录（避免Chrome弹窗报错）
for d_name in ["Local Storage", "Session Storage", "Cache", "Code Cache",
               "GPUCache", "Service Worker", "IndexedDB", "shared_proto_db"]:
    os.makedirs(f"{BASE}/Default/{d_name}", exist_ok=True)
print("  空目录已创建（避免Chrome弹窗）")

# 8. 验证
print(f"\n=== 验证 ===")
print(f"  模板大小: {sum(os.path.getsize(os.path.join(dp,f)) for dp,dn,fn in os.walk(BASE) for f in fn) / 1024:.0f} KB")
print(f"  DTS manifest: {'✅' if os.path.exists(f'{BASE}/Default/Extensions/{DTS_ID}/5.0.6_0/manifest.json') else '❌'}")
print(f"  Secure Preferences: {'✅' if os.path.exists(f'{BASE}/Default/Secure Preferences') else '❌'}")
print(f"  Preferences: {'✅' if os.path.exists(f'{BASE}/Default/Preferences') else '❌'}")
print(f"  Cookie: {'✅ 已清空' if not os.path.exists(f'{BASE}/Default/Cookies') else '⚠️ 存在'}")

# Check DTS in Secure Preferences
with open(f"{BASE}/Default/Secure Preferences") as f:
    sp = json.load(f)
dts = sp.get("extensions", {}).get("settings", {}).get(DTS_ID, {})
print(f"  DTS state: {dts.get('state','?')} (1=ENABLED)")
print(f"  DTS name: {dts.get('manifest',{}).get('name','?')}")

print("\n✅ 基准模板创建完成!")
