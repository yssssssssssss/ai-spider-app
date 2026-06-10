"""
任务规划器：调用 LLM 分析用户需求，生成 AutoGLM 可执行的自然语言指令
"""
import json
from openai import OpenAI
from app.config import settings


SEARCH_SCENE_MARKERS = ("搜索", "search", "检索", "查询", "商品列表", "结果页", "商品详情", "详情页", "商品页")
POPUP_CLOSE_MARKERS = ("弹窗", "浮层", "广告", "关闭", "关闭后", "跳过")
POPUP_CLOSE_RULE = (
    "执行约束：如果出现与本次任务相关的弹窗、广告或浮层，不要立即关闭，也不要立即结束任务；"
    "必须先停留在弹窗页等待一次截图保存，然后点击关闭、跳过、取消或返回关闭弹窗；"
    "确认弹窗消失后，在关闭后的目标页面再等待一次截图保存。"
    "未完成弹窗页截图和关闭后页面截图前，禁止结束任务。"
)
SEARCH_SUBMIT_RULE = (
    "执行约束：如果需要在搜索框输入文本，输入完成后必须点击页面上的“搜索”按钮，再等待搜索结果加载。"
)


def should_search_for_keywords(target_scenario: str | None) -> bool:
    if not target_scenario:
        return True
    normalized = target_scenario.lower()
    return any(marker in normalized for marker in SEARCH_SCENE_MARKERS)


def keyword_instruction(keywords: list[str], target_scenario: str | None) -> str | None:
    if not keywords:
        return None
    keyword_text = "、".join(k for k in keywords if k)
    if not keyword_text:
        return None
    if should_search_for_keywords(target_scenario):
        return f"在搜索框输入'{keyword_text}'后点击“搜索”按钮"
    return f"重点关注'{keyword_text}'相关内容"


def requires_popup_close_flow(text: str | None) -> bool:
    if not text:
        return False
    return any(marker in text for marker in POPUP_CLOSE_MARKERS) and "截图" in text


def append_execution_rules(instruction: str) -> str:
    rules = []
    if "搜索" in instruction and "点击“搜索”按钮" not in instruction and "点击搜索按钮" not in instruction:
        rules.append(SEARCH_SUBMIT_RULE)
    if requires_popup_close_flow(instruction) and "未完成弹窗页截图和关闭后页面截图前，禁止结束任务" not in instruction:
        rules.append(POPUP_CLOSE_RULE)
    if not rules:
        return instruction
    parts = [instruction.rstrip("。")] + [rule.rstrip("。") for rule in rules]
    return "。".join(parts) + "。"


def _planner_client() -> tuple[OpenAI, str]:
    if settings.VLM_API_KEY:
        return OpenAI(api_key=settings.VLM_API_KEY, base_url=settings.VLM_BASE_URL), settings.VLM_MODEL
    if settings.OPENAI_API_KEY:
        return OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL), settings.VLM_MODEL
    return OpenAI(api_key=settings.PHONE_AGENT_API_KEY, base_url=settings.PHONE_AGENT_BASE_URL), settings.PHONE_AGENT_MODEL


async def plan_task(
    target_app: str | None,
    target_scenario: str | None,
    keywords: list[str],
    description: str | None,
) -> str:
    """
    调用 LLM 将用户需求转为 AutoGLM 可执行的自然语言指令。

    Args:
        target_app: 目标 App 名称（如"淘宝"）
        target_scenario: 目标场景（如"大促弹窗"）
        keywords: 搜索词或关注点列表
        description: 用户补充说明

    Returns:
        LLM 生成的自然语言指令字符串
    """
    user_content = json.dumps({
        "目标App": target_app or "未指定",
        "目标场景": target_scenario or "未指定",
        "关键词或关注点": keywords,
        "补充说明": description or "无",
    }, ensure_ascii=False)

    system_prompt = """你是移动端App自动化操作专家。你的任务是将用户需求转化为一条精确的自然语言指令，用于驱动AI手机助手（AutoGLM）自动操作手机App并截图保存。

指令要求：
1. 必须包含完整操作序列：打开App → 搜索/导航 → 到达目标页面 → 截图保存
2. 如果有筛选条件（如价格区间、品牌），要明确描述操作步骤
3. 搜索框、搜索结果页、商品列表页、商品详情页等需要定位具体商品/内容的场景，可以把关键词作为搜索或导航线索
4. 如果需要在搜索框输入文本，输入完成后必须点击页面上的“搜索”按钮，再等待搜索结果加载
5. 弹窗、Banner、频道页等不依赖文本输入的场景，把关键词当作关注点、筛选条件或识别目标，不要强行搜索
6. 指令要具体、可执行，避免模糊表述
7. 只输出一条指令文本，不要解释、不要编号、不要多余内容
8. 指令结尾必须是"并截图保存到本地"

示例输入：
{"目标App": "淘宝", "目标场景": "大促弹窗", "关键词或关注点": ["限时优惠", "红包"], "补充说明": "关注红色主题的限时优惠弹窗"}

示例输出：
打开淘宝App，进入首页或活动入口，找到包含限时优惠和红包利益点的红色主题弹窗，并截图保存到本地"""

    try:
        client, model = _planner_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=256,
        )
        instruction = response.choices[0].message.content.strip()
        print(f"🤖 LLM 生成指令: {instruction}")
        return append_execution_rules(instruction)
    except Exception as e:
        # LLM 调用失败时回退到模板拼接
        print(f"⚠️ LLM 指令生成失败，回退到模板拼接: {e}")
        return _fallback_instruction(target_app, target_scenario, keywords, description)


def _fallback_instruction(
    target_app: str | None,
    target_scenario: str | None,
    keywords: list[str],
    description: str | None,
) -> str:
    """LLM 不可用时的回退：模板拼接生成指令"""
    parts = []
    if target_app:
        parts.append(f"打开{target_app}App")
    instruction = keyword_instruction(keywords, target_scenario)
    if instruction:
        parts.append(instruction)
    if target_scenario:
        parts.append(f"找到{target_scenario}")
    if description:
        parts.append(description)
    parts.append("并截图保存到本地")
    return append_execution_rules("，".join(parts))
