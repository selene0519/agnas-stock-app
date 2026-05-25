from pathlib import Path
import json
import pandas as pd
print('=== v92 report row counts ===')
for name in ['v92_today_summary_kr.csv','v92_today_summary_us.csv','v92_symbol_snapshot_kr.csv','v92_symbol_snapshot_us.csv','v92_confidence_cards_kr.csv','v92_confidence_cards_us.csv','v92_operational_dashboard_kr.csv','v92_operational_dashboard_us.csv']:
    p=Path('reports')/name
    if not p.exists():
        print(name, 'MISSING')
    else:
        try:
            print(name, len(pd.read_csv(p, encoding='utf-8-sig')), 'rows', p.stat().st_size, 'bytes')
        except Exception as e:
            print(name, 'READ_ERROR', type(e).__name__, e)
print('\n=== status ===')
p=Path('reports')/'v92_status.json'
if p.exists():
    try:
        data=json.loads(p.read_text(encoding='utf-8'))
        print(json.dumps({k:data.get(k) for k in ['status','version','updated_at','base_status','copied_files','checks']}, ensure_ascii=False, indent=2))
    except Exception as e:
        print('status read error', e)
else:
    print('v92_status.json not found')
