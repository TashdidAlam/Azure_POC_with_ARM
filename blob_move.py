import logging
import os
import azure.functions as func
from azure.storage.queue import QueueClient, QueueMessage
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
import time

# Set up logging
logging.basicConfig(level=logging.INFO)

# Get app settings
queue_name = os.environ.get('QueueName')
poison_queue_name = os.environ.get('PoisonQueueName')
destination_storage_account = os.environ.get('DestinationStorageAccount')
slack_webhook_uri = os.environ.get('SlackWebhookUri')

# Create queue clients
queue_client = QueueClient.from_connection_string(
    conn_str=os.environ.get('AzureWebJobsStorage'), queue_name=queue_name)
poison_queue_client = QueueClient.from_connection_string(
    conn_str=os.environ.get('AzureWebJobsStorage'), queue_name=poison_queue_name)

# Create blob clients
source_blob_service_client = BlobServiceClient.from_connection_string(
    conn_str=os.environ.get('AzureWebJobsStorage'))
destination_blob_service_client = BlobServiceClient(
    account_url=f"https://{destination_storage_account}.blob.core.windows.net")


def process_csv(blob_name):
    # Download the CSV file from the source blob container
    source_container_client = source_blob_service_client.get_container_client('files')
    source_blob_client = source_container_client.get_blob_client(blob_name)
    csv_data = source_blob_client.download_blob().readall()

    # Process the CSV data
    processed_data = process_csv_data(csv_data)

    # Upload the processed data to the destination blob container
    destination_container_client = destination_blob_service_client.get_container_client('files')
    destination_blob_client = destination_container_client.get_blob_client(blob_name)
    destination_blob_client.upload_blob(processed_data)

    logging.info(f"Processed {blob_name} and uploaded to destination storage account.")


def process_csv_data(csv_data):
    # Example CSV processing logic (replace this with your actual processing code)
    lines = csv_data.decode('utf-8').splitlines()
    processed_lines = [f"Processed: {line}" for line in lines]
    processed_data = '\n'.join(processed_lines).encode('utf-8')
    return processed_data


def send_slack_notification(message):
    # Code to send a notification to Slack (replace with your implementation)
    logging.info(f"Sending Slack notification: {message}")


def main(msg: QueueMessage, context: func.Context):
    blob_name = msg.content

    try:
        process_csv(blob_name)
        queue_client.delete_message(msg)
    except Exception as e:
        logging.error(f"Error processing {blob_name}: {e}")

        # Check if the message is more than 1 hour old
        if msg.insertion_time and time.time() - msg.insertion_time > 3600:
            logging.info(f"Moving {blob_name} to poison queue (message older than 1 hour).")
            poison_queue_client.send_message(msg.content)
            queue_client.delete_message(msg)
            send_slack_notification(f"Failed to process {blob_name} (message older than 1 hour).")

        # Check if the message has been retried 5 times
        if msg.dequeue_count >= 4:
            logging.info(f"Moving {blob_name} to poison queue (5 failed attempts).")
            poison_queue_client.send_message(msg.content)
            queue_client.delete_message(msg)
            send_slack_notification(f"Failed to process {blob_name} (5 failed attempts).")

        else:
            logging.info(f"Rescheduling {blob_name} for retry.")