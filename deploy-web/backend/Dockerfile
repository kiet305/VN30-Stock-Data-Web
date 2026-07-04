FROM python:3.11-slim

WORKDIR /app

COPY deploy-web/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY TradingAgents /tmp/TradingAgents
RUN pip install --no-cache-dir /tmp/TradingAgents

COPY deploy-web/backend/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
