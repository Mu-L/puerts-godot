# Test Runner

This project uses a built-in minimal runtime test framework.

## Run tests

From the repository root:

```powershell
python scripts/run_tests.py --godot C:\path\to\Godot_v4.x.x-stable_win64_console.exe --timeout=80
```

## Notes

- You may need set `timeout` because Nodejs may not exit properly after tests finish, causing the test runner to wait indefinitely.
- Godot test project root: `tests/`
- Build output root: `bin/`
- `scripts/run_tests.py` will sync `bin/` to `tests/bin/` before running tests.
- Headless entrypoint: project main scene (`tests/main.tscn` -> `tests/main.gd`).
- You can limit test backends via `--backends`, for example: `--backends quickjs,lua`.
