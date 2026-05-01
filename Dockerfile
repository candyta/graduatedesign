FROM node:22-slim

# 安装 Python 3 和必要的系统库
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip3 install --no-cache-dir -r backend/requirements.txt

# 安装 Node.js 依赖
COPY backend/package.json backend/package-lock.json* ./backend/
RUN cd backend && npm install --omit=dev

# 复制后端代码
COPY backend/ ./backend/

# 复制前端构建产物
COPY frontend/dist/ ./frontend/dist/

# 复制 ICRP 数据
COPY "P110 data V1.2"/ "./P110 data V1.2"/

EXPOSE 3000

ENV PYTHON_PATH=python3
ENV NODE_ENV=production

CMD ["node", "backend/index.js"]
