"""编程专员——负责代码编写、运行测试和技术方案设计"""

from .base import BaseAgent
from ..tools.code_sandbox import CodeSandbox


CODE_SYSTEM_PROMPT = """你是一个经验丰富的程序员。
你的任务是根据需求编写代码，编写完后会**实际运行代码**来验证。

要求：
1. 代码必须能**直接运行**——包含所有必要的 import 和 main 逻辑
2. 添加 print() 输出运行结果（这样你就能看到运行效果）
3. 代码要清晰、注释完整、考虑边界情况
4. 如果有外部依赖，在代码末尾用注释标注 `# pip: <包名>`

输出格式：
- 先给出设计方案思路
- 再给出完整代码（用 ```python 代码块包裹）
- 运行结果会自动展示给你看
"""


class CodingAgent(BaseAgent):
    """编程专员——负责代码编写和运行验证"""

    def __init__(self, context):
        super().__init__(
            name="编程专员",
            description="负责编写代码、运行测试和技术方案设计。擅长：Python、JavaScript、Web开发、API设计、自动化脚本、数据分析",
            context=context,
            capabilities=[
                "编程", "代码", "写代码", "开发", "Python", "JavaScript",
                "脚本", "程序", "算法", "函数", "API", "Web开发",
                "自动化", "爬虫", "数据库", "debug", "调试", "技术方案",
                "前后端", "架构", "实现", "部署", "数据分析",
            ],
        )

    async def execute(self, task: str, **kwargs) -> str:
        await self.broadcast(f"💻 正在设计方案并编写代码：{task[:60]}...")

        # 检查是否有知识库参考资料
        knowledge_ctx = kwargs.get("knowledge_context", "")
        task_with_context = task
        if knowledge_ctx:
            await self.broadcast(f"📚 引用知识库资料作为技术参考...")
            task_with_context = f"{task}\n\n## 参考资料（用户知识库）\n{knowledge_ctx[:3000]}"

        # Step 1: 让 LLM 生成代码
        code = await self.call_llm(
            system_prompt=CODE_SYSTEM_PROMPT,
            user_prompt=f"请完成以下编程任务，确保代码可以直接运行：\n\n{task_with_context}",
        )

        await self.broadcast(f"⚙️ 正在沙箱中运行代码验证...")

        # Step 2: 提取代码并运行
        sandbox = CodeSandbox(timeout=30)
        python_code = self._extract_code(code, "python")

        if python_code:
            # 检测 pip 依赖
            pip_packages = self._extract_pip_deps(code)

            result = sandbox.run_python(python_code, pip_packages)

            # Step 3: 如果代码有问题，让 LLM 修复
            if not result.success:
                await self.broadcast(f"🔧 运行出错，正在修复...")
                fix_prompt = f"""以下代码运行出错，请修复：

## 原始任务
{task}

## 代码
{python_code}

## 运行错误
{result.error}

## 请修复代码中的问题，确保能正确运行。
"""
                fixed_code = await self.call_llm(
                    system_prompt="你是一个 debug 专家。请修复下面的代码问题，输出修复后的完整代码。",
                    user_prompt=fix_prompt,
                )

                fixed_python = self._extract_code(fixed_code, "python")
                if fixed_python:
                    result = sandbox.run_python(fixed_python, pip_packages)
                    code = fixed_code

            run_info = result.format_markdown()
        else:
            run_info = "📝 未检测到可执行的 Python 代码块，仅输出设计方案。"

        await self.broadcast(f"✅ 代码编写完成{'并运行验证通过' if result and result.success else ''}")

        # 组装最终输出
        final_output = code + "\n\n---\n## ⚡ 运行结果\n\n" + run_info

        self._bus.record_result(self.name, final_output)
        return final_output

    def _extract_code(self, text: str, language: str = "") -> str:
        """从 LLM 输出中提取代码块"""
        import re
        pattern = rf"```{language}\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            return matches[0].strip()
        # 尝试任意语言代码块
        matches = re.findall(r"```\n(.*?)```", text, re.DOTALL)
        return matches[0].strip() if matches else ""

    def _extract_pip_deps(self, text: str) -> list[str]:
        """从注释中提取 pip 依赖"""
        deps = []
        for line in text.splitlines():
            line = line.strip()
            if "# pip:" in line:
                pkg = line.split("# pip:")[1].strip()
                if pkg:
                    deps.append(pkg)
        return deps
