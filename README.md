# QNET-QSD-HPC-Bridge #

Python module and command line script that serves as a bridge between the QNET
QSD-backend, and a HPC cluster. This allows enables MPI-based parallel
calculation of quantum trajectories.

## Prerequisites and Installation ##

The following instructions target a Cray XE Cluster (specifically
[copper.ors.hpc.mil][Copper]. After logging in to the cluster, go through the
following steps:

*   Install the [Anaconda Python Distribution][Anaconda] in your home directory

*   Create a new conda environment, with some standard prerequisites:

        $ conda create -n qnet pip numpy matplotlib scipy sympy ipython bokeh pytest sphinx nose ply cython click
        $ source activate qnet

*   We will have to install some Python packages manually that include compiled
    code. This will not work using the default compilers on the Cray system. We
    must switch to GNU compilers! E.g.,

        $ module switch PrgEnv-pgi PrgEnv-gnu

*   Install qutip manually in the `qnet` environment

        $ pip install –no-use-wheel qutip

*   Install the latest development version of the [clusterjob][] library (version >=2.0)

        $ git clone https://github.com/goerz/clusterjob.git
        $ cd clusterjob
        $ pip install -e .
        $ cd ..

*   Install [mpi4py][] manually. It is important not to install this from a
    package repository. The package must be compiled for the Cray machine.
    Otherwise, all MPI processes will think they are rank 0.

        $ wget https://bitbucket.org/mpi4py/mpi4py/downloads/mpi4py-1.3.1.tar.gz -O mpi4py-1.3.1.tar.gz
        $ tar -xf mpi4py-1.3.1.tar.gz
        $ cd mpi4py-1.3.1
        $ cat >> mpi.cfg <<EOF
        [cray]
        mpicc = cc
        mpicxx = CC
        extra_link_args = -shared
        EOF
        $ python setup.py build –mpi=cray
        python setup.py install
        $ cd ..

*   Obtain the latest development version of [QNET][] and install it

        $ git clone https://github.com/mabuchilab/QNET.git
        $ cd QNET
        $ pip install –process-dependency-links -e .[simulation,circuit_visualization,dev]
        $ cd ..

*   Finally, install the `qnet_qsd_hpc_bridge`

        $ git clone https://github.com/mabuchilab/qnet_qsd_hpc_bridge.git
        $ cd qnet_qsd_hpc_bridge
        $ pip install -e .
        $ cd ..

[Copper]: http://www.ors.hpc.mil/docs/copperUserGuide.html
[Anaconda]: https://www.continuum.io/downloads
[QNET]: https://github.com/mabuchilab/QNET
[clusterjob]: https://clusterjob.readthedocs.org/en/latest/
[mpi4py]: https://mpi4py.readthedocs.org/en/stable/
