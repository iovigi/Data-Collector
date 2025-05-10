from pymongo import MongoClient
import os

def get_db():
    client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/'))
    return client[os.getenv('DB_NAME', 'your_database_name')] 