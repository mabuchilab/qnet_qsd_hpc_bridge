#!/usr/bin/env python
import os
import pickle
import math
from textwrap import dedent
from tempfile import mkdtemp
import logging

import click
from mpi4py import MPI
from qnet.misc.qsd_codegen import qsd_run_worker, compilation_worker
import clusterjob

__version__ = '0.0.1-pre'

BODY_PROPAGATE = r'''
cd $CLUSTERJOB_WORKDIR
source activate qnet
aprun -B qnet_qsd_mpi_wrapper --debug qnet_qsd_kwargs.dump {outfile}
'''

BODY_INI = r'''
[Attributes]
remote = copper
rootdir = $WORKDIR
workdir = qsd
shell = /bin/bash
ssh = /usr/local/ossh/bin/ssh
scp = /usr/local/ossh/bin/scp

[Resources]
queue = standard
-A = XXXXXXXXXXXXX
-j = oe
'''

def make_clusterjob_map(body, inifile, outfile, nodes, ppn):
    """Create a map function suitable to be passed to
    :meth:`qnet.misc.qsd_codegen.run_delayed`
    """
    def clusterjob_map(qsd_run_worker, list_of_kwargs)
        job = clusterjob.JobScript(body, jobname='qnet_qsd')
        job.read_settings(inifile)
        job.resources['nodes'] = nodes
        job.resources['ppn'] = ppn
        job.resources['threads'] = 1
        job.outfile = outfile
        temp_dir = mkdtemp()
        temp_file = os.path.join(temp_dir, 'qnet_qsd_kwargs.dump')
        try:
            with open(temp_file, 'wb') as out_fh:
                pickle.dump(list_of_kwargs, out_fh)
            if job.remote is None:
                prologue = 'cp '+temp_file+' {rootdir}/{workdir}/'
                epilogue = 'mv {rootdir}/{workdir}/'+outfile+" "+temp_dir
            else:
                prologue = 'scp '+temp_file+' {remote}:{rootdir}/{workdir}/'
                epilogue = 'scp {remote}:{rootdir}/{workdir}/'+outfile+" "\
                           +temp_dir+" && ssh rm -f {remote}:{rootdir}/"
                           +"{workdir}/"+outfile
            job.prologue = prologue
            job.epilogue = epilogue
            job.submit(block=True)
            with open(os.path.join(temp_dir, outfile), 'rb') as in_fh:
                return pickle.load(in_fh)
            os.unlink(os.path.join(temp_dir, outfile)
        finally:
            os.unlink(temp_file)
            os.rmdir(temp_dir)



def make_apply_compile():
    def remote_apply(compilation_worker, kwargs):
        #prop_kwargs = pickle.load(compile_kwargs)
        compilation_worker(kwargs)


@click.command()
@click.help_option('-h', '--help')
@click.option('--compile-kwargs', type=click.File('rb'),
              help='Pickled dump of the kwargs dictionary for compilation')
@click.option('--debug', is_flag=True, default=False,
              help="Activate debug logging")
@click.argument('prop_kwargs_list', type=click.File('rb'))
@click.argument('outfile', type=click.File('wb'))
def qnet_qsd_mpi_wrapper(compile_kwargs, debug, prop_kwargs_list, outfile):

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger()
    if debug:
        logger.setLevel(logging.DEBUG)

    if compile_kwargs is not None:

    list_of_kwargs = pickle.load(prop_kwargs_list)

    comm = MPI.COMM_WORLD

    n_procs = comm.Get_size() # number of MPI processes

    # split jobs into batches
    batches = clusterjob.utils.split_seq(list_of_kwargs, n_procs)

    # each MPI process handles one batch
    i_proc = comm.Get_rank() # the index of the current MPI proc
    logger.debug("This is MPI process %d/%d, processing batch of %d tasks",
                 i_proc+1, n_procs, len(batches[i_proc]))
    trajs = [qsd_run_worker(kwargs) for kwargs in batches[i_proc]]
    logger.debug("process %d, finished local propagations", i_proc)
    # we average all of the trajectories in the batch locally
    combined_traj = trajs[0]
    try:
        combined_traj.extend(*trajs[1:])
    except ValueError as exc_info:
        logger.error("process %d, local avg: %s", i_proc, str(exc_info))
    logger.debug("process %d, locally averaged %d trajectories",
                 i_proc, len(combined_traj.record))

    # run through a binary tree communication protocol to average the data
    # from all MPI processes into proccess ID 0. The procedure looks as
    # follows:
    #
    #     i_proc:  0 1 2 3 4 5   n_procs = 6 => n_rounds = 3
    #              -----------
    #     k = 0    r s r s r s   r: receive, s: send (to receiver on the left)
    #     k = 1    r   s  (r)    (r): cannot receive, since no sender
    #     k = 2    r       s
    #
    communication_status = 'receive'
    n_rounds = math.ceil(math.log(n_procs, 2))
    for k in range(n_rounds): # 0 .. n_rounds-1
        # update communication status
        if communication_status == 'send':
            communication_status = 'inactive'
            logger.debug("process %d, round %d: set to %s",
                         i_proc, k, communication_status)
        if communication_status == 'receive':
            if (i_proc//2**k) % 2 == 1:
                communication_status = 'send'
                logger.debug("process %d, round %d: set to %s",
                             i_proc, k, communication_status)
        # send or receive
        if communication_status == 'receive':
            source = i_proc + 2**k
            if source < n_procs: # there is a process with i_proc == source
                logger.debug("process %d, round %d: receive from process %d",
                             i_proc, k, source)
                try:
                    combined_traj.extend(comm.recv(source=source, tag=k))
                except ValueError as exc_info:
                    logger.error("process %d, round %d: %s",
                                 i_proc, k, str(exc_info))
        elif communication_status == 'send':
            dest = i_proc - 2**k
            logger.debug("process %d, round %d: send %d records to process %d",
                         i_proc, k, len(combined_traj.record), dest)
            comm.send(combined_traj, dest=dest, tag=k)

    if i_proc == 0:
        pickle.dump(list_of_kwargs, outfile)

if __name__ == "__main__":
    qnet_qsd_mpi_wrapper()

