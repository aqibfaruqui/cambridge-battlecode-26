from typing import Optional, Callable
import heapq

from cambc import Controller
from entity.builder.roles import BuilderType


class BotReleaseInstruction:
    def __init__(
        self,
        builder_type: BuilderType,
        interval: int,
        round_start: int,
        num_bots: int,
        condition: Optional[Callable[[Controller], bool]] = None,
    ):
        self.builder_type = builder_type
        self.interval = interval
        self.round_start = round_start
        self.num_bots = num_bots
        self.condition = condition


def build_task_queue(
    instructions: list[BotReleaseInstruction],
    controller: Controller,
) -> list[tuple[int, BuilderType]]:
    """Build a priority queue of builder releases.

    Args:
        instructions: List of builder release instructions.
        controller: Controller instance.

    Returns:
        Priority queue of builder releases.
    """
    heap = []

    for instr in instructions:
        for i in range(instr.num_bots):
            round_num = instr.round_start + i * instr.interval
            if instr.condition is None or instr.condition(controller):
                heapq.heappush(heap, (round_num, instr.builder_type))

    return heap


class Core:
    def __init__(self, *, release_instructions: list[BotReleaseInstruction]):
        self.spawned = False
        self.bot_count = 0
        self.next_builder_type = None
        self.release_queue = None
        self.release_instructions = release_instructions

    def run(self, c: Controller):
        if self.release_queue is None:
            self.release_queue = build_task_queue(self.release_instructions, c)

        core_pos = c.get_position()
        if self.release_queue and c.get_current_round() >= self.release_queue[0][0]:
            self.next_builder_type = heapq.heappop(self.release_queue)[1]
        else:
            self.next_builder_type = None

        print(
            f"{c.get_current_round()}: Core has next_builder_type: {self.next_builder_type.name if self.next_builder_type is not None else 'None'}"
        )
        if self.next_builder_type is not None:
            builder_pos = self.next_builder_type.position_from_core(core_pos)
            if c.can_spawn(builder_pos):
                c.spawn_builder(builder_pos)
                self.bot_count += 1
            else:
                print(
                    f"{c.get_current_round()}: Could not spawn {self.next_builder_type.name} at {builder_pos}, requeuing"
                )
                heapq.heappush(self.release_queue, (0, self.next_builder_type))
