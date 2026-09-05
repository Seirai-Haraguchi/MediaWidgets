"""QQ 音乐定制 Triple-DES（QRC 解密用），从 MediaIsland 的 QqMusicDes.cs 逐行移植。

QQ 客户端的 DES 与 FIPS 46-3 标准有两处 S-box 差异（S2[23]=15、S4[53]=10），
"修正"它们反而会解出乱码，必须原样保留。纯位运算实现，无第三方依赖；
QRC 载荷只有几 KB，纯 Python 性能足够。
"""

_ROUNDS = 16

_ROTATIONS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)

_PC1_LEFT = (
    56, 48, 40, 32, 24, 16, 8, 0, 57, 49, 41, 33, 25, 17,
    9, 1, 58, 50, 42, 34, 26, 18, 10, 2, 59, 51, 43, 35,
)
_PC1_RIGHT = (
    62, 54, 46, 38, 30, 22, 14, 6, 61, 53, 45, 37, 29, 21,
    13, 5, 60, 52, 44, 36, 28, 20, 12, 4, 27, 19, 11, 3,
)
_COMPRESSION = (
    13, 16, 10, 23, 0, 4, 2, 27, 14, 5, 20, 9, 22, 18, 11, 3,
    25, 7, 15, 6, 26, 19, 12, 1, 40, 51, 30, 36, 46, 54, 29, 39,
    50, 44, 32, 47, 43, 48, 38, 55, 33, 52, 45, 41, 49, 35, 28, 31,
)

_SBOX1 = (
    14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7,
    0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8,
    4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0,
    15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13,
)
# 注意：索引 23 是 15（标准 DES 为 14）——QQ 客户端就这样
_SBOX2 = (
    15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10,
    3, 13, 4, 7, 15, 2, 8, 15, 12, 0, 1, 10, 6, 9, 11, 5,
    0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15,
    13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9,
)
_SBOX3 = (
    10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8,
    13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1,
    13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7,
    1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12,
)
# 注意：索引 53 是 10（标准 DES 为 1）——QQ 客户端就这样
_SBOX4 = (
    7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15,
    13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9,
    10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4,
    3, 15, 0, 6, 10, 10, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14,
)
_SBOX5 = (
    2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9,
    14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6,
    4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14,
    11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3,
)
_SBOX6 = (
    12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11,
    10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8,
    9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6,
    4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13,
)
_SBOX7 = (
    4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1,
    13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6,
    1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2,
    6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12,
)
_SBOX8 = (
    13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7,
    1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2,
    7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8,
    2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11,
)

_MASK32 = 0xFFFFFFFF
_MASK28 = 0xFFFFFFF0


def _bit_num(source: bytes, bit: int, shift: int) -> int:
    """C# BitNum：按 QQ C 实现的位序从字节串取位。"""
    idx = bit // 32 * 4 + 3 - (bit % 32) // 8
    return (((source[idx] >> (7 - bit % 8)) & 1) << shift)


def _bit_r(value: int, bit: int, shift: int) -> int:
    """C# BitNumIntR：value 第 bit 位（MSB 起数）左移 shift。"""
    return ((value >> (31 - bit)) & 1) << shift


def _bit_l(value: int, bit: int, shift: int) -> int:
    """C# BitNumIntL。"""
    return ((value << bit) & 0x80000000) >> shift


def _sbox_bit(value: int) -> int:
    return (value & 0x20) | ((value & 0x1F) >> 1) | ((value & 1) << 4)


def _build_key_schedule(key: bytes, encrypt: bool) -> list:
    """16 轮各 6 字节的轮密钥；解密时轮序倒排。"""
    schedule = [[0] * 6 for _ in range(_ROUNDS)]
    left = 0
    right = 0
    for i, src in enumerate(_PC1_LEFT):
        left |= _bit_num(key, src, 31 - i)
    for i, src in enumerate(_PC1_RIGHT):
        right |= _bit_num(key, src, 31 - i)

    for rnd in range(_ROUNDS):
        rot = _ROTATIONS[rnd]
        left = ((left << rot) | (left >> (28 - rot))) & _MASK28
        right = ((right << rot) | (right >> (28 - rot))) & _MASK28
        round_key = schedule[rnd if encrypt else _ROUNDS - 1 - rnd]
        for b in range(6):
            round_key[b] = 0
        for bit in range(24):
            round_key[bit // 8] |= _bit_r(left, _COMPRESSION[bit], 7 - bit % 8)
        for bit in range(24, 48):
            round_key[bit // 8] |= _bit_r(right, _COMPRESSION[bit] - 27, 7 - bit % 8)
    return schedule


def _feistel(state: int, round_key) -> int:
    high = (
        _bit_l(state, 31, 0) | ((state & 0xF0000000) >> 1) | _bit_l(state, 4, 5)
        | _bit_l(state, 3, 6) | ((state & 0xF000000) >> 3) | _bit_l(state, 8, 11)
        | _bit_l(state, 7, 12) | ((state & 0xF00000) >> 5) | _bit_l(state, 12, 17)
        | _bit_l(state, 11, 18) | ((state & 0xF0000) >> 7) | _bit_l(state, 16, 23)
    )
    low = (
        _bit_l(state, 15, 0) | ((state & 0xF000) << 15) | _bit_l(state, 20, 5)
        | _bit_l(state, 19, 6) | ((state & 0xF00) << 13) | _bit_l(state, 24, 11)
        | _bit_l(state, 23, 12) | ((state & 0xF0) << 11) | _bit_l(state, 28, 17)
        | _bit_l(state, 27, 18) | ((state & 0xF) << 9) | _bit_l(state, 0, 23)
    )
    e = (
        ((high >> 24) & 0xFF) ^ round_key[0],
        ((high >> 16) & 0xFF) ^ round_key[1],
        ((high >> 8) & 0xFF) ^ round_key[2],
        ((low >> 24) & 0xFF) ^ round_key[3],
        ((low >> 16) & 0xFF) ^ round_key[4],
        ((low >> 8) & 0xFF) ^ round_key[5],
    )
    state = (
        (_SBOX1[_sbox_bit(e[0] >> 2)] << 28)
        | (_SBOX2[_sbox_bit(((e[0] & 3) << 4) | (e[1] >> 4))] << 24)
        | (_SBOX3[_sbox_bit(((e[1] & 0xF) << 2) | (e[2] >> 6))] << 20)
        | (_SBOX4[_sbox_bit(e[2] & 0x3F)] << 16)
        | (_SBOX5[_sbox_bit(e[3] >> 2)] << 12)
        | (_SBOX6[_sbox_bit(((e[3] & 3) << 4) | (e[4] >> 4))] << 8)
        | (_SBOX7[_sbox_bit(((e[4] & 0xF) << 2) | (e[5] >> 6))] << 4)
        | _SBOX8[_sbox_bit(e[5] & 0x3F)]
    )
    return (
        _bit_l(state, 15, 0) | _bit_l(state, 6, 1) | _bit_l(state, 19, 2)
        | _bit_l(state, 20, 3) | _bit_l(state, 28, 4) | _bit_l(state, 11, 5)
        | _bit_l(state, 27, 6) | _bit_l(state, 16, 7) | _bit_l(state, 0, 8)
        | _bit_l(state, 14, 9) | _bit_l(state, 22, 10) | _bit_l(state, 25, 11)
        | _bit_l(state, 4, 12) | _bit_l(state, 17, 13) | _bit_l(state, 30, 14)
        | _bit_l(state, 9, 15) | _bit_l(state, 1, 16) | _bit_l(state, 7, 17)
        | _bit_l(state, 23, 18) | _bit_l(state, 13, 19) | _bit_l(state, 31, 20)
        | _bit_l(state, 26, 21) | _bit_l(state, 2, 22) | _bit_l(state, 8, 23)
        | _bit_l(state, 18, 24) | _bit_l(state, 12, 25) | _bit_l(state, 29, 26)
        | _bit_l(state, 5, 27) | _bit_l(state, 21, 28) | _bit_l(state, 10, 29)
        | _bit_l(state, 3, 30) | _bit_l(state, 24, 31)
    )


def _initial_permutation(block: bytes):
    s0 = (
        _bit_num(block, 57, 31) | _bit_num(block, 49, 30) | _bit_num(block, 41, 29)
        | _bit_num(block, 33, 28) | _bit_num(block, 25, 27) | _bit_num(block, 17, 26)
        | _bit_num(block, 9, 25) | _bit_num(block, 1, 24) | _bit_num(block, 59, 23)
        | _bit_num(block, 51, 22) | _bit_num(block, 43, 21) | _bit_num(block, 35, 20)
        | _bit_num(block, 27, 19) | _bit_num(block, 19, 18) | _bit_num(block, 11, 17)
        | _bit_num(block, 3, 16) | _bit_num(block, 61, 15) | _bit_num(block, 53, 14)
        | _bit_num(block, 45, 13) | _bit_num(block, 37, 12) | _bit_num(block, 29, 11)
        | _bit_num(block, 21, 10) | _bit_num(block, 13, 9) | _bit_num(block, 5, 8)
        | _bit_num(block, 63, 7) | _bit_num(block, 55, 6) | _bit_num(block, 47, 5)
        | _bit_num(block, 39, 4) | _bit_num(block, 31, 3) | _bit_num(block, 23, 2)
        | _bit_num(block, 15, 1) | _bit_num(block, 7, 0)
    )
    s1 = (
        _bit_num(block, 56, 31) | _bit_num(block, 48, 30) | _bit_num(block, 40, 29)
        | _bit_num(block, 32, 28) | _bit_num(block, 24, 27) | _bit_num(block, 16, 26)
        | _bit_num(block, 8, 25) | _bit_num(block, 0, 24) | _bit_num(block, 58, 23)
        | _bit_num(block, 50, 22) | _bit_num(block, 42, 21) | _bit_num(block, 34, 20)
        | _bit_num(block, 26, 19) | _bit_num(block, 18, 18) | _bit_num(block, 10, 17)
        | _bit_num(block, 2, 16) | _bit_num(block, 60, 15) | _bit_num(block, 52, 14)
        | _bit_num(block, 44, 13) | _bit_num(block, 36, 12) | _bit_num(block, 28, 11)
        | _bit_num(block, 20, 10) | _bit_num(block, 12, 9) | _bit_num(block, 4, 8)
        | _bit_num(block, 62, 7) | _bit_num(block, 54, 6) | _bit_num(block, 46, 5)
        | _bit_num(block, 38, 4) | _bit_num(block, 30, 3) | _bit_num(block, 22, 2)
        | _bit_num(block, 14, 1) | _bit_num(block, 6, 0)
    )
    return s0, s1


def _inverse_permutation(s0: int, s1: int) -> bytes:
    out = bytearray(8)

    def mix(bits) -> int:
        (a, b, c, d, e, f, g, h) = bits
        return (
            _bit_r(s1, a, 7) | _bit_r(s0, b, 6) | _bit_r(s1, c, 5) | _bit_r(s0, d, 4)
            | _bit_r(s1, e, 3) | _bit_r(s0, f, 2) | _bit_r(s1, g, 1) | _bit_r(s0, h, 0)
        )

    out[3] = mix((7, 7, 15, 15, 23, 23, 31, 31))
    out[2] = mix((6, 6, 14, 14, 22, 22, 30, 30))
    out[1] = mix((5, 5, 13, 13, 21, 21, 29, 29))
    out[0] = mix((4, 4, 12, 12, 20, 20, 28, 28))
    out[7] = mix((3, 3, 11, 11, 19, 19, 27, 27))
    out[6] = mix((2, 2, 10, 10, 18, 18, 26, 26))
    out[5] = mix((1, 1, 9, 9, 17, 17, 25, 25))
    out[4] = mix((0, 0, 8, 8, 16, 16, 24, 24))
    return bytes(out)


def _crypt(block: bytes, schedule) -> bytes:
    s0, s1 = _initial_permutation(block)
    for rnd in range(_ROUNDS - 1):
        prev = s1
        s1 = _feistel(s1, schedule[rnd]) ^ s0
        s0 = prev
    s0 = _feistel(s1, schedule[_ROUNDS - 1]) ^ s0
    return _inverse_permutation(s0, s1)


class QqTripleDesDecryptor:
    """QQ 音乐 QRC 载荷的 3DES 解密器（D(K3) → E(K2) → D(K1)）。"""

    BLOCK_SIZE = 8

    def __init__(self, key: bytes):
        if len(key) != 24:
            raise ValueError("triple DES key must be 24 bytes")
        self._sched3 = _build_key_schedule(key[16:24], encrypt=False)
        self._sched2 = _build_key_schedule(key[8:16], encrypt=True)
        self._sched1 = _build_key_schedule(key[0:8], encrypt=False)

    def decrypt_ecb(self, data: bytes) -> bytes:
        if len(data) % self.BLOCK_SIZE != 0:
            raise ValueError("ciphertext length must be a multiple of 8")
        out = bytearray()
        for off in range(0, len(data), self.BLOCK_SIZE):
            block = data[off:off + self.BLOCK_SIZE]
            block = _crypt(block, self._sched3)
            block = _crypt(block, self._sched2)
            block = _crypt(block, self._sched1)
            out += block
        return bytes(out)


_QRC_KEY = b"!@#)(*$%123ZXC!@!@#)(NHL"


def decrypt_qrc_payload(hex_text: str) -> str:
    """hex 密文 → 3DES 解密 → zlib 解压 → UTF-8 文本。失败抛异常。"""
    import binascii
    import zlib

    payload = binascii.unhexlify("".join(hex_text.split()))
    decryptor = QqTripleDesDecryptor(_QRC_KEY)
    plain = decryptor.decrypt_ecb(payload)
    try:
        return zlib.decompress(plain).decode("utf-8")
    except zlib.error:
        # 末尾可能有填充字节，忽略多余数据
        d = zlib.decompressobj()
        return d.decompress(plain).decode("utf-8", errors="replace")
