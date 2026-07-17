"""Endpoint behaviour tests (Flask test client): algorithms, balance_females
semantics, response shape and content type."""

import pytest

from app import DEFAULT_MU, DEFAULT_SIGMA, app


@pytest.fixture()
def client():
    return app.test_client()


def make_players(n, mu_start=30, males=()):
    """n players p0..p{n-1}, descending mu, tiny sigma; ids in `males` are male."""
    return {
        f"p{i}": {"mu": mu_start - i, "sigma": 0.001, "male": int(f"p{i}" in males)}
        for i in range(n)
    }


def females_in(team):
    return sum(1 - p["male"] for p in team.values())


def post(client, endpoint, players, balance_females=False):
    resp = client.post(endpoint, json={"balance_females": balance_females, "players": players})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.content_type.startswith("application/json")
    return resp.get_json()


@pytest.mark.parametrize("endpoint", ["/rand", "/topdown", "/avg"])
class TestCommonBehaviour:
    def test_returns_json_with_both_teams(self, client, endpoint):
        out = post(client, endpoint, make_players(4))
        assert set(out["team_a"]) | set(out["team_b"]) == {"p0", "p1", "p2", "p3"}
        assert not set(out["team_a"]) & set(out["team_b"])

    def test_team_sizes_differ_by_at_most_one(self, client, endpoint):
        for n in (2, 3, 6, 7):
            out = post(client, endpoint, make_players(n))
            assert abs(len(out["team_a"]) - len(out["team_b"])) <= 1

    def test_defaults_filled_and_returned(self, client, endpoint):
        out = post(client, endpoint, {"a": {}, "b": {"mu": 20, "sigma": 5}})
        merged = {**out["team_a"], **out["team_b"]}
        assert merged["a"]["mu"] == DEFAULT_MU
        assert merged["a"]["sigma"] == pytest.approx(DEFAULT_SIGMA)
        assert merged["a"]["male"] == 0
        assert merged["b"]["mu"] == 20

    def test_balance_females_splits_females_evenly(self, client, endpoint):
        players = make_players(8, males=("p4", "p5", "p6", "p7"))
        out = post(client, endpoint, players, balance_females=True)
        assert females_in(out["team_a"]) == females_in(out["team_b"]) == 2

    def test_balance_females_odd_female_count(self, client, endpoint):
        players = make_players(6, males=("p3", "p4", "p5"))  # 3 females
        out = post(client, endpoint, players, balance_females=True)
        diff = abs(females_in(out["team_a"]) - females_in(out["team_b"]))
        assert diff == 1

    def test_balance_females_single_female(self, client, endpoint):
        """One female: she simply ends up in exactly one of the teams."""
        players = make_players(6, males=("p1", "p2", "p3", "p4", "p5"))
        out = post(client, endpoint, players, balance_females=True)
        assert females_in(out["team_a"]) + females_in(out["team_b"]) == 1
        assert abs(len(out["team_a"]) - len(out["team_b"])) == 0

    def test_balance_females_no_females_at_all(self, client, endpoint):
        """Zero females: the flag must change nothing and never error."""
        players = make_players(6, males=tuple(f"p{i}" for i in range(6)))
        out = post(client, endpoint, players, balance_females=True)
        assert females_in(out["team_a"]) == females_in(out["team_b"]) == 0
        assert len(out["team_a"]) == len(out["team_b"]) == 3


class TestRand:
    def test_produces_different_splits(self, client):
        players = make_players(8)
        seen = {frozenset(post(client, "/rand", players)["team_a"]) for _ in range(20)}
        assert len(seen) > 1  # 20 shuffles of 8 players: a repeat-only run is ~impossible


class TestTopdown:
    def test_plain_split_is_deterministic_and_balanced(self, client):
        players = make_players(4)  # ranks p0 > p1 > p2 > p3
        out = post(client, "/topdown", players)
        # legacy snake: {p0,p3} vs {p1,p2} — equal rank sums
        teams = {frozenset(out["team_a"]), frozenset(out["team_b"])}
        assert teams == {frozenset({"p0", "p3"}), frozenset({"p1", "p2"})}

    def test_balanced_branch_is_fair(self, client):
        """6 equally spaced players: totals must differ by <= 1 mu (the old
        assign-ties-to-A snake gave team A +3 every time)."""
        players = make_players(6)
        out = post(client, "/topdown", players, balance_females=True)
        total_a = sum(p["mu"] for p in out["team_a"].values())
        total_b = sum(p["mu"] for p in out["team_b"].values())
        assert abs(total_a - total_b) <= 1


class TestAvg:
    def test_finds_the_optimal_split(self, client):
        # mu: 40, 30, 20, 10 -> optimal halves are {40,10} and {30,20}
        players = {
            "a": {"mu": 40, "sigma": 0.001},
            "b": {"mu": 30, "sigma": 0.001},
            "c": {"mu": 20, "sigma": 0.001},
            "d": {"mu": 10, "sigma": 0.001},
        }
        out = post(client, "/avg", players)
        teams = {frozenset(out["team_a"]), frozenset(out["team_b"])}
        assert teams == {frozenset({"a", "d"}), frozenset({"b", "c"})}
        assert out["avg_player_ordinal_difference"] == pytest.approx(0.0, abs=1e-6)

    def test_two_players(self, client):
        """Regression: used to crash with fewer than 4 players."""
        out = post(client, "/avg", make_players(2))
        assert len(out["team_a"]) == len(out["team_b"]) == 1

    def test_three_players(self, client):
        out = post(client, "/avg", make_players(3))
        assert {len(out["team_a"]), len(out["team_b"])} == {1, 2}

    def test_stats_fields_present_and_consistent(self, client):
        out = post(client, "/avg", make_players(6, males=("p0", "p1")))
        assert out["total_players"] == 6
        assert out["team_a_players"] == len(out["team_a"])
        assert out["team_b_players"] == len(out["team_b"])
        assert out["team_a_females"] + out["team_b_females"] == 4
        assert out["team_a_males"] + out["team_b_males"] == 2
        assert out["female_difference"] == abs(out["team_a_females"] - out["team_b_females"])

    def test_balance_females_constrains_the_split(self, client):
        # 2 strong females + 2 weak females + 2 mid males: without the flag the
        # optimum may stack females; with it each team gets exactly 2 females
        players = {
            "f_strong1": {"mu": 40, "sigma": 0.001, "male": 0},
            "f_strong2": {"mu": 39, "sigma": 0.001, "male": 0},
            "f_weak1": {"mu": 5, "sigma": 0.001, "male": 0},
            "f_weak2": {"mu": 4, "sigma": 0.001, "male": 0},
            "m1": {"mu": 22, "sigma": 0.001, "male": 1},
            "m2": {"mu": 21, "sigma": 0.001, "male": 1},
        }
        out = post(client, "/avg", players, balance_females=True)
        assert females_in(out["team_a"]) == females_in(out["team_b"]) == 2
        assert out["female_difference"] == 0
