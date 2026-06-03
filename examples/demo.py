"""Multi-Agent Workbench 演示脚本"""

import asyncio
import os
import sys

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from multi_agent_workbench.agent.base import AgentContext
from multi_agent_workbench.communication.message_bus import MessageBus
from multi_agent_workbench.orchestrator import WorkBench


async def demo():
    """运行一个示例任务"""

    # 创建上下文（优先使用环境变量配置）
    bus = MessageBus()
    context = AgentContext.from_env(bus)

    has_api_key = bool(context.llm_api_key)
    if not has_api_key:
        print("=" * 50)
        print("⚠️  未设置 LLM_API_KEY")
        print("   运行: export LLM_API_KEY='sk-xxx'")
        print("   或者设置 LLM_BASE_URL 使用其他提供商")
        print("   当前将使用默认回复模式（演示效果会简化）")
        print("=" * 50)
        print()

    # 创建 WorkBench
    bench = WorkBench(context=context)

    # 示例任务
    demo_tasks = [
        "帮我写一篇介绍多智能体系统（Multi-Agent System）的科普文章，适合给高中生看",
        "分析一下 RAG 和 Fine-tuning 两种技术的区别，整理成对比文档",
        "解释什么是 MCP（Model Context Protocol），以及它为什么重要",
    ]

    print("🐱 选择演示任务：")
    for i, task in enumerate(demo_tasks, 1):
        print(f"  [{i}] {task}")
    print(f"  [{len(demo_tasks)+1}] 自定义任务")
    print()

    choice = input("请选择 (1-4): ").strip()
    if choice == str(len(demo_tasks) + 1):
        task = input("请输入你的任务: ").strip()
    elif choice.isdigit() and 1 <= int(choice) <= len(demo_tasks):
        task = demo_tasks[int(choice) - 1]
    else:
        task = demo_tasks[0]

    result, work_log = await bench.run(task)

    print(result)


def main():
    asyncio.run(demo())


if __name__ == "__main__":
    main()
