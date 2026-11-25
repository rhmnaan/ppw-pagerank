import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "id,en;q=0.8",
}
URLS = ["https://www.trunojoyo.ac.id", "https://www.binus.ac.id"]

print("== requests + header browser ==")
for u in URLS:
    try:
        r = requests.get(u, headers=HEADERS, timeout=10)
        print(u, "->", r.status_code, "|", r.url)
    except Exception as e:
        print(u, "-> ERROR:", type(e).__name__)

print("== curl_cffi (meniru TLS Chrome) ==")
try:
    from curl_cffi import requests as cr
    for u in URLS:
        try:
            r = cr.get(u, headers=HEADERS, timeout=10, impersonate="chrome")
            print(u, "->", r.status_code, "|", r.url)
        except Exception as e:
            print(u, "-> ERROR:", type(e).__name__)
except ImportError:
    print("curl_cffi belum terpasang: jalankan  pip install curl_cffi  lalu ulangi")