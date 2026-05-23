import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'C:/repos/PythiaxEngine/analisis/_staging_v2e2_violet_dense.html'
with open(path, encoding='utf-8') as f:
    c = f.read()
print('chars:', len(c))
bi = c.find('<body')
print('body at char:', bi)
# Find topbar and kpi-strip positions
for marker in ['<div class="topbar"', '<section class="kpi-strip"', 'class="topbar"', 'class="kpi-strip"', 'id="ticker', 'tkb1', 'h7-nav', 'h7-strip', '<header', 'class="main-wrap"']:
    idx = c.find(marker)
    print(f'{marker!r} at char: {idx}')
# Show body start
print('\n--- BODY START (3000 chars) ---')
print(c[bi:bi+3000])
