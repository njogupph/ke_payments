from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in ke_payments/__init__.py
from ke_payments import __version__ as version

setup(
	name="ke_payments",
	version=version,
	description="MPESA Payment Integrations",
	author="Pointershub",
	author_email="chris@pointershub.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
