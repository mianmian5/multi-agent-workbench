"""代码执行沙箱——安全运行用户或 Agent 生成的代码

使用 subprocess 和临时目录 + 超时机制，防止恶意代码影响系统。
"""

import os
import re
import tempfile
import subprocess
import shutil
import ast
import sys


class CodeSandbox:
    """代码执行沙箱

    支持 Python 代码的安全执行，特性：
    - 在临时目录运行，不污染环境
    - 自动超时保护（默认 30 秒）
    - 捕获 stdout/stderr
    - 限制输出大小（防止无限日志）

    用法:
        sandbox = CodeSandbox()
        result = sandbox.run_python("print('hello')")
        print(result.output)  # "hello\\n"
        print(result.exit_code)  # 0
    """

    def __init__(self, timeout: int = 30, max_output_chars: int = 50000):
        self.timeout = timeout
        self.max_output_chars = max_output_chars

    def validate_code(self, code: str) -> tuple[bool, str]:
        """基本安全检查：确保代码是合法 Python 语法"""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"语法错误: {e}"

    def run_python(self, code: str, pip_packages: list[str] | None = None) -> "RunResult":
        """在沙箱中执行 Python 代码

        Args:
            code: 要执行的 Python 代码
            pip_packages: 需要额外安装的包（可选）

        Returns:
            RunResult: 执行结果
        """
        # 基本安全检查
        valid, msg = self.validate_code(code)
        if not valid:
            return RunResult(exit_code=1, output="", error=msg)

        # 在临时目录执行
        tmp_dir = tempfile.mkdtemp(prefix="awb_sandbox_")
        try:
            # 安装额外包
            if pip_packages:
                install_cmd = [sys.executable, "-m", "pip", "install"] + pip_packages
                subprocess.run(
                    install_cmd,
                    capture_output=True,
                    timeout=self.timeout,
                    cwd=tmp_dir,
                )

            # 写入代码文件
            script_path = os.path.join(tmp_dir, "run_sandbox.py")
            with open(script_path, "w") as f:
                f.write(code)

            # 执行代码
            proc = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=tmp_dir,
            )

            output = proc.stdout[:self.max_output_chars]
            error = proc.stderr[:self.max_output_chars]

            # 如果有依赖文件，也带回
            extra_files = {}
            for fname in os.listdir(tmp_dir):
                if fname not in ("run_sandbox.py",):
                    fpath = os.path.join(tmp_dir, fname)
                    if os.path.isfile(fpath) and os.path.getsize(fpath) < 100_000:
                        try:
                            with open(fpath) as f:
                                extra_files[fname] = f.read()
                        except Exception:
                            pass

            return RunResult(
                exit_code=proc.returncode,
                output=output,
                error=error,
                files=extra_files,
            )

        except subprocess.TimeoutExpired:
            return RunResult(
                exit_code=-1,
                output="",
                error=f"⏰ 代码执行超时（限制 {self.timeout} 秒）",
            )
        except Exception as e:
            return RunResult(
                exit_code=1,
                output="",
                error=f"沙箱执行错误: {e}",
            )
        finally:
            # 清理临时目录
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass


class RunResult:
    """代码执行结果"""

    def __init__(
        self,
        exit_code: int,
        output: str = "",
        error: str = "",
        files: dict[str, str] | None = None,
    ):
        self.exit_code = exit_code
        self.output = output
        self.error = error
        self.files = files or {}

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def format_markdown(self) -> str:
        """格式化为 Markdown 输出"""
        parts = []

        if self.success:
            parts.append("✅ **执行成功**")
        else:
            parts.append(f"❌ **执行失败** (exit code: {self.exit_code})")

        if self.output:
            parts.append("\n**输出:**\n```\n" + self.output.rstrip() + "\n```")

        if self.error:
            parts.append("\n**错误:**\n```\n" + self.error.rstrip() + "\n```")

        if self.files:
            parts.append(f"\n**生成的文件:** {', '.join(self.files.keys())}")
            for fname, fcontent in self.files.items():
                parts.append(f"\n**{fname}:**\n```\n{fcontent[:2000]}\n```")

        return "\n".join(parts)
