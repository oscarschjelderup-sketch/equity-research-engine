"""Render a .pptx to PNG slides (Windows: PowerPoint via COM; else LibreOffice if present)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def export_slides(pptx_path: str | Path, out_dir: str | Path, width: int = 1920) -> list[Path]:
    pptx_path = Path(pptx_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        try:
            return _export_powerpoint(pptx_path, out_dir, width)
        except Exception as exc:  # pragma: no cover - depends on Office
            last = exc
    else:
        last = RuntimeError("PowerPoint COM export is only available on Windows")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        return _export_libreoffice(soffice, pptx_path, out_dir)
    raise RuntimeError(f"Could not render slides: {last}")


def export_pdf(pptx_path: str | Path, pdf_path: str | Path | None = None) -> Path:
    """Save the deck as PDF (PowerPoint COM on Windows, otherwise LibreOffice)."""
    pptx_path = Path(pptx_path).resolve()
    pdf_path = Path(pdf_path).resolve() if pdf_path else pptx_path.with_suffix(".pdf")
    if sys.platform.startswith("win"):
        try:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore

            pythoncom.CoInitialize()
            app = win32com.client.Dispatch("PowerPoint.Application")
            pres = app.Presentations.Open(str(pptx_path), WithWindow=False)
            try:
                pres.SaveAs(str(pdf_path), 32)  # ppSaveAsPDF
            finally:
                pres.Close()
                try:
                    app.Quit()
                except Exception:
                    pass
            return pdf_path
        except Exception as exc:  # pragma: no cover - depends on Office
            last: Exception = exc
    else:
        last = RuntimeError("PowerPoint COM export is only available on Windows")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_path.parent), str(pptx_path)], check=True, capture_output=True)
        return pdf_path
    raise RuntimeError(f"Could not export PDF: {last}")


def _export_powerpoint(pptx_path: Path, out_dir: Path, width: int) -> list[Path]:
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    pythoncom.CoInitialize()
    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(str(pptx_path), WithWindow=False)
    paths: list[Path] = []
    try:
        height = int(width * pres.PageSetup.SlideHeight / pres.PageSetup.SlideWidth)
        for i in range(1, pres.Slides.Count + 1):
            p = out_dir / f"slide_{i:02d}.png"
            pres.Slides(i).Export(str(p), "PNG", width, height)
            paths.append(p)
    finally:
        pres.Close()
        try:
            app.Quit()
        except Exception:
            pass
    return paths


def _export_libreoffice(soffice: str, pptx_path: Path, out_dir: Path) -> list[Path]:
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(pptx_path)], check=True, capture_output=True)
    pdf = out_dir / (pptx_path.stem + ".pdf")
    import fitz  # PyMuPDF

    doc = fitz.open(pdf)
    paths = []
    for i, page in enumerate(doc, 1):
        p = out_dir / f"slide_{i:02d}.png"
        page.get_pixmap(dpi=110).save(p)
        paths.append(p)
    return paths
