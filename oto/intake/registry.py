# -*- coding: utf-8 -*-
"""Extractor registry.

An extractor declares which files it handles and returns a `Document`. Adding a format means adding
one module and registering it. No core file changes, which is the point: a team can support their own
source type without touching the engine.

    from oto.intake.registry import register, Extractor

    @register
    class MyFormat(Extractor):
        name = "myformat"
        extensions = (".xyz",)
        media_type = "XYZ file"

        def extract(self, path, style):
            ...
            return document
"""
import os
import sys as _sys

_REGISTRY = []
_BUILTINS_LOADED = False


class Extractor:
    """Base class. Subclasses set `extensions` and implement `extract`."""

    name = "unnamed"
    extensions = ()
    media_type = "file"
    requires = ()          # importable module names this extractor needs

    def can_handle(self, path):
        name = os.path.basename(path)
        if name.startswith("~$") or name.startswith("."):
            return False                        # Office lock files and dotfiles
        return os.path.splitext(name)[1].lower() in self.extensions

    def available(self):
        """True when every dependency imports. An unavailable extractor is skipped, not fatal."""
        for module in self.requires:
            try:
                __import__(module)
            except ImportError:
                return False
        return True

    def missing(self):
        out = []
        for module in self.requires:
            try:
                __import__(module)
            except ImportError:
                out.append(module)
        return out

    def extract(self, path, style, assets_dir=None):
        """Return a Document.

        `assets_dir` is where extracted media goes. When it is None the extractor must still
        record asset paths, so the rendered output is identical whether or not media is written.
        """
        raise NotImplementedError


def register(cls):
    """Class decorator. Registers an extractor."""
    _REGISTRY.append(cls())
    return cls


# `text` first: it needs no dependencies, so it is the one that always works.
BUILTIN_MODULES = ("text", "docx", "pptx", "pdf", "xlsx", "html", "mht", "legacy")


def load_builtins():
    """Import the bundled extractors so their registrations run.

    Each import is independent: one broken or absent extractor must not stop the others from
    registering, because a user with only PDFs should not be blocked by a Word parser.
    """
    import importlib
    global _BUILTINS_LOADED

    # A flag, not "is the registry non-empty": importing one extractor module directly (a test,
    # a plugin, a REPL) registers it, and that must not make the loader skip the others.
    if _BUILTINS_LOADED:
        return all_extractors()
    _BUILTINS_LOADED = True
    for name in BUILTIN_MODULES:
        try:
            importlib.import_module("%s.extractors.%s" % (__package__, name))
        except ImportError as exc:
            print("oto: extractor %r not loaded (%s)" % (name, exc), file=_sys.stderr)
    return all_extractors()


def all_extractors():
    return list(_REGISTRY)


def find(path):
    """The first registered extractor that handles this path, or None."""
    for extractor in _REGISTRY:
        if extractor.can_handle(path):
            return extractor
    return None


def supported_extensions():
    out = set()
    for extractor in _REGISTRY:
        out.update(extractor.extensions)
    return sorted(out)
