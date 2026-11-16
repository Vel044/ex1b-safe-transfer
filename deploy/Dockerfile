FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml /app/
COPY server /app/server
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home --shell /usr/sbin/nologin transfer
COPY deploy/server.json /app/server.json
COPY deploy/init.py /app/init.py
USER 10001:10001
EXPOSE 8443
CMD ["ex1b", "server", "--config", "/app/server.json"]
