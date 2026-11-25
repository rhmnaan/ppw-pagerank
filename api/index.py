import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutTimeout
from urllib.parse import urljoin, urldefrag, urlparse

import numpy as np
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Opsional: meniru sidik jari TLS Chrome (dipakai otomatis jika terpasang: pip install curl_cffi)
try:
    from curl_cffi import requests as cffi_requests
except Exception:
    cffi_requests = None

app = FastAPI(title="PPW Crawler + PageRank")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SKIP_EXT = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|zip|rar|docx?|xlsx?|pptx?|mp4|mp3|css|js|ico|xml|json)$", re.I
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "id,en;q=0.8",
}
MAX_BYTES = 1_000_000
MAX_CRAWL_PAGES = 500
MAX_CRAWL_SECONDS = 55


class AnalyzeReq(BaseModel):
    url: str
    max_depth: int = Field(..., ge=1, le=6)


def http_get(url: str, timeout: int):
    if cffi_requests:
        return cffi_requests.get(url, headers=HEADERS, timeout=timeout, impersonate="chrome")
    return requests.get(url, headers=HEADERS, timeout=timeout)


def error_kind(e: Exception) -> str:
    msg = str(e).lower()
    code = getattr(e, "code", None)          # kode error curl (curl_cffi)
    if code == 60 or "certificate" in msg or "unable to get local issuer" in msg:
        return "ssl"
    if code == 28 or "timeout" in type(e).__name__.lower() or "timed out" in msg:
        return "timeout"
    if "reset" in msg or "recv failure" in msg or "eof" in msg or "forcibly closed" in msg:
        return "reset"
    return "conn"

def normalize(url: str):
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def allowed(url: str, domains: set) -> bool:
    h = host_of(url)
    ok = any(h == d or h.endswith("." + d) for d in domains)
    return ok and not SKIP_EXT.search(urlparse(url).path)


def probe_seed(seed: str):
    """Tes halaman awal dulu supaya penyebab gagal jelas bagi pengguna."""
    try:
        r = http_get(seed, 10)
    except Exception as e:
        kind = error_kind(e)
        detail = str(e).replace("\n", " ")[:160]
        if kind == "ssl":
            raise HTTPException(422, f"Sertifikat SSL situs tidak bisa diverifikasi. ({detail})")
        if kind == "timeout":
            raise HTTPException(504, f"Situs tidak merespons dalam 10 detik. ({detail})")
        if kind == "reset":
            raise HTTPException(
                422,
                "Koneksi diputus oleh situs atau jaringan (connection reset). Ini bukan masalah "
                f"sertifikat. Coba situs lain atau jaringan lain. ({detail})",
            )
        raise HTTPException(422, f"Tidak bisa terhubung ke situs. ({detail})")
    if r.status_code in (401, 403, 429, 503):
        raise HTTPException(
            422,
            f"Situs menolak akses crawler (HTTP {r.status_code}). Biasanya karena proteksi bot. "
            f"Coba situs lain atau jalankan dengan curl_cffi terpasang.",
        )
    if r.status_code >= 400:
        raise HTTPException(422, f"Halaman awal mengembalikan HTTP {r.status_code}.")
    return r


def fetch_links(url: str, domains: set):
    """Return (url, set_link, pesan_error_atau_None)."""
    try:
        r = http_get(url, 6)
    except Exception as e:
        return url, set(), ("timeout" if error_kind(e) == "timeout" else "koneksi gagal")
    if r.status_code >= 400:
        return url, set(), f"HTTP {r.status_code}"
    if "text/html" not in r.headers.get("Content-Type", ""):
        return url, set(), None  # file non-HTML bukan error
    try:
        soup = BeautifulSoup(r.content[:MAX_BYTES], "html.parser")
    except Exception:
        return url, set(), "HTML tidak terbaca"
    links = set()
    for a in soup.find_all("a", href=True):
        n = normalize(urljoin(str(r.url), a["href"]))
        if n and n != url and allowed(n, domains):
            links.add(n)
    return url, links, None


def crawl(seed: str, max_depth: int, domains: set, workers: int = 12):
    start = time.time()
    depth = {seed: 0}          # url -> kedalaman terpendek dari seed (BFS)
    edges = set()              # (src, dst)
    crawled = set()
    errs = Counter()
    level, d = [seed], 0
    stopped = "selesai"

    while level and d <= max_depth:
        remaining = MAX_CRAWL_SECONDS - (time.time() - start)
        if remaining < 2:
            stopped = "waktu habis"
            break

        ex = ThreadPoolExecutor(workers)
        futures = [ex.submit(fetch_links, u, domains) for u in level]
        next_level = []
        try:
            for f in as_completed(futures, timeout=remaining):
                url, links, err = f.result()
                crawled.add(url)
                if err:
                    errs[err] += 1
                for l in links:
                    if l in depth:
                        edges.add((url, l))
                    elif d < max_depth and len(depth) < MAX_CRAWL_PAGES:
                        depth[l] = d + 1
                        next_level.append(l)
                        edges.add((url, l))
        except FutTimeout:
            stopped = "waktu habis"
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

        if stopped == "waktu habis":
            break
        level, d = next_level, d + 1

    if stopped == "selesai" and len(depth) >= MAX_CRAWL_PAGES:
        stopped = "mencapai batas pengaman jumlah halaman"
    return depth, edges, crawled, errs, round(time.time() - start, 1), stopped


def pagerank(nodes, edges, damping=0.85, iters=100, tol=1e-10):
    n = len(nodes)
    idx = {u: i for i, u in enumerate(nodes)}
    src = np.fromiter((idx[s] for s, _ in edges), dtype=np.int64, count=len(edges))
    dst = np.fromiter((idx[t] for _, t in edges), dtype=np.int64, count=len(edges))
    outdeg = np.bincount(src, minlength=n).astype(float)
    indeg = np.bincount(dst, minlength=n)
    dangling = outdeg == 0
    w = 1.0 / outdeg[src] if len(src) else np.array([])

    pr = np.full(n, 1.0 / n)
    for _ in range(iters):
        contrib = np.bincount(dst, weights=pr[src] * w, minlength=n) if len(src) else np.zeros(n)
        new = damping * (contrib + pr[dangling].sum() / n) + (1 - damping) / n
        if np.abs(new - pr).sum() < tol:
            pr = new
            break
        pr = new
    return pr, indeg, outdeg.astype(int)


@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    raw = req.url if "://" in req.url else "https://" + req.url
    seed = normalize(raw)
    if not seed:
        raise HTTPException(400, "URL tidak valid")

    first = probe_seed(seed)
    domains = {host_of(seed), host_of(str(first.url))}   # ikut domain setelah redirect

    depth, edges, crawled, errs, elapsed, stopped = crawl(seed, req.max_depth, domains)
    if not edges and stopped == "selesai":
        stopped = "tidak ada link internal (mungkin halaman JavaScript)"
    failed = sum(errs.values())
    if failed:
        top_err = ", ".join(f"{k} x{v}" for k, v in errs.most_common(2))
        stopped += f" · {failed} gagal ({top_err})"

    nodes = list(depth.keys())
    pr, indeg, outdeg = pagerank(nodes, edges)

    order = np.argsort(-pr)[:10]
    top = [
        {
            "rank": r + 1,
            "url": nodes[i],
            "score": float(pr[i]),
            "depth": depth[nodes[i]],
            "inlinks": int(indeg[i]),
            "outlinks": int(outdeg[i]),
        }
        for r, i in enumerate(order)
    ]

    per_depth = {}
    for u, dd in depth.items():
        per_depth[dd] = per_depth.get(dd, 0) + 1

    keep = set(nodes)
    graph = {
        "nodes": [
            {
                "id": nodes[i],
                "depth": depth[nodes[i]],
                "pr": float(pr[i]),
                "in": int(indeg[i]),
                "out": int(outdeg[i]),
            }
            for i in range(len(nodes))
        ],
        "links": [
            {"source": s, "target": t}
            for s, t in edges
            if s in keep and t in keep
        ][:20000],
        "truncated": False,
    }

    result = {
        "seed": seed,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "crawled_pages": len(crawled),
        "max_depth_reached": max(depth.values()),
        "nodes_per_depth": dict(sorted(per_depth.items())),
        "elapsed_sec": elapsed,
        "stopped_because": stopped,
        "fail_reasons": dict(errs),
        "top10": top,
        "graph": graph,
    }
    return result


@app.get("/api/health")
def health():
    return {"ok": True, "engine": "curl_cffi" if cffi_requests else "requests"}


# Hanya untuk jalan lokal / di server lab (di Vercel, public/ disajikan otomatis)
if os.path.isdir("public"):
    app.mount("/", StaticFiles(directory="public", html=True), name="static")