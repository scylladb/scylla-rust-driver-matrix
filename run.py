import logging
import os
import re
import shutil
import subprocess
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Dict, List

import yaml
from packaging.version import Version, InvalidVersion

from cluster import TestCluster
from common import scylla_uri_per_node, run_command_in_shell
from processjunit import ProcessJUnit


class Run:
    def __init__(self, rust_driver_git, tag, test, scylla_version):
        self.driver_version = tag.split("-", maxsplit=1)[0]
        self._full_driver_version = tag
        self._rust_driver_git = rust_driver_git
        self._scylla_version = scylla_version
        self._tests = test
        self._venv_path = Path(self._rust_driver_git) / "venv" / self.driver_version
        self.call_test_func = self.__getattribute__(f"run_{test}")
        if not self.call_test_func:
            raise RuntimeError(f"Not supported test: {test}")

    @cached_property
    def version_folder(self) -> Path:
        version_pattern = re.compile(r"(\d+.)+\d+$")
        target_version_folder = Path(os.path.dirname(__file__)) / "versions"
        try:
            target_version = Version(self.driver_version)
        except InvalidVersion:
            target_dir = target_version_folder / self.driver_version
            if target_dir.is_dir():
                return target_dir
            return target_version_folder / "master"

        tags_defined = sorted(
            (
                Version(folder_path.name)
                for folder_path in target_version_folder.iterdir() if version_pattern.match(folder_path.name)
            ),
            reverse=True
        )
        for tag in tags_defined:
            if tag <= target_version:
                return target_version_folder / str(tag)
        else:
            raise ValueError("Not found directory for rust-driver version '%s'", self.driver_version)

    @cached_property
    def ignore_tests(self) -> Dict[str, List[str]]:
        ignore_file = self.version_folder / "ignore.yaml"
        if not ignore_file.exists():
            logging.info("Cannot find ignore file for version '%s'", self.driver_version)
            return {}

        with ignore_file.open(mode="r", encoding="utf-8") as file:
            content = yaml.safe_load(file)
        ignore_tests = content.get("tests", []) or {}
        if not ignore_tests.get("ignore", None):
            logging.info("The file '%s' for version tag '%s' doesn't contains any test to ignore for protocol",
                         ignore_file, self.driver_version)
        return ignore_tests

    @cached_property
    def environment(self) -> Dict:
        result = {}
        result.update(os.environ)
        result["SCYLLA_VERSION"] = self._scylla_version
        return result

    def _run_command_in_shell(self, cmd: str):
        logging.debug("Execute the cmd '%s'", cmd)
        with subprocess.Popen(cmd, shell=True, executable="/bin/bash", env=self.environment,
                              cwd=self._rust_driver_git, stderr=subprocess.PIPE) as proc:
            stderr = proc.communicate()
            status_code = proc.returncode
        assert status_code == 0, stderr

    def _apply_patch_files(self) -> bool:
        for file_path in self.version_folder.iterdir():
            if file_path.name.startswith("patch"):
                try:
                    logging.info("Show patch's statistics for file '%s'", file_path)
                    self._run_command_in_shell(f"git apply --stat {file_path}")
                    logging.info("Detect patch's errors for file '%s'", file_path)
                    try:
                        self._run_command_in_shell(f"git apply --check {file_path}")
                    except AssertionError as exc:
                        if 'tests/integration/conftest.py' in str(exc):
                            self._run_command_in_shell(f"rm tests/integration/conftest.py")
                        else:
                            raise
                    logging.info("Applying patch file '%s'", file_path)
                    self._run_command_in_shell(f"patch -p1 -i {file_path}")
                except Exception:
                    logging.exception("Failed to apply patch '%s' to version '%s'",
                                      file_path, self.driver_version)
                    raise
        return True

    @lru_cache(maxsize=None)
    def _create_venv(self):
        basic_packages = ("pytest",
                          "https://github.com/scylladb/scylla-ccm/archive/master.zip",
                          "pytest-subtests")
        if self._venv_path.exists() and self._venv_path.is_dir():
            logging.info("Removing old rust venv in directory '%s'", self._venv_path)
            shutil.rmtree(self._venv_path)

        logging.info("Creating a new rust venv in directory '%s'", self._venv_path)
        self._venv_path.mkdir(parents=True)
        self._run_command_in_shell(cmd=f"python3 -m venv {self._venv_path}")
        logging.info("Upgrading 'pip' and 'setuptools' packages to the latest version")
        self._run_command_in_shell(cmd=f"{self._activate_venv_cmd()} && pip install --upgrade pip setuptools")
        logging.info("Installing the following packages:\n%s", "\n".join(basic_packages))
        self._run_command_in_shell(cmd=f"{self._activate_venv_cmd()} && pip install {' '.join(basic_packages)}")

    @lru_cache(maxsize=None)
    def _activate_venv_cmd(self):
        return f"source {self._venv_path}/bin/activate"

    @lru_cache(maxsize=None)
    def _install_python_requirements(self):
        if os.environ.get("DEV_MODE", False) and self._venv_path.exists() and self._venv_path.is_dir():
            return True
        try:
            self._create_venv()
            for requirement_file in ["requirements.txt", "test-requirements.txt"]:
                if os.path.exists(requirement_file):
                    self._run_command_in_shell(f"{self._activate_venv_cmd()} && "
                                               f"pip install --force-reinstall -r {requirement_file}")
            return True
        except Exception as exc:
            logging.error("Failed to install python requirements for version %s, with: %s",
                          self.driver_version, str(exc))
            return False

    def _checkout_branch(self):
        try:
            self._run_command_in_shell("git checkout .")
            logging.info("git checkout to '%s' tag branch", self._full_driver_version)
            self._run_command_in_shell(f"git checkout {self._full_driver_version}")
            return True
        except Exception as exc:
            logging.error("Failed to branch for version '%s', with: '%s'", self.driver_version, str(exc))
            return False

    def run_rust(self):
        with TestCluster(Path(self._rust_driver_git), self._scylla_version, nodes=3) as cluster:
            cluster.start()
            cluster_nodes_ip = cluster.nodes_addresses()
            run_command_in_shell(driver_repo_path=self._rust_driver_git,
                                 cmd=f"cd {self._rust_driver_git}; cargo build --verbose --examples")
            test_command = f"{scylla_uri_per_node(nodes_ips=cluster_nodes_ip)} " \
                           "cargo test --verbose -- -Z unstable-options --format json --report-time | " \
                           f"tee rust_results_{self._full_driver_version}.jsocat rust_results_{self._full_driver_version}.json | " \
                           f"/usr/local/cargo/bin/cargo2junit > rust_results_{self._full_driver_version}.xml"
            logging.info("Test command: %s", test_command)
            return self.run(test_command=test_command, test_result_file_pref="rust_results")

    def run(self, test_command: str, test_result_file_pref: str) -> ProcessJUnit | None:
        report = None
        test_results_dir = Path(os.path.dirname(__file__)) / "test_results"
        argus_test_results_dir = Path(os.path.dirname(__file__)) / "argus_test_results"

        logging.info("Changing the current working directory to the '%s' path", self._rust_driver_git)
        os.chdir(self._rust_driver_git)
        if self._checkout_branch():
            logging.info("Run test command: %s", test_command)
            subprocess.call(test_command, shell=True, executable="/bin/bash",
                            env=self.environment, cwd=self._rust_driver_git)
            logging.info("Finish test command: %s", test_command)

            logging.info("Start Copy test result files")
            self.copy_test_results(copy_from_dir=Path(self._rust_driver_git),
                                   copy_to_dir=test_results_dir,
                                   test_result_file_pref=f"{test_result_file_pref}_{self._full_driver_version}",
                                   move=True)
            logging.info("Finish Copy test result files")

            report = ProcessJUnit(
                new_report_xml_path=test_results_dir / f"TEST-{self._tests}-{self._full_driver_version}-"
                                                                                  "summary.xml"
                , tests_result_xml=test_results_dir / f"{test_result_file_pref}_{self._full_driver_version}.xml"
                , tag=self._full_driver_version)

            report.update_testcase_classname_with_tag()

            # Copy test results exclude summary files, as Argus can not parse them
            logging.info("Start Copy test result files for Argus")
            self.copy_test_results(copy_from_dir=test_results_dir,
                                   copy_to_dir=argus_test_results_dir,
                                   test_result_file_pref=f"{test_result_file_pref}_{self._full_driver_version}",
                                   move=False)
            logging.info("Finish Copy test result files for Argus")
        return report

    @staticmethod
    def copy_test_results(copy_from_dir: Path, copy_to_dir: Path, test_result_file_pref: str, move: bool):
        if not (test_result_files := Path(copy_from_dir).glob(f'{test_result_file_pref}*')):
            raise FileNotFoundError(f"Test results files with name like '{test_result_file_pref}' are not found under {copy_from_dir}")

        copy_to_dir.mkdir(parents=True, exist_ok=True)
        for elem in test_result_files:
            if elem.is_file() and elem.name.startswith(test_result_file_pref):
                source_file = copy_from_dir / elem.name
                destination_file = copy_to_dir / elem.name
                logging.info("Move from %s to %s", source_file, destination_file)
                if move:
                    shutil.move(source_file, destination_file)
                else:
                    shutil.copy(source_file, destination_file)
