import os


def resolve_symlink(path):
    if os.path.islink(path):
        return resolve_symlink(os.path.realpath(path))
    return path
