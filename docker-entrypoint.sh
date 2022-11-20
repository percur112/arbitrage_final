#!/bin/bash

uwsgi --http-socket ${HOST}:${PORT} --wsgi-file app.py --callable app --processes 4 --threads 2 --buffer-size 65535