# -*- coding: utf-8 -*-
"""What every command shares: resolving the project, and the arguments that select it."""
import datetime
import os

from ..project import Project


def project_arguments(parser):
    """The argument every project-bound command takes."""
    parser.add_argument("--project", default=".", help="project root (default: current directory)")


def resolve(args):
    return Project.standard(os.path.abspath(args.project))


def today():
    return datetime.date.today().isoformat()
