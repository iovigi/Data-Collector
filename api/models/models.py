from flask_restx import fields

def init_models(api):
    api.model('Data', {
        'data': fields.Raw(description='JSON data to insert/update')
    })

    api.model('BulkData', {
        'data': fields.List(fields.Raw, description='Array of JSON objects to insert/update')
    })

    api.model('QueryParams', {
        'type': fields.String(required=True, description='Collection name'),
        'field': fields.String(description='Field to filter by'),
        'value': fields.String(description='Value to filter for'),
        'page': fields.Integer(description='Page number', default=1),
        'per_page': fields.Integer(description='Items per page', default=10),
        'order_by': fields.String(description='Field to order results by'),
        'order_direction': fields.String(description='Sort direction (asc or desc)', enum=['asc', 'desc'], default='asc')
    })

    api.model('UpdateParams', {
        'type': fields.String(required=True, description='Collection name'),
        'where_field': fields.String(required=True, description='Field to match for update'),
        'where_value': fields.String(required=True, description='Value to match for update')
    })

    api.model('BulkUpdateParams', {
        'type': fields.String(required=True, description='Collection name'),
        'where_field': fields.String(required=True, description='Field to match for update')
    })

    api.model('BulkUpdate', {
        'where_value': fields.String(required=True, description='Value to match for update'),
        'update': fields.Raw(required=True, description='Data to update')
    })

    api.model('IndexParams', {
        'type': fields.String(required=True, description='Collection name'),
        'field': fields.String(required=True, description='Field to create index on')
    }) 