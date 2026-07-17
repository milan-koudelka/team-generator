"""Unit tests: pure helpers and input validation (via Flask's test client)."""

import pytest

from app import (
    DEFAULT_MU,
    DEFAULT_SIGMA,
    MAX_AVG_PLAYERS,
    _assign_balanced,
    _assign_to_smaller,
    _ordinal,
    _split_by_gender,
    _team_stats,
    _teams_dict,
    app,
)


@pytest.fixture()
def client():
    return app.test_client()


def make_players(n, mu_start=30, male=0):
    """n players with distinct, descending mu (p0 strongest) and tiny sigma."""
    return {f"p{i}": {"mu": mu_start - i, "sigma": 0.001, "male": male} for i in range(n)}


# --- helpers -----------------------------------------------------------------


def test_ordinal_is_mu_minus_three_sigma():
    assert _ordinal({"mu": 25.0, "sigma": 8.0}) == pytest.approx(1.0)


def test_ordinal_default_rating_is_zero():
    assert _ordinal({"mu": DEFAULT_MU, "sigma": DEFAULT_SIGMA}) == pytest.approx(0.0)


def test_split_by_gender():
    players = {"f1": {"male": 0}, "m1": {"male": 1}, "f2": {"male": 0}}
    females, males = _split_by_gender(players)
    assert set(females) == {"f1", "f2"}
    assert males == ["m1"]


def test_assign_to_smaller_keeps_sizes_balanced():
    a, b = [], []
    _assign_to_smaller(list("abcdefg"), a, b, tie_random=False)
    assert abs(len(a) - len(b)) <= 1


def test_assign_balanced_no_systematic_first_team_advantage():
    """With players of strictly decreasing strength, the stronger of each pair
    must not always land in team A (the bug the old snake had)."""
    players = make_players(6)
    a, b = [], []
    _assign_balanced(
        sorted(players, key=lambda p: _ordinal(players[p]), reverse=True), a, b, players
    )
    total_a = sum(players[p]["mu"] for p in a)
    total_b = sum(players[p]["mu"] for p in b)
    assert len(a) == len(b) == 3
    assert abs(total_a - total_b) <= 1  # fair snake: 143 vs 142, not 144 vs 141


def test_teams_dict_shape():
    players = make_players(2)
    out = _teams_dict(["p0"], ["p1"], players)
    assert out == {"team_a": {"p0": players["p0"]}, "team_b": {"p1": players["p1"]}}


def test_team_stats():
    players = {
        "f": {"mu": 25, "sigma": 8.333, "male": 0},
        "m": {"mu": 25, "sigma": 8.333, "male": 1},
    }
    ordinal = {pid: _ordinal(p) for pid, p in players.items()}
    stats = _team_stats(["f", "m"], players, ordinal)
    assert stats["players"] == 2
    assert stats["females"] == 1
    assert stats["males"] == 1
    assert stats["avg_ordinal"] == pytest.approx(stats["ordinal"] / 2)


# --- input validation (former 500s must all be 400s now) ---------------------


@pytest.mark.parametrize("endpoint", ["/rand", "/topdown", "/avg"])
class TestValidation:
    def test_non_json_request(self, client, endpoint):
        resp = client.post(endpoint, data="not json", content_type="text/plain")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_body_is_a_list(self, client, endpoint):
        resp = client.post(endpoint, json=[1, 2, 3])
        assert resp.status_code == 400

    def test_missing_players_key(self, client, endpoint):
        resp = client.post(endpoint, json={"balance_females": True})
        assert resp.status_code == 400

    def test_players_not_a_dict(self, client, endpoint):
        resp = client.post(endpoint, json={"players": [1, 2]})
        assert resp.status_code == 400

    def test_zero_players(self, client, endpoint):
        resp = client.post(endpoint, json={"players": {}})
        assert resp.status_code == 400

    def test_one_player(self, client, endpoint):
        resp = client.post(endpoint, json={"players": {"a": {}}})
        assert resp.status_code == 400

    def test_player_not_an_object(self, client, endpoint):
        resp = client.post(endpoint, json={"players": {"a": 5, "b": {}}})
        assert resp.status_code == 400

    def test_mu_not_numeric(self, client, endpoint):
        resp = client.post(endpoint, json={"players": {"a": {"mu": "abc"}, "b": {}}})
        assert resp.status_code == 400

    def test_sigma_not_positive(self, client, endpoint):
        resp = client.post(endpoint, json={"players": {"a": {"sigma": 0}, "b": {}}})
        assert resp.status_code == 400

    def test_male_out_of_range(self, client, endpoint):
        resp = client.post(endpoint, json={"players": {"a": {"male": 5}, "b": {}}})
        assert resp.status_code == 400

    def test_balance_females_not_boolean(self, client, endpoint):
        resp = client.post(endpoint, json={"balance_females": "yes", "players": make_players(2)})
        assert resp.status_code == 400

    def test_error_response_is_json(self, client, endpoint):
        resp = client.post(endpoint, json={"players": {}})
        assert resp.content_type.startswith("application/json")


def test_avg_player_cap(client):
    players = make_players(MAX_AVG_PLAYERS + 1)
    resp = client.post("/avg", json={"players": players})
    assert resp.status_code == 400
    assert str(MAX_AVG_PLAYERS) in resp.get_json()["error"]


def test_avg_at_cap_is_accepted(client):
    # smoke check only for the boundary; runtime grows combinatorially
    players = make_players(10)
    resp = client.post("/avg", json={"players": players})
    assert resp.status_code == 200
