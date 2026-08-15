FROM python:3.12-slim
WORKDIR /app
# node+npm only for supergateway (the stdio→SSE bridge)
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g supergateway
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8001 8002 8003
CMD ["supergateway", "--stdio", "python main_server.py", "--port", "8001"]
