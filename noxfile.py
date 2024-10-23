import os
import pathlib

import nox

# It's a good idea to keep your dev session out of the default list
# so it's not run twice accidentally
nox.options.sessions = [...]  # Sessions other than 'dev'

# this VENV_DIR constant specifies the name of the dir that the `dev`
# session will create, containing the virtualenv;
# the `resolve()` makes it portable
VENV_DIR = pathlib.Path("./venv").resolve()


@nox.session(python=False)
def dev(session: nox.Session) -> None:
    """
    Sets up a python development environment for the project.

    This session will:
    - Create a python virtualenv for the session
    - Install the `virtualenv` cli tool into this environment
    - Use `virtualenv` to create a global project virtual environment
    - Invoke the python interpreter from the global project environment to install
      the project and all it's development dependencies.
    """

    session.run("uv", "venv", "--python", "3.10", os.fsdecode(VENV_DIR))
    session.run("uv", "pip", "install", "pip", env={"VIRTUAL_ENV": os.fsdecode(VENV_DIR)})

    # Use the venv's interpreter to install the project along with
    # all it's dev dependencies, this ensures it's installed in the right way
    session.run("poetry", "install", "--no-root", env={"VIRTUAL_ENV": os.fsdecode(VENV_DIR)})
