import functions_framework

from routes.public_api import handle_request


@functions_framework.http
def main(request):
    return handle_request(request)
