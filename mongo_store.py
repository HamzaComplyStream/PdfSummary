from pymongo import MongoClient
from urllib.parse import quote_plus
from dotenv import load_dotenv
import os

load_dotenv()

# MongoDB connection URI
uri = os.getenv("mongo_db")

def insert_document(document):
    try:
        null = None
        true = True
        false = False
        # Create MongoDB client
        client = MongoClient(uri)
        
        # Test the connection
        # This will raise an exception if connection fails
        client.admin.command('ping')
        print("Successfully connected to MongoDB!")
        
        # Get database reference (replace 'your_database_name' with actual database name)
        db = client['doc_parsing_test']
        collection_docs = db['docs']
        result = collection_docs.insert_one(document)
        # print(dir(result))
        #print(f"Inserted document ID: {result.inserted_id}")
        return str(result.inserted_id)
    except Exception as e:
        print(f"Error inserting document: {e}")
    finally:
        # Close the connection
        if 'client' in locals():
            client.close()
