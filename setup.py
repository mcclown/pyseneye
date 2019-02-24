from __future__ import print_function
from setuptools import setup, find_packages, Command
from setuptools.command.test import test as TestCommand
import io
import codecs
import os
import sys

import pyseneye

here = os.path.abspath(os.path.dirname(__file__))

def read(*filenames, **kwargs):
    encoding = kwargs.get('encoding', 'utf-8')
    sep = kwargs.get('sep', '\n')
    buf = []
    for filename in filenames:
        with io.open(filename, encoding=encoding) as f:
            buf.append(f.read())
    return sep.join(buf)


# Convert README.md with pandoc
long_description = read('README.rst')

class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = ["-rs", "--cov=pyseneye", "--cov-report=term-missing"]
        self.test_suite = True

    def run_tests(self):
        import pytest
        errcode = pytest.main(self.test_args)
        sys.exit(errcode)
        

class CleanCommand(Command):
    """Custom clean command to tidy up the project root."""
    user_options = []
    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def run(self):
        os.system('rm -vrf ./build ./dist ./*.pyc ./*.tgz ./*.egg-info')


setup(
    name='pyseneye',
    version=pyseneye._VERSION_,
    url='http://github.com/mcclown/pyseneye/',
    license='Apache Software License',
    author='Stephen Mc Gowan',
    tests_require=['pytest'],
    install_requires=['pyusb>=1.0.2'],
    cmdclass={'test': PyTest, 'clean': CleanCommand},
    author_email='mcclown@gmail.com',
    description='A module for interacting with the Seneye range or aquarium and pond sensors',
    long_description=long_description,
    packages=['pyseneye'],
    include_package_data=True,
    platforms='any',
    classifiers = [
        'Programming Language :: Python',
        'Development Status :: 3 - Alpha',
        'Natural Language :: English',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Home Automation',
        'Topic :: System :: Hardware',
        ],
    extras_require={
        'testing': ['pytest'],
    }
)

