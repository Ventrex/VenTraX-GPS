FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/instance /app/static/uploads /app/static/backgrounds /app/static/qr /app/logs
ENV DATABASE_URL=sqlite:////app/instance/venfaye.db
ENV SECRET_KEY=change-me
ENV PORT=5000
ENV BASE_URL=http://localhost:5001
EXPOSE 5000
CMD ["python", "run.py"]
