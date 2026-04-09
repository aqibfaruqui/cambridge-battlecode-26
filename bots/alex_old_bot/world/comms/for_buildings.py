from enum import IntEnum
from typing import Optional

from world.comms import Encrypt, PositionEncoder
from cambc import Position


class BuildingMessageType(IntEnum):
    SELF_CORE_LOCATION = 0b0000
    ENEMY_CORE_LOCATION = 0b0001


class BuildingMessages:
    FOR_BUILDINGS = 0b0001

    @classmethod
    def is_building_message(cls, data: int) -> bool:
        decrypted = Encrypt.decrypt(data)
        return (decrypted >> 28) == cls.FOR_BUILDINGS

    @classmethod
    def get_message_type(cls, data: int) -> Optional[BuildingMessageType]:
        decrypted = Encrypt.decrypt(data)
        if (decrypted >> 28) != cls.FOR_BUILDINGS:
            return None
        match BuildingMessageType((decrypted >> 24) & 0xF):
            case BuildingMessageType.SELF_CORE_LOCATION:
                return BuildingMessageType.SELF_CORE_LOCATION
            case BuildingMessageType.ENEMY_CORE_LOCATION:
                return BuildingMessageType.ENEMY_CORE_LOCATION
            case _:
                raise RuntimeError(f"Bad message {((decrypted >> 24) & 0xF):x}")

    @classmethod
    def encode_self_core_location(cls, position: Position) -> int:
        message = (
            cls.FOR_BUILDINGS << 28
            | (BuildingMessageType.SELF_CORE_LOCATION << 24)
            | PositionEncoder.encode(position)
        )
        return Encrypt.encrypt(message)

    @classmethod
    def decode_self_core_location(cls, data: int) -> Position:
        data = Encrypt.decrypt(data)
        return PositionEncoder.decode(data & 0x00000FFF)

    @classmethod
    def encode_enemy_core_location(cls, position: Position) -> int:
        message = (
            cls.FOR_BUILDINGS << 28
            | (BuildingMessageType.ENEMY_CORE_LOCATION << 24)
            | PositionEncoder.encode(position)
        )
        return Encrypt.encrypt(message)

    @classmethod
    def decode_enemy_core_location(cls, data: int) -> Position:
        data = Encrypt.decrypt(data)
        return PositionEncoder.decode(data & 0x00000FFF)
