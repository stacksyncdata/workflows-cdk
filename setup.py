"""
Setup configuration for workflows-cdk package.
"""

from setuptools import find_packages, setup


setup(
    name="workflows_cdk",
    version="0.0.1",
    description="A CDK for developing Stacksync Workflows Connectors",
    author="Stacksync",
    author_email="oliviero@stacksync.com",
    packages=find_packages(),
    install_requires=[
        # Core dependencies
        "flask==2.0.3",
        "werkzeug==2.2",
        "pyopenssl==24.1.0",
        "flask-cors>=4.0.0",
        "python-dotenv>=1.0.0",
        "gunicorn==22.0.0",
        "authlib==1.1.0",
        "sentry-sdk[Flask]==1.26.0"
    ],
    python_requires=">=3.1"
)
