from flask import request
from api.utils.db import db
from api.routes.base import BaseResource
from api.auth.decorators import auth_required

class Insert(BaseResource):
    @auth_required
    def post(self):
        try:
            data_type = request.args.get('type')
            if not data_type:
                return {'error': 'Type parameter is required'}, 400
            
            data = request.get_json()
            if not data:
                return {'error': 'Request body is required'}, 400
            
            result = db[data_type].insert_one(data)
            return {'message': 'Data inserted successfully', 'id': str(result.inserted_id)}, 201
        except Exception as e:
            return {'error': str(e)}, 500

    @classmethod
    def init_api(cls, api):
        super().init_api(api)
        cls.ns.expect(api.models['Data'])(cls.post)
        cls.ns.doc(params={'type': 'Collection name'},
                  security=['Bearer Auth', 'System Auth'])(cls.post)
        return cls

class BulkInsert(BaseResource):
    @auth_required
    def post(self):
        try:
            data_type = request.args.get('type')
            if not data_type:
                return {'error': 'Type parameter is required'}, 400
            
            data = request.get_json()
            if not data or not isinstance(data, list):
                return {'error': 'Request body must be an array'}, 400
            
            result = db[data_type].insert_many(data)
            return {
                'message': 'Data inserted successfully',
                'inserted_ids': [str(id) for id in result.inserted_ids]
            }, 201
        except Exception as e:
            return {'error': str(e)}, 500

    @classmethod
    def init_api(cls, api):
        super().init_api(api)
        cls.ns.expect(api.models['BulkData'])(cls.post)
        cls.ns.doc(params={'type': 'Collection name'},
                  security=['Bearer Auth', 'System Auth'])(cls.post)
        return cls 