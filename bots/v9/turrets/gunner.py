from cambc import Controller


class Gunner:
    def __init__(self):
        pass

    def run(self, c: Controller):
        target = c.get_gunner_target()
        if target is not None and c.can_fire(target):
            c.fire(target)

        # Debug visualization: purple dot + line to target
        current_pos = c.get_position()
        c.draw_indicator_dot(current_pos, 200, 0, 255)
        if target is not None and target != current_pos:
            c.draw_indicator_line(current_pos, target, 200, 0, 255)
