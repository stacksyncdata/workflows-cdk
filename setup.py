from setuptools import find_packages, setup

with open("README.md", "r") as f:
    long_description = f.read()


setup(
    name="workflows-cdk",
    version="0.0.1",
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
    packages=find_packages(include=["workflows_cdk", "workflows_cdk.*"]),
    install_requires=[
        "flask>=2.0.0",
        "pydantic>=2.0.0",
        "typing-extensions>=4.0.0",
        "python-dotenv>=0.19.0",
        "gunicorn>=20.1.0",
        "requests>=2.26.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=2.12.0",
            "black>=22.0.0",
            "isort>=5.0.0",
            "mypy>=0.900",
            "flake8>=4.0.0",
            "twine>=4.0.2",
        ],
        "docs": [
            "sphinx>=4.0.0",
            "sphinx-rtd-theme>=1.0.0",
        ],
    },
    python_requires=">=3.7",
    project_urls={
        "Bug Reports": "https://github.com/stacksync/workflows-cdk/issues",
        "Source": "https://github.com/stacksync/workflows-cdk",
        "Documentation": "https://workflows-cdk.readthedocs.io/",
    },
)
