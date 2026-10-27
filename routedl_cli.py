import argparse, json, os, random, re, socket, subprocess, sys, threading, time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import probe_nodes as pn

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
T0 = time.time()

BASE = r"C:\RouteDL"
BIN = BASE + r"\bin"
DOWNLOADS = BASE + r"\downloads"
CIADPI = BIN + r"\ciadpi.exe"
CACHE = BASE + r"\route_cache.json"
DPI_CACHE = BASE + r"\dpi_strategy.json"
LIST_URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://cdn.jsdelivr.net/gh/igareck/vpn-configs-for-russia@main/BLACK_VLESS_RUS.txt",
]
DPI_PORT = 10860
DPI_URL = f"socks5h://127.0.0.1:{DPI_PORT}"  # socks5h: DNS-запросы тоже через прокси
NODE_PORT0 = 21700
CACHE_TTL = 24 * 3600
ALIVE_TTL = 3600
WANT_ALIVE = 8
TOP_NODES = 16
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CHAIN = {"port": DPI_PORT}

STRATEGIES = [
    "--fake -1 --ttl 8",
    "--fake -1 --ttl 5 --tlsrec 1+s",
    "--split 1 --disorder 3+s --mod-http=h,d --auto=torst --tlsrec 1+s",
    "--disorder 1 --auto=torst --tlsrec 1+s",
    "--tlsrec 1+s --split 1+s",
    "--fake -1 --ttl 4",
    "--oob 1+s --tlsrec 1+s",
]
LABEL = {"direct": "напрямую", "dpi": "локальный DPI-обход (ByeDPI)", "proxy": "через узлы"}

NET_RE = re.compile(
    r"timed out|timeout|connection reset|connection aborted|unable to connect|getaddrinfo|"
    r"name or service not known|temporary failure in name resolution|SSL|EOF occurred|"
    r"certificate_verify|connection refused|failed to establish|max retries exceeded|"
    r"remotedisconnected|incompleteread|unable to download webpage|unable to download video data|"
    r"proxyerror|connectionerror|stalled", re.I)
HTTP_RE = re.compile(r"HTTP Error (403|451)|403 Forbidden|451 Unavailable", re.I)
FILE_RE = re.compile(r"^[A-Za-z]:\\")

ORIG_BUILD = pn.build_config


def log(msg):
    print(f"[RouteDL +{time.time() - T0:.0f}с] {msg}", flush=True)


def err_lines(text):
    return "\n".join(l for l in text.splitlines() if "ERROR" in l or "][error]" in l.lower())


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def wait_port(port, tries=30):
    for _ in range(tries):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
            return True
        except OSError:
            time.sleep(0.15)
    return False


def probe_origin(origin, proxy=None, t=8):
    """Код ответа сайта тем же сетевым стеком, что у yt-dlp/gallery-dl. None = нет соединения."""
    import requests
    try:
        r = requests.get(origin, headers={"User-Agent": UA}, timeout=t, allow_redirects=False,
                         stream=True, proxies={"http": proxy, "https": proxy} if proxy else None)
        code = r.status_code
        r.close()
        return code
    except Exception:
        return None


def probe_country(proxy):
    import requests
    try:
        r = requests.get("https://ipinfo.io/country", timeout=6, headers={"User-Agent": UA},
                         proxies={"http": proxy, "https": proxy})
        cc = r.text.strip()
        return cc if len(cc) == 2 else "?"
    except Exception:
        return "?"


def chained_build(n, port):
    cfg = ORIG_BUILD(n, port)
    if cfg is None:
        return None
    cfg["outbounds"][0]["streamSettings"].setdefault("sockopt", {})["dialerProxy"] = "dpi"
    cfg["outbounds"].append({"tag": "dpi", "protocol": "socks",
                             "settings": {"servers": [{"address": "127.0.0.1", "port": CHAIN["port"]}]}})
    return cfg


def refresh_alive(chain=False, force=False):
    path = BASE + (r"\alive_chain.json" if chain else r"\alive.json")
    if not force and os.path.exists(path) and time.time() - os.path.getmtime(path) < ALIVE_TTL:
        data = load_json(path, [])
        if data:
            return data
    log("обновляю список узлов" + (" (через DPI-обход)" if chain else "") + "...")
    text = None
    for u in LIST_URLS:
        try:
            with urllib.request.urlopen(u, timeout=20) as r:
                text = r.read().decode("utf-8", "replace")
            break
        except Exception as e:
            log(f"список не скачался с {u.split('/')[2]}: {e}")
    if text:
        with open(pn.LIST, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        log("беру локальную копию списка")
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
        if len(alive) >= WANT_ALIVE * 2:
            break
    alive.sort(key=lambda a: a["ms"])
    save_json(path, alive)
    log(f"живых узлов найдено: {len(alive)}")
    return alive


def pick_node(alive, origin, want_foreign):
    """Параллельно проверяет узлы на нужном сайте. Возвращает ((proc, port, path) | None, число ответивших)."""
    cand = alive[:TOP_NODES]

    def work(arg):
        k, a = arg
        n = pn.parse_vless(a["raw"])
        port = NODE_PORT0 + k
        cfg = pn.build_config(n, port) if n else None
        if cfg is None:
            return None
        path = os.path.join(BASE, f"node_{k}.json")
        save_json(path, cfg)
        p = subprocess.Popen([pn.XRAY, "run", "-c", path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=pn.NO_WINDOW)
        keep = False
        try:
            if not wait_port(port):
                return None
            proxy = f"socks5h://127.0.0.1:{port}"
            t0 = time.time()
            code = probe_origin(origin, proxy, 8)
            if code is None:
                return None
            ms = int((time.time() - t0) * 1000)
            cc = probe_country(proxy) if want_foreign else "?"
            keep = True
            return {"ms": ms, "cc": cc, "p": p, "port": port, "path": path}
        finally:
            if not keep:
                p.kill()
                p.wait()
                try:
                    os.remove(path)
                except OSError:
                    pass

    if not cand:
        return None, 0
    with ThreadPoolExecutor(len(cand)) as ex:
        res = [r for r in ex.map(work, enumerate(cand)) if r]
    good = res
    if want_foreign and res:
        foreign = [r for r in res if r["cc"] not in ("RU", "?")]
        if foreign:
            good = foreign
        else:
            log("иностранных узлов для этого сайта не нашлось, беру любой")
    good = sorted(good, key=lambda r: r["ms"])
    best = good[0] if good else None
    for r in res:
        if r is not best:
            r["p"].kill()
            r["p"].wait()
            try:
                os.remove(r["path"])
            except OSError:
                pass
    if best:
        return (best["p"], best["port"], best["path"]), len(res)
    return None, len(res)


def start_dpi(strategy, port):
    p = subprocess.Popen([CIADPI, "--ip", "127.0.0.1", "--port", str(port)] + strategy.split(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=pn.NO_WINDOW)
    if wait_port(port) and p.poll() is None:
        return p
    p.kill()
    p.wait()
    return None


def find_strategy(domain, origin):
    """Возвращает (процесс, стратегия, код ответа, порт) или (None, None, None, None)."""
    cache = load_json(DPI_CACHE, {})
    saved = cache.get(domain)
    if saved:
        p = start_dpi(saved, DPI_PORT)
        if p:
            code = probe_origin(origin, DPI_URL, 6)
            if code is not None:
                log(f"стратегия из кэша: {saved}")
                return p, saved, code, DPI_PORT
            p.kill()
            p.wait()
    cands = [s for s in STRATEGIES if s != saved]

    def work(arg):
        k, s = arg
        port = DPI_PORT + 1 + k
        p = start_dpi(s, port)
        if not p:
            return None
        url = f"socks5h://127.0.0.1:{port}"
        code = None
        for _ in range(2 if "--auto" in s else 1):
            code = probe_origin(origin, url, 6)
            if code is not None:
                break
        if code is None:
            p.kill()
            p.wait()
            return None
        return {"s": s, "p": p, "port": port, "code": code, "k": k}

    log(f"подбираю стратегию DPI-обхода (параллельно, {len(cands)} шт.)...")
    with ThreadPoolExecutor(len(cands)) as ex:
        res = [r for r in ex.map(work, enumerate(cands)) if r]
    if not res:
        return None, None, None, None
    res.sort(key=lambda r: r["k"])
    best = res[0]
    for r in res[1:]:
        r["p"].kill()
        r["p"].wait()
    cache[domain] = best["s"]
    save_json(DPI_CACHE, cache)
    log(f"стратегия: {best['s']} (подошло {len(res)} из {len(cands)})")
    return best["p"], best["s"], best["code"], best["port"]


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


def build_cmd(tool, url, proxy, audio, cover, quality):
    t = "25" if proxy else "8"
    r = "3" if proxy else "1"
    if tool == "yt":
        cmd = [sys.executable, "-m", "yt_dlp", "--no-colors", "--newline", "--progress-delta", "1",
               "--ffmpeg-location", BIN, "-o", DOWNLOADS + r"\%(title)s [%(id)s].%(ext)s",
               "--http-chunk-size", "10M", "-N", "4",
               "--socket-timeout", t, "--retries", r, "--extractor-retries", r]
        if audio:
            cmd += ["-x", "--audio-format", audio, "--audio-quality", "0", "--embed-metadata"]
            if cover and audio in ("mp3", "m4a"):
                cmd += ["--embed-thumbnail"]
        elif quality != "best":
            cmd += ["-S", f"res:{quality},ext:mp4:m4a"]
    else:
        cmd = [sys.executable, "-m", "gallery_dl", "-d", DOWNLOADS, "--http-timeout", t, "-R", r]
    if proxy:
        cmd += ["--proxy", proxy]
    return cmd + [url]


def run(cmd, tool):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env)
    stall = 180 if tool == "gallery" else 150
    state = {"last": time.time(), "killed": False}

    def watchdog():
        while p.poll() is None:
            time.sleep(2)
            if time.time() - state["last"] > stall:
                state["killed"] = True
                p.kill()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    lines, files = [], 0
    for line in p.stdout:
        print(line, end="")
        lines.append(line)
        is_file = bool(FILE_RE.match(line))
        files += is_file
        if tool != "gallery" or is_file:
            state["last"] = time.time()
    p.wait()
    text = "".join(lines)
    if state["killed"]:
        msg = f"ERROR: stalled, timed out: нет прогресса {stall} с, загрузка прервана"
        print(msg)
        return 1, text + "\n" + msg, files
    return p.returncode, text, files


def run_job(ctx, proxy):
    cmd = build_cmd(ctx["tool"], ctx["url"], proxy, ctx["audio"], ctx["cover"], ctx["quality"])
    rc, text, files = run(cmd, ctx["tool"])
    passes = 1
    while rc != 0 and ctx["tool"] == "gallery" and files > 0 and passes < 3 \
            and "Failed to download" in text:
        passes += 1
        log(f"докачка пропущенных файлов (проход {passes})")
        rc, text, files = run(cmd, ctx["tool"])
    return rc, text


def rung_direct(ctx):
    if probe_origin(ctx["origin"], None, 6) is None:
        log("напрямую: нет соединения с сайтом")
        return "skip", None, None
    rc, text = run_job(ctx, None)
    return "ran", rc, text


def rung_dpi(ctx):
    if not os.path.exists(CIADPI):
        log("ciadpi.exe не найден, пропускаю DPI-обход")
        return "skip", None, None
    proc, strat, code, port = find_strategy(ctx["domain"], ctx["origin"])
    if not proc:
        log("ни одна стратегия не сработала")
        return "skip", None, None
    try:
        rc, text = run_job(ctx, f"socks5h://127.0.0.1:{port}")
        return "ran", rc, text
    finally:
        proc.kill()
        proc.wait()


def rung_proxy(ctx):
    dpi = None
    if ctx["chain"]:
        if not os.path.exists(CIADPI):
            log("нужен ciadpi.exe для цепочки, пропускаю узлы")
            return "skip", None, None
        log("узлы через DPI-обход")
        dpi, strat, code, port = find_strategy(ctx["domain"], ctx["origin"])
        if not dpi:
            log("DPI-обход не поднялся, узлы недоступны")
            return "skip", None, None
        CHAIN["port"] = port
        pn.build_config = chained_build
    try:
        node, responded = None, 0
        for force in ((True,) if ctx["refresh"] else (False, True)):
            alive = refresh_alive(ctx["chain"], force)
            node, responded = pick_node(alive, ctx["origin"], ctx["want_foreign"]) if alive else (None, 0)
            if node or responded:
                break
        if not node:
            log("ни один узел не открывает этот сайт")
            return "skip", None, None
        proc, port, path = node
        try:
            log(f"выбран узел (порт {port})")
            rc, text = run_job(ctx, f"socks5h://127.0.0.1:{port}")
            return "ran", rc, text
        finally:
            proc.kill()
            proc.wait()
            try:
                os.remove(path)
            except OSError:
                pass
    finally:
        pn.build_config = ORIG_BUILD
        if dpi:
            dpi.kill()
            dpi.wait()


RUNGS = {"direct": rung_direct, "dpi": rung_dpi, "proxy": rung_proxy}


def ladder(seq, start, ctx):
    net_blocked = False
    i = start
    while i < len(seq):
        step = seq[i]
        log(f"маршрут: {LABEL[step]}")
        if step == "dpi":
            net_blocked = True
        if step == "proxy":
            ctx["chain"] = ctx["force_chain"] or net_blocked or ctx["cached_chain"]
        st, rc, text = RUNGS[step](ctx)
        if st == "skip":
            if step == "direct":
                net_blocked = True
            i += 1
            continue
        if rc == 0:
            return 0, step, (ctx["chain"] if step == "proxy" else False)
        errs = err_lines(text)
        if HTTP_RE.search(errs):
            ctx["want_foreign"] = True
            if "proxy" in seq and step != "proxy":
                log("сайт отказал по IP или стране, пробую узлы")
                i = seq.index("proxy")
                continue
            return rc, step, False
        if NET_RE.search(errs) and i + 1 < len(seq):
            if step == "direct":
                net_blocked = True
            i += 1
            continue
        return rc, step, False
    return 1, None, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--audio", choices=["best", "mp3", "flac", "wav", "m4a", "opus", "vorbis", "aac"])
    ap.add_argument("--quality", choices=["best", "1080", "720", "480"], default="1080")
    ap.add_argument("--route", choices=["auto", "direct", "dpi", "proxy"], default="auto")
    ap.add_argument("--tool", choices=["auto", "yt", "gallery"], default="auto")
    ap.add_argument("--cover", action="store_true", help="встроить обложку (mp3/m4a)")
    ap.add_argument("--chain", action="store_true", help="узлы через DPI-обход (для --route proxy)")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    os.makedirs(DOWNLOADS, exist_ok=True)

    host = (urlsplit(a.url).hostname or "").lower()
    domain = host.removeprefix("www.")
    tool = a.tool
    if tool == "auto":
        tool, yt, gd = pick_tool(a.url)
        log(f"движок: {tool} (yt-dlp знает: {yt}, gallery-dl знает: {gd})")
        if not tool:
            log("ни один движок не знает эту ссылку")
            return 2
    if a.audio and tool != "yt":
        log("--audio работает только с yt-dlp, игнорирую")
        a.audio = None

    ctx = {"tool": tool, "url": a.url, "audio": a.audio, "cover": a.cover, "quality": a.quality,
           "domain": domain, "origin": f"https://{host}/", "refresh": a.refresh,
           "force_chain": a.chain, "chain": a.chain, "cached_chain": False, "want_foreign": False}

    seq = ["direct", "dpi", "proxy"] if a.route == "auto" else [a.route]
    cache = load_json(CACHE, {})
    entry = cache.get(domain)
    cached = None
    if a.route == "auto" and entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
        cached = entry.get("route")
        ctx["cached_chain"] = bool(entry.get("chain"))
    start = seq.index(cached) if cached in seq else 0

    rc, step, chain = ladder(seq, start, ctx)
    if rc != 0 and start > 0:
        log("запомненный маршрут не сработал, начинаю с прямого")
        cache.pop(domain, None)
        ctx["cached_chain"] = False
        rc, step, chain = ladder(seq, 0, ctx)
    if rc == 0 and a.route == "auto":
        if step == "direct":
            cache.pop(domain, None)
        else:
            cache[domain] = {"route": step, "chain": chain, "ts": time.time()}
        save_json(CACHE, cache)
    log(f"готово, код {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())