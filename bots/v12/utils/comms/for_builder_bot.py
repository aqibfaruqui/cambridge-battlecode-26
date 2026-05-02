from enum import IntEnum
from typing import Optional

from utils.comms import Encryption, PositionEncoder
from cambc import Controller, EntityType, Position


class BuilderBotMessageType(IntEnum):
    CLAIM_ORE = 0b0000  # raw nibble, shifted at encode time
    CORE_POSITION = 0b0001
    ENEMY_CORE_POSITION = 0b0010
    CLAIM_POSITION = 0b0011
    SYMMETRY = 0b0100


class BuilderBotMessages(IntEnum):
    FOR_BUILDER_BOT = 0b0000

    @classmethod
    def get_message_type(cls, data: int) -> Optional[BuilderBotMessageType]:
        decrypted = Encryption.decrypt(data)
        if (decrypted >> 28) != cls.FOR_BUILDER_BOT:
            return None
        return BuilderBotMessageType._value2member_map_.get((decrypted >> 24) & 0xF)

    @classmethod
    def encode_claim_ore(cls, position: Position) -> int:
        message = (
            (cls.FOR_BUILDER_BOT << 28)
            | (BuilderBotMessageType.CLAIM_ORE << 24)
            | PositionEncoder.encode(position)
        )
        return Encryption.encrypt(message)

    @classmethod
    def decode_claim_ore(cls, data: int) -> Position:
        data = Encryption.decrypt(data)
        position = PositionEncoder.decode(data & 0x00000FFF)
        return position

    @classmethod
    def encode_core_position(cls, position: Position) -> int:
        message = (
            (cls.FOR_BUILDER_BOT << 28)
            | (BuilderBotMessageType.CORE_POSITION << 24)
            | PositionEncoder.encode(position)
        )
        return Encryption.encrypt(message)

    @classmethod
    def encode_enemy_core_position(cls, position: Position) -> int:
        message = (
            (cls.FOR_BUILDER_BOT << 28)
            | (BuilderBotMessageType.ENEMY_CORE_POSITION << 24)
            | PositionEncoder.encode(position)
        )
        return Encryption.encrypt(message)

    @classmethod
    def encode_claim_position(cls, position: Position) -> int:
        message = (
            (cls.FOR_BUILDER_BOT << 28)
            | (BuilderBotMessageType.CLAIM_POSITION << 24)
            | PositionEncoder.encode(position)
        )
        return Encryption.encrypt(message)

    @classmethod
    def decode_claim_position(cls, data: int) -> Position:
        data = Encryption.decrypt(data)
        position = PositionEncoder.decode(data & 0x00000FFF)
        return position

    @classmethod
    def encode_symmetry(cls, symmetry: int) -> int:
        message = (
            (cls.FOR_BUILDER_BOT << 28)
            | (BuilderBotMessageType.SYMMETRY << 24)
            | (symmetry & 0xFF)
        )
        return Encryption.encrypt(message)

    @classmethod
    def decode_symmetry(cls, data: int) -> int:
        data = Encryption.decrypt(data)
        value = data & 0xFF
        return value

    @classmethod
    def read_nearby_symmetry(cls, c: Controller, nearby_buildings=None) -> Optional[int]:
        """Scan own-team markers in vision for a SYMMETRY broadcast; return raw value or None."""
        my_team = c.get_team()
        if nearby_buildings is None:
            nearby_buildings = c.get_nearby_buildings()
        for bid in nearby_buildings:
            if c.get_entity_type(bid) != EntityType.MARKER:
                continue
            if c.get_team(bid) != my_team:
                continue
            value = c.get_marker_value(bid)
            if cls.get_message_type(value) == BuilderBotMessageType.SYMMETRY:
                return cls.decode_symmetry(value)
        return None
