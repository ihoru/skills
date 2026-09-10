FROM python:3.13-slim

ARG API_TOKEN
ENV API_TOKEN="production-secret-value"

RUN apt-get update
RUN apt-get install -y curl

WORKDIR /app
COPY . .

ENTRYPOINT python app.py
