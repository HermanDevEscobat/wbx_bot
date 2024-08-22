FROM python:3.11
COPY requirements.txt /app/
WORKDIR /app
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8081/tcp 8082/tcp
CMD ["python", "main.py"]
