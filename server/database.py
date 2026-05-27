"""
长文模式多轮对话验证工具 — SQLite 数据层

3 张表：presets / conversations / turn_results
"""
import json
import sqlite3
import uuid
from datetime import datetime
from functools import lru_cache

from config import DB_PATH, DEFAULT_SCORING_MODEL


def _infer_conversation_channel_from_text(prompt_text: str) -> str:
    text = str(prompt_text or "").strip()
    if not text:
        return ""
    if any(keyword in text for keyword in ("1V1语音聊天", "语音聊天", "电话聊天", "语音通话")):
        return "电话聊天沟通"
    if any(keyword in text for keyword in ("文字聊天", "文本聊天")):
        return "文字聊天沟通"
    return ""


@lru_cache(maxsize=64)
def _infer_conversation_channel_from_prompt_ref(prompt_ref: str) -> str:
    ref = str(prompt_ref or "").strip()
    if not ref:
        return ""
    try:
        from services.prompt_service import PromptService

        prompt_service = PromptService()
        template = prompt_service.load_prompt_template(ref)
        system_prompt = prompt_service.extract_system_prompt(template)
    except Exception:
        return ""
    return _infer_conversation_channel_from_text(system_prompt)


def infer_conversation_channel(config: dict | None, prompt_ref: str = "") -> str:
    cfg = dict(config or {})
    runtime = dict(cfg.get("runtime", {}) or {})
    explicit = str(runtime.get("conversation_channel", "")).strip()
    if explicit:
        return explicit
    resolved_prompt = str(cfg.get("prompt_file", "") or prompt_ref or "").strip()
    return _infer_conversation_channel_from_prompt_ref(resolved_prompt)


def get_latest_conversation_channel(role_name: str = "", exclude_conv_id: str = "") -> str:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, prompt_version, config_json
           FROM conversations
           ORDER BY datetime(COALESCE(updated_at, created_at)) DESC"""
    ).fetchall()
    conn.close()

    target_role = str(role_name or "").strip()
    excluded = str(exclude_conv_id or "").strip()
    for row in rows:
        if excluded and row["id"] == excluded:
            continue
        config = json.loads(row["config_json"] or "{}")
        current_role = str(
            dict(config.get("character", {}) or {}).get("Role_Nickname", "")
        ).strip()
        if target_role and current_role != target_role:
            continue
        channel = infer_conversation_channel(config, str(row["prompt_version"] or "").strip())
        if channel:
            return channel
    return ""


def get_latest_dialogue_summary(role_name: str = "", exclude_conv_id: str = "") -> str:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT c.id, c.config_json, t.dialogue_summary
        FROM conversations c
        JOIN turn_results t ON t.conversation_id = c.id
        WHERE TRIM(COALESCE(t.dialogue_summary, '')) != ''
          AND c.archived_at IS NULL
        ORDER BY datetime(COALESCE(c.updated_at, c.created_at)) DESC, t.turn DESC
        """
    ).fetchall()
    conn.close()

    target_role = str(role_name or "").strip()
    excluded = str(exclude_conv_id or "").strip()
    for row in rows:
        if excluded and row["id"] == excluded:
            continue
        config = json.loads(row["config_json"] or "{}")
        current_role = str(
            dict(config.get("character", {}) or {}).get("Role_Nickname", "")
        ).strip()
        if target_role and current_role != target_role:
            continue
        summary = str(row["dialogue_summary"] or "").strip()
        if summary:
            return summary
    return ""


def get_connection() -> sqlite3.Connection:
    """获取 SQLite 连接（开启 WAL 模式 + 外键约束）"""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _normalize_date_only(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text[:10]).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _normalize_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_ai_report_meta(
    *,
    conversation_status: str = "",
    total_turns: int = 0,
    scored_turns: int = 0,
    failed_turns: int = 0,
    skipped_turns: int = 0,
    ai_report_count: int = 0,
    ai_report_updated_at: str = "",
    ai_report_event: str = "",
    ai_report_event_at: str = "",
) -> dict:
    total = max(0, int(total_turns or 0))
    scored = max(0, int(scored_turns or 0))
    failed = max(0, int(failed_turns or 0))
    skipped = max(0, int(skipped_turns or 0))
    report_count = max(0, int(ai_report_count or 0))
    done = scored + failed + skipped
    scoring_complete = total > 0 and done >= total
    normalized_status = str(conversation_status or "").strip().lower()
    normalized_event = str(ai_report_event or "").strip().lower()

    if report_count > 0 or normalized_event in {"summary_generated", "summary_cache_hit"}:
        report_status = "ready"
        report_label = "报告就绪"
    elif normalized_event == "summary_generation_started":
        report_status = "generating"
        report_label = "报告生成中"
    elif normalized_event == "summary_preheat_failed":
        report_status = "failed"
        report_label = "报告生成失败"
    elif total <= 0:
        report_status = "idle"
        report_label = "暂无报告"
    elif normalized_status in {"running", "queued", "pending"}:
        report_status = "waiting_generation"
        report_label = "生成中，待评分"
    elif not scoring_complete:
        report_status = "waiting_scoring"
        report_label = f"待评分完成 {done}/{total}"
    elif scored <= 0:
        report_status = "blocked_no_score"
        report_label = "无已评分轮次"
    else:
        report_status = "pending"
        report_label = "等待生成报告"

    return {
        "ai_report_status": report_status,
        "ai_report_label": report_label,
        "ai_report_ready": report_status == "ready",
        "ai_report_count": report_count,
        "ai_report_updated_at": str(ai_report_updated_at or "").strip(),
        "ai_report_event": normalized_event,
        "ai_report_event_at": str(ai_report_event_at or "").strip(),
        "scoring_done_turns": done,
        "scoring_complete": scoring_complete,
    }


def get_conversation_ai_report_meta(
    conv_id: str,
    *,
    conversation_status: str = "",
    total_turns: int = 0,
    scored_turns: int = 0,
    failed_turns: int = 0,
    skipped_turns: int = 0,
) -> dict:
    conn = get_connection()
    report_count = 0
    report_updated_at = ""
    report_event = ""
    report_event_at = ""
    if _table_exists(conn, "ai_report_summaries"):
        report_row = conn.execute(
            """
            SELECT COUNT(*) AS report_count, MAX(created_at) AS updated_at
            FROM ai_report_summaries
            WHERE target_type='conversation_scoring'
              AND target_id=?
              AND report_kind='scoring_report'
            """,
            (conv_id,),
        ).fetchone()
        if report_row:
            report_count = int(report_row["report_count"] or 0)
            report_updated_at = str(report_row["updated_at"] or "").strip()
    if _table_exists(conn, "conversation_events"):
        event_row = conn.execute(
            """
            SELECT event_type, created_at
            FROM conversation_events
            WHERE conversation_id=?
              AND scope='scoring'
              AND event_type IN (
                'summary_generation_started',
                'summary_generated',
                'summary_cache_hit',
                'summary_preheat_failed',
                'summary_invalidated'
              )
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 1
            """,
            (conv_id,),
        ).fetchone()
        if event_row:
            report_event = str(event_row["event_type"] or "").strip()
            report_event_at = str(event_row["created_at"] or "").strip()
    conn.close()
    return _derive_ai_report_meta(
        conversation_status=conversation_status,
        total_turns=total_turns,
        scored_turns=scored_turns,
        failed_turns=failed_turns,
        skipped_turns=skipped_turns,
        ai_report_count=report_count,
        ai_report_updated_at=report_updated_at,
        ai_report_event=report_event,
        ai_report_event_at=report_event_at,
    )


def init_db():
    """初始化数据库表结构"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS presets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            config_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mode TEXT DEFAULT 'long'
        );

        CREATE TABLE IF NOT EXISTS saved_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            config_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mode TEXT DEFAULT 'long'
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            preset_id TEXT,
            model_id TEXT NOT NULL,
            model_mini TEXT,
            prompt_version TEXT DEFAULT '',
            config_json TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            pinned INTEGER DEFAULT 0,
            archived_at TIMESTAMP,
            mode TEXT DEFAULT 'long',
            FOREIGN KEY (preset_id) REFERENCES presets(id)
        );

        CREATE TABLE IF NOT EXISTS turn_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            turn INTEGER NOT NULL,
            user_input TEXT,
            ai_output TEXT,
            word_count INTEGER DEFAULT 0,
            dialogue_summary TEXT DEFAULT '',
            msg_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            latency_s REAL DEFAULT 0,
            has_deep_injection INTEGER DEFAULT 0,
            has_style_isolation INTEGER DEFAULT 0,
            has_cooldown_reinject INTEGER DEFAULT 0,
            token_trim_level INTEGER DEFAULT 0,
            quality_retries INTEGER DEFAULT 0,
            messages_snapshot TEXT DEFAULT '[]',
            request_payload_snapshot TEXT DEFAULT '{}',
            model_id TEXT DEFAULT '',
            -- Phase 3: 打分结果列
            score_persona_fidelity REAL DEFAULT 0,
            score_narrative_immersion REAL DEFAULT 0,
            score_emotional_tension REAL DEFAULT 0,
            score_boundary_memory REAL DEFAULT 0,
            score_format_compliance REAL DEFAULT 0,
            score_context_coherence REAL DEFAULT 0,
            score_total REAL DEFAULT 0,
            score_reasoning TEXT DEFAULT '',
            score_status TEXT DEFAULT 'unscored',
            mode TEXT DEFAULT 'long',
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_turns_conv
            ON turn_results(conversation_id);
    """)
    _ensure_column(conn, "conversations", "updated_at", "TIMESTAMP")
    _ensure_column(conn, "conversations", "pinned", "INTEGER DEFAULT 0")
    _ensure_column(conn, "conversations", "archived_at", "TIMESTAMP")
    _ensure_column(conn, "turn_results", "request_payload_snapshot", "TEXT DEFAULT '{}'")
    conn.execute(
        "UPDATE conversations SET updated_at=COALESCE(updated_at, created_at)"
    )
    conn.commit()
    conn.close()


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
):
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _touch_conversation(conn: sqlite3.Connection, conv_id: str):
    conn.execute(
        "UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (conv_id,),
    )


# ── Preset CRUD ───────────────────────────────────────────────

def create_preset(name: str, type_: str, config: dict, mode: str = "long") -> str:
    preset_id = str(uuid.uuid4())[:8]
    conn = get_connection()
    conn.execute(
        "INSERT INTO presets (id, name, type, config_json, mode) VALUES (?, ?, ?, ?, ?)",
        (preset_id, name, type_, json.dumps(config, ensure_ascii=False), mode),
    )
    conn.commit()
    conn.close()
    return preset_id


def get_preset(preset_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM presets WHERE id=?", (preset_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {**dict(row), "config": json.loads(row["config_json"])}


def list_presets(mode: str = "") -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, type, created_at, COALESCE(mode, 'long') as mode FROM presets ORDER BY created_at"
    ).fetchall()
    conn.close()
    res = [dict(r) for r in rows]
    if mode:
        res = [r for r in res if r["mode"] == mode]
    return res


def delete_preset(preset_id: str) -> bool:
    conn = get_connection()
    # 保留历史会话，只解除模板引用，允许删除已被使用过的自定义模板。
    conn.execute(
        "UPDATE conversations SET preset_id=NULL WHERE preset_id=?",
        (preset_id,),
    )
    cur = conn.execute("DELETE FROM presets WHERE id=?", (preset_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def create_saved_config(name: str, config: dict, type_: str = "custom_config", mode: str = "long") -> str:
    config_id = f"cfg_{uuid.uuid4().hex[:8]}"
    conn = get_connection()
    conn.execute(
        """INSERT INTO saved_configs (id, name, type, config_json, mode)
           VALUES (?, ?, ?, ?, ?)""",
        (config_id, name, type_, json.dumps(config, ensure_ascii=False), mode),
    )
    conn.commit()
    conn.close()
    return config_id


def get_saved_config(config_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM saved_configs WHERE id=?",
        (config_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {**dict(row), "config": json.loads(row["config_json"])}


def list_saved_configs(mode: str = "") -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, type, created_at, config_json, COALESCE(mode, 'long') as mode FROM saved_configs ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json", "{}"))
        if mode and item["mode"] != mode:
            continue
        result.append(item)
    return result


# ── Conversation CRUD ─────────────────────────────────────────

def create_conversation(
    model_id: str,
    config: dict,
    preset_id: str | None = None,
    model_mini: str | None = None,
    prompt_version: str = "",
    mode: str = "long",
) -> str:
    conv_id = str(uuid.uuid4())[:8]
    conn = get_connection()
    conn.execute(
        """INSERT INTO conversations
           (id, preset_id, model_id, model_mini, prompt_version, config_json, status, mode)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (conv_id, preset_id, model_id, model_mini or "",
         prompt_version, json.dumps(config, ensure_ascii=False), mode),
    )
    conn.commit()
    conn.close()
    return conv_id


def update_conversation_status(conv_id: str, status: str):
    conn = get_connection()
    conn.execute(
        "UPDATE conversations SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, conv_id)
    )
    conn.commit()
    conn.close()


def update_conversation_config(conv_id: str, config: dict) -> bool:
    """更新会话配置快照，用于恢复元数据持久化。"""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE conversations SET config_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (json.dumps(config, ensure_ascii=False), conv_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def set_conversation_pinned(conv_id: str, pinned: bool) -> bool:
    conn = get_connection()
    cur = conn.execute(
        "UPDATE conversations SET pinned=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (1 if pinned else 0, conv_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_conversation(conv_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not row:
        conn.close()
        return None
    conv = {**dict(row), "config": json.loads(row["config_json"])}
    # 附加 turn_results
    turns = conn.execute(
        "SELECT * FROM turn_results WHERE conversation_id=? ORDER BY turn",
        (conv_id,),
    ).fetchall()
    conn.close()
    runtime = conv.get("config", {}).get("runtime", {})
    conv["summary_prompt_version"] = runtime.get("summary_prompt_version", "")
    conv["scoring_prompt_version"] = runtime.get("scoring_prompt_version", "")
    conv["scoring_model_id"] = runtime.get("scoring_model_id", DEFAULT_SCORING_MODEL)
    conv["conversation_channel"] = infer_conversation_channel(
        conv.get("config", {}),
        conv.get("prompt_version", ""),
    )
    conv["archived"] = bool(conv.get("archived_at"))
    conv["results"] = [
        {
            **dict(t),
            "messages_snapshot": json.loads(t["messages_snapshot"] or "[]"),
            "request_payload_snapshot": json.loads(
                t["request_payload_snapshot"] or "{}"
            ),
        }
        for t in turns
    ]
    scored_count = 0
    failed_count = 0
    skipped_count = 0
    scored_totals = [
        float(item.get("score_total", 0) or 0)
        for item in conv["results"]
        if str(item.get("score_status", "")).strip() == "scored"
    ]
    for item in conv["results"]:
        status = str(item.get("score_status", "")).strip()
        if status == "scored":
            scored_count += 1
        elif status == "failed":
            failed_count += 1
        elif status == "skipped":
            skipped_count += 1
    conv["score_avg"] = (
        round(sum(scored_totals) / len(scored_totals), 2)
        if scored_totals
        else (0.0 if skipped_count > 0 else None)
    )
    conv["scored_turns"] = scored_count
    conv["failed_turns"] = failed_count
    conv["skipped_turns"] = skipped_count
    latest_turn = conv["results"][-1] if conv["results"] else {}
    conv["last_message_preview"] = str(
        latest_turn.get("ai_output") or latest_turn.get("user_input") or ""
    ).strip()
    conv["pinned"] = bool(conv.get("pinned"))
    return conv


def list_conversations(
    *,
    model_id: str = "",
    date_from: str = "",
    date_to: str = "",
    status: str = "",
    min_score=None,
    max_score=None,
    archived: bool | None = None,
    include_archived: bool = False,
    mode: str = "",
) -> list:
    conn = get_connection()
    has_ai_report_summaries = _table_exists(conn, "ai_report_summaries")
    has_conversation_events = _table_exists(conn, "conversation_events")
    ai_report_count_sql = (
        """(SELECT COUNT(*) FROM ai_report_summaries s
                   WHERE s.target_type = 'conversation_scoring'
                     AND s.target_id = c.id
                     AND s.report_kind = 'scoring_report') as ai_report_count"""
        if has_ai_report_summaries
        else "0 as ai_report_count"
    )
    ai_report_updated_sql = (
        """(SELECT MAX(s.created_at) FROM ai_report_summaries s
                   WHERE s.target_type = 'conversation_scoring'
                     AND s.target_id = c.id
                     AND s.report_kind = 'scoring_report') as ai_report_updated_at"""
        if has_ai_report_summaries
        else "'' as ai_report_updated_at"
    )
    ai_report_event_sql = (
        """(SELECT e.event_type FROM conversation_events e
                   WHERE e.conversation_id = c.id
                     AND e.scope = 'scoring'
                     AND e.event_type IN (
                       'summary_generation_started',
                       'summary_generated',
                       'summary_cache_hit',
                       'summary_preheat_failed',
                       'summary_invalidated'
                     )
                   ORDER BY datetime(e.created_at) DESC, e.id DESC
                   LIMIT 1) as ai_report_event"""
        if has_conversation_events
        else "'' as ai_report_event"
    )
    ai_report_event_at_sql = (
        """(SELECT e.created_at FROM conversation_events e
                   WHERE e.conversation_id = c.id
                     AND e.scope = 'scoring'
                     AND e.event_type IN (
                       'summary_generation_started',
                       'summary_generated',
                       'summary_cache_hit',
                       'summary_preheat_failed',
                       'summary_invalidated'
                     )
                   ORDER BY datetime(e.created_at) DESC, e.id DESC
                   LIMIT 1) as ai_report_event_at"""
        if has_conversation_events
        else "'' as ai_report_event_at"
    )
    rows = conn.execute(
        f"""SELECT c.id, c.preset_id, c.model_id, c.model_mini, c.prompt_version, c.status, c.created_at,
                  COALESCE(c.updated_at, c.created_at) as updated_at,
                  COALESCE(c.pinned, 0) as pinned,
                  c.archived_at,
                  c.config_json,
                  COALESCE(c.mode, 'long') as mode,
                  (SELECT COUNT(*) FROM turn_results t WHERE t.conversation_id = c.id) as total_turns,
                  (SELECT COALESCE(NULLIF(TRIM(t.ai_output), ''), NULLIF(TRIM(t.user_input), ''), '')
                   FROM turn_results t
                   WHERE t.conversation_id = c.id
                   ORDER BY t.turn DESC
                   LIMIT 1) as last_message_preview,
                  (SELECT AVG(t.score_total) FROM turn_results t
                   WHERE t.conversation_id = c.id AND t.score_status = 'scored') as score_avg,
                  (SELECT COUNT(*) FROM turn_results t
                   WHERE t.conversation_id = c.id AND t.score_status = 'scored') as scored_turns,
                  (SELECT COUNT(*) FROM turn_results t
                   WHERE t.conversation_id = c.id AND t.score_status = 'failed') as failed_turns,
                  (SELECT COUNT(*) FROM turn_results t
                   WHERE t.conversation_id = c.id AND t.score_status = 'skipped') as skipped_turns,
                  {ai_report_count_sql},
                  {ai_report_updated_sql},
                  {ai_report_event_sql},
                  {ai_report_event_at_sql}
            FROM conversations c
            ORDER BY COALESCE(c.pinned, 0) DESC, datetime(c.created_at) DESC,
                     datetime(COALESCE(c.updated_at, c.created_at)) DESC"""
    ).fetchall()
    conn.close()
    result = []
    normalized_model = str(model_id or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    normalized_from = _normalize_date_only(date_from)
    normalized_to = _normalize_date_only(date_to)
    min_score_value = _normalize_float(min_score)
    max_score_value = _normalize_float(max_score)
    include_archived = bool(include_archived or archived is True)
    for r in rows:
        d = dict(r)
        config = json.loads(d.pop("config_json", "{}"))
        character = config.get("character", {})
        d["nickname"] = character.get("Role_Nickname", "")
        d["character_type"] = character.get("personal_type") or character.get("personality") or ""
        d["relationship"] = config.get("context", {}).get("relationship", "")
        d["model"] = d["model_id"]
        d["prompt_file"] = config.get("prompt_file", "")
        d["prompt_version"] = d.get("prompt_version") or d["prompt_file"]
        runtime = config.get("runtime", {})
        completed_turns = d.get("total_turns", 0)
        d["completed_turns"] = completed_turns
        d["total_turns"] = runtime.get("total_turns", completed_turns)
        d["next_turn_index"] = runtime.get("next_turn_index", completed_turns)
        d["resume_supported"] = bool(runtime.get("resume_supported"))
        d["summary_prompt_version"] = runtime.get("summary_prompt_version", "")
        d["scoring_prompt_version"] = runtime.get("scoring_prompt_version", "")
        d["scoring_model_id"] = runtime.get("scoring_model_id", DEFAULT_SCORING_MODEL)
        d["archived"] = bool(d.get("archived_at"))
        d["conversation_channel"] = infer_conversation_channel(
            config,
            d.get("prompt_version", ""),
        )
        d["source"] = "preset" if d.get("preset_id") else "conversation"
        d.update(
            _derive_ai_report_meta(
                conversation_status=d.get("status", ""),
                total_turns=d.get("total_turns", 0),
                scored_turns=d.get("scored_turns", 0),
                failed_turns=d.get("failed_turns", 0),
                skipped_turns=d.get("skipped_turns", 0),
                ai_report_count=d.get("ai_report_count", 0),
                ai_report_updated_at=d.get("ai_report_updated_at", ""),
                ai_report_event=d.get("ai_report_event", ""),
                ai_report_event_at=d.get("ai_report_event_at", ""),
            )
        )
        if d.get("score_avg") is None and int(d.get("skipped_turns") or 0) > 0:
            d["score_avg"] = 0.0
        d["last_message_preview"] = (d.get("last_message_preview") or "").strip()
        d["pinned"] = bool(d.get("pinned"))
        created_date = str(d.get("created_at") or "")[:10]
        current_score = _normalize_float(d.get("score_avg"))
        if mode and str(d.get("mode", "long")).strip().lower() != str(mode).strip().lower():
            continue
        if d["archived"] and not include_archived:
            continue
        if archived is True and not d["archived"]:
            continue
        if archived is False and d["archived"]:
            continue
        if normalized_model and normalized_model not in str(d.get("model_id", "")).strip().lower():
            continue
        if normalized_status and normalized_status != str(d.get("status", "")).strip().lower():
            continue
        if normalized_from and created_date and created_date < normalized_from:
            continue
        if normalized_to and created_date and created_date > normalized_to:
            continue
        if min_score_value is not None:
            if current_score is None or current_score < min_score_value:
                continue
        if max_score_value is not None:
            if current_score is None or current_score > max_score_value:
                continue
        result.append(d)
    return result


def delete_conversation(conv_id: str) -> bool:
    conn = get_connection()
    if _table_exists(conn, "ai_report_summaries"):
        conn.execute(
            "DELETE FROM ai_report_summaries WHERE target_type='conversation_scoring' AND target_id=?",
            (conv_id,),
        )
    if _table_exists(conn, "conversation_events"):
        conn.execute(
            "DELETE FROM conversation_events WHERE conversation_id=?",
            (conv_id,),
        )
    cur = conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def delete_turn_results(conv_id: str) -> int:
    conn = get_connection()
    cur = conn.execute("DELETE FROM turn_results WHERE conversation_id=?", (conv_id,))
    _touch_conversation(conn, conv_id)
    conn.commit()
    conn.close()
    return cur.rowcount


def delete_turn_result(conv_id: str, turn: int) -> int:
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM turn_results WHERE conversation_id=? AND turn=?",
        (conv_id, turn),
    )
    _touch_conversation(conn, conv_id)
    conn.commit()
    conn.close()
    return cur.rowcount


# ── TurnResult CRUD ───────────────────────────────────────────

def insert_turn_result(conv_id: str, data: dict) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO turn_results
           (conversation_id, turn, user_input, ai_output, word_count,
            dialogue_summary, msg_count, input_tokens, output_tokens,
            latency_s, has_deep_injection, has_style_isolation,
            has_cooldown_reinject, token_trim_level, quality_retries,
            messages_snapshot, request_payload_snapshot, model_id, mode)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            conv_id, data["turn"], data.get("user_input", ""),
            data.get("ai_output", ""), data.get("word_count", 0),
            data.get("dialogue_summary", ""), data.get("msg_count", 0),
            data.get("input_tokens", 0), data.get("output_tokens", 0),
            data.get("latency_s", 0),
            int(data.get("has_deep_injection", False)),
            int(data.get("has_style_isolation", False)),
            int(data.get("has_cooldown_reinject", False)),
            data.get("token_trim_level", 0),
            data.get("quality_retries", 0),
            json.dumps(data.get("messages_snapshot", []), ensure_ascii=False),
            json.dumps(data.get("request_payload_snapshot", {}), ensure_ascii=False),
            data.get("model_id", ""),
            data.get("mode", "long"),
        ),
    )
    _touch_conversation(conn, conv_id)
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_turn_results(conv_id: str) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM turn_results WHERE conversation_id=? ORDER BY turn",
        (conv_id,),
    ).fetchall()
    conn.close()
    return [
        {
            **dict(r),
            "messages_snapshot": json.loads(r["messages_snapshot"] or "[]"),
            "request_payload_snapshot": json.loads(
                r["request_payload_snapshot"] or "{}"
            ),
        }
        for r in rows
    ]


def get_history_context(
    conv_id: str,
    current_turn: int,
    *,
    max_turns: int = 10,
    max_chars: int = 8000,
) -> str:
    """读取当前轮之前最近若干轮原始对话，供 v4.0 打分提示词注入。"""
    try:
        normalized_turn = max(1, int(current_turn or 0))
    except (TypeError, ValueError):
        normalized_turn = 1
    normalized_limit = max(1, int(max_turns or 10))
    normalized_chars = max(256, int(max_chars or 8000))

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT turn, user_input, ai_output
        FROM turn_results
        WHERE conversation_id=? AND turn < ?
        ORDER BY turn DESC
        LIMIT ?
        """,
        (conv_id, normalized_turn, normalized_limit),
    ).fetchall()
    conn.close()
    if not rows:
        return ""

    lines: list[str] = []
    for row in reversed(rows):
        user_input = str(row["user_input"] or "").strip()
        ai_output = str(row["ai_output"] or "").strip()
        if user_input:
            lines.append(f"[用户] {user_input}")
        if ai_output:
            lines.append(f"[AI] {ai_output}")
    history = "\n".join(lines)
    if len(history) > normalized_chars:
        history = history[-normalized_chars:]
    return history


def update_turn_dialogue_summary(
    conv_id: str,
    turn: int,
    dialogue_summary: str,
) -> bool:
    conn = get_connection()
    cur = conn.execute(
        """UPDATE turn_results
           SET dialogue_summary=?
           WHERE conversation_id=? AND turn=?""",
        (str(dialogue_summary or ""), conv_id, turn),
    )
    _touch_conversation(conn, conv_id)
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def set_conversation_archived(conv_id: str, archived: bool) -> bool:
    conn = get_connection()
    cur = conn.execute(
        """
        UPDATE conversations
        SET archived_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (1 if archived else 0, conv_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def recalculate_conversation_avg(conv_id: str) -> dict:
    """重算对话平均分，只计入 score_status='scored' 的轮次。"""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT
            AVG(CASE WHEN score_status='scored' THEN score_total END) AS avg_total,
            SUM(CASE WHEN score_status='scored' THEN 1 ELSE 0 END) AS scored_count,
            SUM(CASE WHEN score_status='failed' THEN 1 ELSE 0 END) AS failed_count,
            SUM(CASE WHEN score_status='skipped' THEN 1 ELSE 0 END) AS skipped_count,
            COUNT(*) AS total_count
        FROM turn_results
        WHERE conversation_id=?
        """,
        (conv_id,),
    ).fetchone()
    conn.close()
    return {
        "avg_total": round(float(row["avg_total"] or 0), 2),
        "scored_count": int(row["scored_count"] or 0),
        "failed_count": int(row["failed_count"] or 0),
        "skipped_count": int(row["skipped_count"] or 0),
        "total_count": int(row["total_count"] or 0),
    }


def update_turn_scores(conv_id: str, turn: int, scores: dict):
    """更新某轮的打分结果"""
    score_status = str(scores.get("score_status", "") or "").strip()
    if not score_status:
        score_status = "scored" if scores.get("success", False) else "failed"
    conn = get_connection()
    conn.execute(
        """UPDATE turn_results SET
           score_persona_fidelity=?, score_narrative_immersion=?,
           score_emotional_tension=?, score_boundary_memory=?,
           score_format_compliance=?, score_context_coherence=?, score_total=?,
           score_reasoning=?, score_status=?
           WHERE conversation_id=? AND turn=?""",
        (
            scores.get("persona_fidelity", 0),
            scores.get("narrative_immersion", 0),
            scores.get("emotional_tension", 0),
            scores.get("boundary_memory", 0),
            scores.get("format_compliance", 0),
            scores.get("context_coherence", 0),
            scores.get("mapped_total", 0),
            scores.get("reasoning", ""),
            score_status,
            conv_id, turn,
        ),
    )
    _touch_conversation(conn, conv_id)
    conn.commit()
    conn.close()


def reset_conversation_scores(conv_id: str) -> None:
    """清空整段对话的 AI 打分结果，供切换评分模型后重打分。"""
    conn = get_connection()
    conn.execute(
        """
        UPDATE turn_results
        SET
            score_persona_fidelity=0,
            score_narrative_immersion=0,
            score_emotional_tension=0,
            score_boundary_memory=0,
            score_format_compliance=0,
            score_context_coherence=0,
            score_total=0,
            score_reasoning='',
            score_status='unscored'
        WHERE conversation_id=?
        """,
        (conv_id,),
    )
    _touch_conversation(conn, conv_id)
    conn.commit()
    conn.close()


def migrate_add_score_columns():
    """兼容旧数据库：如果 turn_results 缺少打分列则 ALTER TABLE 追加"""
    conn = get_connection()
    cursor = conn.execute("PRAGMA table_info(turn_results)")
    existing = {row["name"] for row in cursor.fetchall()}
    new_cols = [
        ("score_persona_fidelity", "REAL DEFAULT 0"),
        ("score_narrative_immersion", "REAL DEFAULT 0"),
        ("score_emotional_tension", "REAL DEFAULT 0"),
        ("score_boundary_memory", "REAL DEFAULT 0"),
        ("score_format_compliance", "REAL DEFAULT 0"),
        ("score_context_coherence", "REAL DEFAULT 0"),
        ("score_total", "REAL DEFAULT 0"),
        ("score_reasoning", "TEXT DEFAULT ''"),
        ("score_status", "TEXT DEFAULT 'unscored'"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE turn_results ADD COLUMN {col_name} {col_type}"
            )
    conn.commit()
    conn.close()


def migrate_add_v51_columns():
    """v5.1 迁移：人工打分列 + model_id 列"""
    conn = get_connection()
    cursor = conn.execute("PRAGMA table_info(turn_results)")
    existing = {row["name"] for row in cursor.fetchall()}
    new_cols = [
        ("model_id", "TEXT DEFAULT ''"),
        ("manual_star_score", "REAL"),
        ("manual_comment", "TEXT DEFAULT ''"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE turn_results ADD COLUMN {col_name} {col_type}"
            )
    conn.commit()
    conn.close()


def update_manual_score(
    conv_id: str, turn: int, star_score: float, comment: str
):
    """更新人工打分（v5.1）"""
    conn = get_connection()
    conn.execute(
        """UPDATE turn_results SET manual_star_score=?, manual_comment=?
           WHERE conversation_id=? AND turn=?""",
        (star_score, comment, conv_id, turn),
    )
    _touch_conversation(conn, conv_id)
    conn.commit()
    conn.close()


# ── Compare Reports (v5.1) ────────────────────────────────────

def migrate_add_compare_reports_table():
    """v5.1: 创建对比报告表"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS compare_reports (
            id TEXT PRIMARY KEY,
            groups_json TEXT NOT NULL,
            group_results_json TEXT NOT NULL,
            winners_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mode TEXT DEFAULT 'long'
        );
    """)
    conn.close()


def migrate_add_ai_report_summaries_table():
    """创建 AI 摘要缓存表，按源签名保存多版本报告。"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ai_report_summaries (
            id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            report_kind TEXT NOT NULL,
            model_id TEXT NOT NULL,
            prompt_filename TEXT NOT NULL,
            source_signature TEXT NOT NULL,
            markdown TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mode TEXT DEFAULT 'long'
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_report_summaries_unique
            ON ai_report_summaries(
                target_type,
                target_id,
                report_kind,
                model_id,
                prompt_filename,
                source_signature
            );
    """)
    conn.close()


def migrate_add_conversation_events_table():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'generation',
            level TEXT NOT NULL DEFAULT 'info',
            event_type TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mode TEXT DEFAULT 'long'
        );

        CREATE INDEX IF NOT EXISTS idx_conversation_events_conv_created
            ON conversation_events(conversation_id, datetime(created_at) DESC, id DESC);

        CREATE INDEX IF NOT EXISTS idx_conversation_events_scope_level
            ON conversation_events(scope, level);
    """)
    conn.close()


def migrate_add_orchestration_runs_table():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orchestration_runs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            concurrency INTEGER NOT NULL DEFAULT 1,
            manifest_json TEXT NOT NULL DEFAULT '{}',
            state_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mode TEXT DEFAULT 'long'
        );

        CREATE INDEX IF NOT EXISTS idx_orchestration_runs_kind_updated
            ON orchestration_runs(kind, datetime(updated_at) DESC, id DESC);

        CREATE INDEX IF NOT EXISTS idx_orchestration_runs_status_updated
            ON orchestration_runs(status, datetime(updated_at) DESC, id DESC);
    """)
    conn.close()


def migrate_add_ab_sessions_table():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ab_sessions (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'active',
            base_conversation_id TEXT NOT NULL,
            compare_conversation_id TEXT NOT NULL,
            current_turn INTEGER NOT NULL DEFAULT 0,
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mode TEXT DEFAULT 'long'
        );

        CREATE INDEX IF NOT EXISTS idx_ab_sessions_status_updated
            ON ab_sessions(status, datetime(updated_at) DESC, id DESC);

        CREATE INDEX IF NOT EXISTS idx_ab_sessions_created
            ON ab_sessions(datetime(created_at) DESC, id DESC);
    """)
    conn.close()


def migrate_add_mode_columns():
    """v6.0: 为 9 张表动态添加 mode 字段并创建索引"""
    conn = get_connection()
    tables = [
        "presets",
        "saved_configs",
        "conversations",
        "turn_results",
        "compare_reports",
        "ai_report_summaries",
        "conversation_events",
        "orchestration_runs",
        "ab_sessions"
    ]
    for table in tables:
        if _table_exists(conn, table):
            _ensure_column(conn, table, "mode", "TEXT DEFAULT 'long'")

    # 创建索引以提高按模式检索的效率
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_mode ON conversations(mode)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_turn_results_mode ON turn_results(mode)")
    conn.commit()
    conn.close()



def create_orchestration_run(
    kind: str,
    *,
    title: str = "",
    concurrency: int = 1,
    manifest: dict | None = None,
    state: dict | None = None,
    status: str = "pending",
) -> dict:
    run_id = str(uuid.uuid4())[:12]
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO orchestration_runs
        (id, kind, title, status, concurrency, manifest_json, state_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            str(kind or "").strip(),
            str(title or "").strip(),
            str(status or "pending").strip() or "pending",
            max(1, int(concurrency or 1)),
            json.dumps(manifest or {}, ensure_ascii=False),
            json.dumps(state or {}, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return get_orchestration_run(run_id) or {}


def create_ab_session(
    *,
    session_id: str | None = None,
    status: str = "active",
    base_conversation_id: str,
    compare_conversation_id: str,
    current_turn: int = 0,
    config: dict | None = None,
) -> dict:
    session_id = str(session_id or str(uuid.uuid4())[:12]).strip() or str(uuid.uuid4())[:12]
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO ab_sessions
        (id, status, base_conversation_id, compare_conversation_id, current_turn, config_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            str(status or "active").strip() or "active",
            str(base_conversation_id or "").strip(),
            str(compare_conversation_id or "").strip(),
            max(0, int(current_turn or 0)),
            json.dumps(config or {}, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return get_ab_session(session_id) or {}


def get_ab_session(session_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT id, status, base_conversation_id, compare_conversation_id, current_turn, config_json, created_at, updated_at
        FROM ab_sessions
        WHERE id=?
        """,
        (session_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["config"] = json.loads(data.pop("config_json", "{}") or "{}")
    return data


def list_ab_sessions(
    *,
    statuses: list[str] | tuple[str, ...] | None = None,
    limit: int = 20,
) -> list[dict]:
    conn = get_connection()
    sql = """
        SELECT id, status, base_conversation_id, compare_conversation_id, current_turn, config_json, created_at, updated_at
        FROM ab_sessions
        WHERE 1=1
    """
    params: list[object] = []
    normalized_statuses = [
        str(item or "").strip()
        for item in (statuses or [])
        if str(item or "").strip()
    ]
    if normalized_statuses:
        placeholders = ",".join("?" for _ in normalized_statuses)
        sql += f" AND status IN ({placeholders})"
        params.extend(normalized_statuses)
    sql += " ORDER BY datetime(updated_at) DESC, id DESC LIMIT ?"
    params.append(max(1, int(limit or 20)))
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    items: list[dict] = []
    for row in rows:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json", "{}") or "{}")
        items.append(item)
    return items


def update_ab_session(
    session_id: str,
    *,
    status: str | None = None,
    current_turn: int | None = None,
    config: dict | None = None,
) -> dict | None:
    updates: list[str] = []
    params: list[object] = []
    if status is not None:
        updates.append("status=?")
        params.append(str(status or "active").strip() or "active")
    if current_turn is not None:
        updates.append("current_turn=?")
        params.append(max(0, int(current_turn or 0)))
    if config is not None:
        updates.append("config_json=?")
        params.append(json.dumps(config or {}, ensure_ascii=False))
    if not updates:
        return get_ab_session(session_id)
    updates.append("updated_at=CURRENT_TIMESTAMP")
    params.append(session_id)
    conn = get_connection()
    conn.execute(
        f"UPDATE ab_sessions SET {', '.join(updates)} WHERE id=?",
        tuple(params),
    )
    conn.commit()
    conn.close()
    return get_ab_session(session_id)


def get_latest_active_ab_session() -> dict | None:
    items = list_ab_sessions(statuses=["running", "active"], limit=1)
    return items[0] if items else None


def get_orchestration_run(run_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT id, kind, title, status, concurrency, manifest_json, state_json, created_at, updated_at
        FROM orchestration_runs
        WHERE id=?
        """,
        (run_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["manifest"] = json.loads(data.pop("manifest_json", "{}") or "{}")
    data["state"] = json.loads(data.pop("state_json", "{}") or "{}")
    return data


def list_orchestration_runs(
    *,
    kind: str = "",
    statuses: list[str] | tuple[str, ...] | None = None,
    limit: int = 20,
) -> list[dict]:
    conn = get_connection()
    sql = """
        SELECT id, kind, title, status, concurrency, manifest_json, state_json, created_at, updated_at
        FROM orchestration_runs
        WHERE 1=1
    """
    params: list[object] = []
    if str(kind or "").strip():
        sql += " AND kind=?"
        params.append(str(kind).strip())
    normalized_statuses = [str(item or "").strip() for item in (statuses or []) if str(item or "").strip()]
    if normalized_statuses:
        placeholders = ",".join("?" for _ in normalized_statuses)
        sql += f" AND status IN ({placeholders})"
        params.extend(normalized_statuses)
    sql += " ORDER BY datetime(updated_at) DESC, id DESC LIMIT ?"
    params.append(max(1, int(limit or 20)))
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        item["manifest"] = json.loads(item.pop("manifest_json", "{}") or "{}")
        item["state"] = json.loads(item.pop("state_json", "{}") or "{}")
        result.append(item)
    return result


def update_orchestration_run(
    run_id: str,
    *,
    title: str | None = None,
    status: str | None = None,
    concurrency: int | None = None,
    manifest: dict | None = None,
    state: dict | None = None,
) -> dict | None:
    updates: list[str] = []
    params: list[object] = []
    if title is not None:
        updates.append("title=?")
        params.append(str(title or "").strip())
    if status is not None:
        updates.append("status=?")
        params.append(str(status or "").strip() or "pending")
    if concurrency is not None:
        updates.append("concurrency=?")
        params.append(max(1, int(concurrency or 1)))
    if manifest is not None:
        updates.append("manifest_json=?")
        params.append(json.dumps(manifest or {}, ensure_ascii=False))
    if state is not None:
        updates.append("state_json=?")
        params.append(json.dumps(state or {}, ensure_ascii=False))
    if not updates:
        return get_orchestration_run(run_id)
    updates.append("updated_at=CURRENT_TIMESTAMP")
    params.append(run_id)
    conn = get_connection()
    conn.execute(
        f"UPDATE orchestration_runs SET {', '.join(updates)} WHERE id=?",
        tuple(params),
    )
    conn.commit()
    conn.close()
    return get_orchestration_run(run_id)


def create_compare_report(
    groups: list, group_results: list, winners: dict
) -> str:
    report_id = str(uuid.uuid4())[:8]
    conn = get_connection()
    conn.execute(
        """INSERT INTO compare_reports
           (id, groups_json, group_results_json, winners_json)
           VALUES (?, ?, ?, ?)""",
        (
            report_id,
            json.dumps(groups, ensure_ascii=False),
            json.dumps(group_results, ensure_ascii=False),
            json.dumps(winners, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return report_id


def get_compare_report(report_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM compare_reports WHERE id=?",
        (report_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "groups": json.loads(row["groups_json"]),
        "group_results": json.loads(row["group_results_json"]),
        "winners": json.loads(row["winners_json"]),
        "created_at": row["created_at"],
    }


def get_ai_report_summary(
    *,
    target_type: str,
    target_id: str,
    report_kind: str,
    model_id: str,
    prompt_filename: str,
    source_signature: str,
) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT *
           FROM ai_report_summaries
           WHERE target_type=? AND target_id=? AND report_kind=?
             AND model_id=? AND prompt_filename=? AND source_signature=?
           LIMIT 1""",
        (
            target_type,
            target_id,
            report_kind,
            model_id,
            prompt_filename,
            source_signature,
        ),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_ai_report_summary(
    *,
    target_type: str,
    target_id: str,
    report_kind: str,
    model_id: str,
    prompt_filename: str,
    source_signature: str,
    markdown: str,
) -> dict:
    existing = get_ai_report_summary(
        target_type=target_type,
        target_id=target_id,
        report_kind=report_kind,
        model_id=model_id,
        prompt_filename=prompt_filename,
        source_signature=source_signature,
    )
    conn = get_connection()
    if existing:
        conn.execute(
            """UPDATE ai_report_summaries
               SET markdown=?, created_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (markdown, existing["id"]),
        )
        summary_id = existing["id"]
    else:
        summary_id = uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO ai_report_summaries
               (id, target_type, target_id, report_kind, model_id,
                prompt_filename, source_signature, markdown)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                summary_id,
                target_type,
                target_id,
                report_kind,
                model_id,
                prompt_filename,
                source_signature,
                markdown,
            ),
        )
    conn.commit()
    conn.close()
    return (
        get_ai_report_summary(
            target_type=target_type,
            target_id=target_id,
            report_kind=report_kind,
            model_id=model_id,
            prompt_filename=prompt_filename,
            source_signature=source_signature,
        )
        or {
            "id": summary_id,
            "target_type": target_type,
            "target_id": target_id,
            "report_kind": report_kind,
            "model_id": model_id,
            "prompt_filename": prompt_filename,
            "source_signature": source_signature,
            "markdown": markdown,
        }
    )


def clear_ai_report_summaries(
    *,
    target_type: str,
    target_id: str,
    report_kind: str = "",
) -> int:
    conn = get_connection()
    if report_kind:
        cur = conn.execute(
            """
            DELETE FROM ai_report_summaries
            WHERE target_type=? AND target_id=? AND report_kind=?
            """,
            (target_type, target_id, report_kind),
        )
    else:
        cur = conn.execute(
            """
            DELETE FROM ai_report_summaries
            WHERE target_type=? AND target_id=?
            """,
            (target_type, target_id),
        )
    conn.commit()
    conn.close()
    return cur.rowcount


def log_conversation_event(
    conversation_id: str,
    *,
    scope: str,
    level: str,
    event_type: str,
    detail: dict | None = None,
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO conversation_events
        (conversation_id, scope, level, event_type, detail_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(conversation_id or "__system__").strip() or "__system__",
            str(scope or "generation").strip() or "generation",
            str(level or "info").strip() or "info",
            str(event_type or "event").strip() or "event",
            json.dumps(detail or {}, ensure_ascii=False),
        ),
    )
    conn.commit()
    event_id = int(cur.lastrowid or 0)
    conn.close()
    return event_id


def get_conversation_events(
    conv_id: str,
    *,
    scope: str = "",
    level: str = "",
) -> list[dict]:
    conn = get_connection()
    sql = """
        SELECT id, conversation_id, scope, level, event_type, detail_json, created_at
        FROM conversation_events
        WHERE conversation_id=?
    """
    params: list[str] = [conv_id]
    if str(scope or "").strip():
        sql += " AND scope=?"
        params.append(str(scope).strip())
    if str(level or "").strip():
        sql += " AND level=?"
        params.append(str(level).strip())
    sql += " ORDER BY datetime(created_at) ASC, id ASC"
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    events = []
    for row in rows:
        item = dict(row)
        item["detail"] = json.loads(item.pop("detail_json", "{}") or "{}")
        events.append(item)
    return events


def cleanup_archived_conversations(days: int = 30) -> dict:
    max_days = max(0, int(days or 0))
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id
        FROM conversations
        WHERE archived_at IS NOT NULL
          AND datetime(archived_at) <= datetime('now', ?)
        """,
        (f"-{max_days} days",),
    ).fetchall()
    deleted_ids = [str(row["id"]) for row in rows]
    deleted_count = 0
    for conv_id in deleted_ids:
        if _table_exists(conn, "ai_report_summaries"):
            conn.execute(
                "DELETE FROM ai_report_summaries WHERE target_type='conversation_scoring' AND target_id=?",
                (conv_id,),
            )
        if _table_exists(conn, "conversation_events"):
            conn.execute(
                "DELETE FROM conversation_events WHERE conversation_id=?",
                (conv_id,),
            )
        conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        deleted_count += 1
    conn.commit()
    conn.close()
    log_conversation_event(
        "__system__",
        scope="system",
        level="info",
        event_type="auto_cleanup",
        detail={
            "days": max_days,
            "deleted_count": deleted_count,
            "conversation_ids": deleted_ids,
        },
    )
    return {
        "days": max_days,
        "deleted_count": deleted_count,
        "conversation_ids": deleted_ids,
    }


def migrate_add_mode_switches_table():
    """v6.0: 创建桥接切换日志表"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mode_switches (
            switch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_mode TEXT NOT NULL,
            to_mode TEXT NOT NULL,
            source_conversation_id TEXT NOT NULL,
            target_conversation_id TEXT,
            target_model TEXT NOT NULL,
            triggered_by TEXT NOT NULL DEFAULT 'user_click',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            switch_summary TEXT DEFAULT '',
            summary_model TEXT DEFAULT 'deepseek-v4-flash',
            summary_char_count INTEGER DEFAULT 0,
            summary_token_count INTEGER DEFAULT 0,
            summary_latency_ms INTEGER DEFAULT 0,
            summary_delayed INTEGER DEFAULT 0,

            bridge_turns_requested INTEGER DEFAULT 0,
            bridge_effective_turns INTEGER DEFAULT 0,
            bridge_payload_messages INTEGER DEFAULT 0,
            hetero_assistant_wrapped INTEGER DEFAULT 0,
            source_counts_json TEXT DEFAULT '{}',
            bridge_total_available_messages INTEGER DEFAULT 0,

            first_response_cjk_chars INTEGER DEFAULT 0,
            first_response_paren_pairs INTEGER DEFAULT 0,
            first_response_ngram_max_recent_pct REAL DEFAULT 0,
            first_response_format_issues_json TEXT DEFAULT '[]',

            verification_result TEXT DEFAULT 'pending',
            summary_interval INTEGER DEFAULT 10,
            FOREIGN KEY (source_conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (target_conversation_id) REFERENCES conversations(id)
        );

        CREATE INDEX IF NOT EXISTS idx_mode_switches_from_to ON mode_switches(from_mode, to_mode);
        CREATE INDEX IF NOT EXISTS idx_mode_switches_source ON mode_switches(source_conversation_id);
        CREATE INDEX IF NOT EXISTS idx_mode_switches_created ON mode_switches(created_at);
    """)
    try:
        conn.execute("ALTER TABLE mode_switches ADD COLUMN summary_interval INTEGER DEFAULT 10")
        conn.commit()
    except Exception:
        pass
    conn.close()


def create_mode_switch(
    from_mode: str,
    to_mode: str,
    source_conversation_id: str,
    target_model: str,
    triggered_by: str = 'user_click',
    summary_interval: int = 10,
    bridge_turns_requested: int = 20
) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO mode_switches (
            from_mode, to_mode, source_conversation_id, target_model, triggered_by, summary_interval, bridge_turns_requested
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (from_mode, to_mode, source_conversation_id, target_model, triggered_by, summary_interval, bridge_turns_requested)
    )
    switch_id = int(cur.lastrowid or 0)
    conn.commit()
    conn.close()
    return switch_id


def get_mode_switch(switch_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM mode_switches WHERE switch_id=?", (switch_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def update_mode_switch_summary(
    switch_id: int,
    summary: str,
    summary_model: str,
    char_count: int,
    token_count: int,
    latency_ms: int,
    delayed: bool
):
    conn = get_connection()
    conn.execute(
        """UPDATE mode_switches SET
            switch_summary=?,
            summary_model=?,
            summary_char_count=?,
            summary_token_count=?,
            summary_latency_ms=?,
            summary_delayed=?
           WHERE switch_id=?""",
        (summary, summary_model, char_count, token_count, latency_ms, 1 if delayed else 0, switch_id)
    )
    conn.commit()
    conn.close()


def update_mode_switch_meta(
    switch_id: int,
    turns_requested: int,
    effective_turns: int,
    payload_messages: int,
    hetero_assistant_wrapped: int,
    source_counts: dict,
    total_available_messages: int
):
    conn = get_connection()
    conn.execute(
        """UPDATE mode_switches SET
            bridge_turns_requested=?,
            bridge_effective_turns=?,
            bridge_payload_messages=?,
            hetero_assistant_wrapped=?,
            source_counts_json=?,
            bridge_total_available_messages=?
           WHERE switch_id=?""",
        (
            turns_requested,
            effective_turns,
            payload_messages,
            hetero_assistant_wrapped,
            json.dumps(source_counts, ensure_ascii=False),
            total_available_messages,
            switch_id
        )
    )
    conn.commit()
    conn.close()


def update_mode_switch_first_response(
    switch_id: int,
    target_conversation_id: str | None,
    cjk_chars: int,
    paren_pairs: int,
    ngram_max: float,
    format_issues: list,
    verification_result: str
):
    conn = get_connection()
    conn.execute(
        """UPDATE mode_switches SET
            target_conversation_id=?,
            first_response_cjk_chars=?,
            first_response_paren_pairs=?,
            first_response_ngram_max_recent_pct=?,
            first_response_format_issues_json=?,
            verification_result=?
           WHERE switch_id=?""",
        (
            target_conversation_id,
            cjk_chars,
            paren_pairs,
            ngram_max,
            json.dumps(format_issues, ensure_ascii=False),
            verification_result,
            switch_id
        )
    )
    conn.commit()
    conn.close()


def list_mode_switches(
    from_mode: str | None = None,
    to_mode: str | None = None,
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
    conn = get_connection()
    query = "SELECT * FROM mode_switches"
    params = []
    where_clauses = []
    if from_mode:
        where_clauses.append("from_mode=?")
        params.append(from_mode)
    if to_mode:
        where_clauses.append("to_mode=?")
        params.append(to_mode)
    
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    
    query += " ORDER BY switch_id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_conversation_mode(conv_id: str, mode: str):
    """更新会话模式 (short/long)"""
    conn = get_connection()
    conn.execute("UPDATE conversations SET mode=? WHERE id=?", (mode, conv_id))
    conn.commit()
    conn.close()


def update_turn_mode(conv_id: str, turn: int, mode: str):
    """更新某一轮接话的模式 (short/long)"""
    conn = get_connection()
    conn.execute("UPDATE turn_results SET mode=? WHERE conversation_id=? AND turn=?", (mode, conv_id, turn))
    conn.commit()
    conn.close()

