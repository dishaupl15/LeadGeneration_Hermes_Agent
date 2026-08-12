import ast, sys
sys.stdout.reconfigure(encoding='utf-8')
files = [
    r'd:\Projects\Lead_Generation_Hermes_Agent\backend\app\services\discovery_service.py',
    r'd:\Projects\Lead_Generation_Hermes_Agent\backend\src\routes\leads.py',
]
all_ok = True
for f in files:
    try:
        ast.parse(open(f, encoding='utf-8').read())
        print(f'SYNTAX OK:    {f}')
    except SyntaxError as e:
        print(f'SYNTAX ERROR: {f}  -> {e}')
        all_ok = False
sys.exit(0 if all_ok else 1)
