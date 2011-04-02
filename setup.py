import distribute_setup
distribute_setup.use_setuptools()

from setuptools import setup

import sys

extra = {}
if sys.version_info >= (3,):
	extra['use_2to3'] = True

setup(
	name='evnet',
	version = '1.0-1',
	description='evnet is a networking library built on top of pyev (libev)',
	author='Mark Schloesser',
	author_email='ms@mwcollect.org',
	license = "MIT/BSD/GPL",
	keywords = "evnet pyev network asynchronous nonblocking event",
	url = "https://github.com/rep/evnet",
	install_requires = ['pyev>=0.5.3-3.8'],
	packages = ['evnet',],
	**extra
)

