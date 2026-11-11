"""Shared fixtures for e2e tests.

The tests run inside the `tests` container on the compose network and talk to
services by their names. Each stage adds the readiness checks it needs here.
"""
