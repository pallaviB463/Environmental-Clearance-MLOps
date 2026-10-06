from typing import Any, Dict

from agent.state import ProjectRequest


def get_request_fields(request: ProjectRequest) -> Dict[str, Any]:
    """
    Return the validated request fields in dictionary form.

    This gives the Extractor Agent controlled access to the
    project's structured input.
    """

    return request.model_dump()