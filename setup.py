"""
Setup configuration for workflows-cdk package.
"""

from setuptools import find_packages, setup


setup(
    name="workflows_cdk",
    version="0.1.0",
    description="A CDK for developing Stacksync Workflows Connectors",
    author="Stacksync",
    author_email="oliviero@stacksync.com",
    install_requires=[
        # Core dependencies
        "flask",
        "werkzeug==2.2",
        "pyopenssl==24.1.0",
        "flask-cors>=4.0.0",
        "python-dotenv>=1.0.0",
        "gunicorn==22.0.0",
        "sentry-sdk[Flask]",
        "pydantic>=2.0.0",
        "pyyaml>=6.0.0"
    ],
    python_requires=">=3.10",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
)
