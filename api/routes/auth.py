from flask_restx import Resource
from flask import request
from flask_jwt_extended import create_access_token
import bcrypt
from api.database import get_db
from api.routes.base import BaseResource

class Login(BaseResource):
    @classmethod
    def init_api(cls, api):
        super().init_api(api)
        cls.ns.expect(api.models['Login'])(cls.post)
        return cls

    def post(self):
        """Login and receive JWT token"""
        data = request.get_json()
        db = get_db()
        
        user = db.users.find_one({'username': data['username']})
        if not user:
            return {'message': 'User not found'}, 404
            
        # Check password
        if bcrypt.checkpw(data['password'].encode('utf-8'), user['password'].encode('utf-8')):
            access_token = create_access_token(identity=data['username'])
            return {'access_token': access_token}, 200
        
        return {'message': 'Invalid credentials'}, 401 