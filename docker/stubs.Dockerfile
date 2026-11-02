FROM python:3.12-slim
COPY docker/stubs/server.py /srv/server.py
EXPOSE 8088
CMD ["python", "-u", "/srv/server.py"]
