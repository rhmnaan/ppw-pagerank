# PPW PageRank

Crawler website + graph link + perhitungan PageRank (top 10), dibuat untuk tugas PPW.

## Alur
Masukkan URL dan kedalaman -> telusuri link secara snowball per level sampai kedalaman tersebut -> bentuk graph dari seluruh halaman dan link yang ditemukan -> hitung PageRank -> tampilkan 10 halaman terpenting beserta kedalaman, inlink, dan outlink.

## Struktur
- `api/index.py` : backend FastAPI (crawler + PageRank)
- `public/index.html` : tampilan web
- `vercel.json` : konfigurasi Vercel

## Jalankan lokal

Pastikan Python sudah terpasang, lalu jalankan perintah berikut dari folder proyek melalui PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn api.index:app --reload
```

Jika PowerShell menolak aktivasi virtual environment, izinkan skrip hanya untuk sesi terminal ini:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Buka http://localhost:8000 di browser. Hentikan server dengan `Ctrl+C`.

## Deploy
- Vercel: import repo ini lalu Deploy
- Server lab: `uvicorn api.index:app --host 0.0.0.0 --port 8000`