.PHONY: all fetch normalize extract resolve graph insights app test eval lint service worker

PY := uv run --env-file .env python
PORT ?= 8000

all: fetch normalize extract resolve graph insights

fetch:      ; $(PY) -m policygraph fetch
normalize:  ; $(PY) -m policygraph normalize
extract:    ; $(PY) -m policygraph extract
resolve:    ; $(PY) -m policygraph resolve
graph:      ; $(PY) -m policygraph graph
insights:   ; $(PY) -m policygraph insights
app:        ; uv run streamlit run policygraph/app.py
test:       ; uv run pytest -q
eval:       ; $(PY) -m extraction_service.eval
lint:       ; uv run ruff check . && uv run ruff format --check .
service:    ; uv run uvicorn extraction_service.api:app --port $(PORT)
worker:     ; $(PY) -m extraction_service.worker
