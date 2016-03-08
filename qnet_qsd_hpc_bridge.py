#!/usr/bin/env python
import os
import pickle
import math
from tempfile import mkdtemp
import logging

import click
from qnet.misc.qsd_codegen import qsd_run_worker
import clusterjob

__version__ = '0.0.1-pre'

BODY_PROPAGATE = r'''
cd $CLUSTERJOB_WORKDIR
source activate qnet
aprun -B qnet_qsd_mpi_wrapper --debug qnet_qsd_kwargs.dump {outfile}
'''

BODY_INI = r'''
[Attributes]
backend = pbspro
rootdir = /work/goerz
workdir = qsd
shell = /bin/bash

[Resources]
time = 00:55:00
queue = debug
-A = XXXXXXXXXXXXX
-j = oe
'''

def make_clusterjob_map(body, inifile, outfile, nodes, ppn):
    """Create a map function suitable to be passed to
    :meth:`qnet.misc.qsd_codegen.run_delayed`
    """
    logger = logging.getLogger(__name__)
    def clusterjob_map(qsd_run_worker, list_of_kwargs):
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
                           +temp_dir+" && ssh rm -f {remote}:{rootdir}/" \
                           +"{workdir}/"+outfile
            job.prologue = prologue
            job.epilogue = epilogue
            job.submit(block=True)
            with open(os.path.join(temp_dir, outfile), 'rb') as in_fh:
                result = pickle.load(in_fh)
            os.unlink(os.path.join(temp_dir, outfile))
            return result
        finally:
            try:
                os.unlink(temp_file)
            except OSError as exc_info:
                logger.warn(str(exc_info))
            try:
                os.rmdir(temp_dir)
            except OSError as exc_info:
                logger.warn(str(exc_info))
    return clusterjob_map


@click.command()
@click.help_option('-h', '--help')
@click.option('--debug', is_flag=True, default=False,
              help="Activate debug logging")
@click.argument('prop_kwargs_list', type=click.File('rb'))
@click.argument('outfile', type=click.File('wb'))
def qnet_qsd_mpi_wrapper(debug, prop_kwargs_list, outfile):
    """Load pickled list of kwargs from PROP_KWARGS_LIST (cf.
    qnet.misc.qsd_codegen.QSDCodeGen.run_delayed). For each kwargs dict,
    propagate a trajectory with the parameters given therein, distributing
    the different trajectories over all available MPI processes. Average over
    all trajectories and write pickled list containing one TrajectoryData
    instance (the total average data) to OUTFILE.

    In order to avoid an MPI deadlock, any errors encountered during the
    propagation are handled internally. If errors occur, only a subset of all
    trajectories may be included in the averaged result, or an empty list may
    be dumped to OUTFILE. Any errors will be logged to stdout.
    """

    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger()
    if debug:
        logger.setLevel(logging.DEBUG)

    list_of_kwargs = pickle.load(prop_kwargs_list)

    from mpi4py import MPI
    comm = MPI.COMM_WORLD

    n_procs = comm.Get_size() # number of MPI processes

    # split jobs into batches
    if comm.Get_rank() == 0 and len(list_of_kwargs) < n_procs:
        logger.warn("There are less tasks than MPI processors. You are "
                    "wasting resources.")
    batches = clusterjob.utils.split_seq(list_of_kwargs, n_procs)

    # each MPI process handles one batch
    i_proc = comm.Get_rank() # the index of the current MPI proc
    logger.debug("This is MPI process %3d/%3d, processing batch of %3d tasks",
                 i_proc+1, n_procs, len(batches[i_proc]))
    try:
        trajs = [qsd_run_worker(kwargs) for kwargs in batches[i_proc]]
    except Exception as exc_info:
        logger.error("ERROR calling qsd_run_worker: %s", str(exc_info))
        trajs = []
    logger.debug("process %3d, finished local propagations", i_proc)
    if len(trajs) > 0:
        # we average all of the trajectories in the batch locally
        combined_traj = trajs[0]
        try:
            combined_traj.extend(*trajs[1:])
        except ValueError as exc_info:
            logger.error("process %3d, local avg: %s", i_proc, str(exc_info))
        logger.debug("process %3d, locally averaged %3d trajectories",
                    i_proc, len(combined_traj.record))
    else:
        logger.error("process %3d: no trajectories", i_proc)
        combined_traj = None

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
            logger.debug("process %3d, round %2d: set to %s",
                         i_proc, k, communication_status)
        if communication_status == 'receive':
            if (i_proc//2**k) % 2 == 1:
                communication_status = 'send'
                logger.debug("process %3d, round %2d: set to %s",
                             i_proc, k, communication_status)
        # send or receive
        if communication_status == 'receive':
            source = i_proc + 2**k
            if source < n_procs: # there is a process with i_proc == source
                logger.debug("process %3d, round %2d: receive from process %3d",
                             i_proc, k, source)
                try:
                    received_traj = comm.recv(source=source, tag=k)
                    if received_traj is None:
                        logger.debug("process %3d, round %2d: received None "
                                     "from process %3d", i_proc, k, source)
                    else:
                        if combined_traj is None:
                            combined_traj = received_traj
                        else:
                            combined_traj.extend(received_traj)
                except ValueError as exc_info:
                    logger.error("process %3d, round %2d: %s",
                                 i_proc, k, str(exc_info))
        elif communication_status == 'send':
            dest = i_proc - 2**k
            if combined_traj is None:
                logger.debug("process %3d, round %2d: send None to process %3d",
                            i_proc, k, dest)
            else:
                logger.debug("process %3d, round %2d: send %3d records to "
                             "process %3d", i_proc, k,
                             len(combined_traj.record), dest)
            comm.send(combined_traj, dest=dest, tag=k)

    if i_proc == 0:
        result = []
        if combined_traj is not None:
            result = [combined_traj, ]
        else:
            logger.error("No trajectory data")
        pickle.dump(result, outfile)

if __name__ == "__main__":
    qnet_qsd_mpi_wrapper()

