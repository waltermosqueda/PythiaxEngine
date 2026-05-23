"""
Staging HTTP server para preview_c1_pro.html / _staging_prod_preview.html
Sirve la carpeta analisis/ en http://localhost:8765/
Mima los headers de Cloudflare Pages:
  - Content-Type correcto (utf-8)
  - Sin cache (para ver cambios al instante)
  - No se bloquea con CORS al cargar Bootstrap Icons CDN
Uso:
  python herramientas/staging_server.py
  Luego abrir: http://localhost:8765/_staging_prod_preview.html
"""
import http.server
import socketserver
import os
import sys

PORT = 8765
SERVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analisis")


class StagingHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SERVE_DIR, **kwargs)

    def end_headers(self):
        # Sin cache — cada recarga lee el archivo desde disco
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        # Permite Bootstrap Icons CDN (evita bloqueos CORS en algunos browsers)
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def guess_type(self, path):
        # Forzar utf-8 en HTML (compatible Python 3.9+)
        result = super().guess_type(path)
        ctype = result if isinstance(result, str) else (result[0] if result else "application/octet-stream")
        if ctype and ctype.startswith("text/html"):
            return "text/html; charset=utf-8"
        return ctype

    def log_message(self, fmt, *args):
        # Logging limpio
        print(f"[staging] {self.address_string()} {fmt % args}")


def main():
    if not os.path.isdir(SERVE_DIR):
        print(f"ERROR: directorio analisis/ no encontrado en {SERVE_DIR}", file=sys.stderr)
        sys.exit(1)

    with socketserver.TCPServer(("", PORT), StagingHandler) as httpd:
        httpd.allow_reuse_address = True
        print(f"[staging] Sirviendo analisis/ en http://localhost:{PORT}/")
        print(f"[staging] Dashboard staging:  http://localhost:{PORT}/_staging_prod_preview.html")
        print(f"[staging] Dashboard prod (local): http://localhost:{PORT}/preview_c1_pro.html")
        print("[staging] Ctrl+C para detener")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[staging] Detenido.")


if __name__ == "__main__":
    main()
