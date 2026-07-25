FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt requirements-ml.txt ./
RUN pip install -r requirements.txt

# Optional: the ML stack (sentence-transformers, scikit-learn — needed for LIVE
# matching on a tender outside the demo seed's pre-computed set) adds torch and
# is OFF by default, keeping this image lean/fast to build. Enable via
# docker-compose.ml.yml, which sets INSTALL_ML=true as a build arg — see its
# header comment and the root README ("Live matching in Docker").
ARG INSTALL_ML=false
RUN if [ "$INSTALL_ML" = "true" ]; then pip install -r requirements-ml.txt; fi

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
