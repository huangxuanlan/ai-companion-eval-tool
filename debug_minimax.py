import sqlite3, json, os
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server", "longform.db")
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

# Failed minimax events
rows = db.execute(
    "SELECT e.* FROM conversation_events e "
    "JOIN conversations c ON e.conversation_id = c.id "
    "WHERE c.model_id LIKE '%minimax%' AND e.level IN ('error','warning') "
    "ORDER BY e.created_at DESC LIMIT 10"
).fetchall()
for r in rows:
    d = dict(r)
    detail = d.get("detail_json", "")
    if detail and len(detail) > 500:
        detail = detail[:500] + "..."
    print(f"[{d.get('level')}] {d.get('event_type')} conv={d.get('conversation_id','')[:12]} at={d.get('created_at')}")
    print(f"  detail: {detail}")
    print()

# Also check: are there any minimax conversations with complete data?
print("=== ALL minimax conversations ===")
rows = db.execute(
    "SELECT id, model_id, status, created_at FROM conversations "
    "WHERE model_id LIKE '%minimax%' ORDER BY created_at DESC LIMIT 10"
).fetchall()
for r in rows:
    print(f"  {r['id'][:12]} model={r['model_id']} status={r['status']} at={r['created_at']}")

db.close()
