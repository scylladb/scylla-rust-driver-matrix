import logging
from pathlib import Path
from xml.etree import ElementTree

LOGGER = logging.getLogger(__name__)


class ProcessJUnit:
    def __init__(
        self,
        tests_result_xml: Path,
        tag: str,
        ignore_set: list,
    ):
        self.tests_result_xml = tests_result_xml
        self._summary = {}
        self.tag = tag
        self.ignore_set = set(ignore_set)  # Use set for O(1) lookup
        LOGGER.info("Ignore tests: %s", self.ignore_set)

    def update_testcase_classname_with_tag(self):
        """Prepend driver version tag to all classname attributes."""
        logging.info(
            "Update testcase classname with driver version in '%s'",
            self.tests_result_xml.name,
        )
        with self.tests_result_xml.open(mode="r", encoding="utf-8") as file:
            xml_text = file.read()

        # Simple string replacement - preserves formatting
        updated_text = xml_text.replace('classname="', f'classname="{self.tag}.')

        with self.tests_result_xml.open(mode="w", encoding="utf-8") as file:
            file.write(updated_text)

    def process(self):
        """
        Process the test results:
        1. Compute summary statistics for email reports
        2. Modify XML to mark ignored failures as ignored_on_failure

        This modifies the XML in place, preserving all structure including
        child elements like <failure>, <system-out>, <system-err>.
        """
        if not self.tests_result_xml.is_file():
            raise FileNotFoundError(f"The {self.tests_result_xml} file does not exist")

        tree = ElementTree.parse(self.tests_result_xml)
        root = tree.getroot()  # <testsuites>

        # Initialize summary from root attributes
        testsuite_summary = {
            "time": float(root.attrib.get("time", 0)),
            "tests": int(root.attrib.get("tests", 0)),
            "errors": int(root.attrib.get("errors", 0)),
            "failures": int(root.attrib.get("failures", 0)),
            "skipped": 0,  # nextest doesn't report skipped
            "ignored_on_failure": 0,
        }

        total_ignored = 0

        for testsuite in root.findall("testsuite"):
            suite_name = testsuite.attrib.get("name", "unknown")
            suite_stats = {
                "time": float(testsuite.attrib.get("time", 0)),
                "tests": int(testsuite.attrib.get("tests", 0)),
                "errors": int(testsuite.attrib.get("errors", 0)),
                "failures": int(testsuite.attrib.get("failures", 0)),
                "skipped": int(testsuite.attrib.get("disabled", 0)),
                "ignored_on_failure": 0,
            }

            # Process testcases - mark ignored failures
            for testcase in testsuite.findall("testcase"):
                test_name = testcase.attrib.get("name")
                failure = testcase.find("failure")

                if failure is not None and test_name in self.ignore_set:
                    LOGGER.info(f"Ignoring expected failure: {test_name}")
                    # Rename <failure> to <ignored_on_failure> (preserves all attributes and text)
                    failure.tag = "ignored_on_failure"
                    suite_stats["failures"] -= 1
                    suite_stats["ignored_on_failure"] += 1
                    total_ignored += 1

            # Update testsuite failures attribute in XML
            testsuite.attrib["failures"] = str(suite_stats["failures"])

            self._summary[suite_name] = suite_stats

        # Update root testsuites failures count
        testsuite_summary["failures"] -= total_ignored
        testsuite_summary["ignored_on_failure"] = total_ignored
        root.attrib["failures"] = str(testsuite_summary["failures"])

        self._summary["testsuite_summary"] = testsuite_summary

        # Write modified XML back, preserving structure
        tree.write(self.tests_result_xml, encoding="utf-8", xml_declaration=True)

    @property
    def summary(self):
        if not self._summary:
            self.process()
        return self._summary

    @property
    def is_failed(self) -> bool:
        return (
            sum(info["errors"] + info["failures"] for info in self.summary.values()) > 0
        )
