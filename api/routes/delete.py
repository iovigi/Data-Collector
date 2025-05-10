from flask import request
from api.utils.db import db
from api.routes.base import BaseResource
from api.auth.decorators import auth_required

class Delete(BaseResource):
    @auth_required
    def delete(self):
        try:
            data_type = request.args.get('type')
            where_field = request.args.get('where_field')
            where_value = request.args.get('where_value')
            
            if not all([data_type, where_field, where_value]):
                return {'error': 'Type, where_field, and where_value parameters are required'}, 400
            
            result = db[data_type].delete_one({where_field: where_value})
            return {
                'message': 'Data deleted successfully',
                'deleted_count': result.deleted_count
            }, 200
        except Exception as e:
            return {'error': str(e)}, 500

    @classmethod
    def init_api(cls, api):
        super().init_api(api)
        cls.ns.doc(params={
            'type': 'Collection name',
            'where_field': 'Field to match for deletion',
            'where_value': 'Value to match for deletion'
        }, security=['Bearer Auth', 'System Auth'])(cls.delete)
        return cls 