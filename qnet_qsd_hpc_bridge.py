#!/usr/bin/env python
import click
import pickle
from qnet.misc.qsd_codegen import qsd_run_worker
from mpi4py import MPI
import math
import clusterjob
import logging

TEMPLATE = r'''
cd $CLUSTERJOB_WORKDIR
source activate qnet
aprun -n 160 qnet_qsd_mpi_wrapper --debug list_of_kwargs.dump
'''

def make_clusterjob_map(inifile, template, compile):
    pass


@click.command()
@click.help_option('-h', '--help')
@click.option('--compile-kwargs', type=click.File('rb'),
              help='Pickled dump of the kwargs dictionary for compilation')
@click.option('--debug', is_flag=True, default=False,
              help="Activate debug logging")
@click.argument('prop_kwargs_list', type=click.File('rb'))
def qnet_qsd_mpi_wrapper(compile_kwargs, debug, prop_kwargs_list):

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger()
    if debug:
        logger.setLevel(logging.DEBUG)

    # TODO: call compilation worker
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
        combined_traj.write('mpi_combined_traj.dat')

if __name__ == "__main__":
    qnet_qsd_mpi_wrapper()

