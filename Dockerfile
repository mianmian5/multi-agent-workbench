# ============================
# Multi-Agent Workbench Docker
# ============================
# 使用方式:
#   docker compose up -d
#   打开浏览器访问 http://localhost:8000

FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖（用于 pip 编译和健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建数据目录（知识库、自定义 Agent 等持久化数据）
RUN mkdir -p /root/.awb_knowledge /root/.awb_agents /tmp/awb_workspace

EXPOSE 8000

# 启动
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
