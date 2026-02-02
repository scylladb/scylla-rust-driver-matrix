FROM rust:1.93-slim-bullseye

# Necessary system dependencies
# /var/lib/apt/lists is removed to save space in the final image
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        gcc \
        pkg-config \
		libssl-dev \
		curl \
        git \
        iproute2 \
        patch \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# UV_LINK_MODE=copy
# Various venv will be on different bind mounts,
# so hardlinks won't work. To avoid uv warnings,
# let's instruct it to copy the packages to venvs.
#
# UV_PYTHON_INSTALL_DIR, UV_PYTHON_BIN_DIR
# This ensures single Python directory for all users.
# Thanks to that we can install Python here,
# and then use it on container run as separate user.
ENV UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_PYTHON_BIN_DIR=/usr/local/bin \
    PATH="/usr/local/bin:${PATH}"

# Install a managed Python version system-wide
RUN mkdir -p "$UV_PYTHON_INSTALL_DIR" \
 && uv python install 3.14 \
 && chmod -R a+rX "$UV_PYTHON_INSTALL_DIR"

# Install cargo nextest
RUN dpkgArch="$(dpkg --print-architecture)"; \
    case "${dpkgArch##*-}" in \
        amd64) nextest_url='https://get.nexte.st/latest/linux' ;; \
        arm64) nextest_url='https://get.nexte.st/latest/linux-arm' ;; \
        *) echo >&2 "unsupported architecture: ${dpkgArch}"; exit 1 ;; \
    esac; \
    \
    curl -LsSf "$nextest_url" | tar zxf - -C ${CARGO_HOME:-~/.cargo}/bin

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "main.py", "--help"]
