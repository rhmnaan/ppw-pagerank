# PPW PageRank

Crawler website + graph link + perhitungan PageRank (top 10), dibuat untuk tugas PPW.

## Alur
Masukkan URL -> crawling BFS sampai kedalaman N -> bentuk graph (node = halaman, edge = link) -> hitung PageRank -> tampilkan 10 halaman terpenting beserta kedalaman, inlink, dan outlink.

## Struktur
- `api/index.py` : backend FastAPI (crawler + PageRank)
- `public/index.html` : tampilan web
- `vercel.json` : konfigurasi Vercel

## Jalankan lokal
    pip install -r requirements.txt
    uvicorn api.index:app --reload
Buka http://localhost:8000

## Deploy
- Vercel: import repo ini lalu Deploy
- Server lab: `uvicorn api.index:app --host 0.0.0.0 --port 8000`