from view.game_loop import GameLoop


class FakeGame:
    def __init__(self, game_active: bool):
        self.game_active = game_active


class FakeSceneAnimator:
    def __init__(self, active: bool):
        self._active = active

    def is_active(self) -> bool:
        return self._active


def _make_loop(game_active: bool, scene_active: bool) -> GameLoop:
    """Builds a GameLoop without running __init__ (which creates a real cv2
    window) -- _should_exit only touches self.game/self.scene_animator."""
    loop = object.__new__(GameLoop)
    loop.game = FakeGame(game_active)
    loop.scene_animator = FakeSceneAnimator(scene_active)
    return loop


QUIT_KEY = ord('q')
OTHER_KEY = ord('x')


class TestShouldExit:
    def test_quit_key_always_exits_even_mid_scene(self):
        loop = _make_loop(game_active=True, scene_active=True)
        assert loop._should_exit(QUIT_KEY, window_visible=True) is True

    def test_closed_window_always_exits(self):
        loop = _make_loop(game_active=True, scene_active=True)
        assert loop._should_exit(OTHER_KEY, window_visible=False) is True

    def test_stays_open_while_game_active(self):
        loop = _make_loop(game_active=True, scene_active=False)
        assert loop._should_exit(OTHER_KEY, window_visible=True) is False

    def test_stays_open_while_scene_still_active_after_game_over(self):
        loop = _make_loop(game_active=False, scene_active=True)
        assert loop._should_exit(OTHER_KEY, window_visible=True) is False

    def test_exits_when_game_inactive_and_no_scene_active(self):
        loop = _make_loop(game_active=False, scene_active=False)
        assert loop._should_exit(OTHER_KEY, window_visible=True) is True
