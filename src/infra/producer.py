import pika

class BaseProducer:
    def __init__(self, queue_name: str, host: str = 'localhost'):
        self.queue_name = queue_name
        self.host = host
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self.host)
        )
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue_name)

    def publish(self, message: str):
        self.channel.basic_publish(exchange='', routing_key=self.queue_name, body=message)
        print(f" [x] Sent '{message}' to queue '{self.queue_name}'")

    def close(self):
        self.connection.close()
