# Answers as bigquery.googleapis.com and oauth2.googleapis.com inside the compose network, so the Grafana BigQuery
# plugin (which ignores BIGQUERY_EMULATOR_HOST) talks to the emulator, with a short cache of repeated queries.
FROM python:3.12-alpine
RUN apk add --no-cache openssl
COPY docker/grafana/proxy/proxy.py /srv/proxy.py
CMD ["python", "-u", "/srv/proxy.py"]
