FROM python:3.12-slim
# Node + Claude Code CLI: the server answers questions through `claude -p`
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @anthropic-ai/claude-code@2.1.319 && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*
ENV HOME=/data DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py providers.py entrypoint.sh icon.png ./
RUN mkdir /data && chmod 777 /data
ENV PUID=1000 PGID=100
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
# /ask can take up to 90 s (the CLI call), so the worker timeout is longer than gunicorn's default 30 s
CMD ["gunicorn", "-w", "1", "--threads", "4", "--timeout", "120", "-b", "0.0.0.0:8000", "app:app"]
