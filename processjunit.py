import logging
import shutil
from ast import literal_eval
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree

LOGGER = logging.getLogger(__name__)


class ProcessJUnit:
    def __init__(self, summary_report_xml_path: Path, tests_result_xml: Path, tag: str, ignore_set: list):
        self.summary_report_path = summary_report_xml_path
        self.tests_result_xml = tests_result_xml
        self._summary_keys = {"time": 0.0, "tests": 0, "errors": 0, "skipped": 0, "failures": 0, "ignored_on_failure": 0}
        self._summary = {}
        self.tag = tag
        self.ignore_set = ignore_set
        LOGGER.info("Ignore tests: %s", self.ignore_set)

    @lru_cache(maxsize=None)
    def _create_report(self):
        def get_attribute():
            return literal_eval(testsuite_element.attrib[key].replace(',', '')) \
                        if key in testsuite_element.attrib else 0

        def filter_out_ignored_failed_test():
            failured_tests = testcase_keys[key]
            for test in testsuite_element.iter("failure"):
                if test.attrib["message"].replace("failed ", "") in self.ignore_set:
                    failured_tests -= 1
                    testcase_keys["ignored_on_failure"] += 1
            return failured_tests

        if not self.tests_result_xml.is_file():
            raise NotADirectoryError(f"The {self.tests_result_xml} file not exits")

        new_tree = ElementTree.Element("testsuite")
        tree = ElementTree.parse(self.tests_result_xml)
        testsuite_summary_keys = deepcopy(self._summary_keys)
        for testsuite_element in tree.iter("testsuite"):
            testcase_keys = deepcopy(self._summary_keys)
            for key in testcase_keys:
                testcase_keys[key] = get_attribute()
                if key == "failures" and testcase_keys[key] > 0 and self.ignore_set:
                    testcase_keys[key] = filter_out_ignored_failed_test()

            # rust does not report "skipped" in the <testsuite> summary
            if skipped := testsuite_element.iter("skipped"):
                testcase_keys["skipped"] = len([elem.tag for elem in skipped])

            for key in testcase_keys:
                testsuite_summary_keys[key] += testcase_keys[key]

            self._summary[testsuite_element.attrib["name"]] = testcase_keys

        new_tree.attrib["name"] = self.summary_report_path.stem
        new_tree.attrib.update({key: str(value) for key, value in self._summary.items()})
        new_tree.attrib["time"] = f"{testsuite_summary_keys['time']}:.3f"
        logging.info("Creating a new report file in '%s' path", self.summary_report_path)
        self.summary_report_path.parent.mkdir(exist_ok=True)
        with self.summary_report_path.open(mode="w", encoding="utf-8") as file:
            file.write(ElementTree.tostring(element=new_tree, encoding="utf-8").decode())

        self._summary['testsuite_summary'] = testsuite_summary_keys
        self.save_after_analysis()

    def update_testcase_classname_with_tag(self):
        logging.info("Update testcase classname with driver version in '%s'", self.tests_result_xml.name)
        with self.tests_result_xml.open(mode="r", encoding="utf-8") as file:
            xml_text = file.readlines()

        updated_text = []
        for line in xml_text:
            updated_text.append(line.replace('classname="', f'classname="{self.tag}.'))

        with self.tests_result_xml.open(mode="w", encoding="utf-8") as file:
            file.write("".join(updated_text))

    @lru_cache(maxsize=None)
    def save_after_analysis(self) -> None:
        """
        Mark failed tests as "ignored_on_failure" if those tests expected to fail for the driver version to prevent test failure in Argus
        :param ignored_tests: list with ignored test names
        """
        original_test_result_xml = Path(self.tests_result_xml.parent) / self.tests_result_xml.name.replace(".xml", "_origin.xml")
        shutil.copy(str(self.tests_result_xml), str(original_test_result_xml))

        tree = ElementTree.parse(original_test_result_xml)
        new_tree = ElementTree.Element("testsuites")
        for testsuite_element in tree.iter("testsuite"):
            testsuit_child = ElementTree.SubElement(new_tree, "testsuite", attrib=testsuite_element.attrib)
            for element in testsuite_element.iter("testcase"):
                testcase_element = ElementTree.SubElement(testsuit_child, "testcase", attrib=element.attrib)
                tag_name = element.tag
                if len(list(element.iter())) == 2:
                    element_test_details = list(element.iter())[1]
                    if element_test_details.tag == "failure" and \
                            element_test_details.attrib["message"].replace("failed ", "") in self.ignore_set:
                        logging.info("Failed test %s is ignored for %s driver version. Failure message: %s",
                                     element_test_details.attrib["message"], self.tag, element_test_details.text)
                        # Change tag name to prevent test failure
                        tag_name = "ignored_on_failure"
                        # Decrease amount of failed tests that its failure is expected for the rust driver version
                        testsuit_child.attrib["failures"] = str(int(testsuit_child.attrib["failures"]) - 1)
                    elif element_test_details.tag == "skipped":
                        tag_name = "skipped"

                    new_element_test_details = ElementTree.SubElement(
                        testcase_element, tag_name, attrib=element_test_details.attrib)
                    new_element_test_details.text = element_test_details.text

        with self.tests_result_xml.open(mode="w", encoding="utf-8") as file:
            file.write(minidom.parseString(
                ElementTree.tostring(element=new_tree, encoding="utf-8")).toprettyxml(indent="  "))

        original_test_result_xml.unlink()

    @property
    def summary(self):
        if not self._summary:
            self._create_report()
        return self._summary

    @property
    def is_failed(self) -> bool:
        return not (sum([test_info["errors"] + test_info["failures"] for test_info in self.summary.values()]) == 0)
