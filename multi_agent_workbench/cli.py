"""Multi-Agent Workbench - 命令行入口"""

import asyncio
import os
import sys


def main():
    """CLI 主入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="🤖 多智能体协作工作台 - 让多个 AI Agent 像团队一样工作",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s "帮我写一篇介绍 MCP 协议的文章"
  %(prog)s --model deepseek-chat
  %(prog)s --no-llm "分析一下 RAG 和 Fine-tuning 的区别"
        """,
    )
    parser.add_argument("task", nargs="?", help="要执行的任务描述")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "gpt-4o"),
                        help="LLM 模型 (默认: gpt-4o)")
    parser.add_argument("--api-key", default=os.getenv("LLM_API_KEY", ""),
                        help="LLM API Key")
    parser.add_argument("--base-url", default=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
                        help="LLM API 地址")
    parser.add_argument("--no-llm", action="store_true",
                        help="离线模式（不使用 LLM，仅展示流程）")

    args = parser.parse_args()

    # 交互模式
    if not args.task:
        task = input("🐱 请输入你想让 AI 团队帮你完成的任务：\n> ").strip()
        if not task:
            print("再见～")
            return
    else:
        task = args.task

    # 确定 API Key
    api_key = "" if args.no_llm else args.api_key

    if not api_key:
        print()
        print("⚠️  提示: 当前未设置 LLM_API_KEY，将使用模拟回复。")
        print("   设置后可以使用真实模型：")
        print("   export LLM_API_KEY='sk-xxx'")
        print("   export LLM_MODEL='gpt-4o'         # 或 deepseek-chat")
        print()

    # 延迟导入（避免影响 --help 速度）
    from multi_agent_workbench.agent.base import AgentContext
    from multi_agent_workbench.orchestrator import WorkBench

    context = AgentContext(
        llm_api_key=api_key,
        llm_base_url=args.base_url,
        llm_model=args.model,
    )

    bench = WorkBench(context=context)
    asyncio.run(bench.run(task))


if __name__ == "__main__":
    main()
