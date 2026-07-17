# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm

WORKDIR /python-docker

COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py .

# Run as an unprivileged user; the app only needs to read its own code.
RUN useradd --no-create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 5000

# Production WSGI server instead of the Flask dev server.
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "app:app"]
