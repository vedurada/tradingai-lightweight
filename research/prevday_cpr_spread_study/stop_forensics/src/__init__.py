"""Study implementation modules (read-only against the study snapshot).

Every module here is research-only: it reads a snapshot copy of the production
database, re-simulates the frozen production trigger, and writes exclusively to
the study's own outputs/ and reports/ directories.
"""
