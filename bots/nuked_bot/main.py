from entity.core import BotReleaseInstruction, Core
from entity.builder.roles import BuilderType
from entity.builder import Builder
from cambc import Controller, EntityType

RELEASE_INSTRUCTIONS = [
    BotReleaseInstruction(
        builder_type=BuilderType.RANDOM_EXPLORER,
        interval=80,
        round_start=0,
        num_bots=1,
    ),
]


class Player:
    def __init__(self):
        self.core_logic = None
        self.builder_logic = None

    def run(self, c: Controller):
        etype = c.get_entity_type()

        match etype:
            case EntityType.CORE:
                if self.core_logic is None:
                    self.core_logic = Core(release_instructions=RELEASE_INSTRUCTIONS)
                self.core_logic.run(c)
            case EntityType.BUILDER_BOT:
                if self.builder_logic is None:
                    self.builder_logic = Builder(c)
                self.builder_logic.run(c)
            case _:
                pass
