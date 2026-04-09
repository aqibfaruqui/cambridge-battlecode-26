from enum import IntEnum
from typing import Optional

from world.comms import Encrypt, PositionEncoder
from cambc import Position


class BuilderBotMessageType(IntEnum):
    CLAIM_ORE = 0b0000
    CLAIM_POSITION = 0b0001


class BuilderBotMessages:
    FOR_BUILDER_BOT = 0b0000

    @classmethod
    def is_builder_bot_message(cls, data: int) -> bool:
        decrypted = Encrypt.decrypt(data)
        return (decrypted >> 28) == cls.FOR_BUILDER_BOT

    @classmethod
    def get_message_type(cls, data: int) -> Optional[BuilderBotMessageType]:
        decrypted = Encrypt.decrypt(data)
        if (decrypted >> 28) != cls.FOR_BUILDER_BOT:
            return None
        match BuilderBotMessageType((decrypted >> 24) & 0xF):
            case BuilderBotMessageType.CLAIM_ORE:
                return BuilderBotMessageType.CLAIM_ORE
            case BuilderBotMessageType.CLAIM_POSITION:
                return BuilderBotMessageType.CLAIM_POSITION
            case _:
                return None

    @classmethod
    def encode_claim_ore(cls, position: Position) -> int:
        message = (
            cls.FOR_BUILDER_BOT
            | (BuilderBotMessageType.CLAIM_ORE << 24)
            | PositionEncoder.encode(position)
        )
        return Encrypt.encrypt(message)

    @classmethod
    def decode_claim_ore(cls, data: int) -> Position:
        data = Encrypt.decrypt(data)
        return PositionEncoder.decode(data & 0x00000FFF)

    @classmethod
    def encode_claim_position(cls, position: Position) -> int:
        message = (
            cls.FOR_BUILDER_BOT
            | (BuilderBotMessageType.CLAIM_POSITION << 24)
            | PositionEncoder.encode(position)
        )
        return Encrypt.encrypt(message)

    @classmethod
    def decode_claim_position(cls, data: int) -> Position:
        data = Encrypt.decrypt(data)
        return PositionEncoder.decode(data & 0x00000FFF)
