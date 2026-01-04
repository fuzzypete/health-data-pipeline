FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 POETRY_VERSION=1.8.5
RUN pip install "poetry==$POETRY_VERSION"
WORKDIR /app
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root --no-dev --no-interaction --no-ansi
COPY . .
RUN poetry install --no-interaction --no-ansi
CMD ["bash"]
