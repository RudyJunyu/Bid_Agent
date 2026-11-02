"""Persistent, content-addressed file store. Original bytes never depend on a request temp directory."""
import hashlib
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO, Protocol

from PIL import Image

from bid_agent.core.settings import MAX_UPLOAD_BYTES, STORAGE_DIR

MEDIA_TYPES = {'.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
               '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
               '.html': 'text/html'}


class ObjectStore(Protocol):
    def put(self, stream: BinaryIO, filename: str) -> dict: ...
    def path(self, key: str) -> Path: ...


class FileTooLarge(ValueError):
    pass


class LocalObjectStore:
    def __init__(self, root: Path | None = None, max_bytes: int = MAX_UPLOAD_BYTES):
        self.root = (root or STORAGE_DIR / 'objects').resolve()
        self.max_bytes = max_bytes

    def path(self, key: str) -> Path:
        if not re.fullmatch(r'[0-9a-f]{2}/[0-9a-f]{64}\.(pdf|docx|png|jpg|jpeg|webp|html)', key):
            raise ValueError('Invalid object key')
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Object path escapes storage directory')
        return path

    def put(self, stream: BinaryIO, filename: str) -> dict:
        filename = Path(filename.replace('\\', '/')).name[:240]
        suffix = Path(filename).suffix.lower()
        if suffix not in MEDIA_TYPES:
            raise ValueError('支持 PDF、DOCX、PNG、JPEG、WEBP 和 HTML；旧 DOC 请先转换为 DOCX')
        self.root.mkdir(parents=True, exist_ok=True)
        # NamedTemporaryFile stays under the same filesystem as the final atomic replace.
        descriptor, temporary = tempfile.mkstemp(prefix='.upload-', dir=self.root)
        temporary_path = Path(temporary)
        checksum, size = hashlib.sha256(), 0
        try:
            with os.fdopen(descriptor, 'wb') as destination:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise FileTooLarge('文件超过上传大小限制')
                    checksum.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if not size:
                raise ValueError('文件内容为空')
            self._validate(temporary_path, suffix)
            digest = checksum.hexdigest()
            key = f'{digest[:2]}/{digest}{suffix}'
            target = self.path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Identical content has the same key; concurrent writers cannot change its meaning.
            os.replace(temporary_path, target)
            return {'file_name': filename, 'media_type': MEDIA_TYPES[suffix], 'object_key': key,
                    'sha256': digest, 'size_bytes': size}
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _validate(path: Path, suffix: str) -> None:
        with path.open('rb') as stream:
            signature = stream.read(1024)
        if suffix == '.pdf' and not signature.startswith(b'%PDF-'):
            raise ValueError('PDF 文件头无效')
        if suffix == '.docx':
            try:
                with zipfile.ZipFile(path) as archive:
                    entries = archive.infolist()
                    names = set(archive.namelist())
                    if not {'[Content_Types].xml', 'word/document.xml'}.issubset(names):
                        raise ValueError('文件不是有效 DOCX')
                    expanded = sum(item.file_size for item in entries)
                    if len(entries) > 10000 or expanded > 250 * 1024 * 1024:
                        raise ValueError('DOCX 解压大小或文件数量超过限制')
                    if any(item.flag_bits & 1 for item in entries):
                        raise ValueError('不支持加密 DOCX')
                    if any('..' in Path(item.filename.replace('\\', '/')).parts or item.filename.startswith(('/', '\\'))
                           for item in entries):
                        raise ValueError('DOCX 包含异常文件路径')
            except zipfile.BadZipFile as exc:
                raise ValueError('DOCX 压缩结构损坏') from exc
        if suffix in {'.png', '.jpg', '.jpeg', '.webp'}:
            try:
                with Image.open(path) as image:
                    expected = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}[suffix]
                    if image.format != expected or image.width * image.height > 80_000_000:
                        raise ValueError('图片格式或尺寸无效')
                    image.verify()
            except (OSError, Image.DecompressionBombError) as exc:
                raise ValueError('图片损坏或尺寸过大') from exc
        if suffix == '.html' and b'<html' not in signature.lower() and b'<!doctype html' not in signature.lower():
            raise ValueError('HTML 文件头无效')


object_store: ObjectStore = LocalObjectStore()
