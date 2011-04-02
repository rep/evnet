import distribute_setup
distribute_setup.use_setuptools()

from setuptools import setup

import sys, os

def read_file(name):
	return open(os.path.join(os.path.dirname(__file__),name)).read()

extra = {}
if sys.version_info >= (3,):
	extra['use_2to3'] = True

readme = read_file('README.md')

setup(
	name='evnet',
	version = '1.0-4',
	description='evnet is a networking library built on top of pyev (libev)',
	long_description=readme,
	classifiers=['Development Status :: 4 - Beta','License :: OSI Approved :: MIT License','Programming Language :: Python','Topic :: Software Development :: Libraries :: Python Modules'], # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
	author='Mark Schloesser',
	author_email='ms@mwcollect.org',
	license = "MIT/BSD/GPL",
	keywords = "evnet pyev network asynchronous nonblocking event",
	url = "https://github.com/rep/evnet",
	install_requires = ['pyev>=0.5.3-3.8'],
	packages = ['evnet',],
	**extra
)

