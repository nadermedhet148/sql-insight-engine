import pika
import sys
import os
from abc import ABC, abstractmethod

class BaseConsumer(ABC):
    def __init__(self, queue_name: str, host: str = 'localhost'):
        self.queue_name = queue_name
        self.host = host or "localhost"
        
        try:
            self._connect()
        except Exception as e:
            print(f"[CONSUMER] Initial connection failed to RabbitMQ at {self.host}: {e}")
            # We don't raise here, start_consuming will handle reconnection
            pass

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
        import time
        while True:
            try:
                # Re-initialize connection if it was closed
                if not hasattr(self, 'connection') or self.connection.is_closed:
                    self._connect()
                
                self.channel.basic_consume(
                    queue=self.queue_name, 
                    on_message_callback=self._callback, 
                    auto_ack=False # Forced manual ack for reliability
                )
                print(f"\n[CONSUMER] Waiting for messages on '{self.queue_name}'...")
                self.channel.start_consuming()
            except (pika.exceptions.AMQPConnectionError, pika.exceptions.ConnectionClosedByBroker) as e:
                print(f"[CONSUMER] Connection issue with RabbitMQ: {e}. Retrying in 5 seconds...")
                time.sleep(5)
            except KeyboardInterrupt:
                print(f"\n[CONSUMER] Shutting down {self.queue_name}...")
                self.stop()
                break
            except Exception as e:
                print(f"[CONSUMER] Critical error in consumer loop: {type(e).__name__}: {e}. Retrying in 5 seconds...")
                import traceback
                traceback.print_exc()
                time.sleep(5)
    
    def _connect(self):
        user = os.getenv("RABBITMQ_USER", "guest")
        password = os.getenv("RABBITMQ_PASSWORD", "guest")
        
        credentials = pika.PlainCredentials(user, password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            credentials=credentials,
            heartbeat=600,
            connection_attempts=10,
            retry_delay=5
        )
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue_name, durable=True)
        self.channel.basic_qos(prefetch_count=1)
    
    def stop(self):
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception as e:
            print(f"Error closing connection: {e}")
