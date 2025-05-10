from flask import request
from api.utils.db import db
from api.routes.base import BaseResource
from pymongo import UpdateOne
from api.auth.decorators import auth_required

class Update(BaseResource):
    @auth_required
    def put(self):
        try:
            data_type = request.args.get('type')
            where_field = request.args.get('where_field')
            where_value = request.args.get('where_value')
            
            if not all([data_type, where_field, where_value]):
                return {'error': 'Type, where_field, and where_value parameters are required'}, 400
            
            update_data = request.get_json()
            if not update_data:
                return {'error': 'Request body is required'}, 400
            
            result = db[data_type].update_one(
                {where_field: where_value},
                {'$set': update_data}
            )
            
            return {
                'message': 'Data updated successfully',
                'modified_count': result.modified_count
            }, 200
        except Exception as e:
            return {'error': str(e)}, 500

    @classmethod
    def init_api(cls, api):
        super().init_api(api)
        cls.ns.expect(api.models['Data'])(cls.put)
        cls.ns.doc(params={
            'type': 'Collection name',
            'where_field': 'Field to match for update',
            'where_value': 'Value to match for update'
        }, security=['Bearer Auth', 'System Auth'])(cls.put)
        return cls

class BulkUpdate(BaseResource):
    @auth_required
    def put(self):
        try:
            data_type = request.args.get('type')
            where_field = request.args.get('where_field')
            
            if not all([data_type, where_field]):
                return {'error': 'Type and where_field parameters are required'}, 400
            
            update_data = request.get_json()
            if not update_data or not isinstance(update_data, list):
                return {'error': 'Request body must be an array of updates'}, 400
            
            operations = []
            for update in update_data:
                where_value = update.get('where_value')
                if not where_value:
                    continue
                
                update_values = update.get('update', {})
                if not update_values:
                    continue
                
                operations.append(
                    UpdateOne(
                        {where_field: where_value},
                        {'$set': update_values}
                    )
                )
            
            if not operations:
                return {'error': 'No valid update operations found'}, 400
            
            result = db[data_type].bulk_write(operations)
            
            return {
                'message': 'Bulk update completed successfully',
                'modified_count': result.modified_count
            }, 200
        except Exception as e:
            return {'error': str(e)}, 500

    @classmethod
    def init_api(cls, api):
        super().init_api(api)
        cls.ns.expect(api.models['BulkData'])(cls.put)
        cls.ns.doc(params={
            'type': 'Collection name',
            'where_field': 'Field to match for update'
        }, security=['Bearer Auth', 'System Auth'])(cls.put)
        return cls 