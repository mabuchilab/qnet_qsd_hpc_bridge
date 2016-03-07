#!/usr/bin/env python
import setuptools


def get_version(filename):
    with open(filename) as in_fh:
        for line in in_fh:
            if line.startswith('__version__'):
                return line.split('=')[1].strip()[1:-1]
    raise ValueError("Cannot extract version from %s" % filename)


setuptools.setup(
    name="qnet_qsd_hpc_bridge",
    version=get_version("qnet_qsd_hpc_bridge.py"),
    url="https://github.com/mabuchilab/qnet_qsd_hpc_bridge",
    author="Michael Goerz",
    author_email="goerz@stanford.edu",
    description="Bridge between the QNET-QSD backend and an HPC cluster",
    install_requires=[
        'Click>=5', 'mpi4py', 'qnet', 'clusterjob'
    ],
    extras_require={'dev': ['pytest', 'coverage', 'pytest-cov']},
    py_modules=['qnet_qsd_hpc_bridge'],
    entry_points='''
        [console_scripts]
        qnet_qsd_mpi_wrapper=qnet_qsd_hpc_bridge:qnet_qsd_mpi_wrapper
    ''',
    classifiers=[
        'Environment :: Console',
        'Natural Language :: English',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
    ],
)
