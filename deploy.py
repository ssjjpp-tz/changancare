#!/usr/bin/env python3
"""Chang'an Care — Cloudflare Pages direct-upload deploy (wrangler protocol).

Usage:
  export CF_API_TOKEN=xxx  CF_ACCOUNT_ID=xxx
  python3 deploy.py [path/to/index.html]
"""
import base64, io, json, os, sys, urllib.request, uuid
import blake3

TOK = os.environ["CF_API_TOKEN"]
ACC = os.environ["CF_ACCOUNT_ID"]
API = "https://api.cloudflare.com/client/v4"
PROJ = "changancare"
FPATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

def req(method, url, token, body=None, ctype="application/json", raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        r.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"success": False, "errors": [{"code": e.code, "message": e.read().decode()[:600]}]}

content = open(FPATH, "rb").read()
b64 = base64.b64encode(content).decode()
h = blake3.blake3((b64 + "html").encode()).hexdigest()[:32]
print("hash:", h)

r = req("GET", f"{API}/accounts/{ACC}/pages/projects/{PROJ}/upload-token", TOK)
jwt = r["result"]["jwt"]; print("1) jwt ok")

r = req("POST", f"{API}/pages/assets/check-missing", jwt, {"hashes": [h]})
missing = r.get("result", [h]) if r.get("success") else [h]
print("2) missing:", missing)

if h in missing:
    r = req("POST", f"{API}/pages/assets/upload", jwt,
            [{"key": h, "value": b64, "metadata": {"contentType": "text/html"}, "base64": True}])
    print("3) upload:", "OK" if r.get("success") else r.get("errors"))

r = req("POST", f"{API}/pages/assets/upsert-hashes", jwt, {"hashes": [h]})
print("4) upsert-hashes:", "OK" if r.get("success") else r.get("errors"))

manifest = json.dumps({"/index.html": h})
boundary = uuid.uuid4().hex
buf = io.BytesIO()
def part(name, payload_, filename=None, ctype="application/octet-stream"):
    buf.write(f"--{boundary}\r\n".encode())
    disp = f'Content-Disposition: form-data; name="{name}"'
    if filename:
        disp += f'; filename="{filename}"'
    buf.write(f"{disp}\r\nContent-Type: {ctype}\r\n\r\n".encode())
    buf.write(payload_ if isinstance(payload_, bytes) else payload_.encode())
    buf.write(b"\r\n")
part("manifest", manifest, ctype="application/json")
part("index.html", content, filename="index.html", ctype="text/html")
buf.write(f"--{boundary}--\r\n".encode())

r = req("POST", f"{API}/accounts/{ACC}/pages/projects/{PROJ}/deployments", TOK,
        raw=buf.getvalue(), ctype=f"multipart/form-data; boundary={boundary}")
if r.get("success"):
    d = r["result"]
    print("5) deployment:", d.get("id"), "| env:", d.get("environment"), "| url:", d.get("url"))
else:
    print("5) FAILED:", json.dumps(r.get("errors"), ensure_ascii=False)[:600]); sys.exit(1)
