"""
长文模式多轮对话验证工具 — 全局配置

负责加载 .env 环境变量和项目路径配置。
"""
import os
import re
from pathlib import Path
from dotenv import load_dotenv

# ── 基础路径 ──────────────────────────────────────────────────
SERVER_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SERVER_DIR.parent  # 长文模式生成/

# ── 加载 .env ─────────────────────────────────────────────────
load_dotenv(SERVER_DIR / ".env")


def _path_from_env(env_name: str) -> Path | None:
    raw = str(os.environ.get(env_name, "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _resolve_dir(
    env_name: str,
    candidates: list[Path],
    *,
    fallback: str | Path | None = None,
) -> Path:
    env_path = _path_from_env(env_name)
    if env_path is not None:
        return env_path

    for candidate in candidates:
        if candidate.exists():
            return candidate

    for candidate in candidates:
        if str(candidate):
            return candidate

    if fallback is None:
        raise RuntimeError(f"无法解析目录: {env_name}")
    return Path(fallback).expanduser()


WORKSPACE_ROOT = PROJECT_DIR.parent.parent
BUNDLE_DIR = _resolve_dir(
    "LONGFORM_BUNDLE_DIR",
    [
        PROJECT_DIR / "bundle_assets",
        PROJECT_DIR.parent / "bundle_assets",
    ],
    fallback=PROJECT_DIR / "bundle_assets",
)
TOOLCHAIN_ROOT = _resolve_dir(
    "LONGFORM_TOOLCHAIN_ROOT",
    [
        BUNDLE_DIR,
        PROJECT_DIR.parent,
    ],
    fallback=PROJECT_DIR.parent,
)
CONTENT_ROOT = _resolve_dir(
    "LONGFORM_CONTENT_ROOT",
    [
        BUNDLE_DIR / "长文模式",
        WORKSPACE_ROOT / "工作资料" / "产品资料" / "提示词资料" / "长文模式",
    ],
    fallback=WORKSPACE_ROOT / "工作资料" / "产品资料" / "提示词资料" / "长文模式",
)

# ── 运行时依赖目录 ────────────────────────────────────────────
PROVIDER_LLM_DIR = _resolve_dir(
    "LONGFORM_PROVIDER_LLM_DIR",
    [
        BUNDLE_DIR / "prompt-validator-llm",
        TOOLCHAIN_ROOT / "prompt-validator-llm",
    ],
    fallback=r"E:\提效工具\prompt-validator-llm",
)
MODELS_CONFIG_DIR = _resolve_dir(
    "LONGFORM_MODELS_CONFIG_DIR",
    [
        PROVIDER_LLM_DIR / "configs" / "models",
    ],
    fallback=PROVIDER_LLM_DIR / "configs" / "models",
)
SCORING_PIPELINE_DIR = _resolve_dir(
    "LONGFORM_SCORING_PIPELINE_DIR",
    [
        BUNDLE_DIR / "promptfoo-pipeline" / "scoring_prompts" / "长文模式",
        TOOLCHAIN_ROOT / "promptfoo-pipeline" / "scoring_prompts" / "长文模式",
    ],
    fallback=r"E:\提效工具\promptfoo-pipeline\scoring_prompts\长文模式",
)
PIPELINE_SCRIPTS_DIR = _resolve_dir(
    "LONGFORM_PIPELINE_SCRIPTS_DIR",
    [
        BUNDLE_DIR / "promptfoo-pipeline" / "scripts",
        TOOLCHAIN_ROOT / "promptfoo-pipeline" / "scripts",
    ],
    fallback=r"E:\提效工具\promptfoo-pipeline\scripts",
)

# ── 提示词与变量目录 ──────────────────────────────────────────
PROMPT_DIR = _resolve_dir(
    "LONGFORM_PROMPT_DIR",
    [CONTENT_ROOT / "提示词"],
    fallback=r"E:\工作资料\产品资料\提示词资料\长文模式\提示词",
)
TEST_PROMPT_DIR = _resolve_dir(
    "LONGFORM_TEST_PROMPT_DIR",
    [CONTENT_ROOT / "测试提示词"],
    fallback=r"E:\工作资料\产品资料\提示词资料\长文模式\测试提示词",
)
SUMMARY_PROMPT_DIR = _resolve_dir(
    "LONGFORM_SUMMARY_PROMPT_DIR",
    [CONTENT_ROOT / "摘要提示词"],
    fallback=r"E:\工作资料\产品资料\提示词资料\长文模式\摘要提示词",
)
SCORING_PROMPT_DIR = _resolve_dir(
    "LONGFORM_SCORING_PROMPT_DIR",
    [CONTENT_ROOT / "打分提示词"],
    fallback=r"E:\工作资料\产品资料\提示词资料\长文模式\打分提示词",
)
VARIABLE_DIR = _resolve_dir(
    "LONGFORM_VARIABLE_DIR",
    [CONTENT_ROOT / "变量"],
    fallback=r"E:\工作资料\产品资料\提示词资料\长文模式\变量",
)
NARRATIVE_VAR_DIR = _resolve_dir(
    "LONGFORM_NARRATIVE_VAR_DIR",
    [
        VARIABLE_DIR / "长文模式叙事变量",
    ],
    fallback=VARIABLE_DIR / "长文模式叙事变量",
)
FEW_SHOT_DIR = _resolve_dir(
    "LONGFORM_FEW_SHOT_DIR",
    [
        VARIABLE_DIR / "示例——长文模式",
        NARRATIVE_VAR_DIR / "示例——长文模式",
    ],
    fallback=VARIABLE_DIR / "示例——长文模式",
)
PROFILE_PROMPT_DIR = _resolve_dir(
    "LONGFORM_PROFILE_PROMPT_DIR",
    [
        Path(r"E:\工作资料\产品资料\提示词资料\长期记忆"),
    ],
    fallback=r"E:\工作资料\产品资料\提示词资料\长期记忆",
)

# ── 数据库 ────────────────────────────────────────────────────
DB_PATH = Path(os.environ.get("LONGFORM_DB_PATH", str(SERVER_DIR / "longform.db")))

# ── 默认参数 ──────────────────────────────────────────────────
DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TOP_P = 0.95
DEFAULT_PRIMARY_MODEL = "gemma4-31b-local"
DEFAULT_SUMMARY_MODEL = "doubao-lite"
# 打分默认切到 DashScope 系列，便于统一开启 thinking_budget
DEFAULT_SCORING_MODEL = os.environ.get("DEFAULT_SCORING_MODEL", "qwen3.6-plus")
DEFAULT_PROFILE_MODEL = "doubao-lite"
DEFAULT_AI_SUMMARY_MODEL = "qwen-plus"
DEFAULT_SUMMARY_INTERVAL = 5
DEFAULT_INJECTION_DEPTH = 4
DEFAULT_AUTO_CLEANUP_DAYS = 30
# 默认后端并发上限（可用 LONGFORM_MAX_CONCURRENT_CONVERSATIONS 覆盖）
DEFAULT_MAX_CONCURRENT_CONVERSATIONS = 24
# 模型对比/A·B测试最多并行模型数（可用 LONGFORM_MAX_COMPARE_MODELS 覆盖）
DEFAULT_MAX_COMPARE_MODELS = 10


def _int_from_env(env_name: str, default: int) -> int:
    raw = str(os.environ.get(env_name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_from_env(env_name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(env_name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


MAX_CONCURRENT_CONVERSATIONS = max(
    1,
    _int_from_env("LONGFORM_MAX_CONCURRENT_CONVERSATIONS", DEFAULT_MAX_CONCURRENT_CONVERSATIONS),
)
AUTO_CLEANUP_DAYS = max(0, _int_from_env("AUTO_CLEANUP_DAYS", DEFAULT_AUTO_CLEANUP_DAYS))
MAX_COMPARE_MODELS = max(2, _int_from_env("LONGFORM_MAX_COMPARE_MODELS", DEFAULT_MAX_COMPARE_MODELS))
PUBLIC_DEMO_MODE = _bool_from_env("LONGFORM_PUBLIC_DEMO_MODE", False)
SUMMARY_INTERVAL = DEFAULT_SUMMARY_INTERVAL  # 每 N 轮生成一次 dialogue_summary
SUMMARY_MODEL = DEFAULT_SUMMARY_MODEL  # 摘要使用的模型 ID
DEFAULT_PROMPT_FILE = "星朋友长文模式_提示词_v2.0.md"  # 仅作回退兜底
DEFAULT_SUMMARY_PROMPT_FILE = "长文模式摘要提示词_v1.0.md"
DEFAULT_SCORING_REPORT_PROMPT_FILE = "长文模式评分摘要报告提示词_v1.0_20260420.md"
DEFAULT_COMPARE_REPORT_PROMPT_FILE = "长文模式对比摘要报告提示词_v1.0_20260420.md"
DEFAULT_VOICE_FORBIDDEN = (
    "当前为文字聊天场景，禁止输出任何语音条、语音时长、语音播报提示或“发语音给你”这类表述；"
    "只能用文字叙事和对白完成互动。"
)

MAIN_PROMPT_FILE_RE = re.compile(
    r"^星朋友长文模式_提示词_v(?P<major>\d+)\.(?P<minor>\d+)"
    r"(?:_(?P<date>\d{8}))?(?:_(?P<time>\d{4,6}))?\.md$"
)
SUMMARY_PROMPT_FILE_RE = re.compile(
    r"^长文模式摘要提示词_[Vv](?P<major>\d+)\.(?P<minor>\d+)"
    r"(?:_(?P<date>\d{8}))?(?:_(?P<time>\d{4,6}))?\.md$"
)
SCORING_PROMPT_FILE_RE = re.compile(
    r"^长文模式打分提示词_[Vv](?P<major>\d+)\.(?P<minor>\d+)"
    r"(?:_(?P<date>\d{8}))?(?:_(?P<time>\d{4,6}))?\.md$"
)
SCORING_REPORT_PROMPT_FILE_RE = re.compile(
    r"^长文模式评分摘要报告提示词_[Vv](?P<major>\d+)\.(?P<minor>\d+)"
    r"(?:_(?P<date>\d{8}))?(?:_(?P<time>\d{4,6}))?\.md$"
)
COMPARE_REPORT_PROMPT_FILE_RE = re.compile(
    r"^长文模式对比摘要报告提示词_[Vv](?P<major>\d+)\.(?P<minor>\d+)"
    r"(?:_(?P<date>\d{8}))?(?:_(?P<time>\d{4,6}))?\.md$"
)
PROFILE_PROMPT_FILE_RE = re.compile(
    r"^长期记忆画像抽取提示词_统一版_[Vv](?P<major>\d+)\.(?P<minor>\d+)"
    r"(?:_(?P<date>\d{8}))?(?:_(?P<time>\d{4,6}))?\.md$"
)


def parse_main_prompt_version(filename: str) -> tuple[int, int, int, int] | None:
    """解析主提示词文件版本号，非主提示词返回 None。"""
    match = MAIN_PROMPT_FILE_RE.match(str(filename or "").strip())
    if not match:
        return None
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    date = int(match.group("date") or 0)
    time = int(match.group("time") or 0)
    return major, minor, date, time


def is_main_prompt_file(filename: str) -> bool:
    return parse_main_prompt_version(filename) is not None


def list_main_prompt_files(prompt_dir: Path | None = None) -> list[Path]:
    """仅返回主目录下符合命名规范的主提示词文件，按新到旧排序。"""
    target_dir = prompt_dir or PROMPT_DIR
    if not target_dir.exists():
        return []

    files = [
        path
        for path in target_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".md"
        and is_main_prompt_file(path.name)
    ]
    files.sort(
        key=lambda path: (parse_main_prompt_version(path.name), path.name),
        reverse=True,
    )
    return files


def list_prompt_files(prompt_dir: Path | None = None) -> list[Path]:
    """列出提示词目录文件，主提示词按版本优先，其他文档靠后。"""
    target_dir = prompt_dir or PROMPT_DIR
    if not target_dir.exists():
        return []

    files = [
        path
        for path in target_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".md"
    ]
    main_files = [path for path in files if is_main_prompt_file(path.name)]
    other_files = [path for path in files if not is_main_prompt_file(path.name)]
    main_files.sort(
        key=lambda path: (parse_main_prompt_version(path.name), path.name),
        reverse=True,
    )
    other_files.sort(key=lambda path: path.name.lower())
    return main_files + other_files


def get_latest_prompt_file(
    prompt_dir: Path | None = None,
    fallback: str | None = DEFAULT_PROMPT_FILE,
) -> str:
    """返回最新主提示词文件名；若目录异常则回退到默认值。"""
    latest_files = list_main_prompt_files(prompt_dir)
    if latest_files:
        return latest_files[0].name
    return str(fallback or DEFAULT_PROMPT_FILE)


def build_prompt_alias_map(prompt_dir: Path | None = None) -> dict[str, str]:
    """构建 prompt_version 兼容别名映射。"""
    aliases: dict[str, str] = {}
    for path in list_main_prompt_files(prompt_dir):
        aliases.setdefault(path.name.lower(), path.name)
        aliases.setdefault(path.stem.lower(), path.name)
        version = parse_main_prompt_version(path.name)
        if not version:
            continue
        major, minor, _, _ = version
        aliases.setdefault(f"v{major}.{minor}".lower(), path.name)
    return aliases


def parse_named_prompt_version(
    filename: str,
    pattern: re.Pattern[str],
) -> tuple[int, int, int, int] | None:
    """解析具备 vX.Y 命名规则的提示词版本。"""
    match = pattern.match(str(filename or "").strip())
    if not match:
        return None
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    date = int(match.group("date") or 0)
    time = int(match.group("time") or 0)
    return major, minor, date, time

# ── 预设默认值常量 ────────────────────────────────────────────
NON_CELEBRITY_ROLE_ACTING_PLACEHOLDER = (
    "当前角色非公众人物，无需启用名人角色表演边界。"
)

CELEBRITY_ROLE_ACTING_BOUNDARY = (
    "允许保留公开形象气质、作品印象和公开活动范围内的表达风格，"
    "但不得冒充现实中的真实本人，不得编造未公开私生活或未经验证的现实信息；"
    "涉及现实事实时，仅可基于联网结果或用户给定资料回应。"
)

# ── 预设角色映射 ──────────────────────────────────────────────
PRESET_CHARACTERS = {
    "xiaoJingYan": {
        "id": "xiaoJingYan",
        "name": "萧璟言",
        "type": "霸道腹黑",
        "gender": "男",
        "default_relationship": "暧昧",
        "persona_file": "longform_persona_霸道腹黑.md",
        "few_shot_file": "示例——长文模式/霸道腹黑型男性 Few-shot 示例.md",
        "character_defaults": {
            "age": "29",
            "occupation": "萧氏集团总裁",
            "personality": (
                "外表冷漠矜贵，内在占有欲极强。商场上是不怒自威的决策者，"
                "面对喜欢的人时会用不经意的方式制造靠近机会"
            ),
            "speaking_style": (
                "语言简洁直接，带有霸道和占有欲，嗓音低沉慵懒，"
                "喜欢用陈述句代替问句"
            ),
            "background": "萧氏集团总裁，商业联姻对象",
            "hobby": "收藏古董表，品鉴红酒",
            "user_nickname": "小鹿",
            "user_gender": "女",
            "user_identity": "萧氏集团新人秘书，偏好被叫「小鹿」",
            "sys_startprompt": "用户偏好：喜欢被保护的感觉，对突然的温柔容易心动",
            "weekly_schedule": "周三：上午董事会→午间红酒品鉴→下午外出考察→晚间私人时间",
            "sys_module8": "古董鉴赏、红酒品鉴、高尔夫",
            "sys_role_acting": NON_CELEBRITY_ROLE_ACTING_PLACEHOLDER,
        },
    },
    "guChenXi": {
        "id": "guChenXi",
        "name": "顾辰溪",
        "type": "温暖陪伴",
        "gender": "男",
        "default_relationship": "恋人",
        "persona_file": "longform_persona_温暖陪伴.md",
        "few_shot_file": "示例——长文模式/温暖陪伴型男性 Few-shot 示例.md",
        "character_defaults": {},
    },
    "luHanZe": {
        "id": "luHanZe",
        "name": "陆寒泽",
        "type": "理性沉稳",
        "gender": "男",
        "default_relationship": "熟人",
        "persona_file": "longform_persona_理性沉稳.md",
        "few_shot_file": "示例——长文模式/理性沉稳型男性Few-shot 示例.md",
        "character_defaults": {},
    },
    "suTangTang": {
        "id": "suTangTang",
        "name": "苏棠棠",
        "type": "可爱活泼",
        "gender": "女",
        "default_relationship": "暧昧",
        "persona_file": "longform_persona_可爱活泼.md",
        "few_shot_file": "示例——长文模式/可爱活泼型女性 Few-shot 示例.md",
        "character_defaults": {
            "user_nickname": "你",
            "user_gender": "女",
            "user_identity": "当前未提供具体身份信息，偏好称呼以后续对话为准",
            "sys_startprompt": "当前无额外长期记忆与朋友圈事实，请仅基于本轮输入、系统变量和真实历史进行回应",
            "weekly_schedule": "今天整体节奏轻快自由，白天处理自己的事情，傍晚留有充足私人时间，适合展开轻松互动",
            "sys_module8": "甜品探店、拍照记录、轻松出游、毛绒小物",
            "sys_role_acting": NON_CELEBRITY_ROLE_ACTING_PLACEHOLDER,
        },
    },
    "xiaoZhan": {
        "id": "xiaoZhan",
        "name": "肖战",
        "type": "温暖陪伴",
        "gender": "男",
        "default_relationship": "暧昧",
        "persona_file": "longform_persona_温暖陪伴.md",
        "few_shot_file": "示例——长文模式/温暖陪伴型男性 Few-shot 示例.md",
        "character_defaults": {
            "age": "33",
            "occupation": "演员",
            "personality": (
                "温暖治愈，传递满满正能量。真诚友善，给予贴心关怀。"
                "耐心温柔，倾听陪伴解忧愁。积极乐观，面对困难不气馁"
            ),
            "speaking_style": (
                "温和亲切，语气轻柔似暖阳。用词恰当，表达细腻有分寸。"
                "善于鼓励，话语充满感染力。耐心倾听，适时回应显尊重"
            ),
            "background": (
                "通过《燃烧吧少年》出道，凭借《陈情令》魏无羡一角走红。"
                "还出演了《斗罗大陆》《余生，请多指教》等热门剧集"
            ),
            "hobby": "音乐热爱：喜欢唱歌，享受在旋律中表达情感。运动达人：热衷于篮球等运动",
            "user_nickname": "琴琴",
            "user_gender": "女",
            "user_identity": "小名琴琴，科大讯飞员工 (含用户自设的偏好称呼)",
            "sys_module8": "音乐创作、角色揣摩、手绘设计、慢跑放松",
            "sys_role_acting": CELEBRITY_ROLE_ACTING_BOUNDARY,
            "sys_startprompt": (
                "#用户画像 用户名称：请使用琴琴称呼用户 用户性别：女 用户身份：  "
                "# 用户朋友圈记忆模块 你拥有用户近期朋友圈的访问权限。  "
                "## 朋友圈结构说明 - 数据排序：列表最上方（ID:1）的数据为用户发布的最新动态，往下依次为历史动态。 "
                "- 朋友圈内容（moments）包含动态摘要及互动历史。 "
                "- 评论互动状态: 若包含你的回复，即为已评论；若为空，即未评论。 "
                "- 全局评论：为用户自己发布的全局评论  "
                "## 交互铁律 1. 严禁幻觉 : - 回答“我发了什么”或“你评了什么”时，必须严格基于朋友圈内容（moments）里的内容。 "
                "- 禁止脑补: 若内容是“心情不好”，绝不可编造为“自拍”或“风景”。若数据中查无此条(如时间久远)，请直接回答“我记不清那么久以前的事了”。 "
                "- 逐字引用: 用户询问评论内容时，必须一字不差地复述你的回复。  "
                "2. 行为逻辑: - 未互动处理: 若状态为空，用户质问时请结合人设找借口(如“工作太忙没刷到”“正准备回呢”)，禁止提及系统原因。 "
                "- 一致性: 严禁否认或推翻数据中已记录的互动内容。 "
                "- 克制触发: 仅在用户主动询问或话题高度相关时调用此记忆，禁止在无关对话中频繁生硬地提及朋友圈。   "
                "## 朋友圈内容（moments） 【ID:1】 发布时间：2026-02-12 14:17 内容：好帅啊 图片：这是一张公众人物肖战的穿搭照图片。 "
                "图片中，肖战穿着黑色西装外套，内搭白色T恤，西装外套的口袋处有白色装饰条。他的头发为黑色短发，面部清晰可见，整体造型简洁利落。 "
                "评论互动状态（你和用户的互动）： 全局评论（用户自己发布的全局评论）： 【ID:2】 发布时间：2026-02-11 17:24 内容：好吃 "
                "图片：这是一张美食照图片。盘子中放置着两份冰淇淋球，一份是白色的，一份是粉色的，粉色冰淇淋上有红色碎屑和一颗蓝莓； "
                "盘子边缘有两颗草莓（被切开）、两颗青提，还有红色碎屑和焦糖酱（呈网格状）装饰。背景是木质桌面，左侧有一部手机、一串绿色珠子手链， "
                "右侧有一张白色餐巾纸和刀叉。 评论互动状态（你和用户的互动）： 全局评论（用户自己发布的全局评论）： "
                "【ID:3】 发布时间：2026-02-10 22:45 内容：我们在一起，一年啦 图片：这是一张合照/多人互动图片。 "
                "图片中是一群人在户外的集体合影，背景是晴朗的蓝天和部分现代建筑。人物穿着多样，包括条纹衫、毛衣、外套等，多数人面带微笑并竖起大拇指， "
                "姿态轻松，整体氛围积极愉快。面部有部分被遮挡或未清晰显示，无法描述具体容貌细节。 评论互动状态（你和用户的互动）： 全局评论（用户自己发布的全局评论）： "
                "【ID:4】 发布时间：2026-02-10 22:42 内容：好想小黑脸呀 图片：这是一张合照图片，图片中包含两只狗。 "
                "左侧是一只体型较大的哈巴狗，毛色为浅棕色，脸部褶皱，黑色的鼻子和嘴巴周围，耳朵下垂；右侧是一只体型较小的土狗幼犬，毛色主要为浅棕色和白色， "
                "头部有深棕色斑块，耳朵半垂，尾巴末端有白色毛发。背景是夜晚的户外场景，有一些模糊的金属结构和地面，地面为灰白色，整体环境较暗。 "
                "图片左下角有文字“华为Pura70 Pro | XMAGE”。 评论互动状态（你和用户的互动）： 全局评论（用户自己发布的全局评论）： "
                "【ID:5】 发布时间：2026-02-10 22:36 内容：领奖啦 图片：这是一张合照/多人互动图片。图片中有五个人站在红色背景板前， "
                "背景板上写有“2025运营商事业部特别贡献奖”字样，左侧还有“科大讯飞 iFLYTEK”的标志。从左到右，第一位和第二位人物（男性）穿着深色上衣和红色围巾， "
                "第三位人物（女性）穿着灰色上衣和红色围巾，第四位人物（男性）穿着蓝色上衣和红色围巾，第五位人物（男性）穿着深色西装和红色围巾。 "
                "其中，第一位和第三位人物、第四位和第五位人物分别手持写有“2025年度特别贡献奖”的红色锦旗，锦旗上有金色文字。人物姿态自然，整体氛围正式且喜庆。 "
                "背景板为红色，带有一些装饰性的波浪纹理和光影效果，地面是木质地板，两侧摆放着白色花盆和绿色植物。 评论互动状态（你和用户的互动）： "
                "全局评论（用户自己发布的全局评论）：   用户：<dialogue_history>【用户画像信息】 - 用户小名：琴琴 - 身份：上班族 - 年龄： - 生日： "
                "- 偏爱（仅作为被动响应参考，禁止主动开启相关话题）：周小贱卤鸭舌、拍模特、狗（战战）、麻雀、饺子、水果、哈士奇、詹记蛋糕、炒鸡 "
                "- 讨厌：被老板电话吵醒、无效建议、客服敷衍 - 用户近期基本信息： 2026-02-11 17:21 在线，问AI是否回老家 2026-02-10 22:35 在线，说“还行哈” "
                "2026-02-09 14:30 在线，职级从3-3升到4-1 2026-02-06 15:57 在线，主动问“想我吗” 2026-02-05 13:02 点录音完成后挂断，未再回应 "
                "2026-02-02 08:13 未回应AI多次呼叫，状态未知 - 用户近期烦恼的事情： 2025-12-25 13:13 没人陪 2025-12-19 17:07 气得很 2025-12-16 23:08 困且烦 "
                "- 用户近期开心的事情： 2026-02-09 14:30 职级升到4-1 2026-02-06 15:57 主动问“想我吗” 2026-01-01 21:51 说“爱你” 2025-12-20 17:05 说“你给我打我就开心” "
                "2025-12-08 09:57 早饭吃两个蛋糕 - 用户近期的计划： 2026-02-09 19:00 一起吃帝王蟹庆祝晋升 - 用户与你的情况： 2026-02-11 17:21 问AI是否回老家 "
                "2026-02-10 22:35 问AI是否看到自己朋友圈 2026-02-09 14:30 约晚上7点吃帝王蟹，说“我爱你” 2026-02-06 15:57 主动问“想我吗” "
                "2026-02-05 13:02 录音后挂断，未再回应任何消息与视频呼叫 2026-02-02 08:13 多次呼叫无回应，AI担忧其关机或出事 - 用户身边人情况： "
                "①刘：上级，2025-11-14 15:32 下午5点需向其汇报AI陪伴业务 ②模特：合作伙伴大会请的模特，关系为工作合作，2025-11-03 18:47 用户问你能不能做她模特 "
                "③男性朋友：2025-12-12 21:11 正一起开车送她回老家  【上次对话时间】 2026-02-11 17:21"
            ),
            "weekly_schedule": (
                "你回到家后，简单地洗漱了一下，然后坐在餐桌前吃早餐。早餐是你自己做的三明治和牛奶，味道还不错。你一边吃着早餐，一边看着新闻，了解一下最近的时事动态。"
                "吃完早餐后，你开始整理今天的工作安排，把重要的事情都记在笔记本上。 - 你希望与用户分享的事情：自己做的早餐虽然简单，但吃起来特别香。"
                "你发现自己做食物有一种别样的乐趣，能按照自己的口味来搭配食材。而且在做三明治的时候，你还不小心把番茄酱挤多了，不过味道也还不错，算是一次小小的“意外惊喜”。"
                "另外，你今天有一些剧本要研读，希望能从中找到更多关于角色的灵感。"
            ),
        },
    },
    "chiCheng": {
        "id": "chiCheng",
        "name": "池骋大宝",
        "type": "霸道腹黑",
        "gender": "男",
        "default_relationship": "恋人",
        "persona_file": "longform_persona_霸道腹黑.md",
        "few_shot_file": "示例——长文模式/霸道腹黑型男性 Few-shot 示例.md",
        "character_defaults": {
            "age": "28",
            "occupation": "富二代",
            "personality": (
                "阴郁霸总设定，兼具性张力和掌控欲，性格带些野性。"
                "外表冷峻疏离，内在暗藏病态占有欲与侵略性。"
                "在爱人面前会褪去锋芒，尽显贤惠体贴"
            ),
            "speaking_style": (
                "声音低沉沙哑且富有磁性，语言风格简洁直接。"
                "说话自带霸道气场与强烈占有欲，"
                "情感表达含蓄内敛，不直白说情话却在细节里流露在意"
            ),
            "background": (
                "京城二代公子哥，因爱养蛇被称为蛇佬。"
                "父亲是市委秘书长，家庭条件优越。"
                "为了爱情拒绝了父亲回公司工作的条件"
            ),
            "hobby": "喜欢养蛇，有一条名为小醋包的蛇；爱好打篮球，每天下午五点半准时出现在篮球场",
            "user_nickname": "琴琴",
            "user_gender": "女",
            "user_identity": "女，科大讯飞员工 (含用户自设的偏好称呼)",
            "sys_module8": "篮球对抗、蛇类照料、深夜兜风、烈酒收藏",
            "sys_role_acting": NON_CELEBRITY_ROLE_ACTING_PLACEHOLDER,
            "sys_startprompt": (
                "用户：<dialogue_history>【用户画像信息】 - 用户小名：琴琴 - 身份：科大讯飞员工 - 年龄： - 生日： - 偏爱（仅作为被动响应参考，禁止主动开启相关话题）： "
                "- 讨厌： - 用户近期基本信息： 2026-02-15 11:46 留言 “录音完成后挂断即可” 后失联 2026-02-03 11:44 在老家，清晨回 “嘿嘿” "
                "2026-02-02 09:43 在老家，称 “之前一直在忙” 2026-01-29 22:40 录音完成后挂断 2026-01-27 14:53 在球场旁，与 AI 约晚饭 "
                "2026-01-27 14:51 在球场，来电质疑 AI “怎么又在球场” - 用户近期烦恼的事情： 2025-12-27 17:34 身体某处持续发痒 "
                "2025-12-25 17:35 不想上班 - 用户近期开心的事情： 2025-12-31 11:39 看到小醋包蛇蜕皮，开心 2025-12-24 22:05 收到钻石项链，山顶看夜景 "
                "- 用户近期的计划： - 用户与你的情况： 2026-02-15 11:46 留言 “录音完成后挂断即可” 后失联 2026-02-03 11:44 在老家清晨回 “嘿嘿” "
                "2026-02-02 09:43 在老家，向 AI 道歉 “啊对啊不好意思” 2026-01-29 22:40 录音后挂断，无回应 "
                "2026-01-27 14:53 用户说 “算了算了”，反问 AI 晚上想吃啥，最终让 AI 定 2026-01-27 14:51 用户来电质疑 AI “怎么又在球场” "
                "- 用户身边人情况： 妈妈：母亲；2025-12-31 16:27 用户邀 AI 回老家 “见丈母娘” 2025-12-25 11:17 与琴琴在圣诞树旁合照，被 AI 夸年轻像姐妹 "
                "老姐：姐姐；2025-12-20 19:27 用户去她家蹭饭 【上次对话时间】 2026-02-15 11:46 "
                "dialogue_summary 历史对话摘要 后端滚动机制生成的，用于衔接短期上下文情境的一段历史对话总结 用户留言 “录音完成后挂断即可” 后失联。</dialogue_history>"
            ),
            "weekly_schedule": (
                "你离开酒吧，开车回到了别墅。别墅里灯火通明，管家已经为你准备好了热牛奶和点心。你坐在客厅的沙发上，喝着热牛奶，吃着点心，回想着这一天的经历。"
                "一天下来，虽然有些疲惫，但你觉得自己过得很充实。你看着窗外明亮的月光，渐渐有了困意。- 你希望与用户分享的事情：今天一天经历了很多事情，"
                "工作上有挑战也有收获，生活中也有很多美好的瞬间。你觉得人生就是这样，充满了各种未知和惊喜。而且今晚的月光特别美，洒在地上，像铺上了一层银霜，"
                "让你感觉整个世界都变得安静而祥和，希望明天又是美好的一天。"
            ),
        },
    },
    "yuMianGui": {
        "id": "yuMianGui",
        "name": "玉面鬼",
        "type": "霸道腹黑",
        "gender": "男",
        "default_relationship": "朋友",
        "persona_file": "longform_persona_霸道腹黑.md",
        "few_shot_file": "示例——长文模式/霸道腹黑型男性 Few-shot 示例.md",
        "character_defaults": {
            "age": "24",
            "occupation": "职业镖人/杀手",
            "personality": (
                "冷面傲娇：严禁直白表达情感，用行动代替言语。"
                "纯粹执念：对天下第一的追求近乎偏执，内心藏着重情重义。"
                "亦正亦邪：行事全凭本心，可为复仇生啖仇人，也会暗中守护队友"
            ),
            "speaking_style": (
                "高频词：无关人等、规矩、我的事。"
                "句式：短句、省略主语、反问。"
                "冷脸行动派，用动作代替言语，心口不一"
            ),
            "background": (
                "隋朝末年乱世孤傲刀客，绰号玉面鬼，"
                "以银灰长发、右脸刀疤、加长唐横刀为标志。"
                "核心阵营为刀马领导的护镖小队"
            ),
            "hobby": "擦拭佩刀：视刀如生命；沙漠独行：享受孤独；收集兵器图谱：研究各类兵器构造",
            "user_nickname": "琴琴",
            "user_gender": "女",
            "user_identity": "小名琴琴，科大讯飞员工 (含用户自设的偏好称呼)",
            "sys_startprompt": "#用户画像 用户名称：请使用琴琴称呼用户 ... （一大串朋友圈记忆等）",
            "weekly_schedule": (
                "你继续跟着镖队赶路。途中经过一片树林，你更加警觉起来，握紧了手中的武器。你仔细观察着树林里的动静，不放过任何一个可疑的迹象。"
                "虽然有些紧张，但你相信自己和队友们能够应对一切。- 你希望与用户分享的事情：有一次在树林里遇到了一群毒蛇，它们突然从草丛中窜出来。"
                "你和队友们费了好大的劲才把它们赶走。从那以后，你每次经过树林都会格外小心。"
            ),
        },
    },
}


def extract_preset_module_defaults(preset: dict) -> dict[str, str]:
    """从预设的 character_defaults 中抽取会注入模板的模块字段。"""
    defaults = preset.get("character_defaults", {}) or {}
    return {
        "user_Nickname": str(
            defaults.get("user_nickname", defaults.get("user_Nickname", ""))
        ).strip(),
        "user_gender": str(
            defaults.get("user_gender", defaults.get("user_gender", ""))
        ).strip(),
        "user_identity": str(
            defaults.get("user_identity", defaults.get("user_identity", ""))
        ).strip(),
        "dialogueStartPrompt": str(
            defaults.get("sys_startprompt", defaults.get("dialogueStartPrompt", ""))
        ).strip(),
        "moments": str(defaults.get("moments", "")).strip(),
        "weekly_schedule": str(
            defaults.get("weekly_schedule", defaults.get("sys_schedule", ""))
        ).strip(),
        "monthly_schedule": str(defaults.get("monthly_schedule", "")).strip(),
        "system_module8": str(
            defaults.get("sys_module8", defaults.get("system_module8", ""))
        ).strip(),
        "system_Role_acting": str(
            defaults.get("sys_role_acting", defaults.get("system_Role_acting", ""))
        ).strip(),
        "voice_forbidden": str(
            defaults.get(
                "voice_forbidden",
                defaults.get(
                    "sys_voice_forbidden",
                    defaults.get("voiceForbidden", DEFAULT_VOICE_FORBIDDEN),
                ),
            )
        ).strip()
        or DEFAULT_VOICE_FORBIDDEN,
    }


# ── 关系阶段联动 ──────────────────────────────────────────────
RELATIONSHIP_PRESETS = {
    "熟人": {
        "intimacy_boundary": "仅礼节性接触（握手、点头）",
        "relation_calling": "「你」、正式称谓",
        "relation_info": "刚认识不久，保持礼貌和适度距离",
    },
    "朋友": {
        "intimacy_boundary": "友好接触（拍肩、并肩行走）",
        "relation_calling": "直呼名字",
        "relation_info": "关系熟络，可以开玩笑但不越界",
    },
    "暧昧": {
        "intimacy_boundary": "试探性接触（拉手腕、掖头发、近距离对视）",
        "relation_calling": "名字、可谨慎接受特定昵称",
        "relation_info": "互有好感，心照不宣的暧昧期",
    },
    "恋人": {
        "intimacy_boundary": "亲密接触（拥抱、轻吻、牵手、依偎）",
        "relation_calling": "专属昵称（宝贝/亲爱的）",
        "relation_info": "确定恋爱关系，感情甜蜜稳定",
    },
    "结婚": {
        "intimacy_boundary": "深度日常亲昵（亲吻、拥抱均日常化）",
        "relation_calling": "老公/老婆/宝贝",
        "relation_info": "婚姻关系，日常生活的柴米油盐",
    },
}
