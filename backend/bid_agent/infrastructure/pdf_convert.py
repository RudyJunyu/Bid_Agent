"""Optional LibreOffice DOCX→PDF conversion (B14 draft; sync helper, not a queue worker)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def libreoffice_available() -> bool:
    return bool(shutil.which('soffice') or shutil.which('libreoffice'))


def convert_docx_to_pdf(docx_bytes: bytes, *, timeout_seconds: int = 120) -> dict:
    """
    Convert DOCX bytes to PDF via LibreOffice when installed.
    Returns {'ok': True, 'pdf_bytes': ...} or {'ok': False, 'reason': ...}.
    """
    binary = shutil.which('soffice') or shutil.which('libreoffice')
    if not binary:
        return {
            'ok': False,
            'reason': '未安装 LibreOffice（soffice／libreoffice），跳过 PDF 转换',
        }
    with tempfile.TemporaryDirectory(prefix='bid-export-pdf-') as tmp:
        root = Path(tmp)
        source = root / 'input.docx'
        source.write_bytes(docx_bytes)
        try:
            completed = subprocess.run(
                [
                    binary,
                    '--headless',
                    '--nologo',
                    '--nofirststartwizard',
                    '--convert-to',
                    'pdf',
                    '--outdir',
                    str(root),
                    str(source),
                ],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {'ok': False, 'reason': f'LibreOffice 转换超时（>{timeout_seconds}s）'}
        except OSError as exc:
            return {'ok': False, 'reason': f'无法启动 LibreOffice：{exc}'}
        pdf_path = root / 'input.pdf'
        if completed.returncode != 0 or not pdf_path.is_file():
            detail = (completed.stderr or completed.stdout or '').strip()[:500]
            return {
                'ok': False,
                'reason': detail or f'LibreOffice 转换失败（exit={completed.returncode}）',
            }
        return {'ok': True, 'pdf_bytes': pdf_path.read_bytes()}
