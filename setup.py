import setuptools

with open("README.md") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pysqueezebox",
    version="0.4.0",
    license="apache-2.0",
    author="Raj Laud",
    author_email="raj.laud@gmail.com",
    description="Asynchronous library to control Logitech Media Server",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/rajlaud/pysqueezebox",
    packages=setuptools.find_packages(),
    python_requires=">=3.6",
)
