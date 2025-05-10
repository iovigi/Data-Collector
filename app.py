from flask import Flask
from flask_cors import CORS
from flask_restx import Api
from flask_jwt_extended import JWTManager
from api.models.models import init_models
from api.models.user_model import init_login_model
from api.utils.seeder import seed_users
import os
from datetime import timedelta

def create_app():
    app = Flask(__name__)
    CORS(app)

    # JWT Configuration
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'your-secret-key')  # Change this in production
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
    jwt = JWTManager(app)

    # Define auth schemes for Swagger
    authorizations = {
        'Bearer Auth': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': "Type in the *'Value'* input box below: **'Bearer &lt;JWT&gt;'**, where JWT is the token"
        },
        'System Auth': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'X-System-Auth',
            'description': "Type in the *'Value'* input box below: **'your-system-auth-key'**"
        }
    }

    # Initialize Swagger documentation
    api = Api(app, version='1.0', title='Data Collector API',
              description='A Flask-based REST API for collecting and managing data with MongoDB',
              authorizations=authorizations,
              security=['Bearer Auth', 'System Auth'])

    # Initialize models
    init_models(api)
    init_login_model(api)

    # Create namespace
    ns = api.namespace('api', description='Data collection operations')

    # Import routes
    from api.routes.insert import Insert, BulkInsert
    from api.routes.query import Query
    from api.routes.update import Update, BulkUpdate
    from api.routes.delete import Delete
    from api.routes.index import CreateIndex
    from api.routes.auth import Login

    # Initialize API for all resources
    Insert.init_api(api)
    BulkInsert.init_api(api)
    Query.init_api(api)
    Update.init_api(api)
    BulkUpdate.init_api(api)
    Delete.init_api(api)
    CreateIndex.init_api(api)
    Login.init_api(api)

    # Add resources to namespace
    ns.add_resource(Insert, '/insert')
    ns.add_resource(BulkInsert, '/bulk_insert')
    ns.add_resource(Query, '/query')
    ns.add_resource(Update, '/update')
    ns.add_resource(BulkUpdate, '/bulk_update')
    ns.add_resource(Delete, '/delete')
    ns.add_resource(CreateIndex, '/create_index')
    ns.add_resource(Login, '/login')

    # Seed initial users
    seed_users()

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000) 