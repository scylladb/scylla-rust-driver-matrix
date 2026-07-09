import json
import sys
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.pr_integration_changes import detect_changes


def test_runner_changes_include_shell_wrapper_entrypoint_pyproject_and_workflows():
    for changed_file in [
        "scripts/run_test.sh",
        "scripts/entrypoint.sh",
        "scripts/image",
        "pyproject.toml",
        ".github/workflows/integration-tests.yml",
        ".github/workflows/pr-integration-tests.yml",
        "main.py",
    ]:
        outputs = detect_changes([changed_file], repo_root=REPO_ROOT)

        assert outputs["runner_changed"] == "true", changed_file


def test_changed_scylla_version_expands_to_driver_matrix_entry():
    outputs = detect_changes(["versions/scylla/v1.7.0/ignore.yaml"], repo_root=REPO_ROOT)

    assert outputs["version_count"] == "1"
    matrix = json.loads(outputs["version_matrix"])
    assert matrix["include"] == [
        {
            "driver_type": "scylla",
            "driver_repository": "scylladb/scylla-rust-driver",
            "driver_version": "v1.7.0",
            "driver_ref": "v1.7.0",
        }
    ]


def test_image_source_changes_require_scripts_image_update():
    outputs = detect_changes(["scripts/entrypoint.sh"], repo_root=REPO_ROOT)

    assert outputs["scripts_image_source_changed"] == "true"
    assert outputs["scripts_image_changed"] == "false"


def test_ccm_cache_restore_and_save_use_the_same_path():
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/integration-tests.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["integration-test"]["steps"]
    restore = next(step for step in steps if step.get("id") == "ccm-cache")
    save = next(step for step in steps if step.get("name") == "Save CCM download cache")

    assert restore["with"]["path"] == "~/.ccm/scylla-repository"
    assert save["with"]["path"] == restore["with"]["path"]


def test_integration_workflow_uploads_reports_after_failures():
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/integration-tests.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["integration-test"]["steps"]
    reports = next(step for step in steps if step.get("name") == "Upload integration test reports")
    ccm_logs = next(step for step in steps if step.get("name") == "Upload CCM logs")

    for step in (reports, ccm_logs):
        assert step["if"] == "${{ always() }}"
        assert step["uses"].startswith("actions/upload-artifact@")
        assert len(step["uses"].removeprefix("actions/upload-artifact@")) == 40

    assert "test_results/" in reports["with"]["path"]
    assert "argus_test_results/" in reports["with"]["path"]
    assert "driver/target/nextest/**" in reports["with"]["path"]
    assert "~/.ccm/*/node*/logs/**" in ccm_logs["with"]["path"]
