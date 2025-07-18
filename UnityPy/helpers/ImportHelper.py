from __future__ import annotations

import io
import os
from typing import List, Optional, Tuple, Union

from .. import files
from ..enums import FileType
from ..streams import EndianBinaryReader
from .CompressionHelper import BROTLI_MAGIC, GZIP_MAGIC

FileSourceType = Union[str, bytes, bytearray, io.IOBase, EndianBinaryReader]


def file_name_without_extension(file_name: str) -> str:
    return os.path.join(os.path.dirname(file_name), os.path.splitext(os.path.basename(file_name))[0])


def list_all_files(directory: str) -> List[str]:
    return [
        val
        for sublist in [
            [os.path.join(dir_path, filename) for filename in filenames]
            for (dir_path, dirnames, filenames) in os.walk(directory)
            if ".git" not in dir_path
        ]
        for val in sublist
    ]


def find_all_files(directory: str, search_str: str) -> List[str]:
    return [
        val
        for sublist in [
            [os.path.join(dir_path, filename) for filename in filenames if search_str in filename]
            for (dir_path, dirnames, filenames) in os.walk(directory)
            if ".git" not in dir_path
        ]
        for val in sublist
    ]


def check_file_type(
    input_: FileSourceType,
) -> Tuple[FileType, EndianBinaryReader]:
    if isinstance(input_, str) and os.path.isfile(input_):
        reader = EndianBinaryReader(open(input_, "rb"))
    elif isinstance(input_, EndianBinaryReader):
        reader = input_
    else:
        reader = EndianBinaryReader(input_)

    if reader.Length < 20:
        return FileType.ResourceFile, reader

    signature = reader.read_string_to_null(20)

    reader.Position = 0
    if signature in [
        "UnityWeb",
        "UnityRaw",
        "\xfa\xfa\xfa\xfa\xfa\xfa\xfa\xfa",
        "UnityFS",
    ]:
        return FileType.BundleFile, reader
    elif signature.startswith(("UnityWebData", "TuanjieWebData")):
        return FileType.WebFile, reader
    elif signature == "PK\x03\x04":
        return FileType.ZIP, reader
    else:
        if reader.Length < 128:
            return FileType.ResourceFile, reader

        magic = bytes(reader.read_bytes(2))
        reader.Position = 0
        if GZIP_MAGIC == magic:
            return FileType.WebFile, reader
        reader.Position = 0x20
        magic = bytes(reader.read_bytes(6))
        reader.Position = 0
        if BROTLI_MAGIC == magic:
            return FileType.WebFile, reader

        # check if AssetsFile
        old_endian = reader.endian
        # read as if assetsfile and check version
        # ReadHeader
        reader.Position = 0
        metadata_size = reader.read_u_int()
        file_size = reader.read_u_int()
        version = reader.read_u_int()
        data_offset = reader.read_u_int()

        if version >= 22:
            raw_endian = reader.read_u_byte()
            _endian = ">" if raw_endian else "<"
            _reserved = reader.read_bytes(3)
            metadata_size = reader.read_u_int()
            file_size = reader.read_long()
            data_offset = reader.read_long()
            _unknown = reader.read_long()  # unknown

        # reset
        reader.endian = old_endian
        reader.Position = 0
        # check info
        if any(
            (
                version < 0,
                version > 100,
                *[x < 0 or x > reader.Length for x in [file_size, metadata_size, version, data_offset]],
                file_size < metadata_size,
                file_size < data_offset,
            )
        ):
            return FileType.ResourceFile, reader
        else:
            return FileType.AssetsFile, reader


def parse_file(
    reader: EndianBinaryReader,
    parent: files.File,
    name: str,
    typ: Optional[FileType] = None,
    is_dependency: bool = False,
) -> Union[files.File, EndianBinaryReader]:
    if typ is None:
        typ, _ = check_file_type(reader)
    if typ == FileType.AssetsFile and not name.endswith(
        (
            ".resS",
            ".resource",
            ".config",
            ".xml",
            ".dat",
        )
    ):
        f = files.SerializedFile(reader, parent, name=name, is_dependency=is_dependency)
    elif typ == FileType.BundleFile:
        f = files.BundleFile(reader, parent, name=name, is_dependency=is_dependency)
    elif typ == FileType.WebFile:
        f = files.WebFile(reader, parent, name=name, is_dependency=is_dependency)
    else:
        f = reader
    return f


def find_sensitive_path(dir: str, insensitive_path: str) -> Union[str, None]:
    parts = os.path.split(insensitive_path.strip(os.path.sep))

    sensitive_path = dir
    for part in parts:
        part_lower = part.lower()
        part = next(
            (name for name in os.listdir(sensitive_path) if name.lower() == part_lower),
            None,
        )
        if part is None:
            return None
        sensitive_path = os.path.join(sensitive_path, part)

    return sensitive_path
