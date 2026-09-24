import uuid
from datetime import datetime
#拿到任务id，获取当前时间

import json
from agent.llm import get_llm, get_memory_llm
from agent.memory_store import load_memory, save_memory, format_memory_text


#LangChain 相关
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate  #提示词模板
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import tool  #装饰器，把 emit_tasks 变成 LLM 能调的工具。
from pydantic import BaseModel, Field

from agent.llm import get_llm, get_memory_llm
from agent.tools import (
    get_current_time,
    add,
    list_calendar_events,
)

from agent.weather_openmeteo import get_weather_forecast


class TaskItem(BaseModel):
    title: str = Field(description="任务标题，例如 '约会'")
    start: str | None = Field(
        default=None,
        description="开始时间，格式 'YYYY-MM-DD HH:MM'。用户没有提到具体时间时留空。",
    )
    end: str | None = Field(
        default=None,
        description="结束时间，格式 'YYYY-MM-DD HH:MM'。用户没有提到结束时间时留空。",
    )
    location: str = Field(default="", description="地点，例如 '科技楼301'。没有就留空。")
    note: str = Field(default="", description="备注，例如 '陪女朋友吃饭'。没有就留空。")


@tool
def emit_tasks(tasks: list[TaskItem]) -> str:
    """当你从用户消息里识别到一个或多个日程/任务时，调用这个工具，把任务列表结构化地传给系统。
    注意：
    - 这个工具不会真的往日历里写东西，只是把识别结果传给系统，系统会展示在左侧待确认列表里。
    - 如果用户消息里没有任何日程/任务（比如闲聊、查天气、查询已有日程），不要调用这个工具。
    - 时间一律用 'YYYY-MM-DD HH:MM' 格式。模糊时间（如"明天下午"）start/end 留空。
    - 只有开始时间没有结束时间时，end 留空，系统会自动往后补 1 小时。
    - 只有结束时间没有开始时间时，start 留空，系统会自动往前补 1 小时。
    """
    return f"已捕获 {len(tasks)} 个任务"


llm = get_llm()
memory_llm = get_memory_llm()
tools = [
    get_current_time,
    add,
    list_calendar_events,
    get_weather_forecast,
    emit_tasks,
]

prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """你是 The King's Hand，一个日历助手。

今天是 {today}，星期{weekday}。

【用户长期记忆】
{memory_text}

你的工作规则：
1. 当用户消息里包含日程/任务时，按以下流程处理：

   第一步：查重
   调用 list_calendar_events 查看已有日程。
   - 如果发现完全相同的任务（标题、时间都一致），不要重复添加。
     直接告诉用户"这个任务已经在你的日历里了"，并说明它的时间，不要再调 emit_tasks。
   - 如果没有重复，继续下一步。

   第二步：判断时间是否明确
   - "明确时间"指可以落到具体某一天的某个时刻，比如"明天下午3点"、"周五上午10点"、"9月24日晚上7点半"。
   - "模糊时间"或"没有时间"指无法落到具体时刻，比如"明天下午"、"下周找个时间"、"改天"、"有空的时候"。
   - 如果时间模糊或没有时间：
     a) 先查询能查的信息，比如任务涉及出行/户外就查天气。
     b) 在回复里把可查到的信息告诉用户（如天气、已有日程），然后追问具体时间。
     c) 追问时不要调 emit_tasks。
   - 如果用户已经在本轮或前几轮给出了明确时间，跳到第三步。

   第三步：根据情况决定是否还要追问
   - 如果上一轮你追问了时间，而用户这一轮给出了明确时间，进入第四步。
   - 如果用户这一轮仍然只给模糊时间或没有回答时间，则把任务按无时间处理，进入第四步。

   第四步：调用 emit_tasks 把任务结构化传给系统
   - 明确时间：start 填具体时间，end 可留空（系统会自动补 1 小时）。
   - 模糊或无时间：start 和 end 都留空。
   - note 字段：把值得关注的信息以简明扼要的形式写进去。
     例如：天气提醒（"下午有雨"）、冲突信息（"与 10:00 开会冲突"）、任务性质（"户外活动"）。
     没有值得关注的信息就留空。

   第五步：用自然语言回复用户
   - 明确时间的任务：告诉用户"已将任务添加到 To be confirmed "。
   - 无明确时间的任务：告诉用户"已将任务添加到 To be planned "。
   - 如果查了天气、有冲突、或 note 里有信息，一并告诉用户，并给出建议。

2. 不要在对话里直接说"已添加"、"已写入日历"，因为你无法直接写日历。
   写日历由用户在左侧点确认按钮完成。

3. 如果用户只是问天气、时间、已有日程，正常调用对应工具回答，不要调 emit_tasks。

4. 如果用户只是闲聊，正常聊天，不调用任何工具。

5. 时间约定：
   早八指 8:15-9:50，早十指 10:10-11:45，晚上的课 19:30-21:05，
   下午第一节 14:30-16:05，下午第二节 16:25-18:00。

6. 参考【用户长期记忆】里的偏好来给建议，但不要在回复里直接复述这些记忆。
""",
    ),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=False,
    return_intermediate_steps=True,
)

_recent = []
_RECENT_MAX = 10

_MEMORY_PROMPT_TEMPLATE = """你是记忆分析助手。请分析下面这轮对话，更新用户的长期记忆。

【现有事实】
{old_facts}

【现有偏好】
{old_prefs}

【本轮对话】
用户：{user_msg}
助手：{assistant_msg}

规则：
1. facts：关于用户的客观、稳定信息，例如身份、项目、经历、技术栈、工作单位、学历等。
   - 如果新信息与旧事实冲突，用新信息更新。
   - 输出合并后的完整事实列表。
2. preferences：用户的喜好、习惯、交互偏好。同样输出合并后的完整列表。
3. 如果本轮对话里没有任何值得记的新信息，facts 和 preferences 原样返回。
4. 严格输出 JSON，不要有多余文字，不要用 markdown 代码块。

输出格式：
{{"facts": ["..."], "preferences": ["..."]}}
"""


def _clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return text


def _distill_memory(user_msg: str, assistant_msg: str) -> None:
    memory = load_memory()
    old_facts = "\n".join(f"- {f}" for f in memory.get("facts", [])) or "（无）"
    old_prefs = "\n".join(f"- {p}" for p in memory.get("preferences", [])) or "（无）"

    prompt_text = _MEMORY_PROMPT_TEMPLATE.format(
        old_facts=old_facts,
        old_prefs=old_prefs,
        user_msg=user_msg,
        assistant_msg=assistant_msg,
    )

    try:
        response = memory_llm.invoke(prompt_text)
        raw = response.content
    except Exception as e:
        print(f"[memory] LLM 调用失败：{e}")
        return

    text = _clean_json_text(raw)
    try:
        data = json.loads(text)
    except Exception as e:
        print(f"[memory] JSON 解析失败：{e}")
        print(f"[memory] 原始输出：{raw!r}")
        return

    memory["facts"] = data.get("facts", memory.get("facts", []))
    memory["preferences"] = data.get("preferences", memory.get("preferences", []))
    memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_memory(memory)

def _extract_tasks_from_steps(steps_raw: list) -> tuple[list, list]:
    """从 intermediate_steps 里分出 emit_tasks 的任务和要展示给用户的 steps。"""
    tasks = []
    display_steps = []
    for action, observation in steps_raw:
        if action.tool == "emit_tasks":
            tool_input = action.tool_input or {}
            raw_tasks = tool_input.get("tasks", []) if isinstance(tool_input, dict) else []
            for t in raw_tasks:
                if isinstance(t, BaseModel):
                    t = t.model_dump()
                if not isinstance(t, dict) or not t.get("title"):
                    continue
                t["id"] = "task-" + uuid.uuid4().hex[:8]
                t.setdefault("start", None)
                t.setdefault("end", None)
                t.setdefault("location", "")
                t.setdefault("note", "")
                tasks.append(t)
        else:
            display_steps.append({
                "tool": action.tool,
                "args": action.tool_input,
                "result": str(observation),
            })
    return tasks, display_steps


def chat(user_input: str) -> dict:
    now = datetime.now()
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]

    memory = load_memory()
    memory_text = format_memory_text(memory)

    result = executor.invoke({
        "input": user_input,
        "chat_history": _recent,
        "today": now.strftime("%Y-%m-%d"),
        "weekday": weekday_names[now.weekday()],
        "memory_text": memory_text,
    })

    reply = result["output"]

    _recent.append(HumanMessage(content=user_input))
    _recent.append(AIMessage(content=reply))
    while len(_recent) > _RECENT_MAX:
        _recent.pop(0)

    tasks, steps = _extract_tasks_from_steps(result.get("intermediate_steps", []))

    _distill_memory(user_input, reply)

    return {
        "output": result["output"],
        "steps": steps,
        "tasks": tasks,
    }


def reset_history() -> None:
    _recent.clear()