"""
长文模式多轮对话验证工具 FastAPI 入口。
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

SERVER_DIR = Path(__file__).resolve().parent
if __package__:
    from . import config as _config
    sys.modules.setdefault("config", _config)

    from . import database as _database
    sys.modules.setdefault("database", _database)

    from . import models as _models
    sys.modules.setdefault("models", _models)

    from . import routers as _routers
    sys.modules.setdefault("routers", _routers)

    from . import services as _services
    sys.modules.setdefault("services", _services)

    database = _database
    from .config import AUTO_CLEANUP_DAYS, PUBLIC_DEMO_MODE
    from .routers import (
        ab_sessions,
        chat,
        compare,
        configs,
        conversations,
        export,
        models_router,
        orchestrations,
        presets,
        prompts,
        scoring,
        scoring_prompts,
    )
    from .services.public_demo import (
        build_public_demo_app_config,
        reset_public_demo_runtime,
    )
else:
    import database
    from config import AUTO_CLEANUP_DAYS, PUBLIC_DEMO_MODE
    from routers import (
        ab_sessions,
        chat,
        compare,
        configs,
        conversations,
        export,
        models_router,
        orchestrations,
        presets,
        prompts,
        scoring,
        scoring_prompts,
    )
    from services.public_demo import (
        build_public_demo_app_config,
        reset_public_demo_runtime,
    )


@asynccontextmanager
async def lifespan(app):
    if PUBLIC_DEMO_MODE:
        reset_public_demo_runtime()
    database.init_db()
    database.migrate_add_score_columns()
    database.migrate_add_v51_columns()
    database.migrate_add_compare_reports_table()
    database.migrate_add_ai_report_summaries_table()
    database.migrate_add_conversation_events_table()
    database.migrate_add_orchestration_runs_table()
    database.migrate_add_ab_sessions_table()
    cleanup_result = database.cleanup_archived_conversations(AUTO_CLEANUP_DAYS)
    await conversations.reconcile_conversation_runtime_state()
    await orchestrations.orchestration_service.reconcile_runtime_state()
    (SERVER_DIR / "static").mkdir(exist_ok=True)
    print("[OK] Database initialized with v5.1 migrations")
    print(
        f"[OK] Archived cleanup finished: deleted={cleanup_result.get('deleted_count', 0)} "
        f"(days={cleanup_result.get('days', AUTO_CLEANUP_DAYS)})"
    )
    yield


app = FastAPI(
    title="长文模式多轮对话验证工具",
    description="PRD v5.1 后端服务 API",
    version="5.1.0",
    lifespan=lifespan,
    docs_url=None if PUBLIC_DEMO_MODE else "/docs",
    redoc_url=None if PUBLIC_DEMO_MODE else "/redoc",
    openapi_url=None if PUBLIC_DEMO_MODE else "/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(presets.router)
app.include_router(conversations.router)
app.include_router(ab_sessions.router)
app.include_router(models_router.router)
app.include_router(orchestrations.router)
app.include_router(export.router)
app.include_router(scoring.router)
app.include_router(scoring_prompts.router)
app.include_router(prompts.router)
app.include_router(chat.router)
app.include_router(compare.router)
app.include_router(configs.router)

STATIC_DIR = SERVER_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
APP_SHELL_VERSION = "93"


@app.get("/")
async def root():
    return RedirectResponse(url=f"/static/index.html?v={APP_SHELL_VERSION}")


@app.get("/api/app-config")
async def get_app_config():
    return build_public_demo_app_config()


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("  Longform Multi-turn Validation Tool v5.1")
    print("  Frontend: http://localhost:8000")
    if PUBLIC_DEMO_MODE:
        print("  Mode:     PUBLIC DEMO (write-ops blocked)")
    else:
        print("  API docs: http://localhost:8000/docs")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
