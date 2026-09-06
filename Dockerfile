FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
# The graph and app rebuild from the committed extraction artifacts; `make fetch` and `make extract` need a .env.
CMD ["uv", "run", "streamlit", "run", "policygraph/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
