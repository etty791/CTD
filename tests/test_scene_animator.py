from events.event_bus import EventBus
from events.game_events import GameEnded, GameStarted
from model.piece import Color
from view.scene_animator import NO_SCENE, SceneAnimator


class FakeAssetManager:
    """Stubs AssetManager.get_scene: returns whatever `scenes` maps the
    requested folder to (None by default, i.e. no assets on disk)."""

    def __init__(self, scenes: dict | None = None):
        self._scenes = scenes or {}

    def get_scene(self, folder):
        return self._scenes.get(folder)


class TestCurrentFrameWithMissingAssets:
    def test_no_scene_asset_dismisses_the_scene(self):
        animator = SceneAnimator(EventBus(), FakeAssetManager())
        animator._on_game_started(GameStarted())
        assert animator.is_active() is True

        assert animator.current_frame() is None
        assert animator.is_active() is False

    def test_empty_sprites_dismisses_the_scene(self):
        assets = FakeAssetManager({"victory": {"config": {}, "sprites": []}})
        animator = SceneAnimator(EventBus(), assets)
        animator._on_game_ended(GameEnded(Color.WHITE))
        assert animator.is_active() is True

        assert animator.current_frame() is None
        assert animator.is_active() is False


class TestCurrentFrameWithRealSprites:
    def test_looping_scene_with_sprites_stays_active(self):
        assets = FakeAssetManager(
            {"intro": {"config": {"graphics": {"frames_per_sec": 1, "is_loop": True}},
                       "sprites": ["frame0", "frame1"]}}
        )
        animator = SceneAnimator(EventBus(), assets)
        animator._on_game_started(GameStarted())

        for _ in range(3):
            assert animator.current_frame() is not None
            assert animator.is_active() is True
