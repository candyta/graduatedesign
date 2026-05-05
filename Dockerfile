# ===================== Stage 1: Build frontend =====================
FROM node:22-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ===================== Stage 2: Runtime =====================
FROM node:22-slim

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r backend/requirements.txt

# Install Node.js dependencies
COPY backend/package.json ./backend/
RUN cd backend && npm install --omit=dev

# Copy backend code
COPY backend/ ./backend/

# Copy frontend build output from Stage 1
COPY --from=frontend-builder /frontend/dist/ ./frontend/dist/

# Copy ICRP data
COPY ["P110 data V1.2/", "./P110 data V1.2/"]

EXPOSE 3000

ENV PYTHON_PATH=python3
ENV NODE_ENV=production

CMD ["node", "backend/index.js"]
