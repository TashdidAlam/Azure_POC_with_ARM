import logging
import os
import azure.functions as func
from azure.storage.queue import QueueClient
from azure.storage.blob import BlobClient

# Set up logging
logging.basicConfig(level=logging.INFO)

# Get app settings
source_storage_account_name = os.environ.get('AzureWebJobsStorage').split(';')[1].split('=')[1]
destination_storage_account_name = os.environ.get('DestinationStorageAccount')
queue_name = os.environ.get('PoisonQueueName')

# Create clients
source_blob_service_client = BlobClient.from_connection_string(conn_str=os.environ.get('AzureWebJobsStorage'))
destination_blob_service_client = BlobClient.from_connection_string(
    f"DefaultEndpointsProtocol=https;AccountName={destination_storage_account_name};EndpointSuffix={os.environ.get('WEBSITE_HOSTNAME').split('.')[2]};AccountKey={os.environ.get('DestinationStorageAccountKey')}")
queue_client = QueueClient.from_connection_string(conn_str=os.environ.get('AzureWebJobsStorage'), queue_name=queue_name)

def main(event: func.EventGridEvent):
    blob_name = event.subject.split('/')[-1]
    retry_count = int(event.get_json().get('data', {}).get('retryCount', 0))

    try:
        # Download the blob from the source container
        source_blob = source_blob_service_client.get_blob_client('container1', blob_name)
        blob_data = source_blob.download_blob().readall()

        # Upload the blob to the destination container
        destination_blob = destination_blob_service_client.get_blob_client('container2', blob_name)
        destination_blob.upload_blob(blob_data, overwrite=True)
        logging.info(f"Successfully uploaded {blob_name} to the destination container.")

    except Exception as e:
        logging.error(f"Error processing {blob_name}: {e}")

        if retry_count < 5:
            # Reschedule the message for retry
            queue_client.send_message(
                event.get_json().get('data', {}).update({'retryCount': retry_count + 1}),
                visibility_timeout=60
            )
            logging.info(f"Rescheduling {blob_name} for retry {retry_count + 1}.")
        else:
            # Move the message to the poison queue
            queue_client.send_message(event.get_json().get('data', {}))
            logging.info(f"Moving {blob_name} to the poison queue after 5 failed attempts.")