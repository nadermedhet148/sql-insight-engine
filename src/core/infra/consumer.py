import pika
import sys
import os
from abc import ABC, abstractmethod

class BaseConsumer(ABC):
    def __init__(self, queue_name: str, host: str = 'localhost'):
        self.queue_name = queue_name
        self.host = host or "localhost"
        
        credentials = pika.PlainCredentials('guest', 'guest')
        parameters = pika.ConnectionParameters(
            host=self.host,
            credentials=credentials,
            heartbeat=600
        )
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue_name, durable=True)
        self.channel.basic_qos(prefetch_count=1)

    @abstractmethod
    def process_message(self, ch, method, properties, body):
        """Process the received message. Concrete classes must implement this."""
        pass

    def _callback(self, ch, method, properties, body):
        try:
            self.process_message(ch, method, properties, body)
        except Exception as e:
            print(f"Error in consumer {self.queue_name}: {e}")
            # By default, we nack without requeueing to prevent infinite loops if not handled in process_message
            try:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            except:
                pass

    def start_consuming(self):
        self.channel.basic_consume(
            queue=self.queue_name, 
            on_message_callback=self._callback, 
            auto_ack=False # Forced manual ack for reliability
        )
        print(f"\n[CONSUMER] Waiting for messages on '{self.queue_name}'...")
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            print(f"\n[CONSUMER] Shutting down {self.queue_name}...")
            self.stop()
        except Exception as e:
            print(f"[CONSUMER] Critical error: {e}")
            self.stop()
    
    def stop(self):
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception as e:
            print(f"Error closing connection: {e}")
