"""Operator tooling for a C1 deployment (M13): bootstrap, backup, restore, recovery.

Host commands orchestrate the reference Compose deployment with the container
engine. Commands under ``c1-admin internal`` run inside the ``tools`` container
on the private backend network and use the same configuration as the service.
"""
