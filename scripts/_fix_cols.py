path = r'C:\repos\PythiaxEngine\herramientas\generar_v2e_previews.py'
with open(path, 'r', encoding='utf-8') as f:
    src = f.read()

replacements = [
    ("var cols='20px 1fr 54px 48px 42px 44px 92px';",
     "var cols='18px minmax(62px,1fr) 50px 42px 36px 38px 76px';"),
    ("mspArea(m.sparkVals,m.sparkColor,88,28)",
     "mspArea(m.sparkVals,m.sparkColor,72,26)"),
]

for old, new in replacements:
    if old in src:
        src = src.replace(old, new, 1)
        print(f"OK: {old[:40]}")
    else:
        print(f"NOT FOUND: {old[:40]}")

with open(path, 'w', encoding='utf-8') as f:
    f.write(src)
print("done")
