"""
Saga Publisher for RabbitMQ

Publishes messages to different queues for each saga step.
"""

import pika
import json
import os
from typing import Optional
from agentic_sql.saga.messages import SagaBaseMessage, message_to_json


import threading

class SagaPublisher:
    """Publisher for saga messages"""
    
    # Queue names for each saga step
    QUEUE_GENERATE_QUERY = "query_generate_query"
    QUEUE_EXECUTE_QUERY = "query_execute_query"
    QUEUE_FORMAT_RESULT = "query_format_result"
    QUEUE_ERROR = "query_error"
    
    def __init__(self, host: Optional[str] = None):
        self.host = host or os.getenv("RABBITMQ_HOST", "localhost")
        self.user = os.getenv("RABBITMQ_USER", "guest")
        self.password = os.getenv("RABBITMQ_PASSWORD", "guest")
        self.connection = None
        self.channel = None
        self._lock = threading.Lock()
    
    def connect(self):
        """Establish connection to RabbitMQ"""
        credentials = pika.PlainCredentials(self.user, self.password)
        parameters = pika.ConnectionParameters(
            host=self.host,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300
        )
        
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        
        # Declare all queues
        self._declare_queues()
    
    def _declare_queues(self):
        """Declare all saga queues"""
        queues = [
            self.QUEUE_GENERATE_QUERY,
            self.QUEUE_EXECUTE_QUERY,
            self.QUEUE_FORMAT_RESULT,
            self.QUEUE_ERROR
        ]
        
        for queue in queues:
            self.channel.queue_declare(queue=queue, durable=True)
    
    def _ensure_connection(self):
        """Ensure we have a valid connection and channel. Must be called under lock."""
        if self.connection is None or self.connection.is_closed:
            self.connect()
        elif self.channel is None or self.channel.is_closed:
            self.channel = self.connection.channel()
            self._declare_queues()
    
    def publish(self, queue: str, message: SagaBaseMessage):
        """Publish message to specified queue"""
        with self._lock:
            self._ensure_connection()
            
            message_body = message_to_json(message)
            
            try:
                self.channel.basic_publish(
                    exchange='',
                    routing_key=queue,
                    body=message_body,
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Make message persistent
                        content_type='application/json',
                        headers={
                            'saga_id': message.saga_id,
                            'user_id': str(message.user_id),
                            'account_id': message.account_id
                        }
                    )
                )
            except (pika.exceptions.ChannelClosedByBroker, 
                    pika.exceptions.ChannelWrongStateError,
                    pika.exceptions.StreamLostError) as e:
                print(f"[SAGA PUBLISHER] Channel error, reconnecting: {e}")
                self.connection = None
                self.channel = None
                self._ensure_connection()
                # Retry once
                self.channel.basic_publish(
                    exchange='',
                    routing_key=queue,
                    body=message_body,
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type='application/json',
                        headers={
                            'saga_id': message.saga_id,
                            'user_id': str(message.user_id),
                            'account_id': message.account_id
                        }
                    )
                )
            
            print(f"[SAGA PUBLISHER] Published to '{queue}' - Saga ID: {message.saga_id}")
    
    def publish_query_generation(self, message: SagaBaseMessage):
        """Publish to query generation queue (Step 1)"""
        self.publish(self.QUEUE_GENERATE_QUERY, message)
    
    def publish_query_execution(self, message: SagaBaseMessage):
        """Publish to query execution queue (Step 2)"""
        self.publish(self.QUEUE_EXECUTE_QUERY, message)
    
    def publish_result_formatting(self, message: SagaBaseMessage):
        """Publish to result formatting queue (Step 3)"""
        self.publish(self.QUEUE_FORMAT_RESULT, message)
    
    def publish_error(self, message: SagaBaseMessage):
        """Publish to error queue"""
        self.publish(self.QUEUE_ERROR, message)
    
    def close(self):
        """Close connection"""
        with self._lock:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
                print("[SAGA PUBLISHER] Connection closed")


# Singleton instance
_publisher_instance = None


def get_saga_publisher() -> SagaPublisher:
    """Get or create saga publisher instance"""
    global _publisher_instance
    if _publisher_instance is None:
        _publisher_instance = SagaPublisher()
    return _publisher_instance
