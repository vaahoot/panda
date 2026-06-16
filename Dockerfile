FROM mcr.microsoft.com/playwright/python:v1.50.0-noble
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y xvfb && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

CMD ["python3", "src/bot.py"]
