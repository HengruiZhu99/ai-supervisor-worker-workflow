DEFAULT_QUALITY_TOML = """schema_version = 1

[files.python]
soft_logical_lines = 300
hard_logical_lines = 450

[files.python_cli_api]
soft_logical_lines = 250
hard_logical_lines = 400

[files.shell]
soft_logical_lines = 100
hard_logical_lines = 160

[files.typescript_javascript]
soft_logical_lines = 300
hard_logical_lines = 450

[files.react_component]
soft_logical_lines = 200
hard_logical_lines = 300

[functions]
soft_logical_lines = 60
hard_logical_lines = 100
soft_complexity = 8
hard_complexity = 12

[diff]
soft_source_files = 8
soft_logical_lines = 500
hard_multiplier = 2.0

[oversized_existing]
allow_growth = false
require_architecture_impact_note = true

[housekeeping]
max_tasks_per_milestone = 1
max_fraction = 0.10
"""


DEFAULT_DEPRECATIONS_TOML = """schema_version = 1

[[deprecation]]
id = "legacy-worker-loop"
symbol_or_path = "scripts/worker_loop.sh"
replacement = "aiflow run resume"
introduced_version = "0.4.0"
removal_version = "0.6.0"
removal_deadline = "2027-01-31"
owner = "workflow-maintainers"
compat_tests = ["tests/regression/test_finite_execution_red.py"]
remaining_call_sites = 1

[[deprecation]]
id = "legacy-supervisor-loop"
symbol_or_path = "scripts/supervisor_loop.sh"
replacement = "aiflow controller run"
introduced_version = "0.4.0"
removal_version = "0.6.0"
removal_deadline = "2027-01-31"
owner = "workflow-maintainers"
compat_tests = ["tests/regression/test_finite_execution_red.py"]
remaining_call_sites = 1

[[deprecation]]
id = "legacy-modulator-loop"
symbol_or_path = "scripts/modulator_loop.sh"
replacement = "deterministic controller watchdog"
introduced_version = "0.4.0"
removal_version = "0.6.0"
removal_deadline = "2027-01-31"
owner = "workflow-maintainers"
compat_tests = ["tests/regression/test_finite_execution_red.py"]
remaining_call_sites = 1

[[deprecation]]
id = "legacy-integrator"
symbol_or_path = "scripts/integrate_job.py"
replacement = "aiflow.integration.transaction"
introduced_version = "0.4.0"
removal_version = "0.6.0"
removal_deadline = "2027-01-31"
owner = "workflow-maintainers"
compat_tests = ["tests/regression/test_integration_red.py"]
remaining_call_sites = 0

[[deprecation]]
id = "legacy-workflow-gui"
symbol_or_path = "scripts/workflow_gui.py"
replacement = "aiflow gui"
introduced_version = "0.4.0"
removal_version = "0.6.0"
removal_deadline = "2027-01-31"
owner = "workflow-maintainers"
compat_tests = ["tests/integration/test_api_project_isolation.py"]
remaining_call_sites = 0

[[deprecation]]
id = "legacy-copy-installer"
symbol_or_path = "install.sh"
replacement = "aiflow project init --profile <profile>"
introduced_version = "0.4.0"
removal_version = "0.6.0"
removal_deadline = "2027-01-31"
owner = "workflow-maintainers"
compat_tests = ["tests/integration/test_legacy_installer.py"]
remaining_call_sites = 0
"""
