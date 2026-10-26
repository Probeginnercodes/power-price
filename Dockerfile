FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOSTED_STATE_DIR=/state
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-hosted.txt ./
RUN pip install --no-cache-dir -r requirements-hosted.txt
RUN useradd --uid 10001 --create-home demo && mkdir /state && chown demo:demo /state
COPY . /app
USER demo
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "hosted_api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
