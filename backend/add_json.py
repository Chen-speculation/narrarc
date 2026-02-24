import sys
path = r'scripts/run_realtalk_eval.py'
with open(path, encoding='utf-8') as f:
    c = f.read()
if 'import json' not in c[:500]:
    c = c.replace('import argparse\nimport subprocess', 'import argparse\nimport json\nimport subprocess')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(c)
    print('Added json import')
else:
    print('json already imported')
