import re, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('C:/repos/PythiaxEngine/analisis/_header_h7t3b.html', encoding='utf-8') as f:
    content = f.read()
print('Total chars:', len(content))
ids = re.findall(r'id="([\w-]+)"', content)
print('IDs found:', ids)
# Show line count
lines = content.split('\n')
print('Total lines:', len(lines))
# Show first/last 30 lines
print('\n--- FIRST 60 LINES ---')
for i,l in enumerate(lines[:60], 1):
    print(f'{i:4}: {l[:120]}')
