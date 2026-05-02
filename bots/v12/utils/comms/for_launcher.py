from enum import IntEnum
from typing import Optional

from utils.comms import Encryption, PositionEncoder
from utils.comms.debug import debug_print
from cambc import Position


class LauncherMessageType(IntEnum):
    ONETIME_SEND_OURS = 0b0000


class LauncherMessages(IntEnum):
    FOR_LAUNCHER = 0b0001

    @classmethod
    def is_builder_bot_message(cls, data: int) -> bool:
        decrypted = Encryption.decrypt(data)
        return (decrypted >> 28) == cls.FOR_LAUNCHER

    @classmethod
    def get_message_type(cls, data: int) -> Optional[LauncherMessageType]:
        decrypted = Encryption.decrypt(data)
        if (decrypted >> 28) != cls.FOR_LAUNCHER:
            return None
        return LauncherMessageType._value2member_map_.get((decrypted >> 24) & 0xF)

    @classmethod
    def encode_onetime_send_ours(cls, builder_bot_id: int, position: Position) -> int:
        message = (
            (cls.FOR_LAUNCHER << 28)
            | (LauncherMessageType.ONETIME_SEND_OURS << 24)
            | ((builder_bot_id & 0xFFF) << 12)
            | PositionEncoder.encode(position)
        )
        return Encryption.encrypt(message)

    @classmethod
    def decode_onetime_send_ours(cls, data: int) -> tuple[int, Position]:
        data = Encryption.decrypt(data)
        builder_bot_id = (data >> 12) & 0xFFF
        position = PositionEncoder.decode(data & 0x00000FFF)
        debug_print(
            f"[LauncherMessages] ONETIME_SEND_OURS builder_bot_id={builder_bot_id} "
            f"position=({position.x}, {position.y})"
        )
        return builder_bot_id, position
