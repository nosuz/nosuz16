# syntax=docker/dockerfile:1.4

# Stage 1: LLVM builder
# Build the patched LLVM/Clang toolchain. No local LLVM checkout is needed.
FROM ubuntu:latest AS builder
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG LLVM_BUILD_JOBS=2
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    build-essential ca-certificates cmake git lld ninja-build \
    python3 zlib1g-dev libzstd-dev \
    && rm -rf /var/lib/apt/lists/*

# Cache the pinned upstream checkout separately from backend changes.
COPY llvm-nosuz16/LLVM_BASE_REVISION /src/llvm-nosuz16/LLVM_BASE_REVISION
RUN git init -q /src/llvm-project \
    && git -C /src/llvm-project remote add origin https://github.com/llvm/llvm-project.git \
    && git -C /src/llvm-project fetch --depth 1 origin "$(cat /src/llvm-nosuz16/LLVM_BASE_REVISION)" \
    && git -C /src/llvm-project checkout --detach FETCH_HEAD

COPY llvm-nosuz16/patches/0001-nosuz16-backend.patch /src/llvm-nosuz16/patches/0001-nosuz16-backend.patch
COPY llvm-nosuz16/scripts/apply.sh /src/llvm-nosuz16/scripts/apply.sh
# This step takes over an hour.
RUN /src/llvm-nosuz16/scripts/apply.sh \
    && cmake -S /src/llvm-project/llvm -B /src/build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/out/toolchain \
    -DLLVM_ENABLE_ASSERTIONS=ON -DLLVM_USE_LINKER=lld \
    -DLLVM_PARALLEL_LINK_JOBS=1 \
    -DLLVM_TARGETS_TO_BUILD= -DLLVM_EXPERIMENTAL_TARGETS_TO_BUILD=Nosuz16 \
    -DLLVM_ENABLE_PROJECTS=clang -DLLVM_INCLUDE_TESTS=OFF \
    -DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF \
    -DLLVM_BUILD_LLVM_DYLIB=ON -DLLVM_LINK_LLVM_DYLIB=ON \
    -DCLANG_LINK_CLANG_DYLIB=OFF \
    -DLLVM_ENABLE_LIBXML2=OFF -DLLVM_ENABLE_LIBEDIT=OFF \
    -DLLVM_ENABLE_CURL=OFF -DLLVM_ENABLE_HTTPLIB=OFF \
    -DCLANG_ENABLE_STATIC_ANALYZER=OFF -DCLANG_ENABLE_ARCMT=OFF \
    && cmake --build /src/build --parallel "${LLVM_BUILD_JOBS}" \
    --target clang llc llvm-mc opt llvm-objdump llvm-readobj clang-resource-headers \
    && for component in LLVM clang llc llvm-mc opt llvm-objdump llvm-readobj clang-resource-headers; do \
    cmake --install /src/build --strip --component "${component}" || exit 1; \
    done \
    && rm -f /out/toolchain/bin/clang++ /out/toolchain/bin/clang-cl \
    /out/toolchain/bin/clang-cpp /out/toolchain/bin/clang-dxc \
    && cp /src/llvm-project/llvm/LICENSE.TXT /out/toolchain/LICENSE.TXT

COPY llvm-nosuz16/ /src/llvm-nosuz16/

# Stage 2: Emulator builder
FROM rust:1.85.1 AS emulator-builder

WORKDIR /src/emulator

# Copy Cargo project
COPY nosuz16/Cargo.toml nosuz16/Cargo.lock ./
COPY nosuz16/src/ ./src/

# Build emulator
RUN cargo build --release

# Stage 3: Development environment
# Software development needs installed tools, headers, and runtime sources.
# Shared libLLVM avoids duplicating LLVM in each command-line executable.
FROM ubuntu:latest AS dev
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# suppress clear apt cache
RUN rm /etc/apt/apt.conf.d/docker-clean

ENV LANG=ja_JP.UTF-8
ENV LC_ALL=ja_JP.UTF-8
ENV LC_CTYPE=ja_JP.UTF-8
ENV TZ=Asia/Tokyo

# install packages
ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,sharing=locked,target=/var/lib/apt \
    apt-get update \
    && apt-get install --no-install-recommends -y \
    # ssh is required to handle GitHub in the container
    git ssh \
    python3 ca-certificates \
    build-essential \
    # System tools
    locales tzdata \
    # Configure locale
    && locale-gen ja_JP.UTF-8 \
    && update-locale LANG=ja_JP.UTF-8 \
    # Configure timezone
    && ln -fs /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata

# install npm
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y \
    # curl is required to install npm
    curl \
    # Node.js
    nodejs npm \
    # # pdftotext
    # python3-dev poppler-utils libpoppler-cpp-dev \
    # # OCR
    # tesseract-ocr tesseract-ocr-eng poppler-utils ocrmypdf ghostscript \
    # Claude Code
    # build-essential \
    # gnupg2 \
    # less \
    # fzf \
    # zsh \
    # man-db \
    # unzip \
    # gh \
    # jq \
    # install n
    && npm install n -g \
    && n stable \
    && apt purge -y nodejs npm \
    && apt autoremove -y

# install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ARG UV_CACHE_DIR=/opt/.cache/uv
RUN mkdir -p $UV_CACHE_DIR
# Disable development dependencies
# ENV UV_NO_DEV=1
# specify `__pycache__` directory
ENV PYTHONPYCACHEPREFIX=/tmp/pycache

# set `--frozen` to `uv sync` on runtime
RUN --mount=type=cache,target=$UV_CACHE_DIR,sharing=locked \
    uv venv /opt/venv \
    && if [ -s uv.lock ]; then uv sync --dev; fi

RUN chmod -R a+rX /opt/venv \
    && find /opt/venv -type d -perm -u+w -exec chmod a+w {} +

# activate venv
RUN cat <<'EOF' >> /etc/bash.bashrc

export LANG=$LANG

if [ -n "$UV_PROJECT_ENVIRONMENT" ] &&
    [ -f "$UV_PROJECT_ENVIRONMENT/bin/activate" ] &&
    [ -z "$VIRTUAL_ENV" ]; then
    . "$UV_PROJECT_ENVIRONMENT/bin/activate"
fi
EOF

# install Codex
ARG CODEX_BUST
RUN echo "CODEX_BUST=$CODEX_BUST" \
    && npm i -g @openai/codex

# install Caude
# Claude code is installed under ~/.local
USER ubuntu
ARG CLAUDE_BUST
RUN echo "CLAUDE_BUST=$CLAUDE_BUST" \
    && curl -fsSL https://claude.ai/install.sh | bash

USER root

# install LLVM and Clang
COPY --from=builder /out/toolchain/ /opt/nosuz16/toolchain/
COPY --from=builder /src/llvm-nosuz16/include/ /opt/nosuz16/llvm-nosuz16/include/
COPY --from=builder /src/llvm-nosuz16/runtime/ /opt/nosuz16/llvm-nosuz16/runtime/
COPY --from=builder /src/llvm-nosuz16/examples/ /opt/nosuz16/llvm-nosuz16/examples/
COPY --from=builder /src/llvm-nosuz16/scripts/compile.sh /src/llvm-nosuz16/scripts/compile-c.sh /src/llvm-nosuz16/scripts/image.py /opt/nosuz16/llvm-nosuz16/scripts/
COPY --from=builder /src/llvm-nosuz16/tests/sdk.py /opt/nosuz16/llvm-nosuz16/tests/sdk.py
COPY Nosuz16_CPU_Spec.md /opt/nosuz16/Nosuz16_CPU_Spec.md
COPY llvm-nosuz16/README.md /opt/nosuz16/llvm-nosuz16/README.md
COPY llvm-nosuz16/LLVM_BASE_REVISION /opt/nosuz16/llvm-nosuz16/LLVM_BASE_REVISION

# install emulator
COPY --from=emulator-builder \
    /src/emulator/target/release/nosuz16 \
    /opt/nosuz16/toolchain/bin/nosuz16
RUN strip /opt/nosuz16/toolchain/bin/nosuz16
ENV LLVM_BUILD_DIR=/opt/nosuz16/toolchain \
    PATH="/opt/nosuz16/toolchain/bin:/home/ubuntu/.local/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1
RUN printf '%s\n' '#!/bin/sh' 'exec /opt/nosuz16/llvm-nosuz16/scripts/compile-c.sh "$@"' > /usr/local/bin/nosuz16-cc \
    && printf '%s\n' '#!/bin/sh' 'exec /opt/nosuz16/llvm-nosuz16/scripts/compile.sh "$@"' > /usr/local/bin/nosuz16-ir \
    && chmod +x /usr/local/bin/nosuz16-cc /usr/local/bin/nosuz16-ir \
    && python3 /opt/nosuz16/llvm-nosuz16/tests/sdk.py

WORKDIR /workspaces
# CMD ["/bin/bash"]
