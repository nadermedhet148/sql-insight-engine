import pika

class BaseProducer:
    def __init__(self, queue_name: str, host: str = None):
        import os
        self.queue_name = queue_name
        self.host = host or os.getenv("RABBITMQ_HOST", "localhost")
        
        # Fallback for host development
        if self.host == "rabbitmq" and not os.path.exists('/.dockerenv'):
            self.host = "localhost"
            
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self.host)
        )
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue_name, durable=True)

    def publish(self, message: str):
        self.channel.basic_publish(
            exchange='',
            routing_key=self.queue_name,
            body=message,
            properties=pika.BasicProperties(
                delivery_mode=2,  # make message persistent
            )
        )
        print(f" [x] Sent '{message}' to queue '{self.queue_name}'")

    def close(self):
        self.connection.close()
