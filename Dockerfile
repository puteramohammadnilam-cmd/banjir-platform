FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
USER nobody
ENV PORT=8080
# Cloud Run sets PORT. Shell form so the variable is expanded.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
