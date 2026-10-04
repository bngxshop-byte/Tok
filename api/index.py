# -*- coding: utf-8 -*-
import sys
import os

# Add parent dir to path so we can import app and thunderFF_pb2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app

# Vercel expects `app` or `handler`
app = flask_app

def handler(event, context):
    return flask_app
