# -*- coding: utf-8 -*-
"""
MajorLogin Flask API - Single File (with ~ -> # auto-replace)

Usage:
    pip install flask httpx pycryptodome google-play-scraper protobuf
    python app.py

URL format:
    Instead of # use ~ in password (because # breaks URLs)
    http://127.0.0.1:5000/login?uid=8007695996&password=BNGX_LVL~3HFO19
    Server will auto-convert ~ to # before sending to Garena.

Endpoints:
    GET  /                              -> info
    GET  /health                        -> health check
    GET  /login?uid=XXX&password=YYY    -> main (use ~ for #)
    POST /login                         -> JSON/form (no conversion, raw password)
"""
import asyncio
import os
from datetime import datetime

import httpx
from flask import Flask, request, jsonify
from google_play_scraper import app as play_scraper
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

import thunderFF_pb2  # <-- must be in same folder

# ==================== CONFIG ====================
AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

# Set to False if you ever need literal '~' in passwords (then use POST)
AUTO_REPLACE_TILDE_WITH_HASH = True

_HEADERS = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1',
    'X-GA-SV': '1789535859',
    'X-GA': 'v1 1',
    'ReleaseVersion': 'OB55'
}

_VERSION_CACHE = None


# ==================== PB HELPERS ====================
def _pb_varint(n):
    if n < 0:
        n = (1 << 64) + n
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)


def _pb_tag(f, w):
    return _pb_varint((f << 3) | w)


def _pb_field(f, v):
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return _pb_tag(f, 0) + _pb_varint(v)
    if isinstance(v, str):
        d = v.encode('utf-8')
        return _pb_tag(f, 2) + _pb_varint(len(d)) + d
    if isinstance(v, (bytes, bytearray)):
        d = bytes(v)
        return _pb_tag(f, 2) + _pb_varint(len(d)) + d
    return b""


# ==================== AES ====================
def aes_encrypt(payload, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(payload, AES.block_size))


# ==================== VERSION CONFIG ====================
def _get_playstore_version():
    try:
        result = play_scraper('com.dts.freefireth', lang='hi', country='id')
        return result.get("version")
    except Exception:
        return "1.132.8"


async def version_config(client: httpx.AsyncClient):
    global _VERSION_CACHE
    if _VERSION_CACHE:
        return _VERSION_CACHE

    try:
        loop = asyncio.get_event_loop()
        app_version = await loop.run_in_executor(None, _get_playstore_version) or "1.132.8"
        api_url = (
            "https://version.ggwhitehawk.com/live/ver.php"
            f"?version={app_version}"
            "&lang=hi&device=android&channel=android"
            "&appstore=googleplay&region=BD"
            "&whitelist_version=1.3.0&whitelist_sp_version=1.0.0"
        )
        response = await client.get(api_url, timeout=8.0)
        response.raise_for_status()
        data = response.json()
        server_url = data.get("server_url")
        remote_version = data.get("remote_version")
        latest_release_version = data.get("latest_release_version")
        if server_url and remote_version and latest_release_version:
            _VERSION_CACHE = (latest_release_version, remote_version, server_url)
            return _VERSION_CACHE
    except Exception as e:
        print(f"[-] version_config exception: {e}")
    return None


# ==================== OAUTH ====================
async def get_access_token(client: httpx.AsyncClient, uid: str, password: str):
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    hdrs = {
        "Host": "100067.connect.garena.com",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B Build/SP1A.210812.016)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "close"
    }
    data = {
        "uid": uid,
        "password": password,
        "response_type": "token",
        "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"
    }
    for _ in range(5):
        try:
            response = await client.post(url, headers=hdrs, data=data)
            if response.status_code == 200:
                rd = response.json()
                open_id = rd.get("open_id")
                access_token = rd.get("access_token")
                platform = rd.get("platform", 4)
                if open_id and access_token:
                    return open_id, access_token, platform
            if response.status_code == 429:
                await asyncio.sleep(1)
                continue
        except Exception as e:
            print(f"[-] OAuth exception: {e}")
        await asyncio.sleep(0.5)
    return None


# ==================== MAJORLOGIN PAYLOAD ====================
def build_majorlogin_payload_uid(open_id, access_token, platform, client_version):
    try:
        proto = thunderFF_pb2.MajorLoginReq()
        proto.event_time = str(datetime.now())[:-7]
        proto.game_name = "free fire"
        proto.platform_id = 1
        proto.client_version = client_version
        proto.client_version_code = "2019121229"
        proto.system_software = "Android OS 15 / API-35 (AP3A.240905.015.A2/185014)"
        proto.system_hardware = "Handheld"
        proto.device_type = "Handheld"
        proto.screen_width = 1600
        proto.screen_height = 719
        proto.screen_dpi = "234"
        proto.processor_details = "ARM64 FP ASIMD AES | 1820 | 8"
        proto.memory = 2798
        proto.gpu_renderer = "Mali-G57"
        proto.gpu_version = "OpenGL ES 3.2 v1.r49p1-04eac0.2848c17a2fd4e9340e06555168eaa3c9"
        proto.unique_device_id = "Google|f744e396-5694-4e65-995d-97a958f2bd1f"
        proto.client_ip = "197.0.137.129"
        proto.language = "pt-br"
        proto.open_id = str(open_id)
        proto.open_id_type = "4"
        proto.login_open_id_type = 4
        proto.access_token = str(access_token)
        proto.login_by = 2
        proto.platform_sdk_id = 1
        proto.origin_platform_type = "4"
        proto.primary_platform_type = "4"
        proto.reg_avatar = 1
        proto.channel_type = 3
        proto.telecom_operator = "TUNTEL"
        proto.network_operator_a = "TUNTEL"
        proto.network_type = "WIFI"
        proto.network_type_a = "WIFI"
        proto.cpu_type = 2
        proto.cpu_architecture = "64"
        proto.graphics_api = "OpenGLES2"
        proto.supported_astc_bitset = 8191
        proto.client_using_version = "7428b253defc164018c604a1ebbfebdf"
        proto.loading_time = 15078
        proto.release_channel = "android"
        proto.extra_info = "KqsHTx3+QOmBRR1WKvaWewlcpqJBfjki+PPHQoQG8+0yV+Uos7gUFFjHMQ/e7u6han6Fl77r7c3vMN3p8UbKgN+nfycQCgwBmWgBzomx2gj84c+p"
        proto.android_engine_init_flag = 111207
        proto.if_push = 1
        proto.is_vpn = 0

        memory_available = proto.memory_available
        memory_available.version = 55
        memory_available.hidden_value = 81

        proto.external_storage_total = 49973
        proto.external_storage_available = 11338
        proto.internal_storage_total = 854
        proto.internal_storage_available = 11466
        proto.game_disk_storage_total = 49973
        proto.game_disk_storage_available = 11466
        proto.external_sdcard_total_storage = 49973
        proto.external_sdcard_avail_storage = 11466

        proto.library_path = "/data/app/~~lHFxTCCbupG2QVJmsURtZw==/com.dts.freefireth-N3aCHpHNXpdxjD80uIIbww==/lib/arm64"
        proto.library_token = "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~lHFxTCCbupG2QVJmsURtZw==/com.dts.freefireth-N3aCHpHNXpdxjD80uIIbww==/base.apk"

        base_payload = proto.SerializeToString()

        extra = b""
        extra += _pb_field(96, '{"cur_rate":[90,60,120],"support_etc2":false}')
        extra += _pb_field(97, 1)
        extra += _pb_field(99, "4")
        extra += _pb_field(100, "4")
        extra += _pb_field(102, b"\x17]ENWU\x0eR5")
        extra += _pb_field(104, 52882)
        extra += _pb_field(105, 1)
        extra += _pb_field(106, "https://dl.ak.freefiremobile.com/live/ABHotUpdates/|https://core-ak.freefiremobile.com/live/ABHotUpdates/|6b2078db9d22dd98f8e9386a39af8462")
        extra += _pb_field(107, "c8e41b7a93f02d56e1a94c7b8203f5d1")

        full_payload = base_payload + extra
        return aes_encrypt(full_payload, AES_KEY, AES_IV)
    except Exception as e:
        print(f"[-] build_majorlogin_payload_uid error: {e}")
        return None


# ==================== SEND MAJORLOGIN ====================
async def send_majorlogin(client: httpx.AsyncClient, data, release_version, server_url):
    try:
        url = f"{server_url}MajorLogin" if server_url.endswith('/') else f"{server_url}/MajorLogin"
        req_headers = _HEADERS.copy()
        req_headers["ReleaseVersion"] = release_version
        response = await client.post(url, headers=req_headers, data=data)

        if response.status_code != 200:
            print(f"[-] MajorLogin HTTP {response.status_code}")
            print(f"    Body: {response.content[:200]}")
            return None

        response_content = response.content
        if len(response_content) < 40:
            print(f"[-] MajorLogin response too short: {len(response_content)} bytes")
            return None

        try:
            res_proto = thunderFF_pb2.MajorLoginRes()
            res_proto.ParseFromString(response_content)
            if res_proto.region and res_proto.token:
                return res_proto
        except Exception:
            pass

        if len(response_content) > 64:
            try:
                res_proto = thunderFF_pb2.MajorLoginRes()
                res_proto.ParseFromString(response_content[64:])
                if res_proto.region and res_proto.token:
                    return res_proto
            except Exception:
                pass

        for offset in range(min(128, len(response_content))):
            try:
                candidate = thunderFF_pb2.MajorLoginRes()
                candidate.ParseFromString(response_content[offset:])
                if candidate.region and candidate.token:
                    return candidate
            except Exception:
                pass

        return None
    except Exception as e:
        print(f"[-] send_majorlogin error: {e}")
        return None


# ==================== MAIN EXTRACT ====================
async def extract_majorlogin(uid: str, password: str) -> dict:
    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        ver = await version_config(client)
        if not ver:
            return {"ok": False, "error": "version_config_failed"}
        release_version, client_version, server_url = ver

        tok = await get_access_token(client, uid, password)
        if not tok:
            return {"ok": False, "error": "oauth_failed",
                    "hint": "UID or Password incorrect, or rate-limited."}
        open_id, access_token, platform = tok

        payload = build_majorlogin_payload_uid(open_id, access_token, platform, client_version)
        if not payload:
            return {"ok": False, "error": "payload_build_failed"}

        res = await send_majorlogin(client, payload, release_version, server_url)
        if not res:
            return {"ok": False, "error": "majorlogin_failed"}

        return {
            "ok": True,
            "account_id": int(res.account_id) if res.account_id else None,
            "token": res.token,
            "token_length": len(res.token) if res.token else 0,
            "region": res.region,
            "url": res.url,
            "server_time": int(res.server_time) if res.server_time else None,
            "aes_ak_hex": res.aes_ak.hex() if res.aes_ak else "",
            "iv_i_hex": res.iv_i.hex() if res.iv_i else "",
            "open_id": open_id,
            "access_token": access_token,
            "platform": platform,
            "release_version": release_version,
            "client_version": client_version,
        }


# ==================== FLASK APP ====================
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def run_async(coro):
    return _LOOP.run_until_complete(coro)


def _normalize_password(password: str) -> str:
    """
    Convert ~ back to # for GET requests.
    This lets URLs carry passwords containing '#' safely.
    """
    if AUTO_REPLACE_TILDE_WITH_HASH and password:
        return password.replace("~", "#")
    return password


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "MajorLogin API",
        "version": "1.1",
        "note": "In GET requests, use '~' instead of '#' in password. Server converts it back.",
        "endpoints": {
            "GET /login?uid=XXX&password=YYY": {
                "example": "http://127.0.0.1:5000/login?uid=8007695996&password=BNGX_LVL~3HFO19",
                "note": "~ is converted to # automatically"
            },
            "POST /login": {
                "body": {"uid": "string", "password": "string"},
                "note": "No conversion — send raw password"
            },
            "GET /health": "Health check"
        }
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "status": "alive"})


def _do_login(uid: str, password: str):
    if not uid or not password:
        return jsonify({
            "ok": False,
            "error": "missing_credentials",
            "hint": "Provide 'uid' and 'password'."
        }), 400

    if not uid.isdigit():
        return jsonify({
            "ok": False,
            "error": "invalid_uid",
            "hint": "UID must be digits only."
        }), 400

    try:
        result = run_async(extract_majorlogin(uid, password))
    except Exception as e:
        return jsonify({"ok": False, "error": "server_error", "detail": str(e)}), 500

    if not result.get("ok"):
        err = result.get("error", "unknown")
        code = 401 if err in ("oauth_failed", "majorlogin_failed") else 502
        return jsonify(result), code

    return jsonify(result), 200


# ---------- POST (JSON / form-data) — no conversion ----------
@app.route("/login", methods=["POST"])
def login_post():
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        uid = str(payload.get("uid", "")).strip()
        password = str(payload.get("password", "")).strip()
    else:
        uid = str(request.form.get("uid", "")).strip()
        password = str(request.form.get("password", "")).strip()

    # POST: use raw password (user can send '#' directly in JSON)
    return _do_login(uid, password)


# ---------- GET (query params) — converts ~ to # ----------
@app.route("/login", methods=["GET"])
def login_get():
    uid = str(request.args.get("uid", "")).strip()
    raw_password = str(request.args.get("password", "")).strip()

    # Convert ~ -> # for GET requests
    password = _normalize_password(raw_password)

    return _do_login(uid, password)


@app.errorhandler(404)
def not_found(e):
    return jsonify({"ok": False, "error": "not_found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"ok": False, "error": "method_not_allowed"}), 405


@app.errorhandler(500)
def server_error(e):
    return jsonify({"ok": False, "error": "internal_error"}), 500


# ==================== RUN ====================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print("=" * 60)
    print("   MajorLogin Flask API")
    print("=" * 60)
    print(f"[i] Listening    : http://0.0.0.0:{port}")
    print(f"[i] Health       : http://localhost:{port}/health")
    print(f"[i] POST login   : http://localhost:{port}/login")
    print(f"[i] GET  login   : http://localhost:{port}/login?uid=XXX&password=YYY")
    print(f"[i] NOTE         : In GET, use ~ instead of # in password")
    print(f"[i] Example      : http://127.0.0.1:5000/login?uid=8007695996&password=BNGX_LVL~3HFO19")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)