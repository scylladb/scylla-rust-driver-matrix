import sys
import argparse
import logging
import os
import subprocess
import re
from datetime import timedelta
from pathlib import Path
from typing import List, Set
import traceback

from run import Run
from email_sender import create_report, get_driver_origin_remote, send_mail

logging.basicConfig(level=logging.INFO)


class EmptyTestResult(Exception):
    pass


def main(arguments: argparse.Namespace):
    status = 0
    results = dict()
    # TODO: move docker configure to rust-driver-matrix-test.jenkinsfile
    # Start docker configure
    # run_command_in_shell(driver_repo_path=arguments.rust_driver_git,
    #                      cmd=f"pip3 install https://github.com/scylladb/scylla-ccm/archive/master.zip")
    # run_command_in_shell(driver_repo_path=arguments.rust_driver_git,
    #                      cmd=f"ln -s /usr/local/bin/ccm /bin/ccm")
    # run_command_in_shell(driver_repo_path=arguments.rust_driver_git,
    #                      cmd=f"ccm create -i {CCM_CLUSTER_IP_PREFIX}. -n {CCM_CLUSTER_NODES} --scylla -v "
    #                          f"{arguments.scylla_version} scylla-cluster")
    # run_command_in_shell(driver_repo_path=arguments.rust_driver_git,
    #                      cmd=f"ccm start")
    # Finish docker configure

    for driver_version in arguments.versions:
        results[driver_version] = dict()
        for test in arguments.tests:
            logging.info('=== RUST DRIVER VERSION %s. TEST: %s ===', driver_version, test)
            runner = Run(rust_driver_git=arguments.rust_driver_git,
                             tag=driver_version,
                             test=test,
                             scylla_version=arguments.scylla_version,
                             test_threads=arguments.test_threads)
            try:
                report = runner.call_test_func()

                if not report:
                    raise EmptyTestResult(f"No result for test '{test}' and driver version {driver_version}")

                logging.info("=== RUST DRIVER MATRIX RESULTS FOR DRIVER VERSION %s ===", driver_version)
                logging.info("\n".join(f"{key}: {value}" for key, value in report.summary.items()))
                if report.is_failed:
                    status = 1
                results[driver_version][test] = report.summary
                results[driver_version][test]['time'] = \
                    str(timedelta(seconds=results[driver_version][test]['testsuite_summary']['time']))[:-3]
            except Exception:
                logging.exception(f"{driver_version} failed")
                status = 1
                exc_type, exc_value, exc_traceback = sys.exc_info()
                failure_reason = traceback.format_exception(exc_type, exc_value, exc_traceback)
                results[driver_version] = dict(exception=failure_reason)
                runner.create_metadata_for_failure(reason="\n".join(failure_reason))

    if arguments.recipients:
        email_report = create_report(results=results)
        email_report['driver_remote'] = get_driver_origin_remote(arguments.rust_driver_git)
        email_report['status'] = "SUCCESS" if status == 0 else "FAILED"
        send_mail(arguments.recipients, email_report)

    quit(status)


def extract_n_latest_repo_tags(repo_directory: str, latest_tags_size: int = 2) -> List[str]:

    selected_tags: dict[tuple[str, str], str] = {}
    ignore_tags: Set[tuple[str, str]] = set()
    result: list[str] = []
    try:
        subprocess.check_output("git checkout .", shell=True, stderr=subprocess.STDOUT, cwd=repo_directory)
        lines = subprocess.check_output("git tag --sort=-creatordate | grep '^v[0-9]*\\.[0-9]*\\.[0-9]*$'",
                                        shell=True,
                                        stderr=subprocess.STDOUT,
                                        cwd=repo_directory).decode().splitlines()
    except subprocess.CalledProcessError as e:
        raise RuntimeError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))

    for repo_tag in lines:
        if "." in repo_tag:
            if not re.match(r'^v[0-9]+\.[0-9]+\.[0-9]+$', repo_tag):
                raise RuntimeError(f'Encountered unknown tag: {repo_tag}')
            (first, second, third) = repo_tag[1:].split(".")
            if first == '0':
                # Handling this case is a bit pedantic on my side. In Rust, if version starts with '0', then
                # the second number describes major version and the third number describes minor version.
                # Patch versions are not present in this case.
                # We don't really need to handle this, since Rust Driver reached 1.0 already, but lets
                # do it just to be safe.
                (major, minor) = ('0.' + second, third)
            else:
                (major, minor) = (first, second)
            if (major, minor) not in ignore_tags:
                ignore_tags.add((major, minor))
                selected_tags[(major, minor)] = repo_tag

    for minor_version in sorted(selected_tags.keys(), reverse=True):
        result.append(selected_tags[minor_version])
        if len(result) == latest_tags_size:
            break

    return result


def get_arguments() -> argparse.Namespace:
    num_cpus = len(os.sched_getaffinity(0))
    default_test_threads = 16 if num_cpus > 16 else None
    versions = ['v0.13.0', 'v0.12.0']
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('rust_driver_git', help='folder with git repository of rust-driver')
    parser.add_argument('--versions', default=versions, nargs='*',
                        help='rust-driver versions to test, default={}'.format(','.join(versions)))
    parser.add_argument('--tests', choices=['rust'], nargs='*', type=str,
                        help='Tests to run. Currently only "rust" supported.')
    parser.add_argument('--scylla-version', help="relocatable scylla version to use",
                        default=os.environ.get('SCYLLA_VERSION', None))
    parser.add_argument('--rust-driver-versions-size', help='The number of the latest versions that will test.'
                                                            'The version is filtered by the major and minor values.'
                                                            'For example, the user selects the 2 latest versions.'
                                                            'The values to be returned are: v0.12.0 and v0.11.1',
                        type=int, default=None, nargs='?')
    parser.add_argument('--recipients', help="whom to send mail at the end of the run",  nargs='+', default=None)
    parser.add_argument('--test-threads', help="How many threads to use for testing. Corresponds to the same flag in `cargo test`."
                                               "If not provided, defaults to None (which means the flag won't be passed to Cargo,"
                                               "unless there are more than 16 CPUs available, in which case it defaults to 16."
                                               "This is to prevent overwhelming Scylla cluster with too many schema changes", type=int, default=default_test_threads)
    arguments = parser.parse_args()
    versions = arguments.versions
    if not isinstance(versions, list):
        versions = versions.split(',')

    arguments.versions = versions
    if arguments.rust_driver_versions_size:
        arguments.versions = extract_n_latest_repo_tags(repo_directory=arguments.rust_driver_git,
                                                        latest_tags_size=arguments.rust_driver_versions_size)

    return arguments


if __name__ == '__main__':
    main(get_arguments())
