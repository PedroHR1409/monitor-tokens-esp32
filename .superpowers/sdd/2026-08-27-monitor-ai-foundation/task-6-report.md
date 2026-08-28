# Task 6 — Per-user service management report

## Scope delivered

- Added `tools/service_manager.py` with pure Windows Task Scheduler XML and
  systemd-user-unit renderers, plus install, remove, and status operations.
- Added `service install|remove|status --dry-run` to `tools/monitor.py`.
- Service commands derive absolute Python, repository, and configuration paths.
- Windows uses `schtasks` with a current-user `InteractiveToken` task at least
  privilege. Linux writes only `~/.config/systemd/user/monitor-ai.service` and
  invokes `systemctl --user`.

## TDD record

### RED

Created `tests/test_service_manager.py` before creating `service_manager.py` or
altering `monitor.py`. Each test documents the production break it catches:
quoted paths, non-elevated task XML, systemd hardening, rejected relative paths,
idempotent no-side-effect dry-runs, and CLI availability.

Command:

```powershell
python -m unittest tests.test_service_manager -v
```

Observed expected failure: 7 errors. Six were
`ModuleNotFoundError: No module named 'service_manager'`; the CLI test failed
because `service` was not an accepted `monitor.py` command. No test passed
before implementation.

### GREEN

Implemented the minimal service module and CLI wiring, then reran:

```powershell
python -m unittest tests.test_service_manager -v
python -m py_compile tools\service_manager.py tools\monitor.py
```

Observed: all 7 focused tests passed; compilation exited 0.

## Verification

Full suite command:

```powershell
python -m unittest discover -s tests -v
```

Observed: exit 0, `Ran 152 tests in 1.723s`, `OK`.

`git diff --check` produced no whitespace errors (Git emitted only its normal
LF-to-CRLF checkout warning for the pre-existing tracked Python file).

## Security and operational review

- Rendered commands contain only executable, checkout, and config *paths*;
  the configuration is never parsed by service management, so no token is
  passed in arguments or printed in diagnostics.
- All supplied paths must be absolute; arguments with spaces are quoted.
- `--dry-run` bypasses filesystem writes and all `schtasks`/`systemctl` calls;
  tests inject a runner that fails if called.
- Linux destination is scoped to the requested/current user home, never
  `/etc/systemd/system`. The unit uses `NoNewPrivileges`, `PrivateTmp`,
  `ProtectSystem=strict`, `ProtectHome=read-only`, and a narrow writable config
  directory.
- Windows XML uses an interactive-token, least-privilege task and no startup
  trigger or administrator account.

## Concerns

- Actual service installation/removal intentionally was not executed during
  tests, because doing so would alter the developer's live user service.
- The executable checkout and config location must remain available after
  installation; this is why their resolved absolute paths are embedded.
