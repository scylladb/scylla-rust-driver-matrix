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

        self._summary['testsuite_summary'] = testsuite_summary_keys

    def update_testcase_classname_with_tag(self):
        logging.info("Update testcase classname with driver version in '%s'", self.tests_result_xml.name)
        with self.tests_result_xml.open(mode="r", encoding="utf-8") as file:
            xml_text = file.readlines()

        updated_text = []
        for line in xml_text:
            updated_text.append(line.replace('classname="', f'classname="{self.tag}.'))

        with self.tests_result_xml.open(mode="w", encoding="utf-8") as file:
            file.write("".join(updated_text))

    @property
    def summary(self):
        if not self._summary:
            self._create_report()
        return self._summary

    @property
    def is_failed(self) -> bool:
        return not (sum([test_info["errors"] + test_info["failures"] for test_info in self.summary.values()]) == 0)
