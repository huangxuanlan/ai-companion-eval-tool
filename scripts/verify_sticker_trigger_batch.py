#!/usr/bin/env python3
"""Batch-validate sticker trigger/suppression behavior for shortform prompts."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SERVER_DIR = PROJECT_ROOT / "server"
for path in (PROJECT_ROOT, SERVER_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

try:
    from dotenv import load_dotenv

    load_dotenv(SERVER_DIR / ".env")
except Exception:
    pass

from services.model_adapter import ModelAdapter

DEFAULT_REPORT_ROOT = Path(
    r"E:\工作资料\产品资料\提示词资料\表情包模块\测试报告"
)
REFERENCE_PROMPT_PATH = Path(
    r"E:\工作资料\产品资料\提示词资料\表情包模块\测试输入\chat_pasted_sticker_redpacket_prompt_20260519.md"
)
DEFAULT_TARGET_MODELS = ("deepseek-v4-flash", "doubao-lite", "doubao-1.5-character")
SMOKE_SCENE_IDS = (
    "user_sent_sticker",
    "user_misses_role",
    "user_good_news",
    "user_low_mood",
    "previous_sticker_suppress",
    "plain_info_suppress",
)
STICKER_RE = re.compile(r"\[STICKER:([^\]\r\n]+)\]")
BRACKET_TOKEN_RE = re.compile(r"\[[^\]\r\n]*\]")
BARE_STICKER_RE = re.compile(r"(?<!\[)STICKER\s*[:：]")
UNCLOSED_STICKER_RE = re.compile(r"\[STICKER\s*[:：][^\]\r\n]*(?:\r?\n|$)")
RED_PACKET_RE = re.compile(
    r"\[(?:TRANSFER:[^\]]+|ACCEPT，编号：[^\]]+|REJECT，编号：[^\]]+)\]"
)
PLACEHOLDER_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")

ALL_STICKERS = frozenset(
    {
        "看着你",
        "比心",
        "星星眼期待",
        "小狗的肯定",
        "委屈落泪",
        "搓手手",
        "来啦",
        "目移",
        "傲娇",
        "震惊",
        "点赞",
        "天下第一好",
        "熬夜想你",
        "送小花",
        "嘻嘻",
        "为你加油",
        "非常感谢",
        "不谢",
        "得意笑",
        "理我呀",
        "看着我的眼睛",
        "小狗警告",
        "我枯了",
        "挠下巴",
        "喜欢您来",
    }
)

DEFAULT_PROMPT_TEMPLATE = """# 当前时
- 现在时间是{{完整时间信息}}
- 记住当前的时间，涉及到时间的回复要严谨遵守当前时间。

# 对话场景
你正在与用户文本聊天
- 你与用户{{last_cst_type}}

# 你们的关系
- {{relationship}}，{{relation_info}}

# 终极目标
要有活人感，像真人聊天，让用户觉得有趣、被理解、被回应。

# 输出格式要求
每次输出必须是一段完整叙事，回复字数根据场景控制在90字左右。
- 旁白用 `()` 包裹，动作描写展示微表情、环境互动、身体语言、心理动态。
- 对话包含2-3段，每段对白30字左右。
- ()里的动作描述必须以“你”代指用户，禁止以“她”或“他”代指用户。

# 文字信息字段要求
- 请区分你的姓名是{{Role_Nickname}}，用户大名是{{user_Nickname}}，
  用户希望你叫Ta{{call_name}}。
- 禁止杜撰用户的喜好、之前说过或做过的事情。
- 对话自然、口语化，真诚、共情。
- 禁止角色主动结束对话。
- 禁止上下文重复说相似的话。
- 禁止将用户偏爱列表中的内容作为表达在意的默认素材。

# 对话表达风格
- 经常自然使用口头禅，例如“哈哈”“嗯…”。
- 在适当的时候发一个【表情包】，代表你在用图片回应。
- 本测试只验证表情包，除系统转账消息外禁止输出红包/转账信号。

# 表情包规则
你可以在微信聊天中发送表情包。表情包是“情绪加强动作”，不允许每轮都发。

## 发送判断
只有满足以下情况之一，才可以发送表情包：
1. 用户本轮发送了表情包，角色可以用表情包回应。
2. 当前气氛明显轻松、好笑、开心，适合用表情包补充情绪。
3. 用户情绪明显低落、尴尬、紧张，需要用温和表情包缓和气氛。
4. 角色本轮回复偏轻松、调侃、打招呼、回应夸奖时，可以少量使用。

以下情况禁止发送表情包：
1. 上一轮角色已经发送过表情包，本轮禁止继续发送。
2. 当前关系阶段不支持该表情包表达的亲密程度。
3. 当前回复是认真解释、安慰、处理问题、拒绝越界、表达边界时，不发送。
4. 用户只是普通问候、普通信息交流，不要为了凑频率强发表情包。
5. 当前文字已经能自然表达情绪，不需要额外加表情包。

## 频率原则
- 表情包不是强制项，宁可少发，也不要机械发送。
- 熟人阶段：建议3轮内最多主动发送1次。
- 暧昧阶段：可以适度增加，但不能连续发送。
- 恋人阶段：可根据情绪自然使用，但仍禁止每轮都发。
- 长期不发可以接受，连续乱发是严重错误。

## 表情包输出格式
需要发送表情包时，将表情包信号放在回复的最末尾，信号后不能再有任何文字、标点或括号。
表情包信号格式：[STICKER:表情包名称]

## 可用表情包
看着你、比心、星星眼期待、小狗的肯定、委屈落泪、搓手手、来啦、目移、傲娇、震惊、点赞、天下第一好、熬夜想你、送小花、嘻嘻、为你加油、非常感谢、不谢、得意笑、理我呀、看着我的眼睛、小狗警告、我枯了、挠下巴、喜欢您来。

# 红包规则
本轮不是红包验证。除非最新用户消息为真实系统转账消息，
禁止输出 [TRANSFER:金额:备注]、[ACCEPT，编号：xxxxxx]、
[REJECT，编号：xxxxxx]。

# 身份设定
- 你扮演的角色为{{Role_Nickname}}，截至2025年，年龄{{age}}。职业为{{occupation}}。
- 近期行动：{{monthly_schedule}} {{background}}
- 已拍摄过的作品：{{Role_info_works}}

# 性格特征
{{system_module7}}
{{personality}}

# 你正在做的事情与聊天话题
- 你刚刚在做的事情：{{weekly_schedule}}
- 用户如果跟你对话，重点投入到与用户的互动。

# 次要偏好
{{hobby}}

# 语言风格
{{system_module9}}
{{speaking_style}}

# 人设核心
- 与角色公众形象、性格、价值观一致。
- 对话自然流畅，优先陈述分享，必要时温和引导。
- 保持隐私边界，不泄露未公开信息。

# 当前关系阶段
{{system_module11}}

# 用户朋友圈记忆模块
{{moments}}

{{dialogueStartPrompt}}
"""

DEFAULT_ASSISTANT_SEED = (
    "角色内部认知记录：当前为文字聊天场景，保持可爱活泼男性角色表达，"
    "承接上下文，不跳出角色，不解释规则。"
)


@dataclass(frozen=True)
class RoleFixture:
    role_id: str
    role_type: str
    variables: dict[str, Any]


@dataclass(frozen=True)
class StickerScene:
    scene_id: str
    title: str
    relationship: str
    user_input: str
    expect_sticker: bool
    allowed_stickers: tuple[str, ...] = ()
    additional_messages: tuple[dict[str, str], ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class StickerCase:
    case_id: str
    role: RoleFixture
    scene: StickerScene


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def ensure_runtime_key_aliases() -> dict[str, bool]:
    load_env_file(SERVER_DIR / ".env")
    if not os.environ.get("ARK_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
        os.environ["ARK_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]
    if not os.environ.get("DOUBAO_API_KEY") and os.environ.get("VOLCENGINE_API_KEY"):
        os.environ["DOUBAO_API_KEY"] = os.environ["VOLCENGINE_API_KEY"]
    return {
        "DASHSCOPE_API_KEY": bool(os.environ.get("DASHSCOPE_API_KEY")),
        "VOLCENGINE_API_KEY": bool(os.environ.get("VOLCENGINE_API_KEY")),
        "ARK_API_KEY": bool(os.environ.get("ARK_API_KEY")),
    }


def chinese_time_info(now: datetime | None = None) -> str:
    current = now or datetime.now()
    weekday = "一二三四五六日"[current.weekday()]
    hour = current.hour
    if 5 <= hour < 11:
        period = "上午"
    elif 11 <= hour < 14:
        period = "中午"
    elif 14 <= hour < 18:
        period = "下午"
    else:
        period = "晚上"
    return current.strftime(f"%Y-%m-%d %H时%M分 星期{weekday} {period}")


def build_male_role_fixtures() -> list[RoleFixture]:
    base = {
        "完整时间信息": chinese_time_info(),
        "last_cst_type": "上一次在文字聊天沟通",
        "user_Nickname": "熬夜元老",
        "call_name": "你",
        "Tacall_name": "你",
        "system_module7": "性格可爱活泼，反应快，爱笑，表达亲近但有边界。",
        "hobby": "次要偏好仅作背景，不主动反复提及。",
        "system_module9": "语言轻快、口语化，偶尔用一点调侃和撒娇式反差。",
        "moments": "",
        "dialogueStartPrompt": "<dialogue_history>暂无历史对话</dialogue_history>",
    }
    return [
        RoleFixture(
            role_id="official_male_actor",
            role_type="官方男演员型",
            variables={
                **base,
                "Role_Nickname": "肖战",
                "age": "34",
                "occupation": "演员、歌手",
                "monthly_schedule": "本月以拍摄、排练和品牌活动为主。",
                "weekly_schedule": "刚结束一段拍摄间隙，正坐在休息室看手机。",
                "background": "工作节奏紧，但面对熟悉的人会放松下来。",
                "Role_info_works": "《陈情令》《斗罗大陆》《梦中的那片海》",
                "personality": "外向温柔，笑点低，擅长把认真关心包在轻松玩笑里。",
                "speaking_style": "短句自然，带一点明亮少年感，不油腻。",
            },
        ),
        RoleFixture(
            role_id="custom_playful_male",
            role_type="自定义男性角色",
            variables={
                **base,
                "Role_Nickname": "江小川",
                "age": "27",
                "occupation": "游戏美术设计师",
                "monthly_schedule": "本月在赶一个新角色美术版本，晚上常做灵感整理。",
                "weekly_schedule": "刚把手绘板收起来，桌上还放着半杯冰美式。",
                "background": "平时嘴快心软，喜欢用轻松方式把气氛带起来。",
                "Role_info_works": "原创互动角色企划《星河便利店》",
                "personality": "可爱活泼、反应灵、会撒娇也会接梗。",
                "speaking_style": "像微信聊天一样自然，轻快、有梗、有分寸。",
            },
        ),
    ]


def build_sticker_scenes() -> list[StickerScene]:
    return [
        StickerScene(
            scene_id="user_sent_sticker",
            title="用户发送表情包",
            relationship="暧昧",
            user_input="发送了一个撒娇表情包。",
            expect_sticker=True,
            allowed_stickers=("搓手手", "比心", "嘻嘻", "看着你"),
            rationale="用户本轮发送表情包，角色应使用表情包回应。",
        ),
        StickerScene(
            scene_id="user_misses_role",
            title="用户表达想念",
            relationship="恋人",
            user_input="我有点想你了。",
            expect_sticker=True,
            allowed_stickers=("比心", "熬夜想你", "委屈落泪", "看着你", "嘻嘻"),
            rationale="亲近关系中的想念表达适合用甜感表情包强化。",
        ),
        StickerScene(
            scene_id="user_good_news",
            title="用户分享好消息",
            relationship="暧昧",
            user_input="老板终于同意给我涨工资了！",
            expect_sticker=True,
            allowed_stickers=("星星眼期待", "点赞", "天下第一好", "为你加油", "送小花"),
            rationale="好消息场景适合开心、认可、鼓励类表情包。",
        ),
        StickerScene(
            scene_id="user_low_mood",
            title="用户低落或自我怀疑",
            relationship="熟人",
            user_input="今天真的有点撑不住了，我是不是很没用啊。",
            expect_sticker=True,
            allowed_stickers=("小狗的肯定", "送小花", "为你加油", "我枯了", "委屈落泪"),
            rationale="低落场景需要温和缓和或鼓励类表情包。",
        ),
        StickerScene(
            scene_id="user_praises_role",
            title="用户夸角色",
            relationship="暧昧",
            user_input="你怎么这么会聊天啊，怪可爱的。",
            expect_sticker=True,
            allowed_stickers=("傲娇", "目移", "得意笑", "嘻嘻", "比心"),
            rationale="回应夸奖可以少量使用害羞、傲娇或甜感表情包。",
        ),
        StickerScene(
            scene_id="flirty_tease",
            title="暧昧调侃",
            relationship="暧昧",
            user_input="你是不是就仗着我喜欢你，才这么会撩我？",
            expect_sticker=True,
            allowed_stickers=("搓手手", "目移", "得意笑", "小狗警告", "嘻嘻"),
            rationale="轻松拉扯适合用调侃类表情包补情绪。",
        ),
        StickerScene(
            scene_id="summon_companion",
            title="用户明确召唤陪伴",
            relationship="恋人",
            user_input="快来陪我一下，我现在就想黏你一会儿。",
            expect_sticker=True,
            allowed_stickers=("来啦", "看着你", "比心", "理我呀", "嘻嘻"),
            rationale="召唤陪伴适合热情回应型表情包。",
        ),
        StickerScene(
            scene_id="previous_sticker_suppress",
            title="上一轮已发表情包",
            relationship="暧昧",
            user_input="那你是不是也想我？",
            expect_sticker=False,
            additional_messages=(
                {"role": "user", "content": "我有点想你了。"},
                {
                    "role": "assistant",
                    "content": (
                        "（他偏头笑了一下，耳尖有点红）"
                        "嗯，这句我收到了。[STICKER:比心]"
                    ),
                },
            ),
            rationale="上一轮角色已发表情包，本轮必须抑制连续发送。",
        ),
        StickerScene(
            scene_id="plain_info_suppress",
            title="普通问候或信息交流",
            relationship="熟人",
            user_input="我刚到公司，准备开会了。",
            expect_sticker=False,
            rationale="普通信息交流不应为了凑频率强发表情包。",
        ),
        StickerScene(
            scene_id="serious_boundary_suppress",
            title="认真边界或隐私拒绝",
            relationship="熟人",
            user_input="你能不能告诉我你同事的私人联系方式？",
            expect_sticker=False,
            rationale="隐私边界场景应认真处理，禁止发表情包。",
        ),
    ]


def relation_info(relationship: str) -> str:
    values = {
        "熟人": "初识不久，你们刚认识不久，保持轻松友好但不越界。",
        "暧昧": "朋友，并且在暧昧期，互相有好感，但不能越过当前关系阶段。",
        "恋人": "恋人，彼此在热恋期，可以表达稳定亲近和日常陪伴。",
    }
    return values.get(relationship, relationship)


def variables_for_scene(role: RoleFixture, scene: StickerScene) -> dict[str, Any]:
    values = dict(role.variables)
    values["relationship"] = scene.relationship
    values["relation_info"] = relation_info(scene.relationship)
    values["system_module11"] = (
        f"personal_type=可爱活泼；当前关系阶段={scene.relationship}；"
        "行为表达必须匹配关系边界。"
    )
    return values


def render_template(template: str, variables: dict[str, Any]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(
            "{{" + key + "}}",
            "" if value is None else str(value),
        )
        rendered = rendered.replace(
            "{{ " + key + " }}",
            "" if value is None else str(value),
        )
    return rendered


def render_prompt(
    prompt_template: str,
    role: RoleFixture,
    scene: StickerScene,
) -> str:
    rendered = render_template(prompt_template, variables_for_scene(role, scene))
    unresolved = PLACEHOLDER_RE.findall(rendered)
    if unresolved:
        missing = ", ".join(sorted(set(unresolved)))
        raise ValueError(f"prompt placeholders unresolved: {missing}")
    return rendered


def build_cases(
    *,
    scene_ids: set[str] | None = None,
) -> list[StickerCase]:
    roles = build_male_role_fixtures()
    scenes = [
        scene
        for scene in build_sticker_scenes()
        if scene_ids is None or scene.scene_id in scene_ids
    ]
    cases: list[StickerCase] = []
    for role in roles:
        for index, scene in enumerate(scenes, start=1):
            cases.append(
                StickerCase(
                    case_id=f"{role.role_id}_{index:02d}_{scene.scene_id}",
                    role=role,
                    scene=scene,
                )
            )
    return cases


def build_messages(
    *,
    prompt_template: str,
    case: StickerCase,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": render_prompt(prompt_template, case.role, case.scene),
        },
        {"role": "assistant", "content": DEFAULT_ASSISTANT_SEED},
        *[dict(item) for item in case.scene.additional_messages],
        {"role": "user", "content": case.scene.user_input},
    ]


def validate_sticker_output(text: str, scene: StickerScene) -> dict[str, Any]:
    stripped = str(text or "").strip()
    matches = list(STICKER_RE.finditer(stripped))
    bracket_tokens = list(BRACKET_TOKEN_RE.finditer(stripped))
    issues: list[str] = []
    warnings: list[str] = []

    if len(matches) > 1:
        issues.append("表情包信号数量超过1")
    if any("STICKER" in token.group(0) for token in bracket_tokens) and not matches:
        issues.append("表情包信号格式错乱")
    if UNCLOSED_STICKER_RE.search(stripped):
        issues.append("表情包信号格式错乱")
    if BARE_STICKER_RE.search(stripped):
        issues.append("表情包信号未用[]包裹")

    if matches:
        last = matches[-1]
        sticker_name = last.group(1).strip()
        if last.end() != len(stripped):
            warnings.append("表情包信号后存在文字")
        if sticker_name not in ALL_STICKERS:
            issues.append("表情包名称不在可用集合")
        elif sticker_name not in scene.allowed_stickers:
            warnings.append("表情包名称不在推荐集合")
        if not scene.expect_sticker:
            warnings.append("抑制场景误发表情包")
            if scene.scene_id == "previous_sticker_suppress":
                warnings.append("上一轮已发表情包仍继续发送")
    elif scene.expect_sticker:
        warnings.append("应触发表情包但未输出")

    return {
        "pass": not issues,
        "issues": dedupe_keep_order(issues),
        "warnings": dedupe_keep_order(warnings),
        "sticker_count": len(matches),
        "sticker_name": matches[-1].group(1).strip() if matches else "",
        "expected_sticker": scene.expect_sticker,
        "allowed_stickers": list(scene.allowed_stickers),
    }


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def dry_run_output(scene: StickerScene) -> str:
    if scene.expect_sticker:
        sticker = scene.allowed_stickers[0]
        return (
            "（他看到你的消息后弯起眼睛，语气一下轻快起来）"
            f"嗯，这句我接住了，先给你盖个小章。[STICKER:{sticker}]"
        )
    return "（他把手机拿近了一点，神情认真下来）嗯，这件事我听明白了，我会好好回应你。"


def call_model(
    adapter: ModelAdapter,
    model_id: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = adapter.chat(
        model_id=model_id,
        messages=messages,
        max_tokens=max_tokens,
        thinking_effort="disabled",
    )
    return {
        "success": result.success,
        "error": result.error,
        "output": result.content or "",
        "latency": round(time.perf_counter() - started, 3),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_json(path: Path, item: dict[str, Any]) -> None:
    path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")


def case_record(case: StickerCase) -> dict[str, Any]:
    scene = case.scene
    return {
        "case_id": case.case_id,
        "role_id": case.role.role_id,
        "role_type": case.role.role_type,
        "role_name": case.role.variables.get("Role_Nickname", ""),
        "scene_id": scene.scene_id,
        "scene_title": scene.title,
        "relationship": scene.relationship,
        "user_input": scene.user_input,
        "expect_sticker": scene.expect_sticker,
        "allowed_stickers": list(scene.allowed_stickers),
        "rationale": scene.rationale,
        "additional_messages": list(scene.additional_messages),
    }


def write_payload(
    path: Path,
    meta: dict[str, Any],
    messages: list[dict[str, str]],
) -> None:
    write_json(path, {"meta": meta, "messages": messages})


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for row in results if row.get("pass"))
    by_model: dict[str, dict[str, int]] = {}
    by_expectation: dict[str, dict[str, int]] = {}
    for row in results:
        model = str(row.get("model") or "dry-run")
        model_stats = by_model.setdefault(model, {"total": 0, "passed": 0})
        model_stats["total"] += 1
        model_stats["passed"] += 1 if row.get("pass") else 0

        key = "trigger" if row.get("expect_sticker") else "suppress"
        exp_stats = by_expectation.setdefault(key, {"total": 0, "passed": 0})
        exp_stats["total"] += 1
        exp_stats["passed"] += 1 if row.get("pass") else 0
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total * 100, 2) if total else 0.0,
        "by_model": by_model,
        "by_expectation": by_expectation,
    }


def write_summary(path: Path, results: list[dict[str, Any]], run_level: str) -> None:
    aggregate = aggregate_results(results)
    failures = [row for row in results if not row.get("pass")]
    successes = [row for row in results if row.get("pass")]
    verdict = "PASS" if aggregate["total"] and aggregate["failed"] == 0 else "FAIL"
    lines = [
        "# 表情包触发批量验证报告",
        "",
        "## 整体表现",
        "",
        f"- 执行层级: {run_level}",
        f"- 综合评级: {verdict}",
        (
            f"- 硬格式通过率: {aggregate['passed']}/{aggregate['total']} "
            f"({aggregate['pass_rate']}%)"
        ),
        "- 门禁标准: 仅硬格式 100% 通过才算整体通过；触发/抑制偏差进入 Warning",
        "",
        "## 主要优势 / 主要不足",
        "",
        "主要优势:",
    ]
    if successes:
        lines.extend(
            [
                f"- 已通过样本: {len(successes)} 条",
                "- 硬门禁覆盖表情包信号结构、唯一信号和全局非法表情包名称。",
            ]
        )
    else:
        lines.append("- 暂无通过样本。")

    lines.append("")
    lines.append("主要不足:")
    if failures:
        issue_counts: dict[str, int] = {}
        for row in failures:
            for issue in row.get("issues") or []:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        for issue, count in sorted(
            issue_counts.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"- {issue}: {count} 条")
    else:
        lines.append("- 未发现硬格式失败。")

    warning_counts: dict[str, int] = {}
    for row in results:
        for warning in row.get("warnings") or []:
            warning_counts[warning] = warning_counts.get(warning, 0) + 1
    lines.append("")
    lines.append("软提示 / Warning:")
    if warning_counts:
        for warning, count in sorted(
            warning_counts.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"- {warning}: {count} 条")
    else:
        lines.append("- 暂无。")

    lines.extend(
        [
            "",
            "## 优化建议",
            "",
        ]
    )
    if failures:
        lines.extend(
            [
                "- 优先修复失败最多的硬格式问题，再复跑 smoke。",
                "- 触发/抑制偏差本轮不阻断验收，"
                "但需要结合 Warning 明细评估提示词行为。",
            ]
        )
    elif warning_counts:
        lines.extend(
            [
                "- 当前硬格式已过，下一步重点看 Warning 中的触发/抑制偏差。",
                "- 若业务验收要收紧触发/抑制，可单独建立行为通过率门槛。",
            ]
        )
    else:
        lines.append("- 保持当前规则，下一步可追加红包矩阵或扩大真实样本。")

    lines.extend(
        [
            "",
            "## Top 优秀轮次 / 待改进轮次",
            "",
            "Top 优秀轮次:",
        ]
    )
    for row in successes[:5]:
        lines.append(
            f"- {row['case_id']} / {row['model']}: "
            f"{row.get('sticker_name') or 'no_sticker'}"
        )
    if not successes:
        lines.append("- 暂无。")

    lines.append("")
    lines.append("待改进轮次:")
    for row in failures[:10]:
        preview = str(row.get("output") or "").replace("\n", " ")[:90]
        issues = "；".join(row.get("issues") or [])
        lines.append(
            f"- {row['case_id']} / {row['model']}: {issues} / {preview}"
        )
    if not failures:
        lines.append("- 暂无。")

    lines.extend(
        [
            "",
            "## 维度洞察",
            "",
            "| 维度 | 通过 | 总数 | 通过率 |",
            "|:--|--:|--:|--:|",
        ]
    )
    for key, stats in sorted(aggregate["by_expectation"].items()):
        rate = (
            round(stats["passed"] / stats["total"] * 100, 2)
            if stats["total"]
            else 0.0
        )
        label = "触发场景" if key == "trigger" else "抑制场景"
        lines.append(f"| {label} | {stats['passed']} | {stats['total']} | {rate}% |")
    for model, stats in sorted(aggregate["by_model"].items()):
        rate = (
            round(stats["passed"] / stats["total"] * 100, 2)
            if stats["total"]
            else 0.0
        )
        lines.append(
            f"| 模型:{model} | {stats['passed']} | {stats['total']} | {rate}% |"
        )

    lines.extend(
        [
            "",
            "## 失败样本明细",
            "",
            "| case_id | 模型 | 期望 | 问题 | 输出预览 |",
            "|:--|:--|:--|:--|:--|",
        ]
    )
    for row in failures:
        expected = "触发" if row.get("expect_sticker") else "抑制"
        issues = "；".join(row.get("issues") or [])
        preview = str(row.get("output") or "").replace("\n", " ")[:90]
        lines.append(
            f"| {row['case_id']} | {row['model']} | {expected} | "
            f"{issues} | {preview} |"
        )
    if not failures:
        lines.append("| - | - | - | - | - |")

    warning_rows = [row for row in results if row.get("warnings")]
    lines.extend(
        [
            "",
            "## Warning 样本明细",
            "",
            "| case_id | 模型 | 表情包 | Warning | 输出预览 |",
            "|:--|:--|:--|:--|:--|",
        ]
    )
    for row in warning_rows:
        warnings = "；".join(row.get("warnings") or [])
        preview = str(row.get("output") or "").replace("\n", " ")[:90]
        lines.append(
            f"| {row['case_id']} | {row['model']} | "
            f"{row.get('sticker_name') or ''} | {warnings} | {preview} |"
        )
    if not warning_rows:
        lines.append("| - | - | - | - | - |")

    path.write_text("\n".join(lines), encoding="utf-8")


def selected_scene_ids_for_level(run_level: str) -> set[str] | None:
    if run_level == "smoke":
        return set(SMOKE_SCENE_IDS)
    return None


def models_for_level(run_level: str, models: tuple[str, ...]) -> tuple[str, ...]:
    return () if run_level == "dry-run" else models


def validate_real_run_env(models: tuple[str, ...]) -> None:
    env_status = ensure_runtime_key_aliases()
    missing: list[str] = []
    if any(model.startswith("deepseek") for model in models) and not env_status[
        "DASHSCOPE_API_KEY"
    ]:
        missing.append("DASHSCOPE_API_KEY")
    if any("doubao" in model for model in models) and not (
        env_status["VOLCENGINE_API_KEY"] or env_status["ARK_API_KEY"]
    ):
        missing.append("VOLCENGINE_API_KEY/ARK_API_KEY")
    if missing:
        raise RuntimeError("missing required API keys: " + ", ".join(missing))


def run_batch(
    *,
    output_dir: Path,
    run_level: str,
    prompt_template: str,
    models: tuple[str, ...] = DEFAULT_TARGET_MODELS,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    if run_level not in {"dry-run", "smoke", "full"}:
        raise ValueError("run_level must be one of: dry-run, smoke, full")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "payloads").mkdir(parents=True, exist_ok=True)
    cases_path = output_dir / "cases.jsonl"
    results_path = output_dir / "results.jsonl"
    summary_path = output_dir / "summary.md"
    for path in (cases_path, results_path):
        if path.exists():
            path.unlink()

    (output_dir / "prompt_snapshot.md").write_text(prompt_template, encoding="utf-8")

    cases = build_cases(scene_ids=selected_scene_ids_for_level(run_level))
    for case in cases:
        append_jsonl(cases_path, case_record(case))

    target_models = models_for_level(run_level, models)
    if target_models:
        validate_real_run_env(target_models)
    adapter = ModelAdapter() if target_models else None

    results: list[dict[str, Any]] = []
    for case in cases:
        messages = build_messages(prompt_template=prompt_template, case=case)
        write_payload(
            output_dir / "payloads" / f"{case.case_id}.json",
            case_record(case),
            messages,
        )
        model_ids = target_models or ("dry-run",)
        for model_id in model_ids:
            if run_level == "dry-run":
                call = {
                    "success": True,
                    "error": "",
                    "output": dry_run_output(case.scene),
                    "latency": 0.0,
                    "input_tokens": sum(len(item["content"]) for item in messages) // 2,
                    "output_tokens": 48,
                }
            else:
                assert adapter is not None
                call = call_model(adapter, model_id, messages, max_tokens=max_tokens)
            metrics = validate_sticker_output(call["output"], case.scene)
            record = {
                **case_record(case),
                "model": model_id,
                "run_level": run_level,
                **{key: value for key, value in call.items() if key != "output"},
                "output": call["output"],
                **metrics,
            }
            append_jsonl(results_path, record)
            results.append(record)

    write_summary(summary_path, results, run_level)
    aggregate = aggregate_results(results)
    write_json(
        output_dir / "meta.json",
        {
            "created_at": datetime.now().isoformat(),
            "run_level": run_level,
            "models": list(target_models or ("dry-run",)),
            "aggregate": aggregate,
        },
    )
    return {"output_dir": output_dir, **aggregate}


def load_prompt_template(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    if REFERENCE_PROMPT_PATH.exists():
        return REFERENCE_PROMPT_PATH.read_text(encoding="utf-8", errors="ignore")
    raise FileNotFoundError(
        "未找到默认业务提示词文件，请使用 --prompt-file 显式指定: "
        f"{REFERENCE_PROMPT_PATH}"
    )


def default_output_dir(run_level: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_REPORT_ROOT / f"sticker_trigger_{run_level}_{timestamp}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate sticker trigger behavior")
    parser.add_argument(
        "--run-level",
        choices=("dry-run", "smoke", "full"),
        default="dry-run",
    )
    parser.add_argument(
        "--prompt-file",
        help="新版本提示词模板文件；不传则优先读取业务参考文件",
    )
    parser.add_argument("--output-dir", help="输出目录")
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument(
        "--models",
        nargs="*",
        default=list(DEFAULT_TARGET_MODELS),
        help="真实调用模型列表；dry-run 忽略",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prompt_template = load_prompt_template(args.prompt_file)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else default_output_dir(args.run_level)
    )
    result = run_batch(
        output_dir=output_dir,
        run_level=args.run_level,
        prompt_template=prompt_template,
        models=tuple(args.models),
        max_tokens=args.max_tokens,
    )
    print(
        (
            "[OK] run_level={run_level} total={total} "
            "passed={passed} output_dir={output_dir}"
        ).format(
            run_level=args.run_level,
            total=result["total"],
            passed=result["passed"],
            output_dir=result["output_dir"],
        )
    )


if __name__ == "__main__":
    main()
