"""Public API layer: OAuth and other browser redirects — normalize auth before internal integration."""

import functions_framework

from dispatcher import dispatch


@functions_framework.http
def main(request):
    return dispatch(request)
