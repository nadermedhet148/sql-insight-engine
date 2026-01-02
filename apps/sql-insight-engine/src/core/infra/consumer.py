import pika
import sys
import os
import functools
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod

class ThreadSafeChannel:
    """Wrapper around pika channel to ensure methods are called on the connection's thread."""
    def __init__(self, connection, channel):
        self.connection = connection
        self.channel = channel

    def basic_ack(self, delivery_tag, multiple=False):
        cb = functools.partial(self.channel.basic_ack, delivery_tag=delivery_tag, multiple=multiple)
        self.connection.add_callback_threadsafe(cb)

    def basic_nack(self, delivery_tag, multiple=False, requeue=True):
        cb = functools.partial(self.channel.basic_nack, delivery_tag=delivery_tag, multiple=multiple, requeue=requeue)
        self.connection.add_callback_threadsafe(cb)
    
    def __getattr__(self, name):
        return getattr(self.channel, name)

class BaseConsumer(ABC):
    def __init__(self, queue_name: str, host: str = 'localhost', prefetch_count: int = 100):
        self.queue_name = queue_name
        self.host = host or "localhost"
        self.prefetch_count = prefetch_count
        self.executor = ThreadPoolExecutor(max_workers=prefetch_count)
        
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
        # Define the task to run in the thread pool
        def thread_target():
            safe_ch = ThreadSafeChannel(self.connection, ch)
            try:
                self.process_message(safe_ch, method, properties, body)
            except Exception as e:
                print(f"Error in consumer {self.queue_name} (thread): {e}")
                # Use safe_ch to nack on the main thread
                try:
                    safe_ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                except:
                    pass

        # Validate executor before submitting
        if self.executor is None:
             self.executor = ThreadPoolExecutor(max_workers=self.prefetch_count)
             
        self.executor.submit(thread_target)

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
                print(f"\n[CONSUMER] Waiting for messages on '{self.queue_name}' with {self.prefetch_count} threads...")
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
        self.channel.basic_qos(prefetch_count=self.prefetch_count)
        print(f"[CONSUMER DEBUG] Prefetch count set to {self.prefetch_count} for queue {self.queue_name}")
    
    def stop(self):
        try:
            if self.executor:
                self.executor.shutdown(wait=False)
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception as e:
            print(f"Error closing connection: {e}")
