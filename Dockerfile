FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 ragpipe
WORKDIR /app
COPY pyproject.toml README.md ./
COPY ragpipe ./ragpipe
RUN pip install --upgrade pip && pip install '.[local]'
USER ragpipe
ENTRYPOINT ["ragpipe"]
CMD ["--help"]

