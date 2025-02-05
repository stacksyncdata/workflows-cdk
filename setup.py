"""
Setup configuration for workflows-cdk package.
"""

from setuptools import find_packages, setup

with open("README.md", "r") as f:
    long_description = f.read()


setup(
    name="workflows_cdk",
    version="0.1.0",
    description="A CDK for developing Stacksync Workflows Connectors",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Stacksync",
    author_email="oliviero@stacksync.com",
    license="Stacksync Connector License",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: Stacksync Connector License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    packages=find_packages(),
    install_requires=[
        # Core dependencies
        "flask>=2.0.3,<3.0.0",
        "werkzeug>=2.2.0,<3.0.0",
        "gunicorn>=22.0.0,<23.0.0",
        "flask-cors>=4.0.0",
        
        # Security
        "pyopenssl>=24.0.0",
        
        # Error tracking
        "sentry-sdk[flask]>=1.26.0",
        
        # Utilities
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "black>=23.0.0",
            "isort>=5.0.0",
            "mypy>=1.0.0",
            "flake8>=6.0.0",
        ],
        "docs": [
            "sphinx>=4.0.0",
            "sphinx-rtd-theme>=1.0.0",
        ],
    },
    python_requires=">=3.8",
    project_urls={
        "Bug Reports": "https://github.com/stacksync/workflows-cdk/issues",
        "Source": "https://github.com/stacksync/workflows-cdk",
        "Documentation": "https://workflows-cdk.readthedocs.io/",
    },
)
