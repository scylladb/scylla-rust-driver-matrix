import logging
import shutil
from ast import literal_eval
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree


class ProcessJUnit:
    def __init__(self, new_report_xml_path: Path, tests_result_xml: Path, tag: str):
        self.report_path = new_report_xml_path
        self.tests_result_xml = tests_result_xml
        self._summary_keys = {"time": 0.0, "tests": 0, "errors": 0, "skipped": 0, "failures": 0}
        self._summary = {}
        self.tag = tag

    @lru_cache(maxsize=None)
    def _create_report(self):
        if not self.tests_result_xml.is_file():
            raise NotADirectoryError(f"The {self.tests_result_xml} file not exits")

        new_tree = ElementTree.Element("testsuite")
        tree = ElementTree.parse(self.tests_result_xml)
        testsuite_summary_keys = deepcopy(self._summary_keys)
        for testsuite_element in tree.iter("testsuite"):
            testcase_keys = deepcopy(self._summary_keys)
            for key in testcase_keys:
                testcase_keys[key] = literal_eval(testsuite_element.attrib[key].replace(',', '')) \
                    if key in testsuite_element.attrib else 0

            # rust does not report "skipped" in the <testsuite> summary
            if skipped := testsuite_element.iter("skipped"):
                testcase_keys["skipped"] = len([elem.tag for elem in skipped])

            for key in testcase_keys:
                testsuite_summary_keys[key] += testcase_keys[key]

            self._summary[testsuite_element.attrib["name"]] = testcase_keys

        new_tree.attrib["name"] = self.report_path.stem
        new_tree.attrib.update({key: str(value) for key, value in self._summary.items()})
        new_tree.attrib["time"] = f"{testsuite_summary_keys['time']}:.3f"
        logging.info("Creating a new report file in '%s' path", self.report_path)
        self.report_path.parent.mkdir(exist_ok=True)
        with self.report_path.open(mode="w", encoding="utf-8") as file:
            file.write(ElementTree.tostring(element=new_tree, encoding="utf-8").decode())

        self.tests_result_xml.rename(self.report_path.parent / f"TEST-{self.tests_result_xml.name}")

        self._summary['testsuite_summary'] = testsuite_summary_keys

    @property
    def summary(self):
        self._create_report()
        return self._summary

    @property
    def is_failed(self) -> bool:
        return not (sum([test_info["errors"] + test_info["failures"] for test_info in self.summary.values()]) == 0)

    def clear_original_reports(self):
        logging.info("Removing all run's xml files of '%s' version", self.tag)
        shutil.rmtree(self.tests_result_xml)
