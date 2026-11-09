FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py config.yaml ./
RUN useradd -r -u 10001 app
USER 10001
EXPOSE 9105
CMD ["python", "app.py"]
