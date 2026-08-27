"""Bounded image metadata decoding shared with media adapters."""

from struct import unpack


def image_metadata(content: bytes) -> tuple[str, int, int]:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(content) < 24 or content[12:16] != b"IHDR":
            raise ValueError("The PNG asset has an invalid header.")
        width, height = unpack(">II", content[16:24])
        if width == 0 or height == 0:
            raise ValueError("The PNG asset has invalid dimensions.")
        return "image/png", width, height
    if content.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 <= len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(content):
                break
            segment_length = int.from_bytes(content[index : index + 2], "big")
            if segment_length < 2 or index + segment_length > len(content):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                height = int.from_bytes(content[index + 3 : index + 5], "big")
                width = int.from_bytes(content[index + 5 : index + 7], "big")
                if width <= 0 or height <= 0:
                    break
                return "image/jpeg", width, height
            index += segment_length
        raise ValueError("The JPEG asset has no valid dimensions.")
    raise ValueError("Only bounded PNG and JPEG image assets are accepted.")
