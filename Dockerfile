FROM python:3.11-slim

ARG HOST_UID=1000
RUN useradd -u ${HOST_UID} --home /app --no-create-home app
ENV HOME=/app
WORKDIR /app

COPY ./requirements.txt /app
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . /app
RUN python3 -m pip install --no-cache-dir -e .

RUN chown -R app:app /app
USER app

ENTRYPOINT ["ocmonitor"]
