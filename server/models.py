"""
Pydantic 数据模型。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field
from config import DEFAULT_PRIMARY_MODEL, DEFAULT_SUMMARY_INTERVAL, DEFAULT_SUMMARY_MODEL


class ConversationCreate(BaseModel):
    """创建对话任务请求。"""

    preset_id: Optional[str] = None
    model_id: str = DEFAULT_PRIMARY_MODEL
    model_ids: list[str] = Field(default_factory=list)
    compare_mode: Optional[Literal["prompt", "model"]] = None
    model_mini: str = DEFAULT_SUMMARY_MODEL
    prompt_version: Optional[str] = None
    summary_prompt_version: Optional[str] = None
    scoring_prompt_version: Optional[str] = None
    scoring_model_id: Optional[str] = None
    profile_model_id: Optional[str] = None
    profile_prompt_version: Optional[str] = None
    thinking_enabled: Optional[bool] = None
    thinking_effort: Optional[str] = None
    scoring_thinking_enabled: Optional[bool] = None
    scoring_thinking_effort: Optional[str] = None
    scoring_max_workers: Optional[int] = Field(default=None, ge=1, le=24)
    scoring_retry_count: Optional[int] = Field(default=None, ge=0, le=10)
    summary_interval: int = DEFAULT_SUMMARY_INTERVAL
    injection_depth: int = Field(default=4, ge=1)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    dry_run: bool = False
    auto_scoring: bool = True
    turns: list[str] = Field(default_factory=list)
    character: Optional[dict] = None
    context: Optional[dict] = None
    modules: Optional[dict] = None
    custom_variables: Optional[dict] = Field(default_factory=dict)
    mode: Optional[str] = "long"


class PresetCreate(BaseModel):
    """创建自定义预设。"""

    name: str
    type: str
    config: dict
    mode: Optional[str] = "long"


class ChatRequest(BaseModel):
    """普通聊天请求。"""

    model_ids: list[str] = Field(default=[DEFAULT_PRIMARY_MODEL])
    messages: list[dict] = Field(default_factory=list)
    config: Optional[dict] = None
    prompt_version: Optional[str] = None
    model_prompts: Optional[dict[str, str]] = Field(default_factory=dict)
    web_search: bool = False
    thinking_enabled: Optional[bool] = None
    thinking_effort: str = ""  # disabled / low / medium / high
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)



class ManualScoreRequest(BaseModel):
    """人工打分请求。"""

    star_score: float = Field(ge=0.1, le=10.0)
    comment: str = ""


class ChatScoreRequest(BaseModel):
    """对话体验页单轮AI评分请求。"""

    user_input: str = ""
    ai_output: str = ""
    config: dict = Field(default_factory=dict)
    scoring_prompt_version: Optional[str] = None
    scoring_model_id: Optional[str] = None
    scoring_thinking_enabled: Optional[bool] = None
    scoring_thinking_effort: Optional[str] = None


class ScoringConfigUpdate(BaseModel):
    """更新全局打分执行配置。"""

    max_workers: Optional[int] = Field(default=None, ge=1, le=24)


class TriggerScoringRequest(BaseModel):
    """触发会话打分时的运行时覆盖项。"""

    scoring_model_id: Optional[str] = None
    scoring_prompt_version: Optional[str] = None
    scoring_thinking_enabled: Optional[bool] = None
    scoring_thinking_effort: Optional[str] = None
    max_workers: Optional[int] = Field(default=None, ge=1, le=24)
    scoring_retry_count: Optional[int] = Field(default=None, ge=0, le=10)


class RescoreAllRequest(TriggerScoringRequest):
    """全量重打分请求。"""


class TaskControlRequest(BaseModel):
    """任务控制请求。"""

    action: Literal["pause", "resume", "cancel"]


class OrchestrationItemRequest(BaseModel):
    """后端编排中的单个会话任务。"""

    key: str = ""
    label: str = ""
    relationship: str = ""
    model_id: str = ""
    planned_turns: int = Field(default=0, ge=0)
    payload: dict = Field(default_factory=dict)


class OrchestrationGroupRequest(BaseModel):
    """后端编排中的一组任务。批量模式下一组通常只有 1 个任务。"""

    key: str = ""
    label: str = ""
    relationship: str = ""
    planned_turns: int = Field(default=0, ge=0)
    items: list[OrchestrationItemRequest] = Field(default_factory=list)


class OrchestrationRunCreate(BaseModel):
    """创建批量/对比后端编排任务。"""

    kind: Literal["batch", "compare", "ab"]
    title: str = ""
    concurrency: int = Field(default=1, ge=1, le=24)
    config_snapshot: dict = Field(default_factory=dict)
    groups: list[OrchestrationGroupRequest] = Field(default_factory=list)


class InteractiveConversationCreate(BaseModel):
    """交互式聊天会话创建请求。"""

    model_id: str = DEFAULT_PRIMARY_MODEL
    model_mini: str = DEFAULT_SUMMARY_MODEL
    prompt_version: Optional[str] = None
    summary_prompt_version: Optional[str] = None
    scoring_prompt_version: Optional[str] = None
    scoring_model_id: Optional[str] = None
    profile_model_id: Optional[str] = None
    profile_prompt_version: Optional[str] = None
    thinking_enabled: Optional[bool] = None
    thinking_effort: Optional[str] = None
    scoring_thinking_enabled: Optional[bool] = None
    scoring_thinking_effort: Optional[str] = None
    scoring_max_workers: Optional[int] = Field(default=None, ge=1, le=24)
    scoring_retry_count: Optional[int] = Field(default=None, ge=0, le=10)
    summary_interval: int = DEFAULT_SUMMARY_INTERVAL
    injection_depth: int = Field(default=4, ge=1)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    auto_scoring: bool = True
    dry_run: bool = False
    character: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    modules: dict = Field(default_factory=dict)
    custom_variables: dict = Field(default_factory=dict)
    ab_session_id: Optional[str] = None
    ab_variant: Optional[Literal["base", "compare"]] = None
    mode: Optional[str] = "long"


class ABSessionCreateRequest(BaseModel):
    """创建 Prompt A/B 后端会话。"""

    shared_config: dict = Field(default_factory=dict)
    base: InteractiveConversationCreate
    compare: InteractiveConversationCreate


class ABSessionTurnRequest(BaseModel):
    """向 A/B 实验提交一轮用户输入。"""

    user_input: str = ""
    web_search: bool = False
    thinking_enabled: Optional[bool] = None
    thinking_effort: str = ""
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ABSessionResponse(BaseModel):
    """A/B 实验会话响应。"""

    id: str
    status: str
    base_conversation_id: str
    compare_conversation_id: str
    current_turn: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    shared_config: dict = Field(default_factory=dict)
    base_config: dict = Field(default_factory=dict)
    compare_config: dict = Field(default_factory=dict)


class ABSessionStatusResponse(ABSessionResponse):
    """A/B 实验状态查询响应。"""

    base_status: str = ""
    compare_status: str = ""


class InteractiveGenerateRequest(BaseModel):
    """交互式聊天单轮生成请求。"""

    user_input: str = ""
    model_id: str = ""
    web_search: bool = False
    thinking_enabled: Optional[bool] = None
    thinking_effort: str = ""
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class InteractiveRegenerateRequest(BaseModel):
    """交互式聊天重生成请求。"""

    model_id: str = ""
    web_search: bool = False
    thinking_enabled: Optional[bool] = None
    thinking_effort: str = ""
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class InteractiveTurnCreate(BaseModel):
    """交互式聊天追加一轮结果。"""

    user_input: str = ""
    ai_output: str = ""
    word_count: int = 0
    dialogue_summary: str = ""
    msg_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0
    has_deep_injection: bool = False
    has_style_isolation: bool = False
    has_cooldown_reinject: bool = False
    token_trim_level: int = 0
    quality_retries: int = 0
    messages_snapshot: list[dict] = Field(default_factory=list)
    request_payload_snapshot: dict = Field(default_factory=dict)
    model_id: str = DEFAULT_PRIMARY_MODEL


class InteractiveTurnScoreCreate(BaseModel):
    """交互式聊天单轮评分回写。"""

    scores: dict = Field(default_factory=dict)
    mapped_total: float = 0
    reasoning: str = ""
    success: bool = True


class ManualDialogueTurn(BaseModel):
    """手动输入的一轮对话。"""

    turn: Optional[int] = None
    user_input: str = ""
    ai_output: str = ""


class ManualDialogueRequest(BaseModel):
    """手动输入对话并直接评分。"""

    config: dict = Field(default_factory=dict)
    turns: list[ManualDialogueTurn] = Field(default_factory=list)


class ModelConfigRequest(BaseModel):
    """保存或更新模型配置。"""

    id: str
    name: str
    display_name: str = ""
    provider: str
    api: dict = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)


class ConfigSaveRequest(BaseModel):
    """保存配置快照。"""

    name: str = ""
    type: str = "custom_config"
    config: Optional[dict] = None
    prompt_file: Optional[str] = None
    few_shot_file: Optional[str] = None
    character: Optional[dict] = None
    context: Optional[dict] = None
    modules: Optional[dict] = None
    runtime: Optional[dict] = None
    custom_variables: Optional[dict] = Field(default_factory=dict)
    mode: Optional[str] = "long"


class PresetResponse(BaseModel):
    id: str
    name: str
    type: str
    created_at: Optional[str] = None
    config: Optional[dict] = None
    is_builtin: bool = False


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str
    display_name: str = ""


class TurnResultResponse(BaseModel):
    turn: int
    user_input: str = ""
    ai_output: str = ""
    word_count: int = 0
    dialogue_summary: str = ""
    msg_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0
    has_deep_injection: bool = False
    has_style_isolation: bool = False
    has_cooldown_reinject: bool = False
    token_trim_level: int = 0
    quality_retries: int = 0


class ConversationResponse(BaseModel):
    id: str
    preset_id: Optional[str] = None
    model_id: str
    status: str
    created_at: Optional[str] = None
    results: list[TurnResultResponse] = Field(default_factory=list)


class ConversationListItem(BaseModel):
    id: str
    preset_id: Optional[str] = None
    model_id: str
    status: str
    created_at: Optional[str] = None
