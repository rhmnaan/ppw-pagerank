import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutTimeout
from urllib.parse import urljoin, urldefrag, urlparse

import numpy as np
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="PPW Crawler + PageRank")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SKIP_EXT = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|zip|rar|docx?|xlsx?|pptx?|mp4|mp3|css|js|ico)$", re.I
)
HEADERS = {"User-Agent": "PPW-Crawler/1.0 (tugas kuliah UTM)"}
MAX_BYTES = 1_000_000


class AnalyzeReq(BaseModel):
    url: str
    max_depth: int = Field(2, ge=1, le=6)
    max_pages: int = Field(300, ge=10, le=5000)
    time_budget: int = Field(40, ge=5, le=55)
    graph_nodes: int = Field(1500, ge=50, le=5000)   # BARU: jumlah node yang digambar
    include_edges: bool = False


def normalize(url: str):
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def allowed(url: str, domain: str) -> bool:
    h = host_of(url)
    return (h == domain or h.endswith("." + domain)) and not SKIP_EXT.search(urlparse(url).path)


def fetch_links(url: str, domain: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        if "text/html" not in r.headers.get("Content-Type", ""):
            return url, set()
        soup = BeautifulSoup(r.content[:MAX_BYTES].decode(r.encoding or "utf-8", "ignore"), "html.parser")
        links = set()
        for a in soup.find_all("a", href=True):
            n = normalize(urljoin(r.url, a["href"]))
            if n and n != url and allowed(n, domain):
                links.add(n)
        return url, links
    except Exception:
        return url, set()


def crawl(seed: str, max_depth: int, max_pages: int, time_budget: int, workers: int = 12):
    start = time.time()
    depth = {seed: 0}          # url -> kedalaman terpendek dari seed (BFS)
    edges = set()              # (src, dst)
    crawled = set()
    domain = host_of(seed)
    level, d = [seed], 0
    stopped = "selesai"

    while level and d <= max_depth:
        remaining = time_budget - (time.time() - start)
        if remaining < 2:
            stopped = "waktu habis"
            break

        ex = ThreadPoolExecutor(workers)
        futures = [ex.submit(fetch_links, u, domain) for u in level]
        next_level = []
        try:
            for f in as_completed(futures, timeout=remaining):
                url, links = f.result()
                crawled.add(url)
                for l in links:
                    if l in depth:
                        edges.add((url, l))
                    elif d < max_depth and len(depth) < max_pages:
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

    if stopped == "selesai" and len(depth) >= max_pages:
        stopped = "mencapai max_pages"
    return depth, edges, crawled, round(time.time() - start, 1), stopped


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

    depth, edges, crawled, elapsed, stopped = crawl(
        seed, req.max_depth, req.max_pages, req.time_budget
    )
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

    # ---- BARU: data graph untuk visualisasi ----
    keep_idx = np.argsort(-pr)[: req.graph_nodes]
    keep = {nodes[i] for i in keep_idx}
    graph = {
        "nodes": [
            {
                "id": nodes[i],
                "depth": depth[nodes[i]],
                "pr": float(pr[i]),
                "in": int(indeg[i]),
                "out": int(outdeg[i]),
            }
            for i in keep_idx
        ],
        "links": [
            {"source": s, "target": t}
            for s, t in edges
            if s in keep and t in keep
        ][:20000],
        "truncated": len(nodes) > len(keep),
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
        "top10": top,
        "graph": graph,
    }
    if req.include_edges:
        result["edges"] = [{"src": s, "dst": t} for s, t in list(edges)[:20000]]
        result["depths"] = depth
    return result

@app.get("/api/health")
def health():
    return {"ok": True}


# Hanya untuk jalan lokal / di server lab (di Vercel, public/ disajikan otomatis)
if os.path.isdir("public"):
    app.mount("/", StaticFiles(directory="public", html=True), name="static")