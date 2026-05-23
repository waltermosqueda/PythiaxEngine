import pathlib
html = pathlib.Path('C:/repos/PythiaxEngine/analisis/_staging_prod_preview.html').read_text('utf-8')

tkb1_start = html.find('id="ticker-picks"')
# go back to the opening <div
open_div_pos = html.rfind('<div', 0, tkb1_start)
print('tkb1-wrap opens at:', open_div_pos)

# count nested divs
i = open_div_pos
depth = 0
while i < len(html):
    if html[i:i+4] == '<div':
        depth += 1
        i += 4
    elif html[i:i+6] == '</div>':
        depth -= 1
        if depth == 0:
            tkb1_end = i + 6
            print('tkb1-wrap closes at:', tkb1_end)
            print('After close (200 chars):')
            print(repr(html[tkb1_end:tkb1_end+300]))
            break
        i += 6
    else:
        i += 1

# Also find topbar start
topbar_start = html.find('<header class="topbar"')
print('topbar starts at:', topbar_start)
print('Before topbar (50 chars):', repr(html[topbar_start-60:topbar_start]))
