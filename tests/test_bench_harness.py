from bench.frames_per_game import run_bench


class TestBenchHarness:
    def test_smoke_run_produces_finite_metrics(self):
        result = run_bench(games=2, max_game_ms=5000, seed=1)

        assert result.games == 2
        assert result.simulated_ms == 5000
        assert result.total_frames > 0
        assert result.frames_per_second_per_game > 0
        assert result.bytes_per_frame_mean > 0
        assert result.bytes_per_frame_p50 > 0
        assert result.bytes_per_frame_p99 >= result.bytes_per_frame_p50
        assert result.bytes_per_second_per_game > 0
        assert result.events_per_frame_mean > 0
        assert result.tracemalloc_bytes_per_live_game > 0

    def test_same_seed_is_reproducible(self):
        first = run_bench(games=2, max_game_ms=5000, seed=7)
        second = run_bench(games=2, max_game_ms=5000, seed=7)

        assert first.total_frames == second.total_frames
        assert first.bytes_per_frame_mean == second.bytes_per_frame_mean
        assert first.events_per_frame_mean == second.events_per_frame_mean

    def test_different_seeds_can_diverge(self):
        first = run_bench(games=2, max_game_ms=5000, seed=1)
        second = run_bench(games=2, max_game_ms=5000, seed=99)

        # Not a hard guarantee for every possible pair of seeds, but with a
        # 5s horizon across 2 games the command sequences almost certainly
        # differ - this guards against an accidental global/shared RNG.
        assert (first.total_frames, first.bytes_per_frame_mean) != (
            second.total_frames,
            second.bytes_per_frame_mean,
        )

    def test_to_dict_round_trips_through_json(self):
        import json

        result = run_bench(games=1, max_game_ms=2000, seed=3)
        parsed = json.loads(json.dumps(result.to_dict()))
        assert parsed["games"] == 1
        assert "metrics" in parsed
