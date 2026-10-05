# Image and dependency lock updates must pass the same test suite before deployment.
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS builder
RUN python -m pip install --no-cache-dir uv==0.12.18
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM builder AS tests
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-ind fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN python -c "import shutil, subprocess; assert all(shutil.which(x) for x in ('pdfinfo', 'pdftotext', 'pdfimages', 'pdftoppm', 'tesseract')); assert {'eng', 'ind'} <= set(subprocess.check_output(['tesseract', '--list-langs'], text=True).split())"
RUN uv sync --frozen --no-editable
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests ./tests
COPY compose.knowledge.yaml ./compose.knowledge.yaml
COPY compose.calendar.yaml ./compose.calendar.yaml
COPY scripts ./scripts
COPY infra/postgres/bootstrap.sh ./infra/postgres/bootstrap.sh
ENV PATH="/app/.venv/bin:$PATH"
CMD ["pytest", "--cov=jarvis", "--cov-report=term-missing"]

FROM base AS runtime
RUN groupadd --gid 10001 jarvis && useradd --uid 10001 --gid 10001 --no-create-home jarvis
COPY --from=builder /app/.venv /app/.venv
COPY migrations ./migrations
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH"
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "jarvis.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]

FROM runtime AS parser
USER root
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-ind && rm -rf /var/lib/apt/lists/*
RUN python -c "import shutil, subprocess; assert all(shutil.which(x) for x in ('pdfinfo', 'pdftotext', 'pdfimages', 'pdftoppm', 'tesseract')); assert {'eng', 'ind'} <= set(subprocess.check_output(['tesseract', '--list-langs'], text=True).split())"
USER 10001:10001
CMD ["uvicorn", "jarvis.knowledge.parser_app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "4"]
