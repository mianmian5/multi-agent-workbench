"""Multi-Agent Workbench Web 界面 v2 - 含讨论 + 历史保存"""

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from rate_limit import check_rate_limit, get_remaining

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from multi_agent_workbench.orchestrator import WorkBench
from multi_agent_workbench.agent.base import AgentContext
from multi_agent_workbench.communication.message_bus import WorkLog, Message
from multi_agent_workbench.tools.knowledge_base import (
    upload_file, list_files, delete_file, search_knowledge, get_stats
)
from multi_agent_workbench.tools.memory_system import (
    add_memory, list_memories, get_memory, delete_memory,
    search_memories, get_memory_context, get_memory_stats,
    summarize_conversation,
)
from multi_agent_workbench.tools.docx_gen import markdown_to_docx, markdown_to_pdf
from multi_agent_workbench.tools.custom_agent_registry import (
    list_agents as list_custom_agents,
    get_agent as get_custom_agent,
    create_agent as create_custom_agent,
    update_agent as update_custom_agent,
    delete_agent as delete_custom_agent,
    get_all_agents_info,
)

app = FastAPI(title="Multi-Agent Workbench")

web_dir = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

# 存储运行中的任务
running_tasks: dict[str, dict] = {}
task_events: dict[str, asyncio.Queue] = {}
cancel_flags: dict[str, asyncio.Event] = {}

# 历史记录存储
HISTORY_DIR = Path.home() / ".awb_history"
HISTORY_DIR.mkdir(exist_ok=True)

# 配置文件
CONFIG_FILE = web_dir.parent / ".env"


def _load_history() -> list[dict]:
    """加载历史记录（按时间倒序）"""
    histories = []
    if HISTORY_DIR.exists():
        for f in HISTORY_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                task = data.get("task", "")
                title = data.get("title", "")
                display = title if title else task
                histories.append({
                    "id": f.stem,
                    "task": task,
                    "title": display[:80],
                    "time": data.get("time", ""),
                    "duration": data.get("duration", 0),
                })
            except Exception:
                pass
    # 按时间倒序排列
    histories.sort(key=lambda h: h.get("time", ""), reverse=True)
    return histories[:50]


def _save_history(task_id: str, task_text: str, result: str, duration: float,
                  steps: list | None = None, step_results: dict | None = None,
                  discussions: list | None = None):
    """保存历史记录（含完整的协作过程）"""
    title = task_text.replace("\n", " ").strip()
    if len(title) > 60:
        title = title[:57] + "..."

    record = {
        "task": task_text,
        "title": title,
        "result": result,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration": round(duration, 1),
    }

    # 保存完整的协作过程
    if steps:
        record["steps"] = steps
    if step_results:
        record["results"] = step_results
    if discussions:
        record["discussions"] = discussions

    (HISTORY_DIR / f"{task_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str)
    )


def create_workbench() -> WorkBench:
    context = AgentContext.from_env()
    return WorkBench(context=context)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    html_path = web_dir / "templates" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/settings")
async def get_settings():
    """获取当前配置（不返回完整 Key）"""
    config = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k == "LLM_API_KEY" and v:
                    config["llm_key_prefix"] = v[:8] + "..." + v[-4:]
                elif k in ("LLM_BASE_URL", "LLM_MODEL"):
                    config[k.lower()] = v
    return JSONResponse(config)


# ===== 任务模板 =====
TASK_TEMPLATES = [
    {
        "id": "tech_blog",
        "title": "✍️ 写技术博客",
        "desc": "搜索资料、撰写、审校一篇技术文章",
        "task": "帮我写一篇关于「」的科普文章，面向技术初学者，通俗易懂，包含实际例子"
    },
    {
        "id": "analysis",
        "title": "📊 竞品分析",
        "desc": "搜索竞品信息，分析功能/用户/商业模式",
        "task": "对「」进行全面的竞品分析，包括：产品功能、目标用户、商业模式、市场表现、优劣势"
    },
    {
        "id": "translate",
        "title": "🌐 翻译文档",
        "desc": "翻译并本地化校对",
        "task": "将以下内容翻译成中文（保持技术准确性）：\n\n"
    },
    {
        "id": "code",
        "title": "💻 写代码",
        "desc": "写代码并自动运行验证",
        "task": "用 Python 写一个「」程序，并添加测试用例来验证正确性"
    },
    {
        "id": "story",
        "title": "🎭 构思小说",
        "desc": "世界观、角色、三幕式情节大纲",
        "task": "帮我构思一个「」的故事，包括：世界观设定、主要角色、三幕式情节大纲"
    },
    {
        "id": "free",
        "title": "🆓 自由模式",
        "desc": "不限模板，AI 团队自由发挥",
        "task": ""
    },
    {
        "id": "summary",
        "title": "📝 论文/文章总结",
        "desc": "上传或粘贴长文，AI 提炼核心要点",
        "task": "请总结以下内容的核心观点、关键论据和结论：\n\n"
    },
    {
        "id": "plan",
        "title": "📋 制定学习计划",
        "desc": "根据目标制定分阶段学习路线图",
        "task": "帮我制定一个「」学习计划，包括：学习阶段划分、每周目标、推荐资源、实践项目"
    },
    {
        "id": "marketing",
        "title": "📢 写营销文案",
        "desc": "产品/活动推广文案，多平台适配",
        "task": "为「」写一份营销推广方案，包括：目标用户分析、核心卖点、文案（小红书/公众号/微博各一份）"
    },
    {
        "id": "meeting",
        "title": "📅 会议纪要整理",
        "desc": "将会议录音/笔记整理为结构化纪要",
        "task": "请将以下会议记录整理为结构化纪要，包含：会议主题、讨论要点、决策事项、待办任务（含负责人）：\n\n"
    },
    {
        "id": "interview",
        "title": "💼 面试模拟",
        "desc": "模拟面试问答，提供反馈和改进建议",
        "task": "我准备面试「」岗位，请模拟面试官进行问答，并在结束后给出表现评估和改进建议"
    },
    {
        "id": "debug",
        "title": "🐛 代码 Debug",
        "desc": "分析错误信息，定位问题并修复",
        "task": "以下代码运行出错，请分析原因并给出修复方案：\n\n"
    },
]


@app.get("/api/templates")
async def get_templates():
    """获取任务模板列表"""
    return JSONResponse(TASK_TEMPLATES)


# ===== 知识库 API =====


@app.get("/api/knowledge/stats")
async def knowledge_stats():
    """知识库统计"""
    return JSONResponse(get_stats())


@app.get("/api/knowledge")
async def knowledge_list():
    """列出知识库文件"""
    return JSONResponse(list_files())


@app.post("/api/knowledge/upload")
async def knowledge_upload(request: Request):
    """上传文件到知识库"""
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "请选择文件"}, status_code=400)

    # 保存上传的文件到临时位置（保留原始后缀）
    content = await file.read()
    orig_name = file.filename or "upload.txt"
    ext = Path(orig_name).suffix or ".txt"
    tmp = Path(f"/tmp/awb_upload_{uuid.uuid4().hex[:8]}{ext}")
    tmp.write_bytes(content)

    result = upload_file(str(tmp), orig_name)
    tmp.unlink(missing_ok=True)

    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@app.delete("/api/knowledge/{file_id}")
async def knowledge_delete(file_id: str):
    """删除知识库文件"""
    if delete_file(file_id):
        return JSONResponse({"status": "ok"})
    return JSONResponse({"error": "文件不存在"}, status_code=404)


@app.get("/api/knowledge/search")
async def knowledge_search(query: str = "", max_results: int = 5):
    """搜索知识库"""
    if not query:
        return JSONResponse([])
    result = search_knowledge(query, max_results)
    if result:
        return JSONResponse({"result": result})
    return JSONResponse({"result": ""})


# ===== 自定义 Agent API =====


@app.get("/api/agents/custom")
async def custom_agents_list():
    """列出所有自定义 Agent"""
    return JSONResponse(list_custom_agents())


@app.post("/api/agents/custom")
async def custom_agents_create(request: Request):
    """创建自定义 Agent"""
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "请输入 Agent 名称"}, status_code=400)
    if not data.get("system_prompt", "").strip():
        return JSONResponse({"error": "请输入系统提示词"}, status_code=400)

    agent = create_custom_agent(
        name=name,
        description=data.get("description", "").strip(),
        system_prompt=data["system_prompt"].strip(),
        capabilities=[c.strip() for c in data.get("capabilities", "").split(",") if c.strip()],
    )
    return JSONResponse(agent)


@app.put("/api/agents/custom/{agent_id}")
async def custom_agents_update(agent_id: str, request: Request):
    """更新自定义 Agent"""
    data = await request.json()
    updated = update_custom_agent(
        agent_id=agent_id,
        name=data.get("name"),
        description=data.get("description"),
        system_prompt=data.get("system_prompt"),
        capabilities=[c.strip() for c in data.get("capabilities", "").split(",") if c.strip()]
        if data.get("capabilities") else None,
    )
    if not updated:
        return JSONResponse({"error": "Agent 不存在"}, status_code=404)
    return JSONResponse(updated)


@app.delete("/api/agents/custom/{agent_id}")
async def custom_agents_delete(agent_id: str):
    """删除自定义 Agent"""
    if delete_custom_agent(agent_id):
        return JSONResponse({"status": "ok"})
    return JSONResponse({"error": "Agent 不存在"}, status_code=404)


@app.get("/api/agents/all")
async def all_agents_info():
    """获取所有 Agent 信息（内置+自定义）"""
    return JSONResponse(get_all_agents_info())


# ===== 记忆系统 API =====


@app.get("/api/memory")
async def memory_list(mem_type: str = "", tag: str = "", limit: int = 50):
    """列出记忆"""
    return JSONResponse(list_memories(mem_type, tag, limit))


@app.post("/api/memory")
async def memory_create(request: Request):
    """添加记忆"""
    data = await request.json()
    content = data.get("content", "").strip()
    if not content:
        return JSONResponse({"error": "请输入记忆内容"}, status_code=400)
    entry = add_memory(
        content=content,
        mem_type=data.get("type", "note"),
        tags=data.get("tags", []),
        source=data.get("source", ""),
    )
    return JSONResponse(entry)


@app.get("/api/memory/search")
async def memory_search(query: str = ""):
    """搜索记忆"""
    if not query:
        return JSONResponse([])
    return JSONResponse(search_memories(query))


@app.get("/api/memory/stats")
async def memory_stats():
    """记忆统计（必须放在 {mem_id} 前面）"""
    return JSONResponse(get_memory_stats())


@app.get("/api/memory/{mem_id}")
async def memory_get(mem_id: str):
    """获取单条记忆"""
    entry = get_memory(mem_id)
    if not entry:
        return JSONResponse({"error": "记忆不存在"}, status_code=404)
    return JSONResponse(entry)


@app.delete("/api/memory/{mem_id}")
async def memory_delete(mem_id: str):
    """删除记忆"""
    if delete_memory(mem_id):
        return JSONResponse({"status": "ok"})
    return JSONResponse({"error": "记忆不存在"}, status_code=404)


@app.post("/api/settings")
async def save_settings(request: Request):
    """保存配置到 .env 文件并热生效"""
    data = await request.json()
    lines = []
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k = line.split("=", 1)[0].strip()
                if k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
                    continue
            lines.append(line)

    # 写入新配置 + 同步到进程环境变量（热生效，无需重启）
    if data.get("api_key") and data["api_key"].strip():
        key = data["api_key"].strip()
        lines.append(f'LLM_API_KEY={key}')
        os.environ["LLM_API_KEY"] = key
    elif "LLM_API_KEY" not in os.environ or not os.environ.get("LLM_API_KEY"):
        # 免费试用默认 Key
        default_key = "sk-f0efe677283146978f0bca38505b83cf"
        os.environ["LLM_API_KEY"] = default_key
        lines.append(f'LLM_API_KEY={default_key}')
    if data.get("base_url"):
        url = data["base_url"].strip()
        lines.append(f'LLM_BASE_URL={url}')
        os.environ["LLM_BASE_URL"] = url
    if data.get("model"):
        model = data["model"].strip()
        lines.append(f'LLM_MODEL={model}')
        os.environ["LLM_MODEL"] = model

    CONFIG_FILE.write_text("\n".join(lines) + "\n")

    return JSONResponse({"status": "ok", "message": "✅ 配置已保存并立即生效", "hint": data.get("model", "")})


    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=\"{safe_name}.docx\""},
    )


@app.get("/api/history")
async def get_history():
    """获取历史记录列表"""
    return JSONResponse(_load_history())


@app.get("/api/history/{task_id}")
async def get_history_detail(task_id: str):
    """获取单条历史详情"""
    filepath = HISTORY_DIR / f"{task_id}.json"
    if filepath.exists():
        return JSONResponse(json.loads(filepath.read_text()))
    return JSONResponse({"error": "not found"}, status_code=404)


@app.post("/api/run")
async def run_task(request: Request):
    check_rate_limit(request)
    # 免费试用：未配置 Key 时使用默认 Key
    import os
    if "LLM_API_KEY" not in os.environ or not os.environ.get("LLM_API_KEY"):
        os.environ["LLM_API_KEY"] = "sk-f0efe677283146978f0bca38505b83cf"
        os.environ["LLM_BASE_URL"] = "https://api.deepseek.com/v1"
        os.environ["LLM_MODEL"] = "deepseek-chat"
        print("⚡ 免费试用 MAWB，使用默认 DeepSeek Key")
    """启动一个新的多智能体协作任务"""
    data = await request.json()
    task_text = data.get("task", "").strip()
    discuss_enabled = data.get("discuss", True)
    files = data.get("files", [])  # [{name, content}, ...]
    if not task_text:
        return JSONResponse({"error": "请输入任务描述"}, status_code=400)

    # 如果有上传的文件，把文件内容附加到任务描述
    file_context = ""
    if files:
        file_parts = ["\n\n## 📎 上传的参考资料"]
        for f in files:
            name = f.get("name", "未命名文件")
            content = f.get("content", "")
            if content:
                file_parts.append(f"\n### 📄 {name}\n{content[:3000]}\n")
        file_context = "\n".join(file_parts)

    task_id = str(uuid.uuid4())[:8]
    task_events[task_id] = asyncio.Queue()
    cancel_flags[task_id] = asyncio.Event()

    running_tasks[task_id] = {
        "task": task_text,
        "status": "running",
        "started_at": time.time(),
        "discuss": discuss_enabled,
    }

    asyncio.create_task(_execute_task(task_id, task_text + file_context, discuss_enabled))

    return JSONResponse({"task_id": task_id})


@app.post("/api/cancel/{task_id}")
async def cancel_task(task_id: str):
    """取消正在执行的任务"""
    flag = cancel_flags.get(task_id)
    if flag:
        flag.set()
        running_tasks[task_id]["status"] = "cancelled"
        await _send_event(task_id, {"type": "cancelled", "message": "任务已取消"})
        return JSONResponse({"status": "cancelled"})
    return JSONResponse({"error": "任务不存在"}, status_code=404)


@app.get("/api/stream/{task_id}")
async def stream_task(task_id: str):
    """SSE 实时推送"""

    async def event_generator():
        queue = task_events.get(task_id)
        if not queue:
            yield f"data: {json.dumps({'type': 'error', 'message': '任务不存在'})}\n\n"
            return

        task = running_tasks.get(task_id, {})
        yield f"data: {json.dumps({'type': 'start', 'task': task.get('task', '')})}\n\n"

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("completed", "error"):
                    break
            except asyncio.TimeoutError:
                yield f": heartbeat\n\n"

        task_events.pop(task_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _execute_task(task_id: str, task_text: str, discuss_enabled: bool = True):
    """在后台执行任务（真实搜索 + 真实多Agent讨论）"""
    try:
        bench = create_workbench()
        # 将 Agent 的广播消息转发到前端 SSE
        task_id_capture = task_id
        def on_broadcast(msg):
            import json as _j
            content_preview = msg.content[:300] if msg.content else ""
            asyncio.ensure_future(_send_event(task_id_capture, {
                "type": "broadcast",
                "agent": msg.sender,
                "content": content_preview,
            }))
        bench.message_bus.on_broadcast = on_broadcast

        # 规划
        await _send_event(task_id, {"type": "planning", "message": "📐 正在拆解任务..."})
        steps = await bench.planner.plan(task_text)

        await _send_event(task_id, {
            "type": "plan",
            "steps": [
                {"step": s["step"], "agent": s["agent"], "task": s["task"]}
                for s in steps
            ],
        })

        await _send_event(task_id, {"type": "executing", "message": "🚀 开始执行..."})

        # 并行执行步骤（按依赖关系分组）
        step_results = {}
        remaining = {s["step"]: s for s in steps}

        while remaining:
            # 找出可并行执行的当前波次
            wave = []
            for step_num, step in list(remaining.items()):
                deps = set(step.get("depends_on", []))
                if deps.issubset(set(step_results.keys())):
                    wave.append(step)
                    del remaining[step_num]

            if not wave:
                # 死循环保护
                wave = [list(remaining.values())[0]]
                del remaining[list(remaining.keys())[0]]

            # 发送 wave 中所有步骤的 start 事件
            for step in wave:
                await _send_event(task_id, {
                    "type": "step_start", "step": step["step"],
                    "agent": step["agent"], "task": step["task"],
                    "sub_queries": step.get("sub_queries", []),
                })

            async def _run_one_step(step: dict) -> tuple[int, str]:
                step_num = step["step"]
                agent_name = step["agent"]
                task_desc = step["task"]
                depends_on = step.get("depends_on", [])

                agent = bench.router.get_agent(agent_name)
                if not agent:
                    await _send_event(task_id, {
                        "type": "step_error", "step": step_num,
                        "agent": agent_name, "error": "找不到 Agent",
                    })
                    return (step_num, "[错误]")

                extra_kwargs = {}
                if depends_on:
                    deps = []
                    for dep in depends_on:
                        if dep in step_results:
                            deps.append(step_results[dep])
                    if deps:
                        extra_kwargs.update(
                            search_result="\n\n".join(deps),
                            draft=deps[-1],
                            original_task=task_desc,
                            info="\n\n".join(deps),
                        )

                # 注入知识库上下文
                if agent_name in ("搜索专员", "写作专员", "编程专员"):
                    kb_results = search_knowledge(task_desc, max_results=3)
                    if kb_results:
                        extra_kwargs["knowledge_context"] = kb_results

                try:
                    result = await agent.execute(task_desc, **extra_kwargs)
                    await _send_event(task_id, {
                        "type": "step_done", "step": step_num,
                        "agent": agent_name, "result_preview": result[:2000],
                    })
                    return (step_num, result)
                except Exception as e:
                    await _send_event(task_id, {
                        "type": "step_error", "step": step_num,
                        "agent": agent_name, "error": str(e),
                    })
                    return (step_num, f"[错误] {e}")

            # 执行当前波次（并行）
            if len(wave) == 1:
                num, result = await _run_one_step(wave[0])
                step_results[num] = result
            else:
                # 多个不依赖的步骤并行运行
                batch_results = await asyncio.gather(*[
                    _run_one_step(s) for s in wave
                ])
                for num, result in batch_results:
                    step_results[num] = result

        # 多轮讨论阶段（2 轮，像真人会议一样来回对话）
        main_result = step_results.get(max(step_results.keys(), default=0), "")
        all_rounds = []
        if discuss_enabled and main_result:
            discuss_agent = bench.router.get_agent("讨论专员")
            current_draft = main_result

            for round_num in range(1, 3):  # 2 轮讨论
                round_label = "第一轮审阅" if round_num == 1 else "第二轮深入讨论"

                await _send_event(task_id, {
                    "type": "discuss_start",
                    "message": f"💬 {round_label}...",
                    "round": round_num,
                })

                # 第二轮：主持人先给出讨论要点
                round_context = ""
                if round_num == 2 and all_rounds:
                    try:
                        round_context = await discuss_agent.moderate(
                            task_text, current_draft, all_rounds[-1],
                            round_type="deep_dive",
                        )
                        await _send_event(task_id, {
                            "type": "discuss_context",
                            "context": round_context[:300],
                        })
                    except Exception:
                        pass

                # 每个 Agent 独立审阅
                feedbacks = []
                for agent in bench.agents:
                    if agent.name == "讨论专员":
                        continue
                    # 根据任务类型过滤无关 Agent
                    is_story_task = any(kw in task_text for kw in ["小说", "写作", "故事"])
                    is_code_task = any(kw in task_text for kw in ["代码", "编程"])
                    if is_story_task and agent.name in ("编程专员", "翻译专员"):
                        continue
                    if is_code_task and agent.name == "翻译专员":
                        continue

                    await _send_event(task_id, {
                        "type": "discuss_feedback",
                        "agent": agent.name,
                        "status": "thinking",
                        "round": round_num,
                    })

                    try:
                        kwargs = dict(
                            draft=current_draft,
                            reviewer_name=agent.name,
                            original_task=task_text,
                        )
                        if round_context:
                            kwargs["round_context"] = round_context
                            kwargs["response_to"] = f"第{round_num - 1}轮的讨论要点"

                        feedback = await discuss_agent.execute(task_text, **kwargs)
                        feedbacks.append((agent.name, feedback))
                        await _send_event(task_id, {
                            "type": "discuss_feedback",
                            "agent": agent.name,
                            "status": "done",
                            "feedback": feedback[:2000],
                            "round": round_num,
                        })
                    except Exception as e:
                        await _send_event(task_id, {
                            "type": "discuss_feedback",
                            "agent": agent.name,
                            "status": "error",
                            "feedback": f"审阅失败: {e}",
                        })

                all_rounds.append(feedbacks)

            # 讨论专员做最终总结
            if all_rounds:
                try:
                    summary = await discuss_agent.moderate(
                        task_text, current_draft, all_rounds[-1],
                        round_type="final_summary",
                        history=all_rounds,
                    )
                    await _send_event(task_id, {
                        "type": "discuss_summary",
                        "summary": summary[:500],
                    })
                except Exception as e:
                    pass

        # 组装结果
        final_result = bench._assemble_result(steps, step_results)
        duration = time.time() - running_tasks[task_id]["started_at"]
        running_tasks[task_id]["status"] = "completed"
        running_tasks[task_id]["finished_at"] = time.time()

        # 保存历史（含完整的协作过程）
        discussions = []
        if all_rounds:
            for round_fb in all_rounds:
                discussions.append({
                    "round": len(discussions) + 1,
                    "feedbacks": [{"agent": name, "text": fb[:500]} for name, fb in round_fb],
                })

        _save_history(
            task_id, task_text, final_result, duration,
            steps=steps,
            step_results={str(k): v[:500] for k, v in step_results.items()},
            discussions=discussions if discussions else None,
        )

        # 自动总结对话存入记忆
        try:
            agent_names = [a.name for a in bench.agents]
            summarize_conversation(task_text, final_result, agent_names)
        except Exception:
            pass

        await _send_event(task_id, {
            "type": "completed",
            "result": final_result,
            "duration": round(duration, 1),
        })

    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {e}"
        trace = traceback.format_exc()
        print(f"[ERROR] 任务执行失败: {error_msg}", flush=True)
        print(trace, flush=True)
        running_tasks[task_id]["status"] = "error"
        await _send_event(task_id, {"type": "error", "message": error_msg})


async def _send_event(task_id: str, event: dict):
    queue = task_events.get(task_id)
    if queue:
        await queue.put(event)


def main():
    import uvicorn
    print("🐱 Multi-Agent Workbench")
    print("=" * 40)
    print(f"   地址: http://127.0.0.1:8000")
    print()
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

@app.get("/rate-limit", summary="查看剩余免费次数")
def rate_limit_status(request: Request):
    return get_remaining(request)
