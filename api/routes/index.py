from flask import request
from api.utils.db import db
from api.routes.base import BaseResource
from api.auth.decorators import auth_required

class CreateIndex(BaseResource):
    @auth_required
    def post(self):
        try:
            data_type = request.args.get('type')
            field = request.args.get('field')
            
            if not all([data_type, field]):
                return {'error': 'Type and field parameters are required'}, 400
            
            db[data_type].create_index(field)
            return {'message': f'Index created successfully on {field}'}, 201
        except Exception as e:
            return {'error': str(e)}, 500

    @classmethod
    def init_api(cls, api):
        super().init_api(api)
        cls.ns.doc(params={
            'type': 'Collection name',
            'field': 'Field to create index on'
        }, security=['Bearer Auth', 'System Auth'])(cls.post)
        return cls 