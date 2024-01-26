FROM python:3.11

WORKDIR /app

COPY ./src /app
COPY ./requirements.txt /app

RUN pip install --no-cache-dir --upgrade -r requirements.txt

EXPOSE 9999
CMD ["python", "app.py"]