import pika
import sys
import os
import functools
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod

class QueueingChannel:
    """
    Wrapper around pika channel. Instead of calling methods directly (which is not thread safe),
    it enqueues the action to be performed by the main thread's event loop.
    """
    def __init__(self, channel, action_queue):
        self.channel = channel
        self.action_queue = action_queue

    def basic_ack(self, delivery_tag, multiple=False):
        cb = functools.partial(self.channel.basic_ack, delivery_tag=delivery_tag, multiple=multiple)
        self.action_queue.put(cb)

    def basic_nack(self, delivery_tag, multiple=False, requeue=True):
        cb = functools.partial(self.channel.basic_nack, delivery_tag=delivery_tag, multiple=multiple, requeue=requeue)
        self.action_queue.put(cb)
    
    def basic_publish(self, exchange, routing_key, body, properties=None, mandatory=False):
        # We must capture the arguments at the time of the call
        cb = functools.partial(self.channel.basic_publish, exchange=exchange, routing_key=routing_key, body=body, properties=properties, mandatory=mandatory)
        self.action_queue.put(cb)
        
    def __getattr__(self, name):
        # For other methods, we might need similar wrappers if they are called from threads.
        # For now, we assume only ack/nack/publish are used from threads.
        return getattr(self.channel, name)

class BaseConsumer(ABC):
    def __init__(self, queue_name: str, host: str = 'localhost', prefetch_count: int = 20):
        self.queue_name = queue_name
        self.host = host or "localhost"
        self.prefetch_count = prefetch_count
        self.executor = ThreadPoolExecutor(max_workers=prefetch_count)
        self.action_queue = queue.Queue()
        self.running = True
        self.connection = None
        self.channel = None
        
        # Deferred connection to start_consuming
        self.connection = None
        self.channel = None

    @abstractmethod
    def process_message(self, ch, method, properties, body):
        """Process the received message. Concrete classes must implement this."""
        pass

    def _callback(self, ch, method, properties, body):
        # Define the task to run in the thread pool
        def thread_target():
            # Use QueueingChannel to enqueue actions back to main thread
            safe_ch = QueueingChannel(ch, self.action_queue)
            try:
                self.process_message(safe_ch, method, properties, body)
            except Exception as e:
                print(f"Error in consumer {self.queue_name} (thread): {e}")
                import traceback
                traceback.print_exc()
                # Enqueue nack on failure
                safe_ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

        # Validate executor before submitting
        if self.executor is None:
             self.executor = ThreadPoolExecutor(max_workers=self.prefetch_count)
             
        self.executor.submit(thread_target)

    def start_consuming(self):
        print(f"\n[CONSUMER] Starting manual event loop on '{self.queue_name}' with {self.prefetch_count} threads...")
        self.running = True
        while self.running:
            try:
                # 1. Connection maintenance
                if not self.connection or self.connection.is_closed or not self.channel or self.channel.is_closed:
                    print(f"[CONSUMER] Reconnecting to {self.queue_name} (Conn: {self.connection is not None}, Chan: {self.channel is not None})...")
                    self._connect()
                    # Re-setup consumer
                    consumer_tag = self.channel.basic_consume(
                        queue=self.queue_name, 
                        on_message_callback=self._callback, 
                        auto_ack=False
                    )
                    print(f"[CONSUMER] Consumer registered on {self.queue_name} with tag: {consumer_tag}")

                # 2. Process RabbitMQ network events
                # This will trigger _callback for incoming messages
                self.connection.process_data_events(time_limit=0.1)

                # 3. Process actions from worker threads (Ack/Nack/Publish)
                # We process a batch of actions to prevent locking the loop if the queue is huge,
                # but enough to keep up.
                processed_count = 0
                while not self.action_queue.empty() and processed_count < 1000:
                    try:
                        action = self.action_queue.get_nowait()
                        action() # Execute the closure (e.g. channel.basic_ack) on Main Thread
                        processed_count += 1
                        self.action_queue.task_done()
                    except Exception as e:
                        print(f"[CONSUMER] Error executing queued action: {e}")

            except (pika.exceptions.AMQPConnectionError, pika.exceptions.ConnectionClosedByBroker, pika.exceptions.StreamLostError) as e:
                print(f"[CONSUMER] Connection lost: {e}. sleeping...")
                # Clear action queue as those actions belong to dead channel/connection
                while not self.action_queue.empty():
                    try: self.action_queue.get_nowait() 
                    except: pass
                time.sleep(5)
            except KeyboardInterrupt:
                print(f"\n[CONSUMER] Stopping {self.queue_name}...")
                self.stop()
                break
            except Exception as e:
                print(f"[CONSUMER] Critical loop error: {e}")
                time.sleep(1)

    def _connect(self):
        user = os.getenv("RABBITMQ_USER", "guest")
        password = os.getenv("RABBITMQ_PASSWORD", "guest")
        
        credentials = pika.PlainCredentials(user, password)
        # Use a slightly larger write buffer if possible, or keep defaults.
        parameters = pika.ConnectionParameters(
            host=self.host,
            credentials=credentials,
            heartbeat=600,
            connection_attempts=10,
            retry_delay=5,
            blocked_connection_timeout=300
        )
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self.queue_name, durable=True)
        self.channel.basic_qos(prefetch_count=self.prefetch_count)
        print(f"[CONSUMER DEBUG] Connected. Prefetch={self.prefetch_count}. Queue={self.queue_name}")
    
    def stop(self):
        self.running = False
        try:
            if self.executor:
                self.executor.shutdown(wait=False)
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception as e:
            print(f"Error closing connection: {e}")
