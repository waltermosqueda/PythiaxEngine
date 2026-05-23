import re

content = open('analisis/preview_c1_pro.html', encoding='utf-8').read()
print('Total chars:', len(content))

# Ver atributos data-* usados en el HTML
data_attrs = re.findall(r'data-[\w-]+=', content)
from collections import Counter
print('\ndata-* attributes:', Counter(data_attrs).most_common(20))

# Ver texto cerca de precios/tickers
price_ctx = re.findall(r'.{0,80}(\$[\d,]+\.?\d*).{0,80}', content)
print(f'\nPrice samples (first 5):')
for p in price_ctx[:5]:
    print(' ', repr(p[:100]))

# Ver si hay tablas con precios
table_rows = re.findall(r'<tr[^>]*>.*?</tr>', content, re.DOTALL)
print(f'\nTotal <tr> elements: {len(table_rows)}')
if table_rows:
    print('Sample row:', repr(table_rows[0][:200]))

# Ver estructura de tarjetas de picks
pick_cards = re.findall(r'class=["\'][^"\']*pick[^"\']*["\']', content, re.IGNORECASE)
print(f'\nPick card classes: {Counter(pick_cards).most_common(5)}')

# Buscar dónde aparecen los tickers
ticker_patterns = re.findall(r'data-ticker=["\']([^"\']+)["\']', content)
print(f'\ndata-ticker values (first 10): {ticker_patterns[:10]}')
print(f'Total tickers with data-ticker: {len(ticker_patterns)}')
