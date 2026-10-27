import argparse, json, os, random, re, subprocess, sys, time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import probe_nodes as pn

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"C:\RouteDL"
BIN = BASE + r"\bin"
DOWNLOADS = BASE + r"\downloads"
ALIVE = pn.OUT
CACHE = BASE + r"\route_cache.json"
XRAY_CFG = BASE + r"\xray_run.json"
LIST_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt"
SOCKS_PORT = 10850
PROXY_URL = f"socks5h://127.0.0.1:{SOCKS_PORT}"  # socks5h = DNS-запросы тоже через прокси
CACHE_TTL = 24 * 3600
ALIVE_TTL = 3600
WANT_ALIVE = 8

FAIL_RE = re.compile(
    r"timed out|timeout|Connection reset|Connection aborted|Unable to connect|getaddrinfo failed|"
    r"Name or service not known|Temporary failure in name resolution|HTTP Error (403|451)|"
    r"403 Forbidden|451 Unavailable|"
    r"SSLError|CERTIFICATE_VERIFY|connection refused|Failed to establish|Max retries exceeded|"
    r"RemoteDisconnected|IncompleteRead|Unable to download webpage",
    re.I)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def refresh_alive(force=False):
    if not force and os.path.exists(ALIVE) and time.time() - os.path.getmtime(ALIVE) < ALIVE_TTL:
        data = load_json(ALIVE, [])
        if data:
            return data
    print("[RouteDL] обновляю список узлов...")
    try:
        with urllib.request.urlopen(LIST_URL, timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
        with open(pn.LIST, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"[RouteDL] список не скачался ({e}), беру локальную копию")
    with open(pn.LIST, encoding="utf-8") as f:
        lines = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
    nodes = [n for n in (pn.parse_vless(l) for l in lines) if n]
    random.shuffle(nodes)
    alive = []
    for start in range(0, len(nodes), pn.WORKERS):
        batch = list(enumerate(nodes[start:start + pn.WORKERS], start))
        with ThreadPoolExecutor(pn.WORKERS) as ex:
            res = list(ex.map(pn.probe, batch))
        for (i, n), r in zip(batch, res):
            if r["ok"]:
                kind = f'{n["q"].get("security", "none")}/{n["q"].get("type", "tcp")}'
                alive.append({"ms": r["ms"], "raw": n["raw"], "kind": kind})
        if len(alive) >= WANT_ALIVE:
            break
    alive.sort(key=lambda a: a["ms"])
    save_json(ALIVE, alive)
    print(f"[RouteDL] живых узлов найдено: {len(alive)}")
    return alive


def start_proxy(alive):
    outs = []
    for k, a in enumerate(alive[:WANT_ALIVE]):
        n = pn.parse_vless(a["raw"])
        cfg = pn.build_config(n, 0) if n else None
        if cfg:
            o = cfg["outbounds"][0]
            o["tag"] = f"node-{k}"
            outs.append(o)
    if not outs:
        return None
    cfg = {
        "log": {"loglevel": "none"},
        "inbounds": [{"tag": "socks-in", "listen": "127.0.0.1", "port": SOCKS_PORT,
                      "protocol": "socks", "settings": {"auth": "noauth", "udp": False}}],
        "outbounds": outs,
        "observatory": {"subjectSelector": ["node-"], "probeUrl": pn.TEST_URL, "probeInterval": "30s"},
        "routing": {
            "balancers": [{"tag": "bal", "selector": ["node-"], "strategy": {"type": "leastPing"}}],
            "rules": [{"type": "field", "inboundTag": ["socks-in"], "balancerTag": "bal"}],
        },
    }
    save_json(XRAY_CFG, cfg)
    return subprocess.Popen([pn.XRAY, "run", "-c", XRAY_CFG], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=pn.NO_WINDOW)


def wait_ready(proc, timeout=25):
    t = time.time()
    while time.time() - t < timeout:
        if proc.poll() is not None:
            return False
        r = subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code}", "--socks5-hostname",
             f"127.0.0.1:{SOCKS_PORT}", "--max-time", "6", pn.TEST_URL],
            capture_output=True, text=True, creationflags=pn.NO_WINDOW)
        if r.stdout.strip() == "204":
            return True
        time.sleep(1.5)
    return False


def ensure_proxy(force=False):
    for attempt in (0, 1):
        alive = refresh_alive(force or attempt == 1)
        proc = start_proxy(alive)
        if proc and wait_ready(proc):
            return proc
        if proc:
            proc.kill()
            proc.wait()
    return None


def pick_tool(url):
    yt = gd = False
    try:
        from yt_dlp.extractor import gen_extractor_classes
        yt = any(ie.ie_key() != "Generic" and ie.suitable(url) for ie in gen_extractor_classes())
    except Exception:
        pass
    try:
        from gallery_dl import extractor
        gd = extractor.find(url) is not None
    except Exception:
        pass
    return ("yt" if yt else "gallery" if gd else None), yt, gd


def build_cmd(tool, url, proxy, audio):
    t = "25" if proxy else "8"
    r = "3" if proxy else "1"
    if tool == "yt":
        cmd = [sys.executable, "-m", "yt_dlp", "--no-colors", "--newline", "--ffmpeg-location", BIN,
               "-o", DOWNLOADS + r"\%(title)s [%(id)s].%(ext)s",
               "--http-chunk-size", "10M",
               "--socket-timeout", t, "--retries", r, "--extractor-retries", r]
        if audio:
            cmd += ["-x", "--audio-format", audio, "--audio-quality", "0", "--embed-metadata"]
            if audio in ("mp3", "m4a"):
                cmd += ["--embed-thumbnail"]
    else:
        cmd = [sys.executable, "-m", "gallery_dl", "-d", DOWNLOADS, "--http-timeout", t, "-R", r]
    if proxy:
        cmd += ["--proxy", proxy]
    return cmd + [url]


def run(cmd):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env)
    lines = []
    for line in p.stdout:
        print(line, end="")
        lines.append(line)
    p.wait()
    return p.returncode, "".join(lines)


def selftest():
    def country(via_proxy):
        cmd = ["curl.exe", "-s", "--max-time", "10"]
        if via_proxy:
            cmd += ["--socks5-hostname", f"127.0.0.1:{SOCKS_PORT}"]
        r = subprocess.run(cmd + ["https://ipinfo.io/country"], capture_output=True, text=True,
                           creationflags=pn.NO_WINDOW)
        return r.stdout.strip() or "нет ответа"

    print("напрямую, страна выхода:", country(False))
    proc = ensure_proxy()
    if not proc:
        print("прокси не поднялся")
        return 1
    try:
        print("через прокси, страна выхода:", country(True))
    finally:
        proc.kill()
        proc.wait()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--audio", choices=["mp3", "flac", "wav", "m4a", "opus", "vorbis", "aac"])
    ap.add_argument("--route", choices=["auto", "direct", "proxy"], default="auto")
    ap.add_argument("--tool", choices=["auto", "yt", "gallery"], default="auto")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    os.makedirs(DOWNLOADS, exist_ok=True)
    if a.selftest:
        return selftest()
    if not a.url:
        ap.error("нужна ссылка")

    domain = (urlsplit(a.url).hostname or "").lower().removeprefix("www.")
    tool = a.tool
    if tool == "auto":
        tool, yt, gd = pick_tool(a.url)
        print(f"[RouteDL] движок: {tool} (yt-dlp знает: {yt}, gallery-dl знает: {gd})")
        if not tool:
            print("[RouteDL] ни один движок не знает эту ссылку")
            return 2
    if a.audio and tool != "yt":
        print("[RouteDL] --audio работает только с yt-dlp, игнорирую")
        a.audio = None

    cache = load_json(CACHE, {})
    entry = cache.get(domain)
    cached_proxy = bool(entry and entry.get("route") == "proxy" and time.time() - entry["ts"] < CACHE_TTL)
    route = a.route
    if route == "auto":
        route = "proxy" if cached_proxy else "direct"

    if route == "direct":
        print("[RouteDL] маршрут: напрямую")
        rc, text = run(build_cmd(tool, a.url, None, a.audio))
        if rc == 0:
            if cache.pop(domain, None) is not None:
                save_json(CACHE, cache)
            return 0
        if a.route == "auto" and FAIL_RE.search(text):
            print("[RouteDL] прямое соединение не удалось, включаю маршрут через прокси")
        else:
            return rc

    print("[RouteDL] маршрут: через прокси")
    proc = ensure_proxy(a.refresh)
    if not proc:
        print("[RouteDL] не удалось поднять прокси: нет живых узлов")
        return 3
    try:
        rc, _ = run(build_cmd(tool, a.url, PROXY_URL, a.audio))
    finally:
        proc.kill()
        proc.wait()
    if rc == 0 and a.route == "auto":
        cache[domain] = {"route": "proxy", "ts": time.time()}
        save_json(CACHE, cache)
    return rc


if __name__ == "__main__":
    sys.exit(main())