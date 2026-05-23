import re, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('analisis/_staging_prod_preview.html','r',encoding='utf-8') as f:
    content = f.read()

# Try to find all leag-row-clickable divs  
pat = re.compile(r'leag-row-clickable[^>]*>')
matches = pat.findall(content)
print(f'leag-row-clickable tags: {len(matches)}')
if matches:
    print(matches[0][:400])

# Try finding data-spark-vals directly
pat2 = re.compile(r'data-spark-vals="([^"]+)"')
spark_matches = pat2.findall(content)
print(f'\ndata-spark-vals found: {len(spark_matches)}')
if spark_matches:
    print(spark_matches[0][:100])
