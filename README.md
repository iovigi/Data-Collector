# Data Collector API

A Flask-based REST API for collecting and managing data with MongoDB.

## Quick Setup

You can use the provided setup script to automatically create a virtual environment, install dependencies, and create the necessary configuration files:

```bash
python setup.py
```

This script will:
1. Create a virtual environment
2. Install all required dependencies
3. Create a `.env` file with default settings
4. Optionally start the application

## Manual Setup

If you prefer to set up the environment manually, follow these steps:

### 1. Create and activate a virtual environment

#### Windows:
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate
```

#### Linux/Mac:
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
source venv/bin/activate
```

### 2. Install dependencies:
```bash
pip install -r requirements.txt
```

### 3. Create a `.env` file in the root directory with the following content:
```
MONGODB_URI=mongodb://localhost:27017/
DB_NAME=data_collector
```

### 4. Make sure MongoDB is running on your system.

## Running the Application

```bash
python app.py
```

The server will start on `http://localhost:5000`

## API Documentation

The API documentation is available at `http://localhost:5000/` when the application is running.

## API Endpoints

### Insert Data
- **POST** `/api/insert?type=<collection_name>`
- Body: JSON object to insert

### Bulk Insert
- **POST** `/api/bulk_insert?type=<collection_name>`
- Body: Array of JSON objects to insert

### Query Data
- **GET** `/api/query?type=<collection_name>&field=<field_name>&value=<field_value>&page=<page_number>&per_page=<items_per_page>`
- All parameters except `type` are optional

### Update Data
- **PUT** `/api/update?type=<collection_name>&where_field=<field_name>&where_value=<field_value>`
- Body: JSON object with fields to update

### Bulk Update
- **PUT** `/api/bulk_update?type=<collection_name>&where_field=<field_name>`
- Body: Array of objects with `where_value` and `update_data`

### Delete Data
- **DELETE** `/api/delete?type=<collection_name>&where_field=<field_name>&where_value=<field_value>`

### Create Index
- **POST** `/api/create_index?type=<collection_name>&field=<field_name>`

## Example Usage

### Insert a single record
```bash
curl -X POST "http://localhost:5000/api/insert?type=users" \
     -H "Content-Type: application/json" \
     -d '{"name": "John Doe", "email": "john@example.com"}'
```

### Query records
```bash
curl "http://localhost:5000/api/query?type=users&field=name&value=John&page=1&per_page=10"
```

### Update a record
```bash
curl -X PUT "http://localhost:5000/api/update?type=users&where_field=email&where_value=john@example.com" \
     -H "Content-Type: application/json" \
     -d '{"name": "John Smith"}'
```

### Create an index
```bash
curl -X POST "http://localhost:5000/api/create_index?type=users&field=email"
``` 