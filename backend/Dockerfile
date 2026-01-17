# Stage 1: Build
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.7.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    curl \
    build-essential

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR $PYSETUP_PATH
COPY pyproject.toml README.md ./

# Install dependencies (without the project root itself)
RUN poetry install --only main --no-root

# Stage 2: Production
FROM python:3.11-slim AS production

ENV VENV_PATH="/opt/pysetup/.venv"
ENV PATH="$VENV_PATH/bin:$PATH"

WORKDIR /app

COPY --from=builder $VENV_PATH $VENV_PATH
COPY prometheus/ ./prometheus/

EXPOSE 8000

CMD ["uvicorn", "prometheus.main:app", "--host", "0.0.0.0", "--port", "8000"]
