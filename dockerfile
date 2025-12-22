FROM hysdhlx/livemcpbench:latest

ARG HTTP_PROXY
ARG HTTPS_PROXY

ENV http_proxy=${HTTP_PROXY}
ENV https_proxy=${HTTPS_PROXY}

# 1. 修复 /tmp（apt / pip / pnpm 都依赖）
RUN mkdir -p /tmp && chmod 1777 /tmp

# 装 curl + ca + git，拉 node 18 的脚本需要
RUN apt-get update && apt-get install -y \
    curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js 18（来自 NodeSource）
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get update && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 用 corepack 管 pnpm（比 npm -g 更靠谱）
RUN corepack enable && corepack prepare pnpm@9 --activate

# 验证版本（可留可删）
RUN node -v && pnpm -v

RUN pip install --no-cache-dir \
    git+https://github.com/Chainlit/chainlit.git#subdirectory=backend/