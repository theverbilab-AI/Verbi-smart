#!/bin/sh
set -e
exec gunicorn app:app -c gunicorn.conf.py
