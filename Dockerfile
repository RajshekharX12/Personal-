FROM python:3.11.8-slim

WORKDIR /app

COPY . /app

RUN pip install --upgrade pip \
    && pip install -U -r requirements.txt

CMD ["bash", "start.sh"]


