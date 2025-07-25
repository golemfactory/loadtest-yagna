FROM python:3.12-alpine

RUN apk add build-base linux-headers
RUN apk --no-cache add curl
RUN curl -sSL https://install.python-poetry.org | python3 -
RUN ln -s /root/.local/bin/poetry  /usr/bin/poetry

COPY . /app
WORKDIR /app

RUN poetry install

CMD ["poetry", "run", "locust", "-f", "tests/nanotask.py"]
