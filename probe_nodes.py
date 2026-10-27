import json, os, socket, subprocess, sys, tempfile, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, parse_qs

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

XRAY = r"C:\RouteDL\bin\xray.exe"
LIST = r"C:\RouteDL\list.txt"
OUT = r"C:\RouteDL\alive.json"
TEST_URL = "https://www.gstatic.com/generate_204"
WORKERS = 16
BASE_PORT = 21000
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def parse_vless(line):
    try:
        u = urlsplit(line.strip())
        if u.scheme != "vless" or not u.username or not u.hostname or not u.port:
            return None
        q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        return {"uuid": u.username, "host": u.hostname, "port": u.port, "q": q, "raw": line.strip()}
    except ValueError:
        return None


def build_config(n, port):
    q = n["q"]
    net = q.get("type", "tcp")
    sec = q.get("security", "none")
    if q.get("headerType", "none") not in ("none", ""):
        return None
    ss = {"network": net, "security": sec}
    if sec == "tls":
        tls = {
            "serverName": q.get("sni") or q.get("host") or n["host"],
            "fingerprint": q.get("fp") or "chrome",
            "allowInsecure": q.get("allowInsecure") == "1",
        }
        if q.get("alpn"):
            tls["alpn"] = q["alpn"].split(",")
        ss["tlsSettings"] = tls
    elif sec == "reality":
        ss["realitySettings"] = {
            "serverName": q.get("sni", ""),
            "fingerprint": q.get("fp") or "chrome",
            "publicKey": q.get("pbk", ""),
            "shortId": q.get("sid", ""),
            "spiderX": q.get("spx", ""),
        }
    elif sec != "none":
        return None
    if net == "ws":
        ss["wsSettings"] = {"path": q.get("path", "/"),
                            "headers": {"Host": q.get("host") or q.get("sni") or n["host"]}}
    elif net == "grpc":
        ss["grpcSettings"] = {"serviceName": q.get("serviceName", ""), "multiMode": q.get("mode") == "multi"}
    elif net == "httpupgrade":
        ss["httpupgradeSettings"] = {"path": q.get("path", "/"), "host": q.get("host", "")}
    elif net == "xhttp":
        ss["xhttpSettings"] = {"path": q.get("path", "/"), "host": q.get("host", ""), "mode": q.get("mode", "auto")}
    elif net != "tcp":
        return None
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks",
                      "settings": {"auth": "noauth", "udp": False}}],
        "outbounds": [{"protocol": "vless",
                       "settings": {"vnext": [{"address": n["host"], "port": n["port"],
                                               "users": [{"id": n["uuid"],
                                                          "encryption": q.get("encryption", "none"),
                                                          "flow": q.get("flow", "")}]}]},
                       "streamSettings": ss}],
    }


def probe(args):
    i, n = args
    port = BASE_PORT + i
    cfg = build_config(n, port)
    if cfg is None:
        return {"ok": False, "err": "unsupported"}
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f)
    p = subprocess.Popen([XRAY, "run", "-c", path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    try:
        started = time.time()
        ready = False
        while time.time() - started < 4:
            if p.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    ready = True
                    break
            except OSError:
                time.sleep(0.15)
        if not ready:
            return {"ok": False, "err": "xray_start"}
        r = subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code} %{time_total}",
             "--socks5-hostname", f"127.0.0.1:{port}", "--max-time", "8", TEST_URL],
            capture_output=True, text=True, creationflags=NO_WINDOW)
        out = r.stdout.split()
        if len(out) == 2 and out[0] == "204":
            return {"ok": True, "ms": int(float(out[1]) * 1000)}
        return {"ok": False, "err": f"http_{out[0] if out else 'none'}"}
    finally:
        p.kill()
        p.wait()
        try:
            os.remove(path)
        except OSError:
            pass


def main():
    with open(LIST, encoding="utf-8") as f:
        lines = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
    nodes = [n for n in (parse_vless(l) for l in lines) if n]
    print(f"строк в списке: {len(lines)}, распарсено: {len(nodes)}")
    kinds = Counter((n["q"].get("security", "none"), n["q"].get("type", "tcp")) for n in nodes)
    print("комбинации security/type:", dict(kinds))

    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(probe, enumerate(nodes)))
    print(f"проверка заняла {int(time.time() - t0)} с")

    errs = Counter(r["err"] for r in results if not r["ok"])
    alive = sorted(
        [{"ms": r["ms"], "raw": n["raw"], "kind": f'{n["q"].get("security","none")}/{n["q"].get("type","tcp")}'}
         for n, r in zip(nodes, results) if r["ok"]],
        key=lambda x: x["ms"])
    print(f"ЖИВЫХ: {len(alive)} из {len(nodes)}")
    print("причины отказов:", dict(errs))
    for a in alive[:10]:
        print(f'  {a["ms"]} мс  {a["kind"]}')
    if alive:
        ms = [a["ms"] for a in alive]
        print(f"медиана задержки: {ms[len(ms)//2]} мс")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(alive, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()