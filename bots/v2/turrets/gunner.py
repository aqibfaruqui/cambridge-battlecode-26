from cambc import Controller

class Gunner:
    def __init__(self):
        pass

    def run(self, c: Controller):
        target = c.get_gunner_target()
        if target is not None and c.can_fire(target):
            c.fire(target)