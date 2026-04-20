from cambc import Position


class Encryption:
    # key = 0x3C4E123F
    key = 0x00000000

    @classmethod
    def encrypt(cls, data: int) -> int:
        return data ^ cls.key

    @classmethod
    def decrypt(cls, data: int) -> int:
        return data ^ cls.key


class PositionEncoder:
    @classmethod
    def encode(cls, position: Position) -> int:
        return (position.x << 6) | position.y

    @classmethod
    def decode(cls, data: int) -> Position:
        data = data & 0x00000FFF
        return Position(data >> 6, data & 0x3F)