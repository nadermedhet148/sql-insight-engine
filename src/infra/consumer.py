import pika
import sys
import os
from abc import ABC, abstractmethod

class BaseConsumer(ABC):
    def __init__(self, queue_name: str, host: str = 'localhost'):
        self.queue_name = queue_name
        self.host = host
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self.host)
        )
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue_name)

    @abstractmethod
    def process_message(self, body):
        """Process the received message."""
        pass

    def _callback(self, ch, method, properties, body):
        self.process_message(body.decode())
        # In a real app we might want manual acks
        # ch.basic_ack(delivery_tag=method.delivery_tag)

    def start_consuming(self):
        self.channel.basic_consume(
            queue=self.queue_name, 
            on_message_callback=self._callback, 
            auto_ack=True
        )
        print(f' [*] Waiting for messages in {self.queue_name}. To exit press CTRL+C')
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            print('Interrupted')
            self.stop()
    
    def stop(self):
        try:
            self.connection.close()
        except:
            pass
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
