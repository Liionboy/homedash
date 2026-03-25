FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY server.py .
COPY static/ static/

# Persistent DB in volume
VOLUME /app/data

ENV HOMEDASH_PORT=9876
ENV HOMEDASH_DB=/app/data/homedash.db
ENV HOMEDASH_USER=admin
ENV HOMEDASH_PASS=admin

EXPOSE 9876

CMD ["python", "server.py"]
