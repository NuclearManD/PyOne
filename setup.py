import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="nuclaer-pyone",
    version="0.0.1",
    author="Dylan Brophy",
    author_email="dylanbrophy@gmail.com",
    description="Decentralized data storage framework",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/NuclearManD/PyOne",
    packages=setuptools.find_packages(),
    install_requires=[
          'ecdsa'
      ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
)
