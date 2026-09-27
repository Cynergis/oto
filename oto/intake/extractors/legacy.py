# -*- coding: utf-8 -*-
"""Legacy Office files (.doc, .ppt, .xls, and the OpenDocument formats), via LibreOffice.

There is no permissively licensed pure-Python reader for the Word 97-2003 binary format worth
shipping, and a half-working one would produce a corpus nobody could trust. LibreOffice reads
these formats faithfully and is free, so this extractor converts the file to its modern
equivalent with `soffice --headless --convert-to`, then hands the result to the extractor that
already handles that format. The corpus records the original filename and type, so a citation
still names the file a person can open.

Without LibreOffice on the PATH the extractor reports itself as unavailable, and the run moves
the file to errors/ with that reason, which is the honest outcome.
"""
import os
import shutil
import subprocess
import tempfile

from ..registry import Extractor, register, find

TARGETS = {".doc": "docx", ".dot": "docx", ".rtf": "docx", ".odt": "docx", ".wpd": "docx",
           ".ppt": "pptx", ".pps": "pptx", ".odp": "pptx",
           ".xls": "xlsx", ".ods": "xlsx"}
TYPES = {"docx": "Word document (converted from %s by LibreOffice)",
         "pptx": "PowerPoint deck (converted from %s by LibreOffice)",
         "xlsx": "Excel workbook (converted from %s by LibreOffice)"}
CANDIDATES = ("soffice", "libreoffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice",
              r"C:\Program Files\LibreOffice\program\soffice.exe")


def soffice():
    for candidate in CANDIDATES:
        found = shutil.which(candidate) if not os.path.isabs(candidate) else (candidate if os.path.exists(candidate) else None)
        if found:
            return found
    return None


@register
class Legacy(Extractor):
    name = "legacy"
    extensions = tuple(TARGETS)
    media_type = "Legacy Office document"

    def available(self):
        return soffice() is not None

    def missing(self):
        return [] if self.available() else ["LibreOffice (soffice) on the PATH, to convert legacy Office files"]

    def extract(self, path, style, assets_dir=None):
        ext = os.path.splitext(path)[1].lower()
        target = TARGETS[ext]
        outdir = tempfile.mkdtemp(prefix="oto_convert_")
        try:
            result = subprocess.run([soffice(), "--headless", "--convert-to", target, "--outdir", outdir, path],
                                    capture_output=True, text=True, timeout=300)
            converted = os.path.join(outdir, os.path.splitext(os.path.basename(path))[0] + "." + target)
            if result.returncode != 0 or not os.path.exists(converted):
                raise RuntimeError("LibreOffice could not convert %s: %s"
                                   % (os.path.basename(path), (result.stderr or result.stdout).strip()[:200]))
            delegate = find(converted)
            if delegate is None or not delegate.available():
                raise RuntimeError("no extractor available for the converted %s file" % target)
            doc = delegate.extract(converted, style, assets_dir=assets_dir)
            # The corpus cites the file a person can open: the original.
            doc.source_name = os.path.basename(path)
            doc.media_type = TYPES[target] % ext
            doc.extra = dict(doc.extra or {}, rendered_by=delegate.name)
            return doc
        finally:
            shutil.rmtree(outdir, ignore_errors=True)


def render(doc, style):
    import importlib
    module = importlib.import_module("oto.intake.extractors.%s" % doc.extra.get("rendered_by", "docx"))
    return module.render(doc, style)
