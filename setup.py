import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pysqueezebox",
    version="0.1",
    license="apache-2.0",
    author="Raj Laud",
    author_email="raj.laud@gmail.com",
    description="Asynchronous library to control Logitech Media Server",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/rajlaud/pysqueezebox",
    packages=setuptools.find_packages(),
    python_requires='>=3.6',
    classifiers=[
        "License :: OSI Approved :: Apache 2.0 License",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)
