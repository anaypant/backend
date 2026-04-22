import logging

import functions_framework

from routes.public_api import handle_request

# Match core: default root level WARNING would drop INFO from route handlers.
logging.getLogger().setLevel(logging.INFO)


@functions_framework.http
def main(request):
    return handle_request(request)
