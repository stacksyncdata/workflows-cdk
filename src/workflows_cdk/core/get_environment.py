import os


def get_environment():
    """
    Get the environment from the environment variable.
    """
    prod_names = ["prod", "production"]
    stage_names = ["stage", "staging"]
    environment = os.getenv("ENVIRONMENT", "").lower()
    if environment in prod_names:
        return "prod"
    elif environment in stage_names:
        return "stage"
    else:
        return "dev"
