# encoding: utf-8
from __future__ import annotations

import click

import ckan.lib.jobs as bg_jobs
import ckan.logic as logic
from ckan.cli import error_shout


@click.group(name=u"jobs", short_help=u"Manage background jobs.")
def jobs():
    pass


@jobs.command(short_help=u"Start a worker.",)
@click.option(u"--burst", is_flag=True, help=u"Start worker in burst mode.")
@click.option(u"--max-idle-time", default=None, type=click.INT,
              help=u"Max seconds for worker to be idle. "
              "Defaults to None (never stops idling).")
@click.option("--no-scheduler", is_flag=True,
              help="Do not enqueue scheduled jobs from this worker.")
@click.argument(u"queues", nargs=-1)
def worker(burst: bool, max_idle_time: int, queues: list[str], no_scheduler: bool):
    """Start a worker that fetches jobs from queues and executes them. If
    no queue names are given then the worker listens to the default
    queue, this is equivalent to

        ckan jobs worker default

    If queue names are given then the worker listens to those queues
    and only those:

        ckan jobs worker my-custom-queue

    Hence, if you want the worker to listen to the default queue and
    some others then you must list the default queue explicitly:

        ckan jobs worker default my-custom-queue

    If the `--burst` option is given then the worker will exit as soon
    as all its queues are empty.

    If the `--max-idle-time` option is given then the worker will exit
    after it has been idle for the number of seconds specified.

    If the `--no-scheduler` option is given then this worker will
    not enqueue scheduled jobs. Only one worker will can run as a
    scheduler for each queue so this option may be used on secondary
    workers.
    """
    bg_jobs.Worker(queues).work(
        burst=burst,
        max_idle_time=max_idle_time,
        with_scheduler=not no_scheduler,
    )


@jobs.command(name=u"list", short_help=u"List jobs.")
@click.option("-l", "--limit", type=click.INT,
              help="Number of jobs to return. Default: %s" %
              bg_jobs.DEFAULT_JOB_LIST_LIMIT,
              default=bg_jobs.DEFAULT_JOB_LIST_LIMIT)
@click.option("-i", "--ids", is_flag=True, type=click.BOOL,
              help="Only return a list of job ids.", default=False)
@click.argument(u"queues", nargs=-1)
def list_jobs(queues: list[str],
              limit: int = bg_jobs.DEFAULT_JOB_LIST_LIMIT, ids: bool = False):
    """List currently enqueued jobs from the given queues. If no queue
    names are given then the jobs from all queues are listed.
    """
    data_dict = {
        u"queues": list(queues),
        "limit": limit,
        "ids_only": ids,
    }
    jobs = logic.get_action(u"job_list")({u"ignore_auth": True}, data_dict)
    if not jobs:
        return click.secho(u"There are no pending jobs.", fg=u"green")
    for job in jobs:
        if ids:
            click.secho(job)
        else:
            if job[u"title"] is None:
                job[u"title"] = u""
            else:
                job[u"title"] = u'"{}"'.format(job[u"title"])
            click.secho(u"{created} {id} {queue} {title}".format(**job))


@jobs.command(short_help=u"Show details about a specific job.")
@click.argument(u"id")
def show(id: str):
    try:
        job = logic.get_action(u"job_show")(
            {u"ignore_auth": True}, {u"id": id}
        )
    except logic.NotFound:
        error_shout(u'There is no job with ID "{}"'.format(id))
        raise click.Abort()

    click.secho(u"ID:      {}".format(job[u"id"]))
    if job[u"title"] is None:
        title = u"None"
    else:
        title = u'"{}"'.format(job[u"title"])
    click.secho(u"Title:   {}".format(title))
    click.secho(u"Created: {}".format(job[u"created"]))
    click.secho(u"Queue:   {}".format(job[u"queue"]))


@jobs.command(short_help=u"Cancel a specific job.")
@click.argument(u"id")
def cancel(id: str):
    """Cancel a specific job. Jobs can only be canceled while they are
    enqueued. Once a worker has started executing a job it cannot be
    aborted anymore.

    """
    try:
        logic.get_action(u"job_cancel")(
            {u"ignore_auth": True}, {u"id": id}
        )
    except logic.NotFound:
        error_shout(u'There is no job with ID "{}"'.format(id))
        raise click.Abort()

    click.secho(u"Cancelled job {}".format(id), fg=u"green")


@jobs.command(short_help=u"Cancel all jobs.")
@click.argument(u"queues", nargs=-1)
def clear(queues: list[str]):
    """Cancel all jobs on the given queues. If no queue names are given
    then ALL queues are cleared.

    """
    data_dict = {
        u"queues": list(queues),
    }
    queues = logic.get_action(u"job_clear")(
        {u"ignore_auth": True}, data_dict
    )
    queues = [u'"{}"'.format(q) for q in queues]
    click.secho(u"Cleared queue(s) {}".format(u", ".join(queues)), fg=u"green")


@jobs.command(short_help=u"Enqueue a test job.")
@click.argument(u"queues", nargs=-1)
def test(queues: list[str]):
    """Enqueue a test job. If no queue names are given then the job is
    added to the default queue. If queue names are given then a
    separate test job is added to each of the queues.

    """
    for queue in queues or [bg_jobs.DEFAULT_QUEUE_NAME]:
        job = bg_jobs.enqueue(
            bg_jobs.test_job, [u"A test job"], title=u"A test job", queue=queue
        )
        click.secho(
            u'Added test job {} to queue "{}"'.format(job.id, queue),
            fg=u"green",
        )
