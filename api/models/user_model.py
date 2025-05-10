from flask_restx import fields

def init_login_model(api):
    return api.model('Login', {
        'username': fields.String(required=True, description='Username'),
        'password': fields.String(required=True, description='Password')
    }) 