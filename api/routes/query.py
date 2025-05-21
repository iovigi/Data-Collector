from flask import request
from api.utils.db import db
from api.routes.base import BaseResource
from flask_restx import fields
import json
from bson import ObjectId
from api.auth.decorators import auth_required

class Query(BaseResource):
    @auth_required
    def get(self):
        try:
            data_type = request.args.get('type')
            if not data_type:
                return {'error': 'Type parameter is required'}, 400

            # Get query parameters from query string
            field = request.args.get('field')
            value = request.args.get('value')
            
            # Try to parse value as JSON if it's a string
            if value and isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    # If not valid JSON, keep as string
                    pass
            
            page = max(1, int(request.args.get('page', 1)))
            per_page = max(1, min(100, int(request.args.get('per_page', 10))))
            
            # Add order_by and order_direction parameters
            order_by = request.args.get('order_by')
            order_direction = request.args.get('order_direction', 'asc').lower()
            
            query_filter = {}
            if field and value is not None:
                # Handle special cases for value
                if isinstance(value, str):
                    # Try to convert string to ObjectId if it matches the pattern
                    if field == '_id' and len(value) == 24:
                        try:
                            value = ObjectId(value)
                        except:
                            pass
                query_filter[field] = value
            
            skip = (page - 1) * per_page
            total = db[data_type].count_documents(query_filter)
            
            # Create the query with ordering
            query = db[data_type].find(query_filter)
            if order_by:
                direction = 1 if order_direction == 'asc' else -1
                query = query.sort(order_by, direction)
            
            results = list(query.skip(skip).limit(per_page))
            
            # Convert ObjectId to string for JSON serialization
            for result in results:
                result['_id'] = str(result['_id'])
            
            return {
                'data': results,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page
            }, 200
        except Exception as e:
            return {'error': str(e)}, 500

    @classmethod
    def init_api(cls, api):
        super().init_api(api)
        
        # Define the response model
        response_model = api.model('QueryResponse', {
            'data': fields.List(fields.Raw, description='Query results'),
            'total': fields.Integer(description='Total number of records'),
            'page': fields.Integer(description='Current page number'),
            'per_page': fields.Integer(description='Items per page'),
            'total_pages': fields.Integer(description='Total number of pages')
        })

        # Add example responses
        example_response = {
            'data': [
                {
                    '_id': '507f1f77bcf86cd799439011',
                    'name': 'John Doe',
                    'data': {
                        'test': 'value',
                        'nested': {
                            'field': 'value'
                        }
                    }
                },
                {
                    '_id': '507f1f77bcf86cd799439012',
                    'name': 'Jane Smith',
                    'data': {
                        'test': 'other',
                        'nested': {
                            'field': 'other'
                        }
                    }
                }
            ],
            'total': 2,
            'page': 1,
            'per_page': 10,
            'total_pages': 1
        }

        # Define query parameters
        type_param = api.parser()
        type_param.add_argument('type', type=str, required=True, help='Collection name', location='args')
        type_param.add_argument('field', type=str, required=False, help='Field to filter by', location='args')
        type_param.add_argument('value', type=str, required=False, help='Value to filter for', location='args')
        type_param.add_argument('page', type=int, required=False, default=1, help='Page number', location='args')
        type_param.add_argument('per_page', type=int, required=False, default=10, help='Items per page', location='args')
        type_param.add_argument('order_by', type=str, required=False, help='Field to order results by', location='args')
        type_param.add_argument('order_direction', type=str, required=False, default='asc', 
                              choices=['asc', 'desc'], help='Sort direction (asc or desc)', location='args')

        # Update the documentation with ordering examples
        cls.ns.doc(
            description='''Query data from a collection with pagination, filtering, and sorting.
            
            Example requests:
            ```
            # Simple equality query with sorting
            GET /api/query?type=users&field=age&value=25&page=1&per_page=10&order_by=name&order_direction=asc

            # MongoDB operator query with sorting
            GET /api/query?type=users&field=age&value={"$gt":25}&page=1&per_page=10&order_by=created_at&order_direction=desc

            # String query with sorting
            GET /api/query?type=users&field=name&value=John&page=1&per_page=10&order_by=age&order_direction=desc

            # Array query with sorting
            GET /api/query?type=users&field=tags&value=["admin","user"]&page=1&per_page=10&order_by=name&order_direction=asc

            # JSON object field query with sorting
            GET /api/query?type=users&field=data&value={"test":"value"}&page=1&per_page=10&order_by=data.created_at&order_direction=desc

            # Nested field query with sorting
            GET /api/query?type=users&field=data.nested.field&value=value&page=1&per_page=10&order_by=data.nested.priority&order_direction=asc
            ```
            
            The value field can be any valid JSON value or MongoDB query operator.
            For JSON object fields, you can:
            1. Query the entire object for an exact match
            2. Query specific nested fields using dot notation
            3. Use MongoDB operators on nested fields
            
            Sorting:
            - Use order_by to specify the field to sort by
            - Use order_direction to specify sort direction (asc or desc)
            - Sorting works with both top-level and nested fields using dot notation''',
            security=['Bearer Auth', 'System Auth']
        )
        
        # Register the parser with the endpoint
        cls.ns.expect(type_param)(cls.get)
        
        return cls 