from flask_restx import Resource

class BaseResource(Resource):
    def __init__(self, api=None):
        super().__init__()
        self.api = api

    @property
    def ns(self):
        if self.api and self.api.namespaces:
            return self.api.namespaces[0]
        return None

    @classmethod
    def init_api(cls, api):
        """Initialize the API for this resource class"""
        cls.api = api
        cls.ns = api.namespaces[0]
        return cls

    def get_model(self, model_name):
        if self.api and self.api.models:
            return self.api.models.get(model_name)
        return None 