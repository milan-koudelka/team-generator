# Empty on purpose: its presence makes pytest put the repo root on sys.path,
# so the tests can `import app` when run as a bare `pytest` (as CI does).
