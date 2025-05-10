from functools import wraps
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from flask import request, jsonify
import os

def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Check for system header authentication
        system_auth_header = request.headers.get('X-System-Auth')
        if system_auth_header and system_auth_header == os.getenv('SYSTEM_AUTH_KEY'):
            return fn(*args, **kwargs)
            
        # If system auth fails, try JWT authentication
        try:
            verify_jwt_in_request()
            current_user = get_jwt_identity()
            return fn(*args, **kwargs)
        except Exception as e:
            return {'error': 'Authentication failed'}, 401
            
    return wrapper

def jwt_required_with_role(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        current_user = get_jwt_identity()
        # You can add additional role checks here if needed
        return fn(*args, **kwargs)
    return wrapper 