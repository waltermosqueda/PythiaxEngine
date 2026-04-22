import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
html = (ROOT / "analisis" / "preview_c1_pro.html").read_text(encoding="utf-8")
sys.stdout.write("hm-today occurrences: " + str(html.count("hm-today")) + "\n")
sys.stdout.write("hm-today-hdr: " + str(html.count("hm-today-hdr")) + "\n")
sys.stdout.write("al cierre: " + str(html.count("al cierre")) + "\n")
sys.stdout.write("hm-today-empty: " + str(html.count("hm-today-empty")) + "\n")
# show first hm-today cell
import re
m = re.search(r"hm-today[^>]*data-tip='([^']*)'", html)
if m:
    sys.stdout.write("Sample tip: " + m.group(1)[:120] + "\n")
