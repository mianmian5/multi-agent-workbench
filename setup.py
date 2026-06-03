from setuptools import setup, find_packages

setup(
    name="multi-agent-workbench",
    version="0.5.0",
    description="🤖 多智能体协作工作台 - 让多个 AI Agent 像团队一样协作（含真实搜索、代码沙箱、团队讨论）",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="mianmian5",
    url="https://github.com/mianmian5/multi-agent-workbench",
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=[
        "httpx>=0.27.0",
        "rich>=13.0.0",
        "openai>=1.0.0",
        "beautifulsoup4>=4.12.0",
    ],
    extras_require={
        "web": ["fastapi>=0.100.0", "uvicorn>=0.22.0"],
    },
    entry_points={
        "console_scripts": [
            "agent-workbench=multi_agent_workbench.cli:main",
            "awb-web=multi_agent_workbench.web.app:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
